from flask import jsonify, request, send_file
from flask_socketio import join_room, leave_room, ConnectionRefusedError
from . import db, socketio, redis_client
from .models import AuditLog, Institution,Branch, Queue, Ticket, User, Department, UserRole, InstitutionType, InstitutionService, ServiceCategory, ServiceTag, UserPreference, BranchSchedule, UserBehavior, NotificationLog, Weekday
from .services import QueueService
from .ml_models import wait_time_predictor, service_recommendation_predictor, collaborative_model, demand_model, clustering_model
import uuid
from datetime import datetime, timedelta
import io
import json

import pytz
from .recommendation_service import RecommendationService
import re
from .auth import require_auth
import logging
from sqlalchemy import and_, or_, func
from geopy.distance import geodesic
from firebase_admin import auth
from sqlalchemy.exc import SQLAlchemyError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_queue_routes(app):
    
    def cache_key(endpoint, **kwargs):
        """Gera uma chave de cache única para o endpoint com base nos parâmetros."""
        params = ':'.join(f"{k}={v}" for k, v in sorted(kwargs.items()) if v is not None)
        return f"{endpoint}:{params}"


    
    @app.route("/api/ping")
    def ping():
        return "pong", 200


    @app.route('/branches/<branch_id>/services', methods=['GET'])
    def services_by_branch(branch_id):
        """Lista serviços disponíveis em uma filial específica."""
        try:
            user_id = request.args.get('user_id')
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 10))
            sort_by = request.args.get('sort_by', 'name')  # Opções: name, wait_time
            max_wait_time = request.args.get('max_wait_time', type=float)

            # Validar entrada
            if page < 1 or per_page < 1:
                logger.warning(f"Parâmetros inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'Página e itens por página devem be positivos'}), 400
            if sort_by not in ['name', 'wait_time']:
                logger.warning(f"Ordenação inválida: sort_by={sort_by}")
                return jsonify({'error': 'Ordenação deve ser por "name" ou "wait_time"'}), 400

            # Verificar cache
            cache_params = {
                'branch_id': branch_id,
                'user_id': user_id,
                'page': page,
                'per_page': per_page,
                'sort_by': sort_by,
                'max_wait_time': max_wait_time
            }
            cache_k = cache_key('services_by_branch', **cache_params)
            cached_result = redis_client.get(cache_k)
            if cached_result:
                logger.debug(f"Cache hit para services_by_branch: {cache_k}")
                return jsonify(json.loads(cached_result))

            # Verificar se a filial existe
            branch = Branch.query.get(branch_id)
            if not branch:
                logger.warning(f"Filial não encontrada: branch_id={branch_id}")
                return jsonify({'error': 'Filial não encontrada'}), 404

            # Construir consulta
            now = datetime.utcnow()
            weekday_str = now.strftime('%A').upper()
            try:
                weekday_enum = Weekday[weekday_str]
            except KeyError:
                logger.error(f"Dia da semana inválido para filial {branch_id}: {weekday_str}")
                return jsonify({'error': 'Dia da semana inválido'}), 400

            query_base = Queue.query.join(Department).join(InstitutionService).join(Branch).join(BranchSchedule).filter(
                Department.branch_id == branch_id,
                BranchSchedule.weekday == weekday_enum,
                BranchSchedule.is_closed == False,
                BranchSchedule.open_time <= now.time(),
                BranchSchedule.end_time >= now.time(),
                Queue.active_tickets < Queue.daily_limit
            )

            # Contar total
            total = query_base.count()
            logger.debug(f"Total de serviços encontrados para branch_id={branch_id}: {total}")

            # Ordenação inicial
            if sort_by == 'name':
                query_base = query_base.order_by(InstitutionService.name.asc())

            # Paginação
            queues = query_base.offset((page - 1) * per_page).limit(per_page).all()

            # Montar resposta
            results = []
            for queue in queues:
                service = queue.service
                wait_time = wait_time_predictor.predict(
                    queue_id=queue.id,
                    position=queue.active_tickets + 1,
                    active_tickets=queue.active_tickets,
                    priority=0,
                    hour_of_day=now.hour,
                    user_id=user_id
                )
                if max_wait_time and isinstance(wait_time, (int, float)) and wait_time > max_wait_time:
                    continue

                schedule = BranchSchedule.query.filter_by(
                    branch_id=queue.department.branch_id,
                    weekday=weekday_enum
                ).first()
                results.append({
                    'queue_id': queue.id,
                    'service': {
                        'id': service.id,
                        'name': service.name or 'Desconhecido',
                        'category_id': service.category_id
                    },
                    'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else 'Aguardando início',
                    'active_tickets': queue.active_tickets or 0,
                    'daily_limit': queue.daily_limit or 100,
                    'open_time': schedule.open_time.strftime('%H:%M') if schedule and schedule.open_time else None,
                    'end_time': schedule.end_time.strftime('%H:%M') if schedule and schedule.end_time else None
                })

            # Ordenação por wait_time
            if sort_by == 'wait_time':
                results.sort(key=lambda x: float(x['wait_time'].split()[0]) if x['wait_time'] != 'Aguardando início' else float('inf'))

            result = {
                'services': results,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page,
                'message': 'Nenhum serviço encontrado' if not results else 'Serviços listados com sucesso'
            }

            # Cachear resultado
            redis_client.setex(cache_k, 60, json.dumps(result, default=str))
            logger.info(f"Lista de serviços retornada para branch_id={branch_id}: {total} resultados, cache_key={cache_k}")

            return jsonify(result)
        except Exception as e:
            logger.error(f"Erro ao listar serviços da filial {branch_id}: {str(e)}")
            return jsonify({'error': 'Erro interno do servidor'}), 500


    @app.route('/institutions/<institution_id>/services', methods=['GET'])
    def services_by_institution(institution_id):
        """Lista serviços de uma instituição com informações básicas."""
        try:
            user_id = request.args.get('user_id')
            category_id = request.args.get('category_id')
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 10))
            sort_by = request.args.get('sort_by', 'name')

            # Validar entrada
            if page < 1 or per_page < 1:
                logger.warning(f"Parâmetros inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'Página e itens por página devem ser positivos'}), 400
            if sort_by != 'name':
                logger.warning(f"Ordenação inválida: sort_by={sort_by}")
                return jsonify({'error': 'Ordenação deve ser por "name"'}), 400

            # Verificar se a instituição existe
            institution = Institution.query.get(institution_id)
            if not institution:
                logger.warning(f"Instituição não encontrada: institution_id={institution_id}")
                return jsonify({'error': 'Instituição não encontrada'}), 404

            # Consultar serviços da instituição
            services_query = InstitutionService.query.filter_by(institution_id=institution_id)
            if category_id:
                services_query = services_query.filter_by(category_id=category_id)
            services_query = services_query.order_by(InstitutionService.name.asc())

            # Paginação
            total = services_query.count()
            services = services_query.offset((page - 1) * per_page).limit(per_page).all()
            logger.debug(f"Total de serviços encontrados para institution_id={institution_id}: {total}")

            # Montar resposta
            results = [
                {
                    'id': service.id,
                    'name': service.name or 'Desconhecido',
                    'category_id': service.category_id,
                    'description': service.description or 'Sem descrição',
                    'institution_id': service.institution_id
                }
                for service in services
            ]

            result = {
                'services': results,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page,
                'message': 'Nenhum serviço encontrado' if not results else 'Serviços listados com sucesso'
            }

            # Cachear resultado
            cache_key = f"services_{institution_id}_{user_id}_{category_id}_{page}_{per_page}"
            redis_client.setex(cache_key, 30, json.dumps(result, default=str))
            logger.info(f"Lista de serviços retornada para institution_id={institution_id}: {total} resultados, cache_key={cache_key}")

            return jsonify(result)
        except Exception as e:
            logger.error(f"Erro ao listar serviços da instituição {institution_id}: {str(e)}")
            return jsonify({'error': f'Erro interno do servidor: {str(e)}'}), 500
 
    @app.route('/institutions/<institution_id>/services/<service_id>/branches', methods=['GET'])
    def branches_by_service(institution_id, service_id):
        """Lista filiais que oferecem um serviço específico, com detalhes da fila, distância e recomendações."""
        try:
            user_id = request.args.get('user_id')
            user_lat = request.args.get('user_lat', type=float)
            user_lon = request.args.get('user_lon', type=float)
            max_distance_km = request.args.get('max_distance_km', 10.0, type=float)
            max_wait_time = request.args.get('max_wait_time', type=float)
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 10))
            sort_by = request.args.get('sort_by', 'recommended')  # Opções: recommended, distance, wait_time

            # Validar entrada
            if page < 1 or per_page < 1:
                logger.warning(f"Parâmetros inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'Página e itens por página devem ser positivos'}), 400
            if sort_by not in ['recommended', 'distance', 'wait_time']:
                logger.warning(f"Ordenação inválida: sort_by={sort_by}")
                return jsonify({'error': 'Ordenação deve ser por "recommended", "distance" ou "wait_time"'}), 400
            if sort_by == 'distance' and (user_lat is None or user_lon is None):
                logger.warning("Coordenadas do usuário necessárias para ordenar por distância")
                return jsonify({'error': 'Coordenadas do usuário (user_lat e user_lon) são necessárias para ordenar por distância'}), 400

            # Verificar cache
            cache_params = {
                'institution_id': institution_id,
                'service_id': service_id,
                'user_id': user_id,
                'user_lat': user_lat,
                'user_lon': user_lon,
                'max_distance_km': max_distance_km,
                'max_wait_time': max_wait_time,
                'page': page,
                'per_page': per_page,
                'sort_by': sort_by
            }
            cache_k = cache_key('branches_by_service', **cache_params)
            cached_result = redis_client.get(cache_k)
            if cached_result:
                logger.debug(f"Cache hit para branches_by_service: {cache_k}")
                return jsonify(json.loads(cached_result))

            # Verificar instituição e serviço
            institution = Institution.query.get(institution_id)
            if not institution:
                logger.warning(f"Instituição não encontrada: institution_id={institution_id}")
                return jsonify({'error': 'Instituição não encontrada'}), 404

            service = InstitutionService.query.get(service_id)
            if not service or service.institution_id != institution_id:
                logger.warning(f"Serviço não encontrado ou não pertence à instituição: service_id={service_id}")
                return jsonify({'error': 'Serviço não encontrado ou não pertence à instituição'}), 404

            # Verificar horário de funcionamento
            local_tz = pytz.timezone('Africa/Luanda')  # Ajuste para seu fuso horário
            now = datetime.now(local_tz)
            weekday_str = now.strftime('%A').upper()
            try:
                weekday_enum = Weekday[weekday_str]
            except KeyError:
                logger.error(f"Dia da semana inválido para instituição {institution_id}: {weekday_str}")
                return jsonify({'error': 'Dia da semana inválido'}), 400

            # Consultar filas ativas
            queues = Queue.query.join(Department).join(Branch).join(BranchSchedule).filter(
                Queue.service_id == service_id,
                Branch.institution_id == institution_id,
                BranchSchedule.weekday == weekday_enum,
                BranchSchedule.is_closed == False,
                BranchSchedule.open_time <= now.time(),
                BranchSchedule.end_time >= now.time(),
                Queue.active_tickets < Queue.daily_limit
            ).all()

            # Montar resposta
            results = []
            for queue in queues:
                branch = queue.department.branch
                if not branch.latitude or not branch.longitude:
                    continue

                # Calcular distância
                distance = None
                if user_lat is not None and user_lon is not None:
                    distance = geodesic(
                        (user_lat, user_lon),
                        (branch.latitude, branch.longitude)
                    ).kilometers
                    if distance > max_distance_km:
                        continue

                # Calcular tempo de espera
                wait_time = wait_time_predictor.predict(
                    queue_id=queue.id,
                    position=queue.active_tickets + 1,
                    active_tickets=queue.active_tickets,
                    priority=0,
                    hour_of_day=now.hour,
                    user_id=user_id
                )
                if max_wait_time and isinstance(wait_time, (int, float)) and wait_time > max_wait_time:
                    continue

                # Determinar rótulo e classe do tempo de espera
                wait_label = ""
                wait_class = ""
                if isinstance(wait_time, (int, float)) and wait_time >= 0:
                    if wait_time <= 10:
                        wait_label = "Rápido"
                        wait_class = "text-green-500"
                    elif wait_time <= 20:
                        wait_label = "Moderado"
                        wait_class = "text-yellow-500"
                    else:
                        wait_label = "Longo"
                        wait_class = "text-red-500"

                # Determinar recomendação
                recommendation = ""
                reason_label = ""
                reason = ""
                recommendation_score = 0
                if isinstance(wait_time, (int, float)) and wait_time >= 0:
                    if distance is not None and distance <= 2.0 and wait_time <= 20:
                        recommendation = "RECOMENDADO"
                        reason_label = "Próximo a você"
                        reason = "Esta filial está perto da sua localização com tempo de espera aceitável"
                        recommendation_score = 2  # Alta prioridade
                    elif wait_time <= 5:
                        recommendation = "MAIS RÁPIDO"
                        reason_label = "Menor tempo de espera"
                        reason = "Esta filial tem o menor tempo de espera, mas pode estar mais distante"
                        recommendation_score = 1  # Média prioridade
                    elif wait_time > 30:
                        reason_label = "Alta demanda"
                        reason = "Alta demanda hoje"
                        recommendation_score = -1  # Baixa prioridade

                schedule = BranchSchedule.query.filter_by(
                    branch_id=branch.id,
                    weekday=weekday_enum
                ).first()

                results.append({
                    'queue_id': queue.id,
                    'branch': {
                        'id': branch.id,
                        'name': branch.name or 'Desconhecida',
                        'neighborhood': branch.neighborhood or 'Desconhecido',
                        'latitude': float(branch.latitude) if branch.latitude else None,
                        'longitude': float(branch.longitude) if branch.longitude else None,
                        'distance': float(distance) if distance is not None else None
                    },
                    'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) and wait_time >= 0 else 'Aguardando início',
                    'wait_label': wait_label,
                    'wait_class': wait_class,
                    'active_tickets': queue.active_tickets or 0,
                    'daily_limit': queue.daily_limit or 100,
                    'open_time': schedule.open_time.strftime('%H:%M') if schedule and schedule.open_time else None,
                    'end_time': schedule.end_time.strftime('%H:%M') if schedule and schedule.end_time else None,
                    'recommendation': recommendation,
                    'reason_label': reason_label,
                    'reason': reason,
                    'recommendation_score': recommendation_score
                })

            # Contar total
            total = len(results)
            logger.debug(f"Total de filiais encontradas para institution_id={institution_id}, service_id={service_id}: {total}")

            # Ordenação
            if sort_by == 'recommended':
                results.sort(
                    key=lambda x: (-x['recommendation_score'], x['wait_time'].split()[0] if x['wait_time'] != 'Aguardando início' else float('inf'))
                )
            elif sort_by == 'distance':
                results.sort(
                    key=lambda x: x['branch']['distance'] if x['branch']['distance'] is not None else float('inf')
                )
            else:  # wait_time
                results.sort(
                    key=lambda x: float(x['wait_time'].split()[0]) if x['wait_time'] != 'Aguardando início' else float('inf')
                )

            # Paginação
            start = (page - 1) * per_page
            end = start + per_page
            paginated_results = results[start:end]

            result = {
                'branches': paginated_results,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page,
                'message': 'Nenhuma filial encontrada' if not paginated_results else 'Filiais listadas com sucesso'
            }

            # Cachear resultado
            redis_client.setex(cache_k, 30, json.dumps(result, default=str))  # Cache de 30s para mudanças rápidas
            logger.info(f"Lista de filiais retornada para institution_id={institution_id}, service_id={service_id}: {total} resultados, cache_key={cache_k}")

            return jsonify(result)
        except Exception as e:
            logger.error(f"Erro ao listar filiais para institution_id={institution_id}, service_id={service_id}: {str(e)}")
            return jsonify({'error': 'Erro interno do servidor'}), 500
        
    @app.route('/institutions', methods=['GET'])
    def list_institutions():
        try:
            institution_type_id = request.args.get('institution_type_id')
            user_id = request.args.get('user_id')
            query = request.args.get('query', '').strip()
            latitude = request.args.get('latitude', type=float)
            longitude = request.args.get('longitude', type=float)
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 10, type=int)
            sort_by = request.args.get('sort_by', 'name')

            if page < 1 or per_page < 1:
                return jsonify({'error': 'Página e itens por página devem ser positivos'}), 400
            if sort_by not in ['name', 'distance']:
                return jsonify({'error': 'Ordenação deve ser por "name" ou "distance"'}), 400
            if sort_by == 'distance' and (latitude is None or longitude is None):
                return jsonify({'error': 'Coordenadas do usuário necessárias para ordenar por distância'}), 400

            cache_k = cache_key('list_institutions', **request.args.to_dict())
            try:
                cached_result = redis_client.get(cache_k)
                if cached_result:
                    return jsonify(json.loads(cached_result))
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

            query_base = Institution.query.filter(Institution.name.is_not(None))
            if institution_type_id:
                query_base = query_base.filter(Institution.institution_type_id == institution_type_id)
            if query:
                search_terms = query.lower().replace(' ', ' & ')
                query_base = query_base.filter(
                    or_(
                        Institution.name.ilike(f'%{query}%'),
                        func.to_tsvector('portuguese', Institution.name).op('@@')(
                            func.to_tsquery('portuguese', search_terms)
                        )
                    )
                )

            favorite_ids = set()
            if user_id:
                favorites = UserPreference.query.filter_by(
                    user_id=user_id,
                    is_favorite=True
                ).with_entities(UserPreference.institution_id).all()
                favorite_ids = {f.institution_id for f in favorites if f.institution_id}

            total = query_base.count()

            if sort_by == 'name':
                query_base = query_base.order_by(Institution.name.asc())
                institutions = query_base.offset((page - 1) * per_page).limit(per_page).all()
            else:  # sort_by == 'distance'
                # Subconsulta para calcular a distância mínima por instituição
                subquery = db.session.query(
                    Branch.institution_id,
                    func.min(
                        func.sqrt(
                            func.pow(Branch.latitude - latitude, 2) +
                            func.pow(Branch.longitude - longitude, 2)
                        )
                    ).label('min_distance')
                ).filter(
                    Branch.latitude.is_not(None),
                    Branch.longitude.is_not(None)
                ).group_by(Branch.institution_id).subquery()

                query_base = query_base.outerjoin(
                    subquery,
                    Institution.id == subquery.c.institution_id
                ).order_by(
                    subquery.c.min_distance.asc().nullslast()
                )
                institutions = query_base.offset((page - 1) * per_page).limit(per_page).all()

            results = []
            for inst in institutions:
                distance = None
                if latitude is not None and longitude is not None:
                    nearest_branch = Branch.query.filter(
                        Branch.institution_id == inst.id,
                        Branch.latitude.is_not(None),
                        Branch.longitude.is_not(None)
                    ).order_by(
                        func.sqrt(
                            func.pow(Branch.latitude - latitude, 2) +
                            func.pow(Branch.longitude - longitude, 2)
                        )
                    ).first()
                    if nearest_branch:
                        distance = geodesic(
                            (latitude, longitude),
                            (nearest_branch.latitude, nearest_branch.longitude)
                        ).kilometers

                results.append({
                    'id': inst.id,
                    'name': inst.name,
                    'type': {
                        'id': inst.institution_type_id,
                        'name': inst.type.name if inst.type else 'Desconhecido'
                    },
                    'is_favorite': inst.id in favorite_ids,
                    'logo_url': inst.logo_url,
                    'description': inst.description
                })

            result = {
                'institutions': results,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page,
                'message': 'Nenhuma instituição encontrada' if not results else 'Instituições listadas com sucesso'
            }

            try:
                redis_client.setex(cache_k, 60, json.dumps(result, default=str))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache Redis: {e}")

            return jsonify(result)
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados: {str(e)}", exc_info=True)
            return jsonify({'error': 'Erro no banco de dados'}), 500
        except Exception as e:
            logger.error(f"Erro ao listar instituições: {str(e)}", exc_info=True)
            return jsonify({'error': 'Erro interno do servidor'}), 500

    @app.route('/branches', methods=['GET'])
    def list_branches():
        """Lista filiais com filtros por instituição, tipo de instituição e localização."""
        try:
            institution_id = request.args.get('institution_id')
            institution_type_id = request.args.get('institution_type_id')
            neighborhood = request.args.get('neighborhood')
            user_lat = request.args.get('user_lat', type=float)
            user_lon = request.args.get('user_lon', type=float)
            max_distance_km = request.args.get('max_distance_km', 10.0, type=float)
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 10))
            sort_by = request.args.get('sort_by', 'name')  # Opções: name, distance

            # Validar entrada
            if page < 1 or per_page < 1:
                logger.warning(f"Parâmetros inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'Página e itens por página devem ser positivos'}), 400
            if sort_by not in ['name', 'distance']:
                logger.warning(f"Ordenação inválida: sort_by={sort_by}")
                return jsonify({'error': 'Ordenação deve ser por "name" ou "distance"'}), 400
            if sort_by == 'distance' and (user_lat is None or user_lon is None):
                logger.warning("Ordenação por distância requer user_lat e user_lon")
                return jsonify({'error': 'Coordenadas do usuário necessárias para ordenar por distância'}), 400

            # Verificar cache
            cache_params = {
                'institution_id': institution_id,
                'institution_type_id': institution_type_id,
                'neighborhood': neighborhood,
                'user_lat': user_lat,
                'user_lon': user_lon,
                'max_distance_km': max_distance_km,
                'page': page,
                'per_page': per_page,
                'sort_by': sort_by
            }
            cache_k = cache_key('list_branches', **cache_params)
            cached_result = redis_client.get(cache_k)
            if cached_result:
                logger.debug(f"Cache hit para list_branches: {cache_k}")
                return jsonify(json.loads(cached_result))

            # Construir consulta
            query_base = Branch.query.join(Institution)
            if institution_id:
                query_base = query_base.filter(Branch.institution_id == institution_id)
            if institution_type_id:
                query_base = query_base.filter(Institution.institution_type_id == institution_type_id)
            if neighborhood:
                query_base = query_base.filter(Branch.neighborhood.ilike(f'%{neighborhood}%'))

            # Filtrar por distância
            branches = query_base.all()
            if user_lat is not None and user_lon is not None:
                branches = [
                    b for b in branches
                    if b.latitude and b.longitude and
                    RecommendationService.calculate_distance(user_lat, user_lon, b) <= max_distance_km
                ]
            else:
                branches = branches

            # Contar total
            total = len(branches)
            logger.debug(f"Total de filiais encontradas: {total}")

            # Paginação
            start = (page - 1) * per_page
            end = start + per_page
            paginated_branches = branches[start:end]

            # Montar resposta
            results = []
            for branch in paginated_branches:
                distance = RecommendationService.calculate_distance(user_lat, user_lon, branch) if user_lat is not None and user_lon is not None else None
                results.append({
                    'id': branch.id,
                    'name': branch.name or 'Desconhecida',
                    'institution': {
                        'id': branch.institution_id,
                        'name': branch.institution.name if branch.institution else 'Desconhecida'
                    },
                    'location': branch.location or 'Desconhecida',
                    'neighborhood': branch.neighborhood or 'Desconhecido',
                    'latitude': float(branch.latitude) if branch.latitude else None,
                    'longitude': float(branch.longitude) if branch.longitude else None,
                    'distance': float(distance) if distance is not None else 'Desconhecida'
                })

            # Ordenação
            if sort_by == 'distance' and user_lat is not None and user_lon is not None:
                results.sort(key=lambda x: x['distance'] if x['distance'] != 'Desconhecida' else float('inf'))
            else:
                results.sort(key=lambda x: x['name'])

            result = {
                'branches': results,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page,
                'message': 'Nenhuma filial encontrada' if not results else 'Filiais listadas com sucesso'
            }

            # Cachear resultado
            redis_client.setex(cache_k, 60, json.dumps(result, default=str))
            logger.info(f"Lista de filiais retornada: {total} resultados, cache_key={cache_k}")

            return jsonify(result)
        except Exception as e:
            logger.error(f"Erro ao listar filiais: {str(e)}")
            return jsonify({'error': 'Erro interno do servidor'}), 500

    @app.route('/institution_types', methods=['GET'])
    def list_institution_types():
        """Lista tipos de instituições com busca textual."""
        try:
            query = request.args.get('query', '').strip()
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 10))
            sort_by = request.args.get('sort_by', 'name')  # Opções: name, id

            # Validar entrada
            if page < 1 or per_page < 1:
                logger.warning(f"Parâmetros inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'Página e itens por página devem ser positivos'}), 400
            if sort_by not in ['name', 'id']:
                logger.warning(f"Ordenação inválida: sort_by={sort_by}")
                return jsonify({'error': 'Ordenação deve ser por "name" ou "id"'}), 400

            # Verificar cache
            cache_params = {
                'query': query,
                'page': page,
                'per_page': per_page,
                'sort_by': sort_by
            }
            cache_k = cache_key('list_institution_types', **cache_params)
            cached_result = redis_client.get(cache_k)
            if cached_result:
                logger.debug(f"Cache hit para list_institution_types: {cache_k}")
                return jsonify(json.loads(cached_result))

            # Construir consulta
            query_base = InstitutionType.query
            if query:
                query_base = query_base.filter(InstitutionType.name.ilike(f'%{query}%'))

            # Contar total
            total = query_base.count()
            logger.debug(f"Total de tipos de instituições encontrados: {total}")

            # Ordenação
            if sort_by == 'name':
                query_base = query_base.order_by(InstitutionType.name.asc())
            else:
                query_base = query_base.order_by(InstitutionType.id.asc())

            # Paginação
            types = query_base.offset((page - 1) * per_page).limit(per_page).all()

            # Montar resposta
            results = [{
                'id': t.id,
                'name': t.name or 'Desconhecido',
                'logo_url': t.logo_url,
                'description': t.description
            } for t in types]

            result = {
                'institution_types': results,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page,
                'message': 'Nenhum tipo de instituição encontrado' if not results else 'Tipos de instituições listados com sucesso'
            }

            # Cachear resultado
            redis_client.setex(cache_k, 60, json.dumps(result, default=str))
            logger.info(f"Lista de tipos de instituições retornada: {total} resultados, cache_key={cache_k}")

            return jsonify(result)
        except Exception as e:
            logger.error(f"Erro ao listar tipos de instituições: {str(e)}")
            return jsonify({'error': 'Erro interno do servidor'}), 500
        
    @app.route('/api/recommendation/featured', methods=['GET'])
    @require_auth
    def get_featured_recommendations():
        user_id = request.args.get('user_id')
        latitude = request.args.get('latitude', type=float)
        longitude = request.args.get('longitude', type=float)
        limit = request.args.get('limit', default=5, type=int)
        sort_by = request.args.get('sort_by', default='preference_score')
        include_alternatives = request.args.get('include_alternatives', default='true') == 'true'
        max_demand = request.args.get('max_demand', default=20, type=int)

        if not user_id or user_id != request.user_id:
            return jsonify({'error': 'user_id inválido ou não autorizado'}), 403

        recommendation_service = RecommendationService()
        queue_service = QueueService()

        # Buscar preferências do usuário
        preferences = db.session.query(UserPreference).filter_by(user_id=user_id, is_favorite=True).all()
        institution_ids = [p.institution_id for p in preferences if p.institution_id]
        category_ids = [p.service_category_id for p in preferences if p.service_category_id]
        neighborhoods = [p.neighborhood for p in preferences if p.neighborhood]

        # Query corrigida usando Queue.department_id -> Department -> Branch
        query = db.session.query(
            Queue,
            Department,
            Branch,
            InstitutionService,
            Institution,
            func.coalesce(Queue.estimated_wait_time, 15).label('wait_time')
        ).join(
            Department, Queue.department_id == Department.id
        ).join(
            Branch, Department.branch_id == Branch.id
        ).join(
            InstitutionService, Queue.service_id == InstitutionService.id
        ).join(
            Institution, Branch.institution_id == Institution.id
        ).filter(
            Queue.active_tickets <= max_demand
        )

        if institution_ids:
            query = query.filter(Branch.institution_id.in_(institution_ids))
        if category_ids:
            query = query.filter(InstitutionService.category_id.in_(category_ids))
        if neighborhoods:
            query = query.filter(Branch.neighborhood.in_(neighborhoods))

        queues = query.limit(limit).all()
        services = []

        for queue, department, branch, service, institution, wait_time in queues:
            service_data = {
                'queue': {
                    'id': queue.id,
                    'institution_name': institution.name if institution else 'Desconhecido',
                    'branch_name': branch.name,
                    'wait_time': f'{int(wait_time)} min',
                    'demand': queue.active_tickets or 0
                },
                'service': {
                    'id': service.id,
                    'name': service.name
                },
                'institution_id': branch.institution_id,
                'reason': 'Próximo a você com baixa espera' if latitude and longitude else 'Baseado nas suas preferências'
            }

            # Adicionar filiais recomendadas
            if include_alternatives:
                try:
                    branches_data = recommendation_service.get_recommendations(
                        user_id=user_id,
                        institution_id=branch.institution_id,
                        service_id=service.id,
                        user_lat=latitude,
                        user_lon=longitude,
                        max_distance_km=10,
                        max_wait_time=30,
                        sort_by='distance'
                    )
                    service_data['recommended_branches'] = [
                        {
                            'branch': {'name': b['branch_name']},
                            'distance': b['distance'],
                            'wait_time': b['wait_time']
                        } for b in branches_data.get('branches', [])
                    ]
                except Exception as e:
                    service_data['recommended_branches'] = []

            # Adicionar filas alternativas
            if include_alternatives:
                alternatives = queue_service.suggest_alternative_queues(
                    queue_id=queue.id,
                    user_id=user_id,
                    user_lat=latitude,
                    user_lon=longitude,
                    max_distance_km=10
                )
                service_data['alternatives'] = [
                    {
                        'institution_name': alt['institution_name'],
                        'branch_name': alt['branch_name'],
                        'wait_time': alt['wait_time']
                    } for alt in alternatives
                ]

            services.append(service_data)

        return jsonify({'services': services}), 200

    @app.route('/api/recommendation/popular', methods=['GET'])
    @require_auth
    def get_popular_recommendations():
        user_id = request.args.get('user_id')
        limit = request.args.get('limit', default=1, type=int)

        if not user_id or user_id != request.user_id:
            return jsonify({'error': 'user_id inválido ou não autorizado'}), 403

        recommendation_service = RecommendationService()
        queue_service = QueueService()

        # Buscar serviços populares com base em tickets emitidos
        popular_services = db.session.query(
            InstitutionService,
            func.count(Ticket.id).label('ticket_count')
        ).join(
            Queue, InstitutionService.id == Queue.service_id
        ).join(
            Ticket, Queue.id == Ticket.queue_id
        ).group_by(
            InstitutionService.id
        ).order_by(
            func.count(Ticket.id).desc()
        ).limit(limit).all()

        services = []
        for service, _ in popular_services:
            # Buscar uma fila ativa para o serviço
            queue_data = db.session.query(
                Queue,
                Department,
                Branch,
                Institution,
                func.coalesce(Queue.estimated_wait_time, 15).label('wait_time')
            ).join(
                Department, Queue.department_id == Department.id
            ).join(
                Branch, Department.branch_id == Branch.id
            ).join(
                Institution, Branch.institution_id == Institution.id
            ).filter(
                Queue.service_id == service.id
            ).first()

            if queue_data:
                queue, department, branch, institution, wait_time = queue_data
                service_data = {
                    'service': {
                        'id': service.id,
                        'name': service.name
                    },
                    'institution': {
                        'id': branch.institution_id,
                        'name': institution.name if institution else 'Desconhecido'
                    },
                    'queue': {
                        'id': queue.id,
                        'institution_name': institution.name if institution else 'Desconhecido',
                        'branch_name': branch.name,
                        'wait_time': f'{int(wait_time)} min'
                    },
                    'reason': 'Serviço popular entre os usuários'
                }
                services.append(service_data)

        return jsonify({'services': services}), 200

    @app.route('/api/user/favorites', methods=['GET'])
    @require_auth
    def get_user_favorites():
        """Retorna as instituições favoritas do usuário para um tipo específico."""
        user_id = request.user_id
        institution_type_id = request.args.get('institution_type_id')

        if not institution_type_id:
            logger.warning(f"Parâmetro institution_type_id ausente para user_id={user_id}")
            return jsonify({'error': 'institution_type_id é obrigatório'}), 400

        cache_k = f"cache:user_favorites:{user_id}:{institution_type_id}"
        try:
            cached_result = redis_client.get(cache_k)
            if cached_result:
                logger.debug(f"Cache hit para {cache_k}")
                return jsonify(json.loads(cached_result)), 200
        except Exception as e:
            logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            # Consulta otimizada usando índices
            preferences = UserPreference.query.filter_by(
                user_id=user_id,
                is_favorite=True
            ).join(Institution, UserPreference.institution_id == Institution.id).filter(
                Institution.institution_type_id == institution_type_id,
                Institution.name.is_not(None)
            ).all()

            results = [
                {
                    'id': pref.institution.id,
                    'name': pref.institution.name,
                    'type': {
                        'id': pref.institution.institution_type_id,
                        'name': pref.institution.type.name if pref.institution.type else 'Desconhecido'
                    },
                    'is_favorite': True,
                    'distance': None,  # Adicionar cálculo de distância se necessário
                    'quality_score': float(pref.institution.quality_score) if pref.institution.quality_score else None
                } for pref in preferences if pref.institution
            ]

            response = {
                'institutions': results,
                'total': len(results),
                'message': 'Nenhuma instituição favorita encontrada' if not results else 'Favoritos listados com sucesso'
            }

            try:
                redis_client.setex(cache_k, 3600, json.dumps(response, default=str))
                logger.info(f"Cache armazenado para {cache_k}")
            except Exception as e:
                logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Favoritos retornados para user_id={user_id}: {len(results)} instituições")
            return jsonify(response), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao obter favoritos para user_id={user_id}: {str(e)}", exc_info=True)
            return jsonify({'error': 'Erro no banco de dados'}), 500
        except Exception as e:
            logger.error(f"Erro ao obter favoritos para user_id={user_id}: {str(e)}", exc_info=True)
            return jsonify({'error': 'Erro interno do servidor'}), 500

    @app.route('/api/users/last-service', methods=['GET'])
    @require_auth
    def get_last_service():
        """Retorna o último serviço acessado pelo usuário."""
        user_id = request.user_id
        cache_key = f"cache:last_service:{user_id}"

        # Verificar cache
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            # Buscar o último comportamento do usuário com ação 'accessed_service'
            last_behavior = UserBehavior.query.filter_by(
                user_id=user_id,
                action='accessed_service'
            ).order_by(UserBehavior.timestamp.desc()).first()

            if not last_behavior:
                logger.info(f"Nenhum serviço recente encontrado para user_id={user_id}")
                return jsonify({'service': None}), 200

            # Buscar a fila associada ao serviço
            queue = Queue.query.filter_by(
                service_id=last_behavior.service_id,
                department_id=last_behavior.branch_id
            ).first()

            if not queue:
                logger.warning(f"Fila não encontrada para service_id={last_behavior.service_id}, branch_id={last_behavior.branch_id}")
                return jsonify({'service': None}), 200

            # Buscar detalhes do serviço, instituição e filial
            service = InstitutionService.query.get(queue.service_id)
            department = Department.query.get(queue.department_id)
            branch = Branch.query.get(department.branch_id)
            institution = Institution.query.get(branch.institution_id)

            if not all([service, department, branch, institution]):
                logger.warning(f"Dados incompletos: service={service}, department={department}, branch={branch}, institution={institution}")
                return jsonify({'service': None}), 200

            # Montar a resposta
            response = {
                'service': {
                    'id': service.id,
                    'name': service.name,
                    'category': {
                        'id': service.category.id if service.category else None,
                        'name': service.category.name if service.category else None
                    } if service.category else None,
                    'description': service.description
                },
                'institution': {
                    'id': institution.id,
                    'name': institution.name,
                    'type': {
                        'id': institution.type.id,
                        'name': institution.type.name
                    }
                },
                'branch': {
                    'id': branch.id,
                    'name': branch.name,
                    'neighborhood': branch.neighborhood,
                    'latitude': branch.latitude,
                    'longitude': branch.longitude
                },
                'queue': {
                    'id': queue.id,
                    'estimated_wait_time': queue.estimated_wait_time,
                    'active_tickets': queue.active_tickets,
                    'current_ticket': queue.current_ticket
                },
                'last_accessed': last_behavior.timestamp.isoformat()
            }

            # Armazenar no cache
            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Último serviço retornado para user_id={user_id}")
            return jsonify(response), 200

        except Exception as e:
            logger.error(f"Erro ao obter último serviço para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter último serviço'}), 500



from flask import jsonify, request, send_file
from flask_socketio import join_room, leave_room, ConnectionRefusedError
from . import db, socketio, redis_client
from .models import AuditLog, Institution,QueueSchedule ,Branch, Queue, Ticket, User, Department, UserRole, InstitutionType, InstitutionService, ServiceCategory, ServiceTag, UserPreference, BranchSchedule, UserBehavior, NotificationLog, Weekday
from .services import QueueService
from .ml_models import wait_time_predictor, service_recommendation_predictor, collaborative_model, demand_model, clustering_model
import uuid
from datetime import datetime, timedelta
import io
import json
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


    @app.route('/api/user/preferences', methods=['POST'])
    @require_auth
    def set_user_preference():
        """Define preferências do usuário."""
        user_id = request.user_id
        data = request.get_json() or {}
        institution_type_id = data.get('institution_type_id')
        institution_id = data.get('institution_id')
        service_category_id = data.get('service_category_id')
        neighborhood = data.get('neighborhood')
        is_client = data.get('is_client', False)
        is_favorite = data.get('is_favorite', False)

        if not any([institution_type_id, institution_id, service_category_id, neighborhood]):
            logger.warning(f"Dados insuficientes para definir preferência: user_id={user_id}")
            return jsonify({'error': 'Pelo menos um critério de preferência é obrigatório'}), 400

        if institution_type_id and not InstitutionType.query.get(institution_type_id):
            logger.warning(f"Tipo de instituição não encontrado: institution_type_id={institution_type_id}")
            return jsonify({'error': 'Tipo de instituição não encontrado'}), 404
        if institution_id and not Institution.query.get(institution_id):
            logger.warning(f"Instituição não encontrada: institution_id={institution_id}")
            return jsonify({'error': 'Instituição não encontrada'}), 404
        if service_category_id and not ServiceCategory.query.get(service_category_id):
            logger.warning(f"Categoria de serviço não encontrada: service_category_id={service_category_id}")
            return jsonify({'error': 'Categoria de serviço não encontrada'}), 404
        if neighborhood and not re.match(r'^[A-Za-zÀ-ÿ\s,]{1,100}$', neighborhood):
            logger.warning(f"Bairro inválido: {neighborhood}")
            return jsonify({'error': 'Bairro inválido'}), 400

        try:
            preference = UserPreference.query.filter_by(
                user_id=user_id,
                institution_type_id=institution_type_id,
                institution_id=institution_id,
                service_category_id=service_category_id,
                neighborhood=neighborhood,
                is_client=is_client
            ).first()

            if not preference:
                preference = UserPreference(
                    user_id=user_id,
                    institution_type_id=institution_type_id,
                    institution_id=institution_id,
                    service_category_id=service_category_id,
                    neighborhood=neighborhood,
                    is_client=is_client,
                    is_favorite=is_favorite,
                    preference_score=1,
                    visit_count=0
                )
                db.session.add(preference)
            else:
                preference.is_favorite = is_favorite
                preference.preference_score += 1
                preference.updated_at = datetime.utcnow()

            db.session.commit()
            AuditLog.create(
                user_id=user_id,
                action="set_preference",
                resource_type="user_preference",
                resource_id=preference.id,
                details=f"Preferência definida: institution_type_id={institution_type_id}, institution_id={institution_id}, service_category_id={service_category_id}, neighborhood={neighborhood}"
            )

            if redis_client:
                try:
                    redis_client.delete(f"cache:user_preferences:{user_id}")
                    logger.info(f"Cache invalidado para user_preferences:{user_id}")
                except Exception as e:
                    logger.warning(f"Erro ao invalidar cache Redis: {e}")

            logger.info(f"Preferência definida para user_id={user_id}")
            return jsonify({'message': 'Preferência definida com sucesso', 'preference_id': preference.id}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao definir preferência para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao definir preferência'}), 500

    @app.route('/api/user/preferences', methods=['GET'])
    @require_auth
    def get_user_preferences():
        """Retorna as preferências do usuário."""
        user_id = request.user_id
        cache_key = f"cache:user_preferences:{user_id}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            preferences = UserPreference.query.filter_by(user_id=user_id).all()
            result = [
                {
                    'id': pref.id,
                    'institution_type': {
                        'id': pref.institution_type.id,
                        'name': pref.institution_type.name
                    } if pref.institution_type else None,
                    'institution': {
                        'id': pref.institution.id,
                        'name': pref.institution.name
                    } if pref.institution else None,
                    'service_category': {
                        'id': pref.service_category.id,
                        'name': pref.service_category.name
                    } if pref.service_category else None,
                    'neighborhood': pref.neighborhood,
                    'is_client': pref.is_client,
                    'is_favorite': pref.is_favorite,
                    'visit_count': pref.visit_count,
                    'last_visited': pref.last_visited.isoformat() if pref.last_visited else None,
                    'preference_score': pref.preference_score
                } for pref in preferences
            ]

            response = {'preferences': result}
            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Preferências retornadas para user_id={user_id}: {len(result)} preferências")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter preferências para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter preferências'}), 500

    @app.route('/api/user/preferences/<preference_id>', methods=['DELETE'])
    @require_auth
    def delete_user_preference(preference_id):
        """Remove uma preferência do usuário."""
        user_id = request.user_id
        preference = UserPreference.query.get(preference_id)
        if not preference:
            logger.warning(f"Preferência não encontrada: preference_id={preference_id}")
            return jsonify({'error': 'Preferência não encontrada'}), 404

        if preference.user_id != user_id:
            logger.warning(f"Tentativa não autorizada de excluir preferência {preference_id} por user_id={user_id}")
            return jsonify({'error': 'Não autorizado'}), 403

        try:
            db.session.delete(preference)
            db.session.commit()
            AuditLog.create(
                user_id=user_id,
                action="delete_preference",
                resource_type="user_preference",
                resource_id=preference_id,
                details=f"Preferência excluída: preference_id={preference_id}"
            )

            if redis_client:
                try:
                    redis_client.delete(f"cache:user_preferences:{user_id}")
                    logger.info(f"Cache invalidado para user_preferences:{user_id}")
                except Exception as e:
                    logger.warning(f"Erro ao invalidar cache Redis: {e}")

            logger.info(f"Preferência {preference_id} excluída para user_id={user_id}")
            return jsonify({'message': 'Preferência excluída com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao excluir preferência {preference_id} para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao excluir preferência'}), 500

    @app.route('/api/queues/totem', methods=['POST'])
    def generate_totem_ticket():
        """Gera um ticket físico via totem, com limite por IP."""
        data = request.get_json() or {}
        queue_id = data.get('queue_id')
        client_ip = request.remote_addr

        if not queue_id:
            logger.warning("queue_id não fornecido")
            return jsonify({'error': 'queue_id é obrigatório'}), 400

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        cache_key = f"totem:throttle:{client_ip}"
        if redis_client.get(cache_key):
            logger.warning(f"Limite de emissão atingido para IP {client_ip}")
            return jsonify({'error': 'Limite de emissão atingido. Tente novamente em 30 segundos'}), 429
        redis_client.setex(cache_key, 30, "1")

        try:
            ticket, pdf_buffer = QueueService.generate_physical_ticket_for_totem(queue_id=queue_id)
            emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue_id,
                event_type='ticket_issued',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'timestamp': ticket.issued_at.isoformat()
                }
            )
            logger.info(f"Ticket físico emitido via totem: {ticket.queue.prefix}{ticket.ticket_number} (IP: {client_ip})")
            return send_file(
                io.BytesIO(pdf_buffer.getvalue()),
                as_attachment=True,
                download_name=f"ticket_{ticket.queue.prefix}{ticket.ticket_number}.pdf",
                mimetype='application/pdf'
            )
        except ValueError as e:
            logger.error(f"Erro ao emitir ticket via totem para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao emitir ticket via totem: {str(e)}")
            return jsonify({'error': 'Erro interno ao emitir ticket'}), 500

    @app.route('/api/services/similar/<service_id>', methods=['GET'])
    def similar_services(service_id):
        """Retorna serviços similares ao serviço especificado."""
        service = InstitutionService.query.get(service_id)
        if not service:
            logger.warning(f"Serviço não encontrado: service_id={service_id}")
            return jsonify({'error': 'Serviço não encontrado'}), 404

        user_id = request.args.get('user_id')
        user_lat = request.args.get('latitude')
        user_lon = request.args.get('longitude')
        limit = request.args.get('limit', '5')

        try:
            limit = int(limit)
            if limit < 1:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"Limite inválido: {limit}")
            return jsonify({'error': 'limit deve ser um número positivo'}), 400

        if user_lat:
            try:
                user_lat = float(user_lat)
            except (ValueError, TypeError):
                logger.warning(f"Latitude inválida: {user_lat}")
                return jsonify({'error': 'Latitude deve ser um número'}), 400
        if user_lon:
            try:
                user_lon = float(user_lon)
            except (ValueError, TypeError):
                logger.warning(f"Longitude inválida: {user_lon}")
                return jsonify({'error': 'Longitude deve ser um número'}), 400

        cache_key = f"cache:similar_services:{service_id}:{user_id}:{user_lat}:{user_lon}:{limit}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            similar_service_ids = collaborative_model.get_similar_services(service_id, n=limit)
            result = []
            for sim_service_id in similar_service_ids:
                sim_service = InstitutionService.query.get(sim_service_id)
                if not sim_service:
                    continue
                queues = Queue.query.filter_by(service_id=sim_service.id).all()
                branch = queues[0].department.branch if queues else None
                distance = QueueService.calculate_distance(user_lat, user_lon, branch) if user_lat and user_lon and branch else None
                quality_score = service_recommendation_predictor.predict_service(sim_service, user_id)
                result.append({
                    'id': sim_service.id,
                    'name': sim_service.name,
                    'institution': {
                        'id': sim_service.institution.id,
                        'name': sim_service.institution.name
                    },
                    'category': {
                        'id': sim_service.category.id,
                        'name': sim_service.category.name
                    } if sim_service.category else None,
                    'distance_km': float(distance) if distance is not None else 'Desconhecida',
                    'quality_score': float(quality_score)
                })

            response = {'service_id': service_id, 'similar_services': result}
            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Serviços similares retornados para service_id={service_id}: {len(result)} serviços")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter serviços similares para service_id={service_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter serviços similares'}), 500

    @app.route('/api/search/structured', methods=['GET'])
    def search_structured():
        """Busca estruturada por serviços, instituições, filiais e filas."""
        query = request.args.get('query', '').strip()
        institution_type_id = request.args.get('institution_type_id')
        service_category_id = request.args.get('service_category_id')
        neighborhood = request.args.get('neighborhood')
        user_lat = request.args.get('latitude')
        user_lon = request.args.get('longitude')
        page = request.args.get('page', '1')
        per_page = request.args.get('per_page', '20')

        if query and not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', query):
            logger.warning(f"Query inválida: {query}")
            return jsonify({'error': 'Query inválida'}), 400
        if institution_type_id and not InstitutionType.query.get(institution_type_id):
            logger.warning(f"Tipo de instituição não encontrado: institution_type_id={institution_type_id}")
            return jsonify({'error': 'Tipo de instituição não encontrado'}), 404
        if service_category_id and not ServiceCategory.query.get(service_category_id):
            logger.warning(f"Categoria de serviço não encontrada: service_category_id={service_category_id}")
            return jsonify({'error': 'Categoria de serviço não encontrada'}), 404
        if neighborhood and not re.match(r'^[A-Za-zÀ-ÿ\s,]{1,100}$', neighborhood):
            logger.warning(f"Bairro inválido: {neighborhood}")
            return jsonify({'error': 'Bairro inválido'}), 400
        if user_lat:
            try:
                user_lat = float(user_lat)
            except (ValueError, TypeError):
                logger.warning(f"Latitude inválida: {user_lat}")
                return jsonify({'error': 'Latitude deve ser um número'}), 400
        if user_lon:
            try:
                user_lon = float(user_lon)
            except (ValueError, TypeError):
                logger.warning(f"Longitude inválida: {user_lon}")
                return jsonify({'error': 'Longitude deve ser um número'}), 400
        try:
            page = int(page)
            per_page = int(per_page)
            if page < 1 or per_page < 1:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
            return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

        cache_key = f"cache:search_structured:{query}:{institution_type_id}:{service_category_id}:{neighborhood}:{user_lat}:{user_lon}:{page}:{per_page}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            services = InstitutionService.query
            if query:
                services = services.filter(InstitutionService.name.ilike(f'%{query}%'))
            if institution_type_id:
                services = services.join(Institution).filter(Institution.institution_type_id == institution_type_id)
            if service_category_id:
                services = services.filter_by(category_id=service_category_id)

            services = services.all()
            result = []
            for service in services:
                queues = Queue.query.filter_by(service_id=service.id).all()
                for queue in queues:
                    branch = queue.department.branch
                    if neighborhood and branch.neighborhood != neighborhood:
                        continue
                    distance = QueueService.calculate_distance(user_lat, user_lon, branch) if user_lat and user_lon else None
                    result.append({
                        'service': {
                            'id': service.id,
                            'name': service.name,
                            'category': {
                                'id': service.category.id,
                                'name': service.category.name
                            } if service.category else None
                        },
                        'queue': {
                            'id': queue.id,
                            'prefix': queue.prefix,
                            'estimated_wait_time': f"{int(queue.estimated_wait_time)} minutos" if queue.estimated_wait_time else "N/A",
                            'active_tickets': queue.active_tickets
                        },
                        'branch': {
                            'id': branch.id,
                            'name': branch.name,
                            'neighborhood': branch.neighborhood,
                            'latitude': float(branch.latitude) if branch.latitude else None,
                            'longitude': float(branch.longitude) if branch.longitude else None,
                            'distance_km': float(distance) if distance is not None else 'Desconhecida'
                        },
                        'institution': {
                            'id': service.institution.id,
                            'name': service.institution.name
                        }
                    })

            total_results = len(result)
            start = (page - 1) * per_page
            end = start + per_page
            paginated_result = result[start:end]

            response = {
                'results': paginated_result,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_results': total_results,
                    'total_pages': (total_results + per_page - 1) // per_page
                }
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Busca estruturada retornada: {len(paginated_result)} resultados")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao realizar busca estruturada: {str(e)}")
            return jsonify({'error': 'Erro ao realizar busca estruturada'}), 500

    @app.route('/api/recommendations/featured', methods=['GET'])
    def featured_recommendations():
        """Retorna recomendações destacadas com base nas preferências do usuário."""
        user_id = request.args.get('user_id')
        user_lat = request.args.get('latitude')
        user_lon = request.args.get('longitude')
        limit = request.args.get('limit', '5')

        if user_lat:
            try:
                user_lat = float(user_lat)
            except (ValueError, TypeError):
                logger.warning(f"Latitude inválida: {user_lat}")
                return jsonify({'error': 'Latitude deve ser um número'}), 400
        if user_lon:
            try:
                user_lon = float(user_lon)
            except (ValueError, TypeError):
                logger.warning(f"Longitude inválida: {user_lon}")
                return jsonify({'error': 'Longitude deve ser um número'}), 400
        try:
            limit = int(limit)
            if limit < 1:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"Limite inválido: {limit}")
            return jsonify({'error': 'limit deve ser um número positivo'}), 400

        cache_key = f"cache:featured_recommendations:{user_id}:{user_lat}:{user_lon}:{limit}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            recommendations = collaborative_model.get_recommendations_for_user(user_id, n=limit)
            result = []
            for queue_id in recommendations:
                queue = Queue.query.get(queue_id)
                if not queue:
                    continue
                branch = queue.department.branch
                distance = QueueService.calculate_distance(user_lat, user_lon, branch) if user_lat and user_lon else None
                quality_score = service_recommendation_predictor.predict(queue, user_id, user_lat, user_lon)
                explanation = []
                if distance is not None:
                    explanation.append(f"Filial a {distance:.2f} km")
                if queue.estimated_wait_time:
                    explanation.append(f"Espera de {int(queue.estimated_wait_time)} min")
                if quality_score > 0.8:
                    explanation.append("Alta qualidade")
                result.append({
                    'queue_id': queue.id,
                    'service': {
                        'id': queue.service.id,
                        'name': queue.service.name
                    },
                    'branch': {
                        'id': branch.id,
                        'name': branch.name,
                        'neighborhood': branch.neighborhood
                    },
                    'institution': {
                        'id': branch.institution.id,
                        'name': branch.institution.name
                    },
                    'wait_time': f"{int(queue.estimated_wait_time)} minutos" if queue.estimated_wait_time else "N/A",
                    'distance_km': float(distance) if distance is not None else 'Desconhecida',
                    'quality_score': float(quality_score),
                    'explanation': "; ".join(explanation) or "Recomendado com base nas suas preferências"
                })

            response = {'recommendations': result}
            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Recomendações destacadas retornadas para user_id={user_id}: {len(result)} recomendações")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter recomendações destacadas para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter recomendações destacadas'}), 500

    @app.route('/api/services/search', methods=['GET'])
    def search_all_services():
        """Busca todos os serviços disponíveis."""
        query = request.args.get('query', '').strip()
        page = request.args.get('page', '1')
        per_page = request.args.get('per_page', '20')

        if query and not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', query):
            logger.warning(f"Query inválida: {query}")
            return jsonify({'error': 'Query inválida'}), 400
        try:
            page = int(page)
            per_page = int(per_page)
            if page < 1 or per_page < 1:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
            return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

        cache_key = f"cache:search_all_services:{query}:{page}:{per_page}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            services = InstitutionService.query
            if query:
                services = services.filter(InstitutionService.name.ilike(f'%{query}%'))

            services = services.paginate(page=page, per_page=per_page, error_out=False)
            result = [
                {
                    'id': s.id,
                    'name': s.name,
                    'institution': {
                        'id': s.institution.id,
                        'name': s.institution.name
                    },
                    'category': {
                        'id': s.category.id,
                        'name': s.category.name
                    } if s.category else None,
                    'description': s.description or "Sem descrição"
                } for s in services.items
            ]

            response = {
                'services': result,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_results': services.total,
                    'total_pages': services.pages
                }
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Serviços retornados: {len(result)} resultados")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao buscar serviços: {str(e)}")
            return jsonify({'error': 'Erro ao buscar serviços'}), 500

    @app.route('/api/queues/<queue_id>/stats', methods=['GET'])
    @require_auth
    def queue_stats(queue_id):
        """Retorna estatísticas detalhadas de uma fila."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar estatísticas por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {user_id} não tem permissão para acessar estatísticas da fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para acessar estatísticas na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        cache_key = f"cache:queue_stats:{queue_id}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            tickets = Ticket.query.filter_by(queue_id=queue_id).all()
            status_distribution = {
                'Pendente': 0,
                'Chamado': 0,
                'Atendido': 0,
                'Cancelado': 0
            }
            for t in tickets:
                status_distribution[t.status] += 1

            peak_hours = db.session.query(
                func.extract('hour', Ticket.issued_at).label('hour'),
                func.count().label('ticket_count')
            ).filter_by(queue_id=queue_id).group_by('hour').order_by('ticket_count').limit(5).all()

            response = {
                'queue_id': queue_id,
                'service': queue.service.name,
                'branch': queue.department.branch.name,
                'stats': {
                    'total_tickets': len(tickets),
                    'active_tickets': queue.active_tickets,
                    'avg_wait_time': f"{int(queue.avg_wait_time)} minutos" if queue.avg_wait_time else "N/A",
                    'avg_service_time': f"{int(queue.last_service_time)} minutos" if queue.last_service_time else "N/A",
                    'status_distribution': status_distribution,
                    'peak_hours': [
                        {'hour': int(h.hour), 'ticket_count': h.ticket_count} for h in peak_hours
                    ],
                    'predicted_demand': float(demand_model.predict(queue_id, hours_ahead=1))
                }
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Estatísticas retornadas para queue_id={queue_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter estatísticas da fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter estatísticas'}), 500

    @app.route('/api/branches/<branch_id>/schedule', methods=['GET'])
    def get_branch_schedule(branch_id):
        """Retorna o horário de funcionamento de uma filial."""
        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial não encontrada: branch_id={branch_id}")
            return jsonify({'error': 'Filial não encontrada'}), 404

        cache_key = f"cache:branch_schedule:{branch_id}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            schedules = BranchSchedule.query.filter_by(branch_id=branch_id).all()
            result = [
                {
                    'id': s.id,
                    'weekday': s.weekday.value,
                    'open_time': s.open_time.strftime('%H:%M') if s.open_time else None,
                    'end_time': s.end_time.strftime('%H:%M') if s.end_time else None,
                    'is_closed': s.is_closed
                } for s in schedules
            ]

            response = {'branch_id': branch_id, 'schedules': result}
            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Horários da filial retornados para branch_id={branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter horários da filial {branch_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter horários da filial'}), 500

    @app.route('/api/branches/<branch_id>/schedule', methods=['POST'])
    @require_auth
    def update_branch_schedule(branch_id):
        """Atualiza o horário de funcionamento de uma filial."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de atualizar horário por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial não encontrada: branch_id={branch_id}")
            return jsonify({'error': 'Filial não encontrada'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and branch.id != user.branch_id:
            logger.warning(f"Usuário {user_id} não tem permissão para atualizar horário da filial {branch_id}")
            return jsonify({'error': 'Sem permissão para esta filial'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para atualizar horário na instituição {branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        data = request.get_json() or {}
        if not isinstance(data, list):
            logger.warning("Dados de horário devem ser uma lista")
            return jsonify({'error': 'Dados de horário devem ser uma lista'}), 400

        try:
            for schedule_data in data:
                schedule_id = schedule_data.get('id')
                weekday = schedule_data.get('weekday')
                open_time = schedule_data.get('open_time')
                end_time = schedule_data.get('end_time')
                is_closed = schedule_data.get('is_closed', False)

                if weekday not in [w.value for w in Weekday]:
                    logger.warning(f"Dia da semana inválido: {weekday}")
                    return jsonify({'error': f'Dia da semana inválido: {weekday}'}), 400

                if not is_closed:
                    if not open_time or not end_time:
                        logger.warning("open_time e end_time são obrigatórios se não for fechado")
                        return jsonify({'error': 'open_time e end_time são obrigatórios se não for fechado'}), 400
                    try:
                        open_time = datetime.strptime(open_time, '%H:%M').time()
                        end_time = datetime.strptime(end_time, '%H:%M').time()
                    except ValueError:
                        logger.warning(f"Formato de horário inválido: open_time={open_time}, end_time={end_time}")
                        return jsonify({'error': 'Formato de horário inválido. Use HH:MM'}), 400

                schedule = BranchSchedule.query.filter_by(id=schedule_id, branch_id=branch_id).first() if schedule_id else None
                if not schedule:
                    logger.warning(f"Horário não encontrado: schedule_id={schedule_id}")
                    return jsonify({'error': f'Horário não encontrado: {schedule_id}'}), 404

                schedule.weekday = weekday
                schedule.is_closed = is_closed
                if not is_closed:
                    schedule.open_time = open_time
                    schedule.end_time = end_time
                else:
                    schedule.open_time = None
                    schedule.end_time = None

            db.session.commit()
            AuditLog.create(
                user_id=user_id,
                action="update_branch_schedule",
                resource_type="branch_schedule",
                resource_id=branch_id,
                details=f"Horários atualizados para branch_id={branch_id}"
            )

            if redis_client:
                try:
                    redis_client.delete(f"cache:branch_schedule:{branch_id}")
                    logger.info(f"Cache invalidado para branch_schedule:{branch_id}")
                except Exception as e:
                    logger.warning(f"Erro ao invalidar cache Redis: {e}")

            logger.info(f"Horários atualizados para branch_id={branch_id}")
            return jsonify({'message': 'Horários atualizados com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar horários da filial {branch_id}: {str(e)}")
            return jsonify({'error': 'Erro ao atualizar horários'}), 500

    @app.route('/api/branches/<branch_id>/schedule/create', methods=['POST'])
    @require_auth
    def create_branch_schedule(branch_id):
        """Cria um novo horário para uma filial."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de criar horário por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial não encontrada: branch_id={branch_id}")
            return jsonify({'error': 'Filial não encontrada'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and branch.id != user.branch_id:
            logger.warning(f"Usuário {user_id} não tem permissão para criar horário da filial {branch_id}")
            return jsonify({'error': 'Sem permissão para esta filial'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para criar horário na instituição {branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        data = request.get_json() or {}
        weekday = data.get('weekday')
        open_time = data.get('open_time')
        end_time = data.get('end_time')
        is_closed = data.get('is_closed', False)

        if not weekday:
            logger.warning("weekday é obrigatório")
            return jsonify({'error': 'weekday é obrigatório'}), 400
        if weekday not in [w.value for w in Weekday]:
            logger.warning(f"Dia da semana inválido: {weekday}")
            return jsonify({'error': f'Dia da semana inválido: {weekday}'}), 400

        if not is_closed:
            if not open_time or not end_time:
                logger.warning("open_time e end_time são obrigatórios se não for fechado")
                return jsonify({'error': 'open_time e end_time são obrigatórios se não for fechado'}), 400
            try:
                open_time = datetime.strptime(open_time, '%H:%M').time()
                end_time = datetime.strptime(end_time, '%H:%M').time()
            except ValueError:
                logger.warning(f"Formato de horário inválido: open_time={open_time}, end_time={end_time}")
                return jsonify({'error': 'Formato de horário inválido. Use HH:MM'}), 400

        try:
            existing_schedule = BranchSchedule.query.filter_by(branch_id=branch_id, weekday=weekday).first()
            if existing_schedule:
                logger.warning(f"Horário já existe para branch_id={branch_id}, weekday={weekday}")
                return jsonify({'error': f'Horário já existe para {weekday}'}), 400

            schedule = BranchSchedule(
                branch_id=branch_id,
                weekday=weekday,
                open_time=open_time if not is_closed else None,
                end_time=end_time if not is_closed else None,
                is_closed=is_closed
            )
            db.session.add(schedule)
            db.session.commit()
            AuditLog.create(
                user_id=user_id,
                action="create_branch_schedule",
                resource_type="branch_schedule",
                resource_id=schedule.id,
                details=f"Horário criado para branch_id={branch_id}, weekday={weekday}"
            )

            if redis_client:
                try:
                    redis_client.delete(f"cache:branch_schedule:{branch_id}")
                    logger.info(f"Cache invalidado para branch_schedule:{branch_id}")
                except Exception as e:
                    logger.warning(f"Erro ao invalidar cache Redis: {e}")

            logger.info(f"Horário criado para branch_id={branch_id}, weekday={weekday}")
            return jsonify({'message': 'Horário criado com sucesso', 'schedule_id': schedule.id}), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao criar horário para branch_id={branch_id}: {str(e)}")
            return jsonify({'error': 'Erro ao criar horário'}), 500


    @app.route('/api/queues/<queue_id>/predict-wait-time', methods=['GET'])
    def predict_wait_time(queue_id):
        """Prediz o tempo de espera para uma fila."""
        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        priority = request.args.get('priority', 0)
        user_lat = request.args.get('latitude')
        user_lon = request.args.get('longitude')

        try:
            priority = int(priority)
            if priority < 0:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"Prioridade inválida: {priority}")
            return jsonify({'error': 'Prioridade deve ser um número inteiro não negativo'}), 400

        if user_lat:
            try:
                user_lat = float(user_lat)
            except (ValueError, TypeError):
                logger.warning(f"Latitude inválida: {user_lat}")
                return jsonify({'error': 'Latitude deve ser um número'}), 400
        if user_lon:
            try:
                user_lon = float(user_lon)
            except (ValueError, TypeError):
                logger.warning(f"Longitude inválida: {user_lon}")
                return jsonify({'error': 'Longitude deve ser um número'}), 400

        cache_key = f"cache:predict_wait_time:{queue_id}:{priority}:{user_lat}:{user_lon}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            wait_time = QueueService.calculate_wait_time(
                queue_id=queue_id,
                ticket_number=queue.current_ticket + 1,
                priority=priority,
                user_lat=user_lat,
                user_lon=user_lon
            )
            response = {
                'queue_id': queue_id,
                'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
                'active_tickets': queue.active_tickets,
                'predicted_demand': float(demand_model.predict(queue_id, hours_ahead=1))
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Tempo de espera predito para queue_id={queue_id}: {response['wait_time']}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao predizer tempo de espera para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao predizer tempo de espera'}), 500

 

    @app.route('/api/institutions/<institution_id>/dashboard', methods=['GET'])
    @require_auth
    def institution_dashboard(institution_id):
        """Retorna dados para o painel de uma instituição."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar painel por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição não encontrada: institution_id={institution_id}")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        if user.user_role == UserRole.INSTITUTION_ADMIN and institution.id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para acessar painel da instituição {institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        cache_key = f"cache:institution_dashboard:{institution_id}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            branches = Branch.query.filter_by(institution_id=institution_id).all()
            branch_ids = [b.id for b in branches]
            department_ids = [d.id for d in Department.query.filter(Department.branch_id.in_(branch_ids)).all()]
            queues = Queue.query.filter(Queue.department_id.in_(department_ids)).all()

            total_tickets = sum(q.active_tickets for q in queues)
            avg_wait_time = sum(q.avg_wait_time or 0 for q in queues) / len(queues) if queues else 0
            quality_scores = [service_recommendation_predictor.predict(q) for q in queues]
            avg_quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0

            response = {
                'institution_id': institution_id,
                'name': institution.name,
                'stats': {
                    'total_branches': len(branches),
                    'total_queues': len(queues),
                    'total_tickets': total_tickets,
                    'avg_wait_time': f"{int(avg_wait_time)} minutos" if avg_wait_time else "N/A",
                    'avg_quality_score': float(avg_quality_score),
                    'predicted_demand': float(demand_model.predict_institution(institution_id, hours_ahead=1))
                },
                'branches': [
                    {
                        'id': b.id,
                        'name': b.name,
                        'queues': [
                            {
                                'id': q.id,
                                'service': q.service.name,
                                'active_tickets': q.active_tickets,
                                'estimated_wait_time': f"{int(q.estimated_wait_time)} minutos" if q.estimated_wait_time else "N/A"
                            } for q in queues if q.department.branch_id == b.id
                        ]
                    } for b in branches
                ]
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Dados do painel retornados para institution_id={institution_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter dados do painel para institution_id={institution_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter dados do painel'}), 500

    @socketio.on('connect', namespace='/')
    def handle_connect():
        """Gerencia conexão WebSocket."""
        try:
            token = request.args.get('token')
            if not token:
                logger.warning("Token não fornecido na conexão WebSocket")
                raise ConnectionRefusedError('Token não fornecido')

            decoded_token = auth.verify_id_token(token)
            user_id = decoded_token.get('uid')
            if not user_id:
                logger.warning("ID do usuário não encontrado no token")
                raise ConnectionRefusedError('ID do usuário inválido')

            join_room(user_id)
            logger.info(f"Usuário {user_id} conectado ao WebSocket")
        except Exception as e:
            logger.error(f"Erro na conexão WebSocket: {str(e)}")
            raise ConnectionRefusedError('Autenticação falhou')

    @socketio.on('disconnect', namespace='/')
    def handle_disconnect():
        """Gerencia desconexão WebSocket."""
        try:
            user_id = request.sid
            leave_room(user_id)
            logger.info(f"Usuário {user_id} desconectado do WebSocket")
        except Exception as e:
            logger.error(f"Erro na desconexão WebSocket: {str(e)}")

    @socketio.on('connect', namespace='/dashboard')
    def handle_dashboard_connect():
        """Gerencia conexão WebSocket para painel."""
        try:
            token = request.args.get('token')
            if not token:
                logger.warning("Token não fornecido na conexão WebSocket do painel")
                raise ConnectionRefusedError('Token não fornecido')

            decoded_token = auth.verify_id_token(token)
            user_id = decoded_token.get('uid')
            user = User.query.get(user_id)
            if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
                logger.warning(f"Usuário {user_id} não autorizado para painel")
                raise ConnectionRefusedError('Acesso não autorizado')

            institution_id = user.institution_id if user.user_role == UserRole.INSTITUTION_ADMIN else request.args.get('institution_id')
            if not institution_id:
                logger.warning("institution_id não fornecido")
                raise ConnectionRefusedError('institution_id não fornecido')

            join_room(institution_id)
            logger.info(f"Usuário {user_id} conectado ao painel WebSocket para institution_id={institution_id}")
        except Exception as e:
            logger.error(f"Erro na conexão WebSocket do painel: {str(e)}")
            raise ConnectionRefusedError('Autenticação falhou')

    @socketio.on('disconnect', namespace='/dashboard')
    def handle_dashboard_disconnect():
        """Gerencia desconexão WebSocket para painel."""
        try:
            user_id = request.sid
            logger.info(f"Usuário {user_id} desconectado do painel WebSocket")
        except Exception as e:
            logger.error(f"Erro na desconexão WebSocket do painel: {str(e)}")
            
    @app.route("/api/ping")
    def ping():
        return "pong", 200



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
                    'distance': float(distance) if distance is not None else None,
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
                return jsonify({'error': 'Página e itens por página devem ser positivos'}), 400
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
            query_base = Queue.query.join(Department).join(InstitutionService).join(QueueSchedule).filter(
                Department.branch_id == branch_id,
                QueueSchedule.weekday == getattr(Weekday, now.strftime('%A').upper(), None),
                QueueSchedule.is_closed == False,
                QueueSchedule.open_time <= now.time(),
                QueueSchedule.end_time >= now.time(),
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
                wait_time = RecommendationService.wait_time_predictor.predict(
                    queue_id=queue.id,
                    position=queue.active_tickets + 1,
                    active_tickets=queue.active_tickets,
                    priority=0,
                    hour_of_day=now.hour,
                    user_id=user_id
                )
                if max_wait_time and isinstance(wait_time, (int, float)) and wait_time > max_wait_time:
                    continue

                schedule = QueueSchedule.query.filter_by(
                    queue_id=queue.id,
                    weekday=getattr(Weekday, now.strftime('%A').upper(), None)
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
                'name': t.name or 'Desconhecido'
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

    @app.route('/institutions/<institution_id>/services', methods=['GET'])
    def services_by_institution(institution_id):
        """Lista serviços disponíveis para uma instituição, com informações de disponibilidade e tempo de espera."""
        try:
            user_id = request.args.get('user_id')
            category_id = request.args.get('category_id')
            max_wait_time = request.args.get('max_wait_time', type=float)
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 10))
            sort_by = request.args.get('sort_by', 'name')  # Opções: name, wait_time

            # Validar entrada
            if page < 1 or per_page < 1:
                logger.warning(f"Parâmetros inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'Página e itens por página devem ser positivos'}), 400
            if sort_by not in ['name', 'wait_time']:
                logger.warning(f"Ordenação inválida: sort_by={sort_by}")
                return jsonify({'error': 'Ordenação deve ser por "name" ou "wait_time"'}), 400

            # Verificar cache
            cache_params = {
                'institution_id': institution_id,
                'user_id': user_id,
                'category_id': category_id,
                'max_wait_time': max_wait_time,
                'page': page,
                'per_page': per_page,
                'sort_by': sort_by
            }
            cache_k = cache_key('services_by_institution', **cache_params)
            cached_result = redis_client.get(cache_k)
            if cached_result:
                logger.debug(f"Cache hit para services_by_institution: {cache_k}")
                return jsonify(json.loads(cached_result))

            # Verificar se a instituição existe
            institution = Institution.query.get(institution_id)
            if not institution:
                logger.warning(f"Instituição não encontrada: institution_id={institution_id}")
                return jsonify({'error': 'Instituição não encontrada'}), 404

            # Consultar serviços da instituição
            services_query = InstitutionService.query.filter_by(institution_id=institution_id)
            if category_id:
                services_query = services_query.filter_by(category_id=category_id)

            # Obter serviços
            services = services_query.all()
            total = len(services)
            logger.debug(f"Total de serviços encontrados para institution_id={institution_id}: {total}")

            # Consultar filas ativas para cada serviço
            now = datetime.utcnow()
            results = []
            for service in services:
                # Encontrar uma fila ativa para o serviço
                queue = Queue.query.join(Department).join(Branch).join(QueueSchedule).filter(
                    Queue.service_id == service.id,
                    Branch.institution_id == institution_id,
                    QueueSchedule.weekday == getattr(Weekday, now.strftime('%A').upper(), None),
                    QueueSchedule.is_closed == False,
                    QueueSchedule.open_time <= now.time(),
                    QueueSchedule.end_time >= now.time(),
                    Queue.active_tickets < Queue.daily_limit
                ).first()

                # Calcular tempo de espera (se houver fila ativa)
                wait_time = None
                queue_info = {}
                if queue:
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

                    schedule = QueueSchedule.query.filter_by(
                        queue_id=queue.id,
                        weekday=getattr(Weekday, now.strftime('%A').upper(), None)
                    ).first()
                    queue_info = {
                        'queue_id': queue.id,
                        'branch': {
                            'id': queue.department.branch.id,
                            'name': queue.department.branch.name or 'Desconhecida'
                        },
                        'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else 'Aguardando início',
                        'active_tickets': queue.active_tickets or 0,
                        'daily_limit': queue.daily_limit or 100,
                        'open_time': schedule.open_time.strftime('%H:%M') if schedule and schedule.open_time else None,
                        'end_time': schedule.end_time.strftime('%H:%M') if schedule and schedule.end_time else None
                    }

                results.append({
                    'service': {
                        'id': service.id,
                        'name': service.name or 'Desconhecido',
                        'category_id': service.category_id,
                        'description': service.description or 'Sem descrição'
                    },
                    'is_available': bool(queue),
                    **queue_info
                })

            # Paginação
            start = (page - 1) * per_page
            end = start + per_page
            paginated_results = results[start:end]

            # Ordenação
            if sort_by == 'wait_time':
                paginated_results.sort(
                    key=lambda x: float(x['wait_time'].split()[0]) if 'wait_time' in x and x['wait_time'] != 'Aguardando início' else float('inf')
                )
            else:
                paginated_results.sort(key=lambda x: x['service']['name'])

            result = {
                'services': paginated_results,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page,
                'message': 'Nenhum serviço encontrado' if not results else 'Serviços listados com sucesso'
            }

            # Cachear resultado
            redis_client.setex(cache_k, 60, json.dumps(result, default=str))
            logger.info(f"Lista de serviços retornada para institution_id={institution_id}: {total} resultados, cache_key={cache_k}")

            return jsonify(result)
        except Exception as e:
            logger.error(f"Erro ao listar serviços da instituição {institution_id}: {str(e)}")
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


    @app.route('/institutions/<institution_id>', methods=['GET'])
    @require_auth
    def get_institution(institution_id):
        """Retorna os detalhes de uma instituição específica."""
        try:
            logger.debug(f"Buscando instituição: {institution_id}")
            institution = Institution.query.get(institution_id)
            if not institution:
                logger.warning(f"Instituição não encontrada: {institution_id}")
                return jsonify({'error': 'Instituição não encontrada'}), 404

            institution_type = InstitutionType.query.get(institution.institution_type_id)
            response = {
                'id': institution.id,
                'name': institution.name or 'Desconhecida',
                'type': {
                    'id': institution.institution_type_id,
                    'name': institution_type.name if institution_type else 'Desconhecido'
                },
                'description': institution.description or 'Sem descrição'
            }
            logger.debug(f"Resposta para instituição {institution_id}: {response}")
            return jsonify(response)
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao buscar instituição {institution_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados'}), 500
        except Exception as e:
            logger.error(f"Erro ao buscar instituição {institution_id}: {str(e)}")
            return jsonify({'error': 'Erro interno do servidor'}), 500
    
    @app.route('/institutions/<institution_id>/services/<service_id>/branches', methods=['GET'])
    def branches_by_service(institution_id, service_id):
        """Lista filiais de uma instituição que oferecem um serviço específico, ordenadas por distância ou tempo de espera."""
        try:
            user_id = request.args.get('user_id')
            user_lat = request.args.get('user_lat', type=float)
            user_lon = request.args.get('user_lon', type=float)
            max_distance_km = request.args.get('max_distance_km', 10.0, type=float)
            max_wait_time = request.args.get('max_wait_time', type=float)
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 10))
            sort_by = request.args.get('sort_by', 'distance')  # Opções: distance, wait_time

            # Validar entrada
            if page < 1 or per_page < 1:
                logger.warning(f"Parâmetros inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'Página e itens por página devem ser positivos'}), 400
            if sort_by not in ['distance', 'wait_time']:
                logger.warning(f"Ordenação inválida: sort_by={sort_by}")
                return jsonify({'error': 'Ordenação deve ser por "distance" ou "wait_time"'}), 400
            if user_lat is None or user_lon is None:
                logger.warning("Coordenadas do usuário são necessárias")
                return jsonify({'error': 'Coordenadas do usuário (user_lat e user_lon) são necessárias'}), 400

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

            # Verificar se a instituição e o serviço existem
            institution = Institution.query.get(institution_id)
            if not institution:
                logger.warning(f"Instituição não encontrada: institution_id={institution_id}")
                return jsonify({'error': 'Instituição não encontrada'}), 404

            service = InstitutionService.query.get(service_id)
            if not service or service.institution_id != institution_id:
                logger.warning(f"Serviço não encontrado ou não pertence à instituição: service_id={service_id}")
                return jsonify({'error': 'Serviço não encontrado ou não pertence à instituição'}), 404

            # Construir consulta para filas ativas do serviço
            now = datetime.utcnow()
            queues = Queue.query.join(Department).join(Branch).join(QueueSchedule).filter(
                Queue.service_id == service_id,
                Branch.institution_id == institution_id,
                QueueSchedule.weekday == getattr(Weekday, now.strftime('%A').upper(), None),
                QueueSchedule.is_closed == False,
                QueueSchedule.open_time <= now.time(),
                QueueSchedule.end_time >= now.time(),
                Queue.active_tickets < Queue.daily_limit
            ).all()

            # Filtrar por distância e tempo de espera
            results = []
            for queue in queues:
                branch = queue.department.branch
                if not branch.latitude or not branch.longitude:
                    continue

                distance = RecommendationService.calculate_distance(user_lat, user_lon, branch)
                if distance > max_distance_km:
                    continue

                wait_time = RecommendationService.wait_time_predictor.predict(
                    queue_id=queue.id,
                    position=queue.active_tickets + 1,
                    active_tickets=queue.active_tickets,
                    priority=0,
                    hour_of_day=now.hour,
                    user_id=user_id
                )
                if max_wait_time and isinstance(wait_time, (int, float)) and wait_time > max_wait_time:
                    continue

                schedule = QueueSchedule.query.filter_by(
                    queue_id=queue.id,
                    weekday=getattr(Weekday, now.strftime('%A').upper(), None)
                ).first()

                results.append({
                    'branch': {
                        'id': branch.id,
                        'name': branch.name or 'Desconhecida',
                        'location': branch.location or 'Desconhecida',
                        'neighborhood': branch.neighborhood or 'Desconhecido',
                        'latitude': float(branch.latitude),
                        'longitude': float(branch.longitude),
                        'distance': float(distance)
                    },
                    'queue': {
                        'id': queue.id,
                        'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else 'Aguardando início',
                        'active_tickets': queue.active_tickets or 0,
                        'daily_limit': queue.daily_limit or 100,
                        'open_time': schedule.open_time.strftime('%H:%M') if schedule and schedule.open_time else None,
                        'end_time': schedule.end_time.strftime('%H:%M') if schedule and schedule.end_time else None
                    }
                })

            # Contar total
            total = len(results)
            logger.debug(f"Total de filiais encontradas para institution_id={institution_id}, service_id={service_id}: {total}")

            # Paginação
            start = (page - 1) * per_page
            end = start + per_page
            paginated_results = results[start:end]

            # Ordenação
            if sort_by == 'wait_time':
                paginated_results.sort(
                    key=lambda x: float(x['queue']['wait_time'].split()[0]) if x['queue']['wait_time'] != 'Aguardando início' else float('inf')
                )
            else:
                paginated_results.sort(key=lambda x: x['branch']['distance'])

            result = {
                'branches': paginated_results,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page,
                'message': 'Nenhuma filial encontrada' if not paginated_results else 'Filiais sugeridas com sucesso'
            }

            # Cachear resultado
            redis_client.setex(cache_k, 60, json.dumps(result, default=str))
            logger.info(f"Lista de filiais retornada para institution_id={institution_id}, service_id={service_id}: {total} resultados, cache_key={cache_k}")

            return jsonify(result)
        except Exception as e:
            logger.error(f"Erro ao listar filiais para institution_id={institution_id}, service_id={service_id}: {str(e)}")
            return jsonify({'error': 'Erro interno do servidor'}), 500
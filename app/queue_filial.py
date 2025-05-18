from flask import jsonify, request, send_file
from flask_socketio import join_room, leave_room, ConnectionRefusedError

from app.utils.websocket_utils import emit_ticket_update
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

def init_queue_filial(app):
    
    def cache_key(endpoint, **kwargs):
        """Gera uma chave de cache única para o endpoint com base nos parâmetros."""
        params = ':'.join(f"{k}={v}" for k, v in sorted(kwargs.items()) if v is not None)
        return f"{endpoint}:{params}"


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
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao realizar busca estruturada: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao realizar busca estruturada'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao realizar busca estruturada: {str(e)}")
            return jsonify({'error': 'Erro interno ao realizar busca estruturada'}), 500

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
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao obter recomendações destacadas para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao obter recomendações destacadas'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao obter recomendações destacadas para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao obter recomendações destacadas'}), 500

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
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao buscar serviços: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao buscar serviços'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar serviços: {str(e)}")
            return jsonify({'error': 'Erro interno ao buscar serviços'}), 500

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
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao obter estatísticas da fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao obter estatísticas'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao obter estatísticas da fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao obter estatísticas'}), 500

    @app.route('/api/branches/<branch_id>/schedule', methods=['GET'])
    def get_branch_schedul(branch_id):
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
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao obter horários da filial {branch_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao obter horários da filial'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao obter horários da filial {branch_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao obter horários da filial'}), 500




    @app.route('/api/branches/<branch_id>/schedule', methods=['POST'])
    @require_auth
    def update_branch_schedul(branch_id):
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
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro no banco de dados ao atualizar horários da filial {branch_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao atualizar horários'}), 500
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao atualizar horários da filial {branch_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao atualizar horários'}), 500

    @app.route('/api/branches/<branch_id>/schedule/create', methods=['POST'])
    @require_auth
    def create_branch_schedul(branch_id):
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
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro no banco de dados ao criar horário para branch_id={branch_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao criar horário'}), 500
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao criar horário para branch_id={branch_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao criar horário'}), 500

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
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao predizer tempo de espera para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao predizer tempo de espera'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao predizer tempo de espera para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao predizer tempo de espera'}), 500

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
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao obter dados do painel para institution_id={institution_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao obter dados do painel'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao obter dados do painel para institution_id={institution_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao obter dados do painel'}), 500
        
        
        
    @app.route('/api/update_location', methods=['POST'])
    @require_auth
    def update_location():
        user_id = request.user_id
        data = request.get_json()
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        email = data.get('email')

        if latitude is None or longitude is None:
            logger.error(f"Latitude ou longitude não fornecidos por user_id={user_id}")
            return jsonify({'error': 'Latitude e longitude são obrigatórios'}), 400

        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (ValueError, TypeError):
            logger.error(f"Latitude ou longitude inválidos: lat={latitude}, lon={longitude}")
            return jsonify({'error': 'Latitude e longitude devem ser números'}), 400

        user = User.query.get(user_id)
        if not user:
            if not email:
                logger.error(f"Email não encontrado para user_id={user_id}")
                return jsonify({'error': 'Email é obrigatório para criar um novo usuário'}), 400
            user = User(id=user_id, email=email, name="Usuário Desconhecido", active=True)
            db.session.add(user)

        user.last_known_lat = latitude
        user.last_known_lon = longitude
        user.last_location_update = datetime.utcnow()
        db.session.commit()
        logger.info(f"Localização atualizada para user_id={user_id}: lat={latitude}, lon={longitude}")

        QueueService.check_proximity_notifications(user_id, latitude, longitude)
        QueueService.check_proactive_notifications(user_id)
        return jsonify({'message': 'Localização atualizada com sucesso'}), 200

    @app.route('/api/queue/create', methods=['POST'])
    @require_auth
    def create_queues():
        user = User.query.get(request.user_id)
        if not user or not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
            logger.warning(f"Tentativa não autorizada de criar fila por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        data = request.get_json()
        required = ['service', 'prefix', 'department_id', 'open_time', 'daily_limit', 'num_counters', 'branch_id']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de fila.")
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400

        if not re.match(r'^[A-Z]$', data['prefix']):
            logger.warning(f"Prefixo inválido: {data['prefix']}")
            return jsonify({'error': 'Prefixo deve ser uma única letra maiúscula'}), 400
        if not isinstance(data['daily_limit'], int) or data['daily_limit'] <= 0:
            logger.warning(f"Limite diário inválido: {data['daily_limit']}")
            return jsonify({'error': 'Limite diário deve ser um número positivo'}), 400
        if not isinstance(data['num_counters'], int) or data['num_counters'] <= 0:
            logger.warning(f"Número de guichês inválido: {data['num_counters']}")
            return jsonify({'error': 'Número de guichês deve ser um número positivo'}), 400

        department = Department.query.get(data['department_id'])
        branch = Branch.query.get(data['branch_id'])
        if not department or not branch:
            logger.error(f"Departamento ou filial não encontrados: department_id={data['department_id']}, branch_id={data['branch_id']}")
            return jsonify({'error': 'Departamento ou filial não encontrados'}), 404

        if user.is_department_admin and user.department_id != data['department_id']:
            logger.warning(f"Usuário {user.id} não tem permissão para criar fila no departamento {data['department_id']}")
            return jsonify({'error': 'Sem permissão para este departamento'}), 403
        if user.is_institution_admin and department.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para criar fila na instituição {department.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        if Queue.query.filter_by(service=data['service'], department_id=data['department_id'], branch_id=data['branch_id']).first():
            logger.warning(f"Fila já existe para o serviço {data['service']} no departamento {data['department_id']} e filial {data['branch_id']}.")
            return jsonify({'error': 'Fila já existe'}), 400

        try:
            open_time = datetime.strptime(data['open_time'], '%H:%M').time()
        except ValueError:
            logger.error(f"Formato de open_time inválido: {data['open_time']}")
            return jsonify({'error': 'Formato de open_time inválido (HH:MM)'}), 400

        queue = Queue(
            id=str(uuid.uuid4()),
            department_id=data['department_id'],
            branch_id=data['branch_id'],
            service=data['service'],
            prefix=data['prefix'],
            open_time=open_time,
            daily_limit=data['daily_limit'],
            num_counters=data['num_counters'],
            avg_wait_time=0.0
        )
        db.session.add(queue)
        db.session.commit()
        logger.info(f"Fila criada: {queue.service} (ID: {queue.id})")
        return jsonify({'message': f'Fila {data["service"]} criada', 'queue_id': queue.id}), 201

    @app.route('/api/queue/<id>', methods=['PUT'])
    @require_auth
    def update_queues(id):
        user = User.query.get(request.user_id)
        if not user or not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
            logger.warning(f"Tentativa não autorizada de atualizar fila por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get_or_404(id)
        data = request.get_json()

        if user.is_department_admin and queue.department_id != user.department_id:
            logger.warning(f"Usuário {user.id} não tem permissão para atualizar fila {id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.is_institution_admin and queue.department.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para atualizar fila na instituição {queue.department.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        if 'prefix' in data and not re.match(r'^[A-Z]$', data['prefix']):
            logger.warning(f"Prefixo inválido: {data['prefix']}")
            return jsonify({'error': 'Prefixo deve ser uma única letra maiúscula'}), 400
        if 'daily_limit' in data and (not isinstance(data['daily_limit'], int) or data['daily_limit'] <= 0):
            logger.warning(f"Limite diário inválido: {data['daily_limit']}")
            return jsonify({'error': 'Limite diário deve ser um número positivo'}), 400
        if 'num_counters' in data and (not isinstance(data['num_counters'], int) or data['num_counters'] <= 0):
            logger.warning(f"Número de guichês inválido: {data['num_counters']}")
            return jsonify({'error': 'Número de guichês deve ser um número positivo'}), 400

        queue.service = data.get('service', queue.service)
        queue.prefix = data.get('prefix', queue.prefix)
        if 'department_id' in data:
            department = Department.query.get(data['department_id'])
            if not department:
                logger.error(f"Departamento não encontrado: department_id={data['department_id']}")
                return jsonify({'error': 'Departamento não encontrado'}), 404
            queue.department_id = data['department_id']
        if 'branch_id' in data:
            branch = Branch.query.get(data['branch_id'])
            if not branch:
                logger.error(f"Filial não encontrada: branch_id={data['branch_id']}")
                return jsonify({'error': 'Filial não encontrada'}), 404
            queue.branch_id = data['branch_id']
        if 'open_time' in data:
            try:
                queue.open_time = datetime.strptime(data['open_time'], '%H:%M').time()
            except ValueError:
                logger.error(f"Formato de open_time inválido: {data['open_time']}")
                return jsonify({'error': 'Formato de open_time inválido (HH:MM)'}), 400
        queue.daily_limit = data.get('daily_limit', queue.daily_limit)
        queue.num_counters = data.get('num_counters', queue.num_counters)
        db.session.commit()
        logger.info(f"Fila atualizada: {queue.service} (ID: {id})")
        return jsonify({'message': 'Fila atualizada'}), 200

    @app.route('/api/queue/<id>', methods=['DELETE'])
    @require_auth
    def delete_queues(id):
        user = User.query.get(request.user_id)
        if not user or not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
            logger.warning(f"Tentativa não autorizada de excluir fila por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get_or_404(id)
        if user.is_department_admin and queue.department_id != user.department_id:
            logger.warning(f"Usuário {user.id} não tem permissão para excluir fila {id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.is_institution_admin and queue.department.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para excluir fila na instituição {queue.department.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        if Ticket.query.filter_by(queue_id=id, status='Pendente').first():
            logger.warning(f"Tentativa de excluir fila {id} com tickets pendentes")
            return jsonify({'error': 'Não é possível excluir: fila possui tickets pendentes'}), 400
        db.session.delete(queue)
        db.session.commit()
        logger.info(f"Fila excluída: {id}")
        redis_client.delete(f"cache:search:*")  # Invalida cache de busca
        return jsonify({'message': 'Fila excluída'}), 200

        
    @app.route('/api/tickets/<ticket_id>', methods=['GET'])
    @require_auth
    def get_ticket(ticket_id):
        user_id = request.user_id
        try:
            cache_k = cache_key('get_ticket', ticket_id=ticket_id, user_id=user_id)
            cached_result = redis_client.get(cache_k)
            if cached_result:
                logger.debug(f"Cache hit para get_ticket: {cache_k}")
                return jsonify(json.loads(cached_result))

            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                logger.warning(f"Ticket não encontrado: ticket_id={ticket_id}")
                return jsonify({'error': 'Ticket não encontrado'}), 404

            if ticket.user_id != user_id:
                logger.warning(f"Usuário {user_id} não é dono do ticket {ticket_id}")
                return jsonify({'error': 'Você não é o dono deste ticket'}), 403

            queue = Queue.query.get(ticket.queue_id)
            if not queue:
                logger.warning(f"Fila não encontrada: queue_id={ticket.queue_id}")
                return jsonify({'error': 'Fila não encontrada'}), 404

            service = InstitutionService.query.get(queue.service_id)
            branch = Branch.query.get(queue.department.branch_id)
            institution = Institution.query.get(branch.institution_id)
            department = Department.query.get(queue.department_id)

            local_tz = pytz.timezone('Africa/Luanda')
            now = datetime.now(local_tz)
            weekday_str = now.strftime('%A').upper()
            try:
                weekday_enum = Weekday[weekday_str]
            except KeyError:
                logger.error(f"Dia da semana inválido: {weekday_str}")
                return jsonify({'error': 'Dia da semana inválido'}), 400

            schedule = BranchSchedule.query.filter_by(
                branch_id=branch.id,
                weekday=weekday_enum
            ).first()
            is_open = bool(schedule and not schedule.is_closed and schedule.open_time <= now.time() <= schedule.end_time)

            wait_time = QueueService.calculate_wait_time(queue.id, ticket.ticket_number, ticket.priority)
            position = max(0, ticket.ticket_number - queue.current_ticket) if queue.current_ticket else ticket.ticket_number

            response = {
                'ticket_id': ticket.id,
                'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
                'queue_id': ticket.queue_id,
                'status': ticket.status,
                'priority': ticket.priority,
                'is_physical': ticket.is_physical,
                'trade_available': ticket.trade_available,
                'service': {
                    'id': service.id,
                    'name': service.name or 'Desconhecido'
                },
                'institution': {
                    'id': institution.id,
                    'name': institution.name or 'Desconhecida'
                },
                'branch': {
                    'id': branch.id,
                    'name': branch.name or 'Desconhecida',
                    'latitude': float(branch.latitude) if branch.latitude else None,
                    'longitude': float(branch.longitude) if branch.longitude else None
                },
                'department': {
                    'id': department.id,
                    'name': department.name or 'Desconhecido'
                },
                'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else 'Aguardando início',
                'position': position,
                'issued_at': ticket.issued_at.isoformat(),
                'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None,
                'active_tickets': queue.active_tickets or 0,
                'is_open': is_open,
                'current_ticket': f"{queue.prefix}{queue.current_ticket}" if queue.current_ticket else 'N/A'
            }

            redis_client.setex(cache_k, 60, json.dumps(response, default=str))
            emit_ticket_update(ticket)

            AuditLog.create(
                user_id=user_id,
                action="view_ticket",
                resource_type="ticket",
                resource_id=ticket_id,
                details=f"Visualização do ticket {response['ticket_number']}"
            )

            logger.info(f"Ticket retornado: {response['ticket_number']} (ticket_id={ticket_id}, user_id={user_id})")
            return jsonify(response), 200

        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao buscar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados'}), 500
        except Exception as e:
            logger.error(f"Erro ao buscar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro interno do servidor'}), 500
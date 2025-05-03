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

    # Funções auxiliares
    def emit_ticket_update(ticket):
        try:
            if not ticket or not ticket.user_id or ticket.user_id == 'PRESENCIAL' or ticket.is_physical:
                logger.warning(f"Não é possível emitir atualização para ticket_id={ticket.id}: usuário inválido ou ticket presencial")
                return

            user = User.query.get(ticket.user_id)
            if not user:
                logger.warning(f"Usuário não encontrado para ticket_id={ticket.id}, user_id={ticket.user_id}")
                return

            ticket_data = {
                'ticket_id': ticket.id,
                'queue_id': ticket.queue_id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'status': ticket.status,
                'priority': ticket.priority,
                'is_physical': ticket.is_physical,
                'issued_at': ticket.issued_at.isoformat(),
                'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None,
                'counter': ticket.counter
            }

            mensagens_status = {
                'Pendente': f"Sua senha {ticket_data['ticket_number']} está aguardando atendimento.",
                'Chamado': f"Sua senha {ticket_data['ticket_number']} foi chamada no guichê {ticket_data['counter']}. Dirija-se ao atendimento.",
                'Atendido': f"Sua senha {ticket_data['ticket_number']} foi atendida com sucesso.",
                'Cancelado': f"Sua senha {ticket_data['ticket_number']} foi cancelada."
            }
            mensagem = mensagens_status.get(ticket.status, f"Sua senha {ticket_data['ticket_number']} foi atualizada: {ticket.status}")

            cache_key = f"notificacao:throttle:{ticket.user_id}:{ticket.id}"
            if redis_client.get(cache_key):
                logger.debug(f"Notificação suprimida para ticket_id={ticket.id} devido a throttling")
                return
            redis_client.setex(cache_key, 60, "1")

            QueueService.send_notification(
                fcm_token=user.fcm_token,
                message=mensagem,
                ticket_id=ticket.id,
                via_websocket=True,
                user_id=ticket.user_id
            )

            if socketio:
                try:
                    socketio.emit('ticket_update', ticket_data, namespace='/', room=str(ticket.user_id))
                    logger.info(f"Atualização de ticket emitida via WebSocket: ticket_id={ticket.id}, user_id={ticket.user_id}")
                except Exception as e:
                    logger.error(f"Erro ao emitir atualização WebSocket para ticket_id={ticket.id}: {str(e)}")
        except Exception as e:
            logger.error(f"Erro geral ao processar atualização de ticket_id={ticket.id}: {str(e)}")

    def emit_dashboard_update(institution_id, queue_id, event_type, data):
        try:
            socketio.emit('dashboard_update', {
                'institution_id': institution_id,
                'queue_id': queue_id,
                'event_type': event_type,
                'data': data
            }, room=institution_id, namespace='/dashboard')
            logger.info(f"Atualização de painel emitida: institution_id={institution_id}, event_type={event_type}")
        except Exception as e:
            logger.error(f"Erro ao emitir atualização de painel: {str(e)}")

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


    @app.route('/api/tickets/trade_available', methods=['GET'])
    @require_auth
    def list_trade_available_tickets():
        """Lista tickets disponíveis para troca."""
        user_id = request.user_id
        try:
            user_tickets = Ticket.query.filter_by(user_id=user_id, status='Pendente').all()
            user_queue_ids = {t.queue_id for t in user_tickets}

            if not user_queue_ids:
                return jsonify([]), 200

            tickets = Ticket.query.filter(
                Ticket.queue_id.in_(user_queue_ids),
                Ticket.trade_available == True,
                Ticket.status == 'Pendente',
                Ticket.user_id != user_id
            ).all()

            result = []
            for t in tickets:
                wait_time = QueueService.calculate_wait_time(t.queue.id, t.ticket_number, t.priority)
                result.append({
                    'id': t.id,
                    'service': t.queue.service.name,
                    'institution': {
                        'name': t.queue.department.branch.institution.name,
                        'type': {
                            'id': t.queue.department.branch.institution.type.id,
                            'name': t.queue.department.branch.institution.type.name
                        }
                    },
                    'branch': t.queue.department.branch.name,
                    'number': f"{t.queue.prefix}{t.ticket_number}",
                    'position': max(0, t.ticket_number - t.queue.current_ticket),
                    'user_id': t.user_id,
                    'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
                    'quality_score': float(service_recommendation_predictor.predict(t.queue, user_id))
                })

            logger.info(f"Tickets disponíveis para troca retornados para user_id={user_id}: {len(result)} tickets")
            return jsonify(result), 200
        except Exception as e:
            logger.error(f"Erro ao listar tickets disponíveis para troca para user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar tickets para troca'}), 500

    @app.route('/api/ticket/<ticket_id>/cancel', methods=['POST'])
    @require_auth
    def cancel_ticket(ticket_id):
        """Cancela um ticket."""
        user_id = request.user_id
        try:
            ticket = QueueService.cancel_ticket(ticket_id, user_id)
            emit_ticket_update(ticket)
            logger.info(f"Senha cancelada: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket.id})")
            QueueService.send_notification(
                fcm_token=User.query.get(user_id).fcm_token,
                message=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} cancelado",
                ticket_id=ticket.id,
                via_websocket=True,
                user_id=user_id
            )
            AuditLog.create(
                user_id=user_id,
                action="cancel_ticket",
                resource_type="ticket",
                resource_id=ticket_id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} cancelado"
            )
            return jsonify({'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} cancelada', 'ticket_id': ticket.id}), 200
        except ValueError as e:
            logger.error(f"Erro ao cancelar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao cancelar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao cancelar ticket'}), 500

    @app.route('/api/queues/<queue_id>/metrics', methods=['GET'])
    @require_auth
    def queue_metrics(queue_id):
        """Retorna métricas detalhadas de uma fila."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar métricas por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {user_id} não tem permissão para acessar métricas da fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para acessar métricas na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        cache_key = f"cache:queue_metrics:{queue_id}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            metrics = QueueService.get_queue_metrics(queue_id)
            response = {
                'queue_id': queue_id,
                'service': queue.service.name,
                'branch': queue.department.branch.name,
                'metrics': {
                    'total_tickets': metrics['total_tickets'],
                    'active_tickets': queue.active_tickets,
                    'avg_wait_time': f"{int(queue.avg_wait_time)} minutos" if queue.avg_wait_time else "N/A",
                    'avg_service_time': f"{int(queue.last_service_time)} minutos" if queue.last_service_time else "N/A",
                    'peak_hours': [
                        {'hour': h['hour'], 'ticket_count': h['ticket_count']}
                        for h in metrics['peak_hours']
                    ],
                    'ticket_status_distribution': metrics['ticket_status_distribution'],
                    'predicted_demand': float(demand_model.predict(queue_id, hours_ahead=1)),
                    'quality_score': float(service_recommendation_predictor.predict(queue))
                }
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Métricas retornadas para queue_id={queue_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter métricas da fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter métricas'}), 500

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

    @app.route('/api/queues/<queue_id>/audit', methods=['GET'])
    @require_auth
    def queue_audit(queue_id):
        """Retorna logs de auditoria para uma fila."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar auditoria por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para acessar auditoria na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        page = request.args.get('page', '1')
        per_page = request.args.get('per_page', '20')
        action = request.args.get('action')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        try:
            page = int(page)
            per_page = int(per_page)
            if page < 1 or per_page < 1:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
            return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

        if start_date:
            try:
                start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"start_date inválido: {start_date}")
                return jsonify({'error': 'Formato de start_date inválido. Use ISO 8601'}), 400
        if end_date:
            try:
                end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"end_date inválido: {end_date}")
                return jsonify({'error': 'Formato de end_date inválido. Use ISO 8601'}), 400

        cache_key = f"cache:queue_audit:{queue_id}:{action}:{start_date}:{end_date}:{page}:{per_page}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            query = AuditLog.query.filter_by(resource_id=queue_id, resource_type='queue')
            if action:
                query = query.filter_by(action=action)
            if start_date:
                query = query.filter(AuditLog.timestamp >= start_date)
            if end_date:
                query = query.filter(AuditLog.timestamp <= end_date)

            logs = query.paginate(page=page, per_page=per_page, error_out=False)
            result = [
                {
                    'id': log.id,
                    'user_id': log.user_id,
                    'action': log.action,
                    'resource_type': log.resource_type,
                    'resource_id': log.resource_id,
                    'details': log.details,
                    'timestamp': log.timestamp.isoformat()
                } for log in logs.items
            ]

            response = {
                'logs': result,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_results': logs.total,
                    'total_pages': logs.pages
                }
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Logs de auditoria retornados para queue_id={queue_id}: {len(result)} logs")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter logs de auditoria para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter logs de auditoria'}), 500

    @app.route('/api/queues/<queue_id>/ticket', methods=['POST'])
    @require_auth
    def generate_ticket(queue_id):
        """Gera um ticket virtual para um usuário autenticado."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user:
            logger.warning(f"Usuário não encontrado: user_id={user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        data = request.get_json() or {}
        priority = data.get('priority', 0)
        user_lat = data.get('latitude')
        user_lon = data.get('longitude')

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

        # Verificar se o usuário já possui um ticket ativo na mesma fila
        existing_ticket = Ticket.query.filter_by(
            user_id=user_id, queue_id=queue_id, status='Pendente'
        ).first()
        if existing_ticket:
            logger.warning(f"Usuário {user_id} já possui ticket ativo na fila {queue_id}")
            return jsonify({'error': 'Você já possui um ticket ativo nesta fila'}), 400

        # Verificar horário de funcionamento da filial
        branch = queue.department.branch
        schedules = BranchSchedule.query.filter_by(branch_id=branch.id).all()
        current_weekday = datetime.utcnow().strftime('%A').lower()
        current_time = datetime.utcnow().time()
        is_open = False
        for schedule in schedules:
            if schedule.weekday == current_weekday and not schedule.is_closed:
                if schedule.open_time <= current_time <= schedule.end_time:
                    is_open = True
                    break
        if not is_open:
            logger.warning(f"Fila {queue_id} não está disponível fora do horário de funcionamento")
            return jsonify({'error': 'Fila não disponível fora do horário de funcionamento'}), 400

        try:
            ticket = QueueService.generate_virtual_ticket(
                queue_id=queue_id,
                user_id=user_id,
                priority=priority,
                user_lat=user_lat,
                user_lon=user_lon
            )
            db.session.commit()
            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue_id,
                event_type='ticket_issued',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'timestamp': ticket.issued_at.isoformat()
                }
            )

            AuditLog.create(
                user_id=user_id,
                action="generate_ticket",
                resource_type="ticket",
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} gerado na fila {queue_id}"
            )

            response = {
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'queue_id': ticket.queue_id,
                'status': ticket.status,
                'priority': ticket.priority,
                'issued_at': ticket.issued_at.isoformat(),
                'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None,
                'estimated_wait_time': f"{int(queue.estimated_wait_time)} minutos" if queue.estimated_wait_time else "N/A"
            }

            logger.info(f"Ticket gerado: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket.id}, user_id={user_id})")
            return jsonify(response), 201
        except ValueError as e:
            db.session.rollback()
            logger.error(f"Erro ao gerar ticket para queue_id={queue_id}, user_id={user_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao gerar ticket para queue_id={queue_id}, user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao gerar ticket'}), 500
        
    @app.route('/api/tickets/<ticket_id>/trade', methods=['POST'])
    @require_auth
    def trade_ticket(ticket_id):
        """Realiza a troca de um ticket com outro usuário."""
        user_id = request.user_id
        data = request.get_json() or {}
        target_ticket_id = data.get('target_ticket_id')

        if not target_ticket_id:
            logger.warning(f"target_ticket_id não fornecido para troca por user_id={user_id}")
            return jsonify({'error': 'target_ticket_id é obrigatório'}), 400

        try:
            ticket = Ticket.query.get(ticket_id)
            target_ticket = Ticket.query.get(target_ticket_id)

            if not ticket or not target_ticket:
                logger.warning(f"Ticket não encontrado: ticket_id={ticket_id}, target_ticket_id={target_ticket_id}")
                return jsonify({'error': 'Ticket não encontrado'}), 404

            if ticket.user_id != user_id:
                logger.warning(f"Usuário {user_id} não é dono do ticket {ticket_id}")
                return jsonify({'error': 'Você não é o dono deste ticket'}), 403

            if not target_ticket.trade_available:
                logger.warning(f"Ticket {target_ticket_id} não está disponível para troca")
                return jsonify({'error': 'O ticket solicitado não está disponível para troca'}), 400

            if ticket.queue_id != target_ticket.queue_id:
                logger.warning(f"Tickets de filas diferentes: ticket_id={ticket_id}, target_ticket_id={target_ticket_id}")
                return jsonify({'error': 'Os tickets devem pertencer à mesma fila'}), 400

            if ticket.status != 'Pendente' or target_ticket.status != 'Pendente':
                logger.warning(f"Tickets não estão pendentes: ticket_id={ticket_id}, target_ticket_id={target_ticket_id}")
                return jsonify({'error': 'Ambos os tickets devem estar pendentes'}), 400

            ticket.user_id, target_ticket.user_id = target_ticket.user_id, ticket.user_id
            ticket.updated_at = datetime.utcnow()
            target_ticket.updated_at = datetime.utcnow()

            db.session.commit()

            emit_ticket_update(ticket)
            emit_ticket_update(target_ticket)

            AuditLog.create(
                user_id=user_id,
                action="trade_ticket",
                resource_type="ticket",
                resource_id=ticket_id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} trocado com {target_ticket.queue.prefix}{target_ticket.ticket_number}"
            )

            logger.info(f"Ticket trocado: {ticket.queue.prefix}{ticket.ticket_number} com {target_ticket.queue.prefix}{target_ticket.ticket_number}")
            return jsonify({
                'message': 'Troca realizada com sucesso',
                'ticket_id': ticket.id,
                'target_ticket_id': target_ticket.id
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao trocar ticket {ticket_id} com {target_ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro ao realizar troca de ticket'}), 500

    @app.route('/api/tickets/<ticket_id>/trade_available', methods=['PATCH'])
    @require_auth
    def toggle_trade_availability(ticket_id):
        """Alterna a disponibilidade de um ticket para troca."""
        user_id = request.user_id
        try:
            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                logger.warning(f"Ticket não encontrado: ticket_id={ticket_id}")
                return jsonify({'error': 'Ticket não encontrado'}), 404

            if ticket.user_id != user_id:
                logger.warning(f"Usuário {user_id} não é dono do ticket {ticket_id}")
                return jsonify({'error': 'Você não é o dono deste ticket'}), 403

            if ticket.status != 'Pendente':
                logger.warning(f"Ticket {ticket_id} não está pendente")
                return jsonify({'error': 'O ticket deve estar pendente para alterar a disponibilidade de troca'}), 400

            ticket.trade_available = not ticket.trade_available
            db.session.commit()

            emit_ticket_update(ticket)
            AuditLog.create(
                user_id=user_id,
                action="toggle_trade_availability",
                resource_type="ticket",
                resource_id=ticket_id,
                details=f"Disponibilidade de troca do ticket {ticket.queue.prefix}{ticket.ticket_number} alterada para {ticket.trade_available}"
            )

            logger.info(f"Disponibilidade de troca alterada para ticket_id={ticket_id}: {ticket.trade_available}")
            return jsonify({
                'message': f"Disponibilidade de troca {'ativada' if ticket.trade_available else 'desativada'}",
                'ticket_id': ticket.id,
                'trade_available': ticket.trade_available
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao alterar disponibilidade de troca do ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro ao alterar disponibilidade de troca'}), 500

    @app.route('/api/queues/<queue_id>/call', methods=['POST'])
    @require_auth
    def call_next_ticket(queue_id):
        """Chama o próximo ticket de uma fila."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de chamar ticket por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {user_id} não tem permissão para chamar ticket na fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para chamar ticket na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        data = request.get_json() or {}
        counter = data.get('counter')

        if not counter:
            logger.warning("counter é obrigatório")
            return jsonify({'error': 'counter é obrigatório'}), 400

        try:
            ticket = QueueService.call_next_ticket(queue_id, counter)
            if not ticket:
                logger.info(f"Nenhum ticket pendente para chamar na fila {queue_id}")
                return jsonify({'message': 'Nenhum ticket pendente para chamar'}), 200

            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue_id,
                event_type='ticket_called',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': counter,
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            AuditLog.create(
                user_id=user_id,
                action="call_ticket",
                resource_type="ticket",
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} chamado no guichê {counter}"
            )

            logger.info(f"Ticket chamado: {ticket.queue.prefix}{ticket.ticket_number} no guichê {counter} (queue_id={queue_id})")
            return jsonify({
                'message': 'Ticket chamado com sucesso',
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'counter': counter
            }), 200
        except ValueError as e:
            logger.error(f"Erro ao chamar próximo ticket na fila {queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao chamar próximo ticket na fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao chamar ticket'}), 500

    @app.route('/api/tickets/<ticket_id>/complete', methods=['POST'])
    @require_auth
    def complete_ticket(ticket_id):
        """Marca um ticket como atendido."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de completar ticket por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            logger.warning(f"Ticket não encontrado: ticket_id={ticket_id}")
            return jsonify({'error': 'Ticket não encontrado'}), 404

        queue = ticket.queue
        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {user_id} não tem permissão para completar ticket na fila {queue.id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para completar ticket na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        try:
            ticket = QueueService.complete_ticket(ticket_id)
            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue.id,
                event_type='ticket_completed',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            AuditLog.create(
                user_id=user_id,
                action="complete_ticket",
                resource_type="ticket",
                resource_id=ticket_id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} marcado como atendido"
            )

            logger.info(f"Ticket completado: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket_id})")
            return jsonify({
                'message': 'Ticket marcado como atendido',
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}"
            }), 200
        except ValueError as e:
            logger.error(f"Erro ao completar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao completar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao completar ticket'}), 500

    @app.route('/api/user/tickets', methods=['GET'])
    @require_auth
    def get_user_tickets():
        """Retorna os tickets de um usuário."""
        user_id = request.user_id
        status = request.args.get('status')
        page = request.args.get('page', '1')
        per_page = request.args.get('per_page', '20')

        try:
            page = int(page)
            per_page = int(per_page)
            if page < 1 or per_page < 1:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
            return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

        cache_key = f"cache:user_tickets:{user_id}:{status}:{page}:{per_page}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            query = Ticket.query.filter_by(user_id=user_id)
            if status:
                query = query.filter_by(status=status)

            tickets = query.paginate(page=page, per_page=per_page, error_out=False)
            result = [
                {
                    'id': t.id,
                    'ticket_number': f"{t.queue.prefix}{t.ticket_number}",
                    'queue_id': t.queue_id,
                    'service': t.queue.service.name,
                    'branch': t.queue.department.branch.name,
                    'institution': t.queue.department.branch.institution.name,
                    'status': t.status,
                    'priority': t.priority,
                    'is_physical': t.is_physical,
                    'trade_available': t.trade_available,
                    'issued_at': t.issued_at.isoformat(),
                    'expires_at': t.expires_at.isoformat() if t.expires_at else None,
                    'counter': t.counter,
                    'estimated_wait_time': f"{int(t.queue.estimated_wait_time)} minutos" if t.queue.estimated_wait_time else "N/A"
                } for t in tickets.items
            ]

            response = {
                'tickets': result,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_results': tickets.total,
                    'total_pages': tickets.pages
                }
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Tickets retornados para user_id={user_id}: {len(result)} tickets")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter tickets do usuário {user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter tickets'}), 500

 
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
            if (user_lat is None or user_lon is None) and user_id is None:
                logger.warning("Coordenadas ou user_id são necessários")
                return jsonify({'error': 'Coordenadas do usuário ou user_id são necessários'}), 400

            # Obter coordenadas do usuário
            if user_id and (user_lat is None or user_lon is None):
                user = User.query.get(user_id)
                if user and user.last_known_lat and user.last_known_lon:
                    user_lat, user_lon = user.last_known_lat, user.last_known_lon
                else:
                    logger.warning(f"Usuário {user_id} sem coordenadas válidas")
                    return jsonify({'error': 'Coordenadas do usuário não disponíveis'}), 400

            if sort_by == 'distance' and (user_lat is None or user_lon is None):
                logger.warning("Ordenação por distância requer coordenadas")
                return jsonify({'error': 'Coordenadas do usuário necessárias para ordenar por distância'}), 400

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
from flask import jsonify, request, send_file
from flask_socketio import join_room, leave_room, ConnectionRefusedError
from . import db, socketio, redis_client
from .models import AuditLog, Institution, Branch, Queue, Ticket, User, Department, UserRole, QueueSchedule, Weekday, ServiceCategory, ServiceTag, UserPreference, InstitutionType
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
from sqlalchemy import and_, or_
from geopy.distance import geodesic
from firebase_admin import auth
from sqlalchemy.exc import SQLAlchemyError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_queue_routes(app):

    def emit_ticket_update(ticket):
        """Emite atualização de ticket via WebSocket com notificações profissionais e direcionadas."""
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
                fcm_token=None,
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

    @app.route('/api/queues/suggestions', methods=['GET'])
    def suggest_queues():
        """Sugere filas alternativas com base em um serviço ou localização."""
        user_id = request.args.get('user_id')
        queue_id = request.args.get('queue_id')
        user_lat = request.args.get('latitude')
        user_lon = request.args.get('longitude')
        max_results = request.args.get('max_results', '5')

        if not queue_id:
            logger.warning("queue_id não fornecido")
            return jsonify({'error': 'queue_id é obrigatório'}), 400

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

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
            max_results = int(max_results)
            if max_results < 1:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"max_results inválido: {max_results}")
            return jsonify({'error': 'max_results deve ser um número positivo'}), 400

        cache_key = f"cache:queue_suggestions:{queue_id}:{user_id}:{user_lat}:{user_lon}:{max_results}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            suggestions = QueueService.suggest_alternative_queues(queue_id=queue_id, user_id=user_id, user_lat=user_lat, user_lon=user_lon, max_results=max_results)
            result = []
            for alt_queue in suggestions:
                alt_wait_time = QueueService.calculate_wait_time(alt_queue.id, alt_queue.active_tickets + 1, 0, user_lat, user_lon)
                alt_distance = QueueService.calculate_distance(user_lat, user_lon, alt_queue.department.branch) if user_lat and user_lon else None
                alt_quality_score = service_recommendation_predictor.predict(alt_queue, user_id, user_lat, user_lon)
                explanation = []
                if alt_distance is not None:
                    explanation.append(f"Filial a {alt_distance:.2f} km")
                if isinstance(alt_wait_time, (int, float)):
                    explanation.append(f"Espera de {int(alt_wait_time)} min")
                if alt_quality_score > 0.8:
                    explanation.append("Alta qualidade")
                result.append({
                    'queue_id': alt_queue.id,
                    'service': alt_queue.service or "Desconhecido",
                    'branch': alt_queue.department.branch.name or "Desconhecida",
                    'wait_time': f"{int(alt_wait_time)} minutos" if isinstance(alt_wait_time, (int, float)) else 'N/A',
                    'distance': float(alt_distance) if alt_distance is not None else 'Desconhecida',
                    'quality_score': float(alt_quality_score),
                    'explanation': "; ".join(explanation) or "Alternativa recomendada"
                })

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(result, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Sugestões de filas retornadas para queue_id={queue_id}: {len(result)} resultados")
            return jsonify({'suggestions': result}), 200
        except Exception as e:
            logger.error(f"Erro ao sugerir filas alternativas: {str(e)}")
            return jsonify({'error': 'Erro ao sugerir filas alternativas'}), 500

    @app.route('/api/notifications/proximity', methods=['POST'])
    @require_auth
    def proximity_notifications():
        """Verifica e envia notificações de filas próximas com serviços semelhantes."""
        data = request.get_json() or {}
        user_id = request.user_id
        user_lat = data.get('latitude')
        user_lon = data.get('longitude')
        desired_service = data.get('desired_service')

        if not user_id or user_lat is None or user_lon is None:
            logger.warning(f"Parâmetros obrigatórios faltando: user_id={user_id}, lat={user_lat}, lon={user_lon}")
            return jsonify({'error': 'user_id, latitude e longitude são obrigatórios'}), 400

        try:
            user_lat = float(user_lat)
            user_lon = float(user_lon)
        except (ValueError, TypeError):
            logger.warning(f"Latitude ou longitude inválidos: lat={user_lat}, lon={user_lon}")
            return jsonify({'error': 'Latitude e longitude devem ser números'}), 400

        if desired_service and not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', desired_service):
            logger.warning(f"desired_service inválido: {desired_service}")
            return jsonify({'error': 'desired_service inválido'}), 400

        try:
            notifications = QueueService.check_proximity_notifications(
                user_id=user_id,
                user_lat=user_lat,
                user_lon=user_lon,
                desired_service=desired_service
            )
            for notification in notifications:
                socketio.emit('notification', {
                    'message': notification['message'],
                    'queue_id': notification['queue_id'],
                    'timestamp': datetime.utcnow().isoformat()
                }, namespace='/', room=str(user_id))
            logger.info(f"Notificações de proximidade enviadas para user_id={user_id}: {len(notifications)} notificações")
            return jsonify({'message': 'Notificações de proximidade enviadas', 'notifications': notifications}), 200
        except Exception as e:
            logger.error(f"Erro ao enviar notificações de proximidade: {str(e)}")
            return jsonify({'error': 'Erro ao enviar notificações de proximidade'}), 500

    @app.route('/api/notifications/proactive', methods=['POST'])
    def proactive_notifications():
        """Dispara verificação de notificações proativas para tickets pendentes."""
        try:
            notifications = QueueService.check_proactive_notifications()
            for notification in notifications:
                socketio.emit('notification', {
                    'message': notification['message'],
                    'ticket_id': notification['ticket_id'],
                    'timestamp': datetime.utcnow().isoformat()
                }, namespace='/', room=str(notification['user_id']))
            logger.info(f"Notificações proativas enviadas: {len(notifications)} notificações")
            return jsonify({'message': 'Notificações proativas enviadas', 'notifications': notifications}), 200
        except Exception as e:
            logger.error(f"Erro ao enviar notificações proativas: {str(e)}")
            return jsonify({'error': 'Erro ao enviar notificações proativas'}), 500

    @app.route('/api/dashboard/<institution_id>', methods=['GET'])
    def dashboard_data(institution_id):
        """Retorna dados do dashboard para uma instituição."""
        user_id = request.args.get('user_id')
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar dashboard por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição não encontrada: institution_id={institution_id}")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        if user.user_role == UserRole.INSTITUTION_ADMIN and institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para acessar dashboard da instituição {institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        cache_key = f"cache:dashboard:{institution_id}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            dashboard = QueueService.get_dashboard_data(institution_id)
            response = {
                'institution': {
                    'id': institution.id,
                    'name': institution.name or "Desconhecida",
                    'type': {
                        'id': institution.type.id if institution.type else None,
                        'name': institution.type.name if institution.type else "Desconhecido"
                    }
                },
                'metrics': {
                    'total_tickets': dashboard['total_tickets'],
                    'active_tickets': dashboard['active_tickets'],
                    'avg_wait_time': f"{int(dashboard['avg_wait_time'])} minutos" if dashboard['avg_wait_time'] else "N/A",
                    'avg_service_time': f"{int(dashboard['avg_service_time'])} minutos" if dashboard['avg_service_time'] else "N/A",
                    'popular_services': [
                        {
                            'service': service['name'],
                            'count': service['count'],
                            'wait_time': f"{int(service['wait_time'])} minutos" if service['wait_time'] else "N/A"
                        } for service in dashboard['popular_services']
                    ]
                },
                'queues': [
                    {
                        'queue_id': queue['id'],
                        'service': queue['service'],
                        'branch': queue['branch'],
                        'active_tickets': queue['active_tickets'],
                        'wait_time': f"{int(queue['wait_time'])} minutos" if queue['wait_time'] else "N/A",
                        'quality_score': float(queue['quality_score'])
                    } for queue in dashboard['queues']
                ]
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Dados do dashboard retornados para institution_id={institution_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter dados do dashboard: {str(e)}")
            return jsonify({'error': 'Erro ao obter dados do dashboard'}), 500

    @app.route('/api/queues/status/<queue_id>', methods=['GET'])
    def queue_status(queue_id):
        """Retorna o estado atual de uma fila."""
        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        cache_key = f"cache:queue_status:{queue_id}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            wait_time = QueueService.calculate_wait_time(queue_id, queue.current_ticket + 1, 0)
            alternatives = QueueService.suggest_alternative_queues(queue_id=queue_id, max_results=3)
            alt_queues = []
            for alt_queue in alternatives:
                alt_wait_time = QueueService.calculate_wait_time(alt_queue.id, alt_queue.active_tickets + 1, 0)
                alt_quality_score = service_recommendation_predictor.predict(alt_queue)
                alt_queues.append({
                    'queue_id': alt_queue.id,
                    'service': alt_queue.service or "Desconhecido",
                    'branch': alt_queue.department.branch.name or "Desconhecida",
                    'wait_time': f"{int(alt_wait_time)} minutos" if isinstance(alt_wait_time, (int, float)) else 'N/A',
                    'quality_score': float(alt_quality_score)
                })

            response = {
                'queue_id': queue_id,
                'service': queue.service or "Desconhecido",
                'branch': queue.department.branch.name if queue.department and queue.department.branch else "Desconhecida",
                'active_tickets': queue.active_tickets,
                'current_ticket': f"{queue.prefix}{queue.current_ticket}" if queue.current_ticket else None,
                'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
                'alternatives': alt_queues
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Status da fila retornado para queue_id={queue_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter status da fila: {str(e)}")
            return jsonify({'error': 'Erro ao obter status da fila'}), 500

    @app.route('/api/institutions', methods=['GET'])
    def list_institutions():
        """Lista instituições com filtros e paginação."""
        try:
            query = request.args.get('query', '').strip()
            institution_type_id = request.args.get('institution_type_id')
            user_lat = request.args.get('latitude')
            user_lon = request.args.get('longitude')
            neighborhood = request.args.get('neighborhood')
            sort_by = request.args.get('sort_by', 'name')
            page = request.args.get('page', '1')
            per_page = request.args.get('per_page', '20')

            if query and not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', query):
                logger.warning(f"Query inválida: {query}")
                return jsonify({'error': 'Query inválida'}), 400
            if institution_type_id and not InstitutionType.query.get(institution_type_id):
                logger.warning(f"institution_type_id não encontrado: {institution_type_id}")
                return jsonify({'error': 'Tipo de instituição não encontrado'}), 404
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
            if neighborhood and not re.match(r'^[A-Za-zÀ-ÿ\s,]{1,100}$', neighborhood):
                logger.warning(f"Bairro inválido: {neighborhood}")
                return jsonify({'error': 'Bairro inválido'}), 400
            if sort_by not in ['name', 'distance', 'quality_score']:
                logger.warning(f"sort_by inválido: {sort_by}")
                return jsonify({'error': 'sort_by deve ser name, distance ou quality_score'}), 400
            try:
                page = int(page)
                per_page = int(per_page)
                if page < 1 or per_page < 1:
                    raise ValueError
            except (ValueError, TypeError):
                logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

            cache_key = f"cache:institutions:{query}:{institution_type_id}:{user_lat}:{user_lon}:{neighborhood}:{sort_by}:{page}:{per_page}"
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        logger.info(f"Cache hit para {cache_key}")
                        return jsonify(json.loads(cached)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar cache Redis: {e}")

            query_obj = Institution.query
            if query:
                query_obj = query_obj.filter(Institution.name.ilike(f'%{query}%'))
            if institution_type_id:
                query_obj = query_obj.filter_by(institution_type_id=institution_type_id)

            institutions = query_obj.all()
            result = []

            for inst in institutions:
                branches = Branch.query.filter_by(institution_id=inst.id).all()
                min_distance = None
                if user_lat and user_lon:
                    distances = [
                        geodesic((user_lat, user_lon), (b.latitude, b.longitude)).km
                        for b in branches if b.latitude and b.longitude
                    ]
                    min_distance = min(distances) if distances else None

                branch_ids = [b.id for b in branches]
                department_ids = [d.id for d in Department.query.filter(Department.branch_id.in_(branch_ids)).all()]
                queues = Queue.query.filter(Queue.department_id.in_(department_ids)).all()
                quality_scores = [
                    service_recommendation_predictor.predict(q) for q in queues
                ]
                avg_quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

                result.append({
                    'id': inst.id,
                    'name': inst.name or "Desconhecida",
                    'description': inst.description or "Sem descrição",
                    'type': {
                        'id': inst.type.id if inst.type else None,
                        'name': inst.type.name if inst.type else "Desconhecido"
                    },
                    'distance_km': float(min_distance) if min_distance is not None else 'Desconhecida',
                    'quality_score': float(avg_quality_score),
                    'branches': [
                        {
                            'id': b.id,
                            'name': b.name or "Desconhecida",
                            'neighborhood': b.neighborhood or "Desconhecido",
                            'latitude': float(b.latitude) if b.latitude else None,
                            'longitude': float(b.longitude) if b.longitude else None
                        } for b in branches
                    ]
                })

            if sort_by == 'distance' and user_lat and user_lon:
                result = sorted(result, key=lambda x: float(x['distance_km']) if x['distance_km'] != 'Desconhecida' else float('inf'))
            elif sort_by == 'quality_score':
                result = sorted(result, key=lambda x: x['quality_score'], reverse=True)
            else:
                result = sorted(result, key=lambda x: x['name'].lower())

            total_results = len(result)
            start = (page - 1) * per_page
            end = start + per_page
            paginated_result = result[start:end]

            response = {
                'institutions': paginated_result,
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

            logger.info(f"Lista de instituições retornada: {len(paginated_result)} resultados")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar instituições: {str(e)}")
            return jsonify({'error': 'Erro ao listar instituições'}), 500

    # Rotas existentes (mantidas com ajustes)
    @app.route('/api/suggest-service', methods=['GET'])
    def suggest_service():
        """Sugere serviços com base em parâmetros, com explicações detalhadas."""
        service = request.args.get('service', '').strip()
        user_lat = request.args.get('lat')
        user_lon = request.args.get('lon')
        neighborhood = request.args.get('neighborhood')
        max_wait_time = request.args.get('max_wait_time')
        min_quality_score = request.args.get('min_quality_score')
        category_id = request.args.get('category_id')
        tags = request.args.get('tags')
        institution_type_id = request.args.get('institution_type_id')
        institution_id = request.args.get('institution_id')
        restrict_to_preferred = request.args.get('restrict_to_preferred', 'false').lower() == 'true'
        user_id = request.args.get('user_id')

        if user_lat is not None:
            try:
                user_lat = float(user_lat)
            except (ValueError, TypeError):
                logger.warning(f"Latitude inválida: {user_lat}")
                return jsonify({'error': 'Latitude deve ser um número'}), 400
        if user_lon is not None:
            try:
                user_lon = float(user_lon)
            except (ValueError, TypeError):
                logger.warning(f"Longitude inválida: {user_lon}")
                return jsonify({'error': 'Longitude deve ser um número'}), 400
        if neighborhood and not re.match(r'^[A-Za-zÀ-ÿ\s,]{1,100}$', neighborhood):
            logger.warning(f"Bairro inválido: {neighborhood}")
            return jsonify({'error': 'Bairro inválido'}), 400
        if max_wait_time:
            try:
                max_wait_time = float(max_wait_time)
                if max_wait_time <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                logger.warning(f"max_wait_time inválido: {max_wait_time}")
                return jsonify({'error': 'max_wait_time deve ser um número positivo'}), 400
        if min_quality_score:
            try:
                min_quality_score = float(min_quality_score)
                if not 0 <= min_quality_score <= 1:
                    raise ValueError
            except (ValueError, TypeError):
                logger.warning(f"min_quality_score inválido: {min_quality_score}")
                return jsonify({'error': 'min_quality_score deve estar entre 0 e 1'}), 400
        if category_id and not isinstance(category_id, str):
            logger.warning(f"category_id inválido: {category_id}")
            return jsonify({'error': 'category_id deve ser uma string'}), 400
        if tags:
            tags = tags.split(',')
            if not all(re.match(r'^[A-Za-zÀ-ÿ\s]{1,50}$', tag.strip()) for tag in tags):
                logger.warning(f"Tags inválidas: {tags}")
                return jsonify({'error': 'Tags inválidas'}), 400
        if institution_type_id and not isinstance(institution_type_id, str):
            logger.warning(f"institution_type_id inválido: {institution_type_id}")
            return jsonify({'error': 'institution_type_id deve ser uma string'}), 400
        if institution_id:
            if not isinstance(institution_id, str):
                logger.warning(f"institution_id inválido: {institution_id}")
                return jsonify({'error': 'institution_id deve ser uma string'}), 400
            if not Institution.query.get(institution_id):
                logger.warning(f"institution_id não encontrado: {institution_id}")
                return jsonify({'error': 'Instituição não encontrada'}), 404

        try:
            if not institution_id and restrict_to_preferred and user_id:
                pref = UserPreference.query.filter_by(user_id=user_id, is_client=True).first()
                if pref and pref.institution_id:
                    institution_id = pref.institution_id
                    logger.debug(f"Inferiu institution_id={institution_id} de UserPreference")
                else:
                    recent_ticket = Ticket.query.filter_by(user_id=user_id).join(Queue).join(Department).join(Branch).order_by(Ticket.issued_at.desc()).first()
                    if recent_ticket:
                        institution_id = recent_ticket.queue.department.branch.institution_id
                        logger.debug(f"Inferiu institution_id={institution_id} do histórico de tickets")

            cache_key = f"cache:suggest_service:{service}:{user_id}:{user_lat}:{user_lon}:{neighborhood}:{category_id}:{tags}:{max_wait_time}:{min_quality_score}:{institution_type_id}:{institution_id}"
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        logger.info(f"Cache hit para {cache_key}")
                        return jsonify(json.loads(cached)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar cache Redis: {e}")

            suggestions = RecommendationService.search_services(
                query=service,
                user_id=user_id,
                user_lat=user_lat,
                user_lon=user_lon,
                neighborhood=neighborhood,
                max_results=10,
                max_distance_km=10.0,
                category_id=category_id,
                tags=tags,
                max_wait_time=max_wait_time,
                min_quality_score=min_quality_score,
                institution_type_id=institution_type_id,
                institution_id=institution_id,
                sort_by='score'
            )

            for service in suggestions['services']:
                explanation = []
                if institution_id and service['institution']['id'] == institution_id:
                    explanation.append(f"Você prefere {service['institution']['name']}")
                if service['queue']['distance'] != 'Desconhecida':
                    explanation.append(f"Filial a {service['queue']['distance']:.2f} km")
                if service['queue']['wait_time'] != "N/A":
                    wait_time = int(float(service['queue']['wait_time'].split()[0]))
                    explanation.append(f"Espera de {wait_time} min")
                if service['queue']['quality_score'] > 0.8:
                    explanation.append("Alta qualidade")
                service['queue']['explanation'] = "; ".join(explanation) or "Recomendado com base na sua busca"

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(suggestions, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Sugestões geradas para user_id={user_id}: {len(suggestions['services'])} resultados")
            return jsonify(suggestions), 200
        except Exception as e:
            logger.error(f"Erro ao gerar sugestões: {e}")
            return jsonify({'error': "Erro ao gerar sugestões"}), 500

    @app.route('/api/update_location', methods=['POST'])
    @require_auth
    def update_location():
        """Atualiza a localização do usuário."""
        data = request.get_json() or {}
        user_id = request.user_id
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        email = data.get('email')
        institution_type_id = data.get('institution_type_id')

        if not user_id or latitude is None or longitude is None:
            logger.error(f"Parâmetros obrigatórios faltando: user_id={user_id}, lat={latitude}, lon={longitude}")
            return jsonify({'error': 'user_id, latitude e longitude são obrigatórios'}), 400

        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (ValueError, TypeError):
            logger.error(f"Latitude ou longitude inválidos: lat={latitude}, lon={longitude}")
            return jsonify({'error': 'Latitude e longitude devem ser números'}), 400

        if institution_type_id and not isinstance(institution_type_id, str):
            logger.warning(f"institution_type_id inválido: {institution_type_id}")
            return jsonify({'error': 'institution_type_id deve ser uma string'}), 400

        user = User.query.get(user_id)
        if not user:
            if not email:
                logger.error(f"Email não fornecido para criar usuário: user_id={user_id}")
                return jsonify({'error': 'Email é obrigatório para criar um novo usuário'}), 400
            user = User(id=user_id, email=email, name="Usuário Desconhecido", active=True)
            db.session.add(user)

        user.last_known_lat = latitude
        user.last_known_lon = longitude
        user.last_location_update = datetime.utcnow()
        db.session.commit()
        logger.info(f"Localização atualizada para user_id={user_id}: lat={latitude}, lon={longitude}")

        QueueService.check_proximity_notifications(
            user_id=user_id,
            user_lat=latitude,
            user_lon=longitude,
            institution_type_id=institution_type_id
        )
        QueueService.check_proactive_notifications()
        return jsonify({'message': 'Localização atualizada com sucesso'}), 200

    @app.route('/api/queue/create', methods=['POST'])
    @require_auth
    def create_queue():
        """Cria uma nova fila."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de criar fila por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        data = request.get_json() or {}
        required = ['service', 'prefix', 'department_id', 'daily_limit', 'num_counters', 'branch_id']
        if not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de fila")
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400

        if not isinstance(data['service'], str) or not data['service'].strip():
            logger.warning(f"Serviço inválido: {data['service']}")
            return jsonify({'error': 'Serviço deve ser uma string válida'}), 400
        if not re.match(r'^[A-Z]$', data['prefix']):
            logger.warning(f"Prefixo inválido: {data['prefix']}")
            return jsonify({'error': 'Prefixo deve ser uma única letra maiúscula'}), 400
        if not isinstance(data['daily_limit'], int) or data['daily_limit'] <= 0:
            logger.warning(f"Limite diário inválido: {data['daily_limit']}")
            return jsonify({'error': 'Limite diário deve ser um número positivo'}), 400
        if not isinstance(data['num_counters'], int) or data['num_counters'] <= 0:
            logger.warning(f"Número de guichês inválido: {data['num_counters']}")
            return jsonify({'error': 'Número de guichês deve ser um número positivo'}), 400
        if not isinstance(data['department_id'], str) or not isinstance(data['branch_id'], str):
            logger.warning(f"department_id ou branch_id inválidos: {data['department_id']}, {data['branch_id']}")
            return jsonify({'error': 'department_id e branch_id devem ser strings'}), 400

        department = Department.query.get(data['department_id'])
        branch = Branch.query.get(data['branch_id'])
        if not department or not branch:
            logger.error(f"Departamento ou filial não encontrados: department_id={data['department_id']}, branch_id={data['branch_id']}")
            return jsonify({'error': 'Departamento ou filial não encontrados'}), 404

        if user.user_role == UserRole.DEPARTMENT_ADMIN and user.department_id != data['department_id']:
            logger.warning(f"Usuário {user.id} não tem permissão para criar fila no departamento {data['department_id']}")
            return jsonify({'error': 'Sem permissão para este departamento'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para criar fila na instituição {branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        if Queue.query.filter_by(service=data['service'], department_id=data['department_id']).first():
            logger.warning(f"Fila já existe para o serviço {data['service']} no departamento {data['department_id']}")
            return jsonify({'error': 'Fila já existe'}), 400

        queue = Queue(
            id=str(uuid.uuid4()),
            department_id=data['department_id'],
            service=data['service'],
            prefix=data['prefix'],
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
    def update_queue(id):
        """Atualiza uma fila."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de atualizar fila por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get_or_404(id)
        data = request.get_json() or {}

        if user.user_role == UserRole.DEPARTMENT_ADMIN and queue.department_id != user.department_id:
            logger.warning(f"Usuário {user.id} não tem permissão para atualizar fila {id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para atualizar fila na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        if 'service' in data and (not isinstance(data['service'], str) or not data['service'].strip()):
            logger.warning(f"Serviço inválido: {data['service']}")
            return jsonify({'error': 'Serviço deve ser uma string válida'}), 400
        if 'prefix' in data and not re.match(r'^[A-Z]$', data['prefix']):
            logger.warning(f"Prefixo inválido: {data['prefix']}")
            return jsonify({'error': 'Prefixo deve ser uma única letra maiúscula'}), 400
        if 'daily_limit' in data and (not isinstance(data['daily_limit'], int) or data['daily_limit'] <= 0):
            logger.warning(f"Limite diário inválido: {data['daily_limit']}")
            return jsonify({'error': 'Limite diário deve ser um número positivo'}), 400
        if 'num_counters' in data and (not isinstance(data['num_counters'], int) or data['num_counters'] <= 0):
            logger.warning(f"Número de guichês inválido: {data['num_counters']}")
            return jsonify({'error': 'Número de guichês deve ser um número positivo'}), 400
        if 'department_id' in data and not isinstance(data['department_id'], str):
            logger.warning(f"department_id inválido: {data['department_id']}")
            return jsonify({'error': 'department_id deve ser uma string'}), 400

        queue.service = data.get('service', queue.service)
        queue.prefix = data.get('prefix', queue.prefix)
        if 'department_id' in data:
            department = Department.query.get(data['department_id'])
            if not department:
                logger.error(f"Departamento não encontrado: department_id={data['department_id']}")
                return jsonify({'error': 'Departamento não encontrado'}), 404
            queue.department_id = data['department_id']
        queue.daily_limit = data.get('daily_limit', queue.daily_limit)
        queue.num_counters = data.get('num_counters', queue.num_counters)
        db.session.commit()
        logger.info(f"Fila atualizada: {queue.service} (ID: {id})")
        return jsonify({'message': 'Fila atualizada'}), 200

    @app.route('/api/queue/<id>', methods=['DELETE'])
    @require_auth
    def delete_queue(id):
        """Exclui uma fila."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de excluir fila por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get_or_404(id)
        if user.user_role == UserRole.DEPARTMENT_ADMIN and queue.department_id != user.department_id:
            logger.warning(f"Usuário {user.id} não tem permissão para excluir fila {id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para excluir fila na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        if Ticket.query.filter_by(queue_id=id, status='Pendente').first():
            logger.warning(f"Tentativa de excluir fila {id} com tickets pendentes")
            return jsonify({'error': 'Não é possível excluir: fila possui tickets pendentes'}), 400
        db.session.delete(queue)
        db.session.commit()
        logger.info(f"Fila excluída: {id}")
        if redis_client:
            try:
                redis_client.delete(f"cache:search:*")
            except Exception as e:
                logger.warning(f"Erro ao invalidar cache Redis: {e}")
        return jsonify({'message': 'Fila excluída'}), 200

    @app.route('/api/queue/<service>/ticket', methods=['POST'])
    @require_auth
    def get_ticket(service):
        """Emite um ticket para uma fila."""
        data = request.get_json() or {}
        fcm_token = data.get('fcm_token')
        priority = data.get('priority', 0)
        is_physical = data.get('is_physical', False)
        branch_id = data.get('branch_id')
        user_lat = data.get('user_lat')
        user_lon = data.get('user_lon')

        if not isinstance(service, str) or not service.strip():
            logger.warning(f"Serviço inválido: {service}")
            return jsonify({'error': 'Serviço deve ser uma string válida'}), 400
        if not isinstance(priority, int) or priority < 0:
            logger.warning(f"Prioridade inválida: {priority}")
            return jsonify({'error': 'Prioridade deve ser um número inteiro não negativo'}), 400
        if is_physical and not branch_id:
            logger.warning("branch_id é obrigatório para tickets físicos")
            return jsonify({'error': 'branch_id é obrigatório para tickets físicos'}), 400
        if branch_id and not isinstance(branch_id, str):
            logger.warning(f"branch_id inválido: {branch_id}")
            return jsonify({'error': 'branch_id deve ser uma string'}), 400
        if user_lat is not None:
            try:
                user_lat = float(user_lat)
            except (ValueError, TypeError):
                logger.warning(f"Latitude inválida: {user_lat}")
                return jsonify({'error': 'Latitude deve ser um número'}), 400
        if user_lon is not None:
            try:
                user_lon = float(user_lon)
            except (ValueError, TypeError):
                logger.warning(f"Longitude inválida: {user_lon}")
                return jsonify({'error': 'Longitude deve ser um número'}), 400

        try:
            user_id = request.user_id
            ticket, pdf_buffer = QueueService.add_to_queue(
                service=service,
                user_id=user_id,
                priority=priority,
                is_physical=is_physical,
                fcm_token=fcm_token,
                branch_id=branch_id,
                user_lat=user_lat,
                user_lon=user_lon
            )
            emit_ticket_update(ticket)
            wait_time = QueueService.calculate_wait_time(ticket.queue.id, ticket.ticket_number, ticket.priority, user_lat, user_lon)
            quality_score = service_recommendation_predictor.predict(ticket.queue, user_id, user_lat, user_lon)
            predicted_demand = demand_model.predict(ticket.queue.id, hours_ahead=1)

            alternatives = clustering_model.get_alternatives(ticket.queue.id, n=3)
            alternative_queues = Queue.query.filter(Queue.id.in_(alternatives)).all()
            alternatives_data = []
            for alt_queue in alternative_queues:
                alt_wait_time = QueueService.calculate_wait_time(alt_queue.id, alt_queue.active_tickets + 1, 0, user_lat, user_lon)
                alt_distance = QueueService.calculate_distance(user_lat, user_lon, alt_queue.department.branch) if user_lat and user_lon else None
                alt_quality_score = service_recommendation_predictor.predict(alt_queue, user_id, user_lat, user_lon)
                explanation = []
                if alt_distance is not None:
                    explanation.append(f"Filial a {alt_distance:.2f} km")
                if isinstance(alt_wait_time, (int, float)):
                    explanation.append(f"Espera de {int(alt_wait_time)} min")
                if alt_quality_score > 0.8:
                    explanation.append("Alta qualidade")
                alternatives_data.append({
                    'queue_id': alt_queue.id,
                    'service': alt_queue.service or "Desconhecido",
                    'branch': alt_queue.department.branch.name or "Desconhecida",
                    'wait_time': f"{int(alt_wait_time)} minutos" if isinstance(alt_wait_time, (int, float)) else 'Aguardando início',
                    'distance': float(alt_distance) if alt_distance is not None else 'Desconhecida',
                    'quality_score': float(alt_quality_score),
                    'explanation': ", ".join(explanation) or "Alternativa recomendada"
                })

            response = {
                'message': 'Senha emitida',
                'ticket': {
                    'id': ticket.id,
                    'number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'qr_code': ticket.qr_code,
                    'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
                    'receipt': ticket.receipt_data,
                    'priority': ticket.priority,
                    'is_physical': ticket.is_physical,
                    'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None,
                    'branch_id': ticket.queue.department.branch_id if ticket.queue.department else None,
                    'quality_score': float(quality_score),
                    'predicted_demand': float(predicted_demand),
                    'alternatives': alternatives_data
                }
            }

            if is_physical and pdf_buffer:
                return send_file(
                    io.BytesIO(pdf_buffer.getvalue()),
                    as_attachment=True,
                    download_name=f"ticket_{ticket.queue.prefix}{ticket.ticket_number}.pdf",
                    mimetype='application/pdf'
                )

            logger.info(f"Senha emitida: {ticket.queue.prefix}{ticket.ticket_number} para user_id={user_id}")
            QueueService.check_proactive_notifications()
            return jsonify(response), 201
        except ValueError as e:
            logger.error(f"Erro ao emitir senha para serviço {service}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao emitir senha para serviço {service}: {str(e)}")
            return jsonify({'error': 'Erro interno ao emitir senha'}), 500

    @app.route('/api/ticket/<ticket_id>/pdf', methods=['GET'])
    @require_auth
    def download_ticket_pdf(ticket_id):
        """Baixa o PDF de um ticket."""
        ticket = Ticket.query.get_or_404(ticket_id)
        user_id = request.user_id
        if ticket.user_id != user_id and ticket.user_id != 'PRESENCIAL':
            logger.warning(f"Tentativa não autorizada de baixar PDF do ticket {ticket_id} por user_id={user_id}")
            return jsonify({'error': 'Não autorizado'}), 403

        try:
            pdf_buffer = QueueService.generate_pdf_ticket(ticket)
            logger.info(f"PDF gerado para ticket {ticket_id}")
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=f"ticket_{ticket.queue.prefix}{ticket.ticket_number}.pdf",
                mimetype='application/pdf'
            )
        except Exception as e:
            logger.error(f"Erro ao gerar PDF para ticket {ticket_id}: {e}")
            return jsonify({'error': 'Erro ao gerar PDF'}), 500

    @app.route('/api/ticket/<ticket_id>', methods=['GET'])
    @require_auth
    def ticket_status(ticket_id):
        """Consulta o status de um ticket."""
        ticket = Ticket.query.get_or_404(ticket_id)
        user_id = request.user_id
        if ticket.user_id != user_id and ticket.user_id != 'PRESENCIAL':
            logger.warning(f"Tentativa não autorizada de visualizar status do ticket {ticket_id} por user_id={user_id}")
            return jsonify({'error': 'Não autorizado'}), 403

        queue = ticket.queue
        wait_time = QueueService.calculate_wait_time(queue.id, ticket.ticket_number, ticket.priority)
        quality_score = service_recommendation_predictor.predict(queue, user_id)
        predicted_demand = demand_model.predict(queue.id, hours_ahead=1)

        institution = queue.department.branch.institution if queue.department and queue.department.branch and queue.department.branch.institution else None

        return jsonify({
            'service': queue.service or "Desconhecido",
            'institution': {
                'name': institution.name if institution else "Desconhecida",
                'type': {
                    'id': institution.type.id if institution and institution.type else None,
                    'name': institution.type.name if institution and institution.type else "Desconhecido"
                }
            },
            'branch': queue.department.branch.name if queue.department and queue.department.branch else "Desconhecida",
            'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
            'qr_code': ticket.qr_code,
            'status': ticket.status,
            'counter': f"{ticket.counter:02d}" if ticket.counter else None,
            'position': max(0, ticket.ticket_number - queue.current_ticket),
            'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
            'priority': ticket.priority,
            'is_physical': ticket.is_physical,
            'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None,
            'quality_score': float(quality_score),
            'predicted_demand': float(predicted_demand)
        }), 200

    @app.route('/api/queue/<service>/call', methods=['POST'])
    @require_auth
    def call_next_ticket(service):
        """Chama o próximo ticket."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de chamar ticket por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        try:
            data = request.get_json() or {}
            branch_id = data.get('branch_id')
            ticket = QueueService.call_next(service, branch_id=branch_id)
            if user.user_role == UserRole.DEPARTMENT_ADMIN and ticket.queue.department_id != user.department_id:
                logger.warning(f"Usuário {user.id} não tem permissão para chamar ticket na fila {ticket.queue_id}")
                return jsonify({'error': 'Sem permissão para esta fila'}), 403
            if user.user_role == UserRole.INSTITUTION_ADMIN and ticket.queue.department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {user.id} não tem permissão para chamar ticket na instituição {ticket.queue.department.branch.institution_id}")
                return jsonify({'error': 'Sem permissão para esta instituição'}), 403

            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=ticket.queue.department.branch.institution_id,
                queue_id=ticket.queue_id,
                event_type='new_call',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter,
                    'timestamp': ticket.attended_at.isoformat() if ticket.attended_at else None,
                    'predicted_demand': float(demand_model.predict(ticket.queue.id, hours_ahead=1))
                }
            )
            logger.info(f"Senha chamada: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket.id})")
            return jsonify({
                'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} chamada',
                'ticket_id': ticket.id,
                'remaining': ticket.queue.active_tickets
            }), 200
        except ValueError as e:
            logger.error(f"Erro ao chamar próxima senha para serviço {service}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao chamar próxima senha para serviço {service}: {str(e)}")
            return jsonify({'error': 'Erro interno ao chamar senha'}), 500

    @app.route('/api/ticket/call/<string:ticket_id>', methods=['POST'])
    @require_auth
    def call_ticket(ticket_id):
        """Chama um ticket específico."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de chamar ticket {ticket_id} por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.status != 'Pendente':
            logger.warning(f"Tentativa de chamar ticket {ticket_id} com status {ticket.status}")
            return jsonify({'error': f'Ticket já está {ticket.status}'}), 400

        if user.user_role == UserRole.DEPARTMENT_ADMIN and ticket.queue.department_id != user.department_id:
            logger.warning(f"Usuário {user.id} não tem permissão para chamar ticket {ticket_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and ticket.queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para chamar ticket na instituição {ticket.queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        try:
            queue = ticket.queue
            data = request.get_json() or {}
            counter = data.get('counter', queue.last_counter or 1)

            ticket.status = 'Chamado'
            ticket.attended_at = datetime.utcnow()
            ticket.counter = counter
            queue.current_ticket = ticket.ticket_number
            queue.active_tickets -= 1
            queue.last_counter = counter
            db.session.commit()

            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue.id,
                event_type='new_call',
                data={
                    'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter,
                    'timestamp': ticket.attended_at.isoformat() if ticket.attended_at else None,
                    'predicted_demand': float(demand_model.predict(queue.id, hours_ahead=1))
                }
            )

            logger.info(f"Ticket {ticket_id} chamado com sucesso: {queue.prefix}{ticket.ticket_number}")
            QueueService.check_proactive_notifications()
            return jsonify({
                'message': 'Ticket chamado com sucesso',
                'ticket': {
                    'id': ticket.id,
                    'number': f"{queue.prefix}{ticket.ticket_number}",
                    'status': ticket.status,
                    'counter': ticket.counter
                }
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao chamar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': f'Erro ao chamar ticket: {str(e)}'}), 500

    @app.route('/api/ticket/trade/offer/<ticket_id>', methods=['POST'])
    @require_auth
    def offer_trade(ticket_id):
        """Oferece um ticket para troca."""
        user_id = request.user_id
        try:
            ticket = QueueService.offer_trade(ticket_id, user_id)
            emit_ticket_update(ticket)
            logger.info(f"Senha oferecida para troca: {ticket_id}")
            QueueService.send_notification(
                fcm_token=None,
                message=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} oferecido para troca",
                ticket_id=ticket.id,
                via_websocket=True,
                user_id=ticket.user_id
            )
            return jsonify({'message': 'Senha oferecida para troca', 'ticket_id': ticket.id}), 200
        except ValueError as e:
            logger.error(f"Erro ao oferecer troca para ticket {ticket_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao oferecer troca para ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao oferecer troca'}), 500

    @app.route('/api/ticket/trade/<ticket_to_id>', methods=['POST'])
    @require_auth
    def trade_ticket(ticket_to_id):
        """Realiza a troca de tickets."""
        user_id = request.user_id
        data = request.get_json() or {}
        ticket_from_id = data.get('ticket_from_id')
        if not ticket_from_id:
            logger.warning("ticket_from_id não fornecido para troca")
            return jsonify({'error': 'ticket_from_id é obrigatório'}), 400

        try:
            result = QueueService.trade_tickets(ticket_from_id, ticket_to_id, user_id)
            emit_ticket_update(result['ticket_from'])
            emit_ticket_update(result['ticket_to'])
            logger.info(f"Troca realizada entre tickets {ticket_from_id} e {ticket_to_id}")
            QueueService.send_notification(
                fcm_token=None,
                message=f"Troca realizada: Ticket {result['ticket_from'].queue.prefix}{result['ticket_from'].ticket_number}",
                ticket_id=result['ticket_from'].id,
                via_websocket=True,
                user_id=result['ticket_from'].user_id
            )
            QueueService.send_notification(
                fcm_token=None,
                message=f"Troca realizada: Ticket {result['ticket_to'].queue.prefix}{result['ticket_to'].ticket_number}",
                ticket_id=result['ticket_to'].id,
                via_websocket=True,
                user_id=result['ticket_to'].user_id
            )
            return jsonify({
                'message': 'Troca realizada',
                'tickets': {
                    'from': {'id': result['ticket_from'].id, 'number': f"{result['ticket_from'].queue.prefix}{result['ticket_from'].ticket_number}"},
                    'to': {'id': result['ticket_to'].id, 'number': f"{result['ticket_to'].queue.prefix}{result['ticket_to'].ticket_number}"}
                }
            }), 200
        except ValueError as e:
            logger.error(f"Erro ao realizar troca entre tickets {ticket_from_id} e {ticket_to_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao realizar troca entre tickets {ticket_from_id} e {ticket_to_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao realizar troca'}), 500

    @app.route('/api/ticket/validate', methods=['POST'])
    def validate_ticket():
        """Valida a presença de um ticket."""
        data = request.get_json() or {}
        qr_code = data.get('qr_code')
        user_lat = data.get('user_lat')
        user_lon = data.get('user_lon')

        if not qr_code:
            logger.warning("Requisição de validação sem qr_code")
            return jsonify({'error': 'qr_code é obrigatório'}), 400

        if user_lat is not None and user_lon is not None:
            try:
                user_lat = float(user_lat)
                user_lon = float(user_lon)
            except (ValueError, TypeError):
                logger.warning(f"Latitude ou longitude inválidos: lat={user_lat}, lon={user_lon}")
                return jsonify({'error': 'Latitude e longitude devem ser números'}), 400

        try:
            ticket = QueueService.validate_presence(
                qr_code=qr_code,
                user_lat=user_lat,
                user_lon=user_lon
            )
            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=ticket.queue.department.branch.institution_id,
                queue_id=ticket.queue_id,
                event_type='call_completed',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter,
                    'timestamp': ticket.attended_at.isoformat() if ticket.attended_at else None,
                    'service_time': float(ticket.service_time) if ticket.service_time else None
                }
            )
            logger.info(f"Presença validada para ticket {ticket.id}")
            QueueService.send_notification(
                fcm_token=None,
                message=f"Presença validada para ticket {ticket.queue.prefix}{ticket.ticket_number}",
                ticket_id=ticket.id,
                via_websocket=True,
                user_id=ticket.user_id
            )
            return jsonify({'message': 'Presença validada com sucesso', 'ticket_id': ticket.id}), 200
        except ValueError as e:
            logger.error(f"Erro ao validar ticket (qr_code={qr_code}): {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao validar ticket: {str(e)}")
            return jsonify({'error': f'Erro ao validar ticket: {str(e)}'}), 500

    @app.route('/api/queues', methods=['GET'])
    def list_queues():
        """Lista todas as filas."""
        try:
            now = datetime.utcnow()
            current_weekday_str = now.strftime('%A')
            try:
                current_weekday_enum = getattr(Weekday, current_weekday_str.upper())
            except AttributeError:
                logger.error(f"Dia da semana inválido: {current_weekday_str}")
                return jsonify({'error': 'Dia da semana inválido'}), 500
            current_time = now.time()
            result = []

            institutions = Institution.query.all()
            for inst in institutions:
                branches = Branch.query.filter_by(institution_id=inst.id).all()
                branch_ids = [b.id for b in branches]
                departments = Department.query.filter(Department.branch_id.in_(branch_ids)).all()
                department_ids = [d.id for d in departments]
                queues = Queue.query.filter(Queue.department_id.in_(department_ids)).all()
                queue_data = []

                for q in queues:
                    schedule = QueueSchedule.query.filter_by(queue_id=q.id, weekday=current_weekday_enum).first()
                    is_open = False
                    if schedule and not schedule.is_closed:
                        is_open = (
                            schedule.open_time and schedule.end_time and
                            current_time >= schedule.open_time and
                            current_time <= schedule.end_time and
                            q.active_tickets < q.daily_limit
                        )

                    wait_time = QueueService.calculate_wait_time(q.id, q.current_ticket + 1, 0)
                    quality_score = service_recommendation_predictor.predict(q)
                    predicted_demand = demand_model.predict(q.id, hours_ahead=1)

                    queue_data.append({
                        'id': q.id,
                        'service': q.service or "Desconhecido",
                        'prefix': q.prefix,
                        'sector': q.department.sector if q.department else None,
                        'department': q.department.name if q.department else None,
                        'branch': q.department.branch.name if q.department and q.department.branch else None,
                        'open_time': schedule.open_time.strftime('%H:%M') if schedule and schedule.open_time else None,
                        'end_time': schedule.end_time.strftime('%H:%M') if schedule and schedule.end_time else None,
                        'daily_limit': q.daily_limit or 0,
                        'active_tickets': q.active_tickets or 0,
                        'avg_wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
                        'num_counters': q.num_counters or 1,
                        'status': 'Aberto' if is_open else 'Fechado',
                        'quality_score': float(quality_score),
                        'predicted_demand': float(predicted_demand)
                    })

                result.append({
                    'institution': {
                        'id': inst.id,
                        'name': inst.name or "Desconhecida",
                        'description': inst.description or "Sem descrição",
                        'type': {
                            'id': inst.type.id if inst.type else None,
                            'name': inst.type.name if inst.type else "Desconhecido"
                        }
                    },
                    'queues': queue_data,
                    'branches': [
                        {
                            'id': b.id,
                            'name': b.name or "Desconhecida",
                            'location': b.location or "Desconhecida",
                            'neighborhood': b.neighborhood or "Desconhecido",
                            'latitude': float(b.latitude) if b.latitude else None,
                            'longitude': float(b.longitude) if b.longitude else None
                        } for b in branches
                    ]
                })

            logger.info(f"Lista de filas retornada: {len(result)} instituições encontradas")
            return jsonify(result), 200
        except Exception as e:
            logger.error(f"Erro ao listar filas: {str(e)}")
            return jsonify({'error': f'Erro ao listar filas: {str(e)}'}), 500

    @app.route('/api/tickets', methods=['GET'])
    @require_auth
    def list_user_tickets():
        """Lista os tickets de um usuário."""
        user_id = request.user_id
        try:
            tickets = Ticket.query.filter_by(user_id=user_id).all()
            return jsonify([{
                'id': t.id,
                'service': t.queue.service or "Desconhecido",
                'institution': {
                    'name': t.queue.department.branch.institution.name if t.queue.department and t.queue.department.branch and t.queue.department.branch.institution else "Desconhecida",
                    'type': {
                        'id': t.queue.department.branch.institution.type.id if t.queue.department and t.queue.department.branch and t.queue.department.branch.institution and t.queue.department.branch.institution.type else None,
                        'name': t.queue.department.branch.institution.type.name if t.queue.department and t.queue.department.branch and t.queue.department.branch.institution and t.queue.department.branch.institution.type else "Desconhecido"
                    }
                },
                'branch': t.queue.department.branch.name if t.queue.department and t.queue.department.branch else "Desconhecida",
                'number': f"{t.queue.prefix}{t.ticket_number}",
                'status': t.status,
                'counter': f"{t.counter:02d}" if t.counter else None,
                'position': max(0, t.ticket_number - t.queue.current_ticket) if t.status == 'Pendente' else 0,
                'wait_time': f"{int(wait_time)} minutos" if isinstance((wait_time := QueueService.calculate_wait_time(t.queue.id, t.ticket_number, t.priority)), (int, float)) else "N/A",
                'qr_code': t.qr_code,
                'trade_available': t.trade_available,
                'quality_score': float(service_recommendation_predictor.predict(t.queue, user_id)),
                'predicted_demand': float(demand_model.predict(t.queue.id, hours_ahead=1))
            } for t in tickets]), 200
        except Exception as e:
            logger.error(f"Erro ao listar tickets do usuário {user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar tickets'}), 500

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

            return jsonify([{
                'id': t.id,
                'service': t.queue.service or "Desconhecido",
                'institution': {
                    'name': t.queue.department.branch.institution.name if t.queue.department and t.queue.department.branch and t.queue.department.branch.institution else "Desconhecida",
                    'type': {
                        'id': t.queue.department.branch.institution.type.id if t.queue.department and t.queue.department.branch and t.queue.department.branch.institution and t.queue.department.branch.institution.type else None,
                        'name': t.queue.department.branch.institution.type.name if t.queue.department and t.queue.department.branch and t.queue.department.branch.institution and t.queue.department.branch.institution.type else "Desconhecido"
                    }
                },
                'branch': t.queue.department.branch.name if t.queue.department and t.queue.department.branch else "Desconhecida",
                'number': f"{t.queue.prefix}{t.ticket_number}",
                'position': max(0, t.ticket_number - t.queue.current_ticket),
                'user_id': t.user_id,
                'wait_time': f"{int(wait_time)} minutos" if isinstance((wait_time := QueueService.calculate_wait_time(t.queue.id, t.ticket_number, t.priority)), (int, float)) else "N/A",
                'quality_score': float(service_recommendation_predictor.predict(t.queue, user_id))
            } for t in tickets]), 200
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
                fcm_token=None,
                message=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} cancelado",
                ticket_id=ticket.id,
                via_websocket=True,
                user_id=ticket.user_id
            )
            return jsonify({'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} cancelada', 'ticket_id': ticket.id}), 200
        except ValueError as e:
            logger.error(f"Erro ao cancelar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao cancelar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao cancelar ticket'}), 500

    @app.route('/api/queues/<queue_id>/schedule', methods=['GET'])
    def get_queue_schedule(queue_id):
        """Retorna o horário de funcionamento de uma fila."""
        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        cache_key = f"cache:queue_schedule:{queue_id}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            schedules = QueueSchedule.query.filter_by(queue_id=queue_id).all()
            result = []
            for schedule in schedules:
                result.append({
                    'weekday': schedule.weekday.value,
                    'open_time': schedule.open_time.strftime('%H:%M') if schedule.open_time else None,
                    'end_time': schedule.end_time.strftime('%H:%M') if schedule.end_time else None,
                    'is_closed': schedule.is_closed
                })

            response = {'queue_id': queue_id, 'schedules': result}

            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Horários da fila retornados para queue_id={queue_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter horários da fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter horários da fila'}), 500

    @app.route('/api/queues/<queue_id>/schedule', methods=['POST'])
    @require_auth
    def update_queue_schedule(queue_id):
        """Atualiza o horário de funcionamento de uma fila."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de atualizar horário por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.DEPARTMENT_ADMIN and queue.department_id != user.department_id:
            logger.warning(f"Usuário {user_id} não tem permissão para atualizar horário da fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user_id} não tem permissão para atualizar horário na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        data = request.get_json() or {}
        if not isinstance(data, list):
            logger.warning("Dados de horário devem ser uma lista")
            return jsonify({'error': 'Dados de horário devem ser uma lista'}), 400

        try:
            for schedule_data in data:
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

                schedule = QueueSchedule.query.filter_by(queue_id=queue_id, weekday=weekday).first()
                if not schedule:
                    schedule = QueueSchedule(queue_id=queue_id, weekday=weekday)
                    db.session.add(schedule)

                schedule.is_closed = is_closed
                if not is_closed:
                    schedule.open_time = open_time
                    schedule.end_time = end_time
                else:
                    schedule.open_time = None
                    schedule.end_time = None

            db.session.commit()

            if redis_client:
                try:
                    redis_client.delete(f"cache:queue_schedule:{queue_id}")
                    logger.info(f"Cache invalidado para queue_schedule:{queue_id}")
                except Exception as e:
                    logger.warning(f"Erro ao invalidar cache Redis: {e}")

            logger.info(f"Horários atualizados para queue_id={queue_id}")
            return jsonify({'message': 'Horários atualizados com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar horários da fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao atualizar horários'}), 500

    @app.route('/api/queues/<queue_id>/metrics', methods=['GET'])
    @require_auth
    def queue_metrics(queue_id):
        """Retorna métricas detalhadas de uma fila."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar métricas por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.DEPARTMENT_ADMIN and queue.department_id != user.department_id:
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
                'service': queue.service or "Desconhecido",
                'branch': queue.department.branch.name if queue.department and queue.department.branch else "Desconhecida",
                'metrics': {
                    'total_tickets': metrics['total_tickets'],
                    'active_tickets': metrics['active_tickets'],
                    'avg_wait_time': f"{int(metrics['avg_wait_time'])} minutos" if metrics['avg_wait_time'] else "N/A",
                    'avg_service_time': f"{int(metrics['avg_service_time'])} minutos" if metrics['avg_service_time'] else "N/A",
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

    @socketio.on('connect', namespace='/')
    def handle_connect():
        """Gerencia conexão WebSocket."""
        try:
            auth_token = request.args.get('token')
            if not auth_token:
                logger.warning("Tentativa de conexão WebSocket sem token")
                raise ConnectionRefusedError('Token de autenticação necessário')

            try:
                decoded_token = auth.verify_id_token(auth_token)
                user_id = decoded_token['uid']
            except Exception as e:
                logger.error(f"Erro ao verificar token de autenticação: {str(e)}")
                raise ConnectionRefusedError('Token de autenticação inválido')

            join_room(user_id)
            logger.info(f"Usuário {user_id} conectado ao WebSocket")
        except ConnectionRefusedError as e:
            logger.error(f"Conexão WebSocket recusada: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Erro inesperado na conexão WebSocket: {str(e)}")
            raise ConnectionRefusedError('Erro ao conectar')

    @socketio.on('disconnect', namespace='/')
    def handle_disconnect():
        """Gerencia desconexão WebSocket."""
        try:
            auth_token = request.args.get('token')
            if auth_token:
                decoded_token = auth.verify_id_token(auth_token)
                user_id = decoded_token['uid']
                leave_room(user_id)
                logger.info(f"Usuário {user_id} desconectado do WebSocket")
        except Exception as e:
            logger.error(f"Erro ao desconectar WebSocket: {str(e)}")

    @socketio.on('subscribe_dashboard', namespace='/dashboard')
    def handle_dashboard_subscription(data):
        """Inscreve um cliente no painel de uma instituição."""
        try:
            institution_id = data.get('institution_id')
            auth_token = data.get('token')
            if not institution_id or not auth_token:
                logger.warning("institution_id ou token não fornecidos para inscrição no painel")
                raise ConnectionRefusedError('institution_id e token são obrigatórios')

            try:
                decoded_token = auth.verify_id_token(auth_token)
                user_id = decoded_token['uid']
            except Exception as e:
                logger.error(f"Erro ao verificar token para inscrição no painel: {str(e)}")
                raise ConnectionRefusedError('Token de autenticação inválido')

            user = User.query.get(user_id)
            if not user or user.user_role not in [UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
                logger.warning(f"Usuário {user_id} não autorizado a se inscrever no painel")
                raise ConnectionRefusedError('Acesso restrito a administradores')

            if user.user_role == UserRole.INSTITUTION_ADMIN and user.institution_id != institution_id:
                logger.warning(f"Usuário {user_id} não tem permissão para o painel da instituição {institution_id}")
                raise ConnectionRefusedError('Sem permissão para esta instituição')

            join_room(institution_id)
            logger.info(f"Usuário {user_id} inscrito no painel da instituição {institution_id}")
            socketio.emit('dashboard_update', {
                'institution_id': institution_id,
                'event_type': 'subscription',
                'data': {'message': 'Inscrito com sucesso'}
            }, room=institution_id, namespace='/dashboard')
        except ConnectionRefusedError as e:
            logger.error(f"Inscrição no painel recusada: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Erro ao inscrever no painel: {str(e)}")
            raise ConnectionRefusedError('Erro ao inscrever no painel')

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
            logger.warning(f"Usuário {user_id} não tem permissão para acessar auditoria da instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

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

        try:
            audit_logs = AuditLog.query.filter_by(queue_id=queue_id).order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
            response = {
                'audit_logs': [
                    {
                        'id': log.id,
                        'action': log.action,
                        'user_id': log.user_id,
                        'ticket_id': log.ticket_id,
                        'details': log.details,
                        'timestamp': log.timestamp.isoformat()
                    } for log in audit_logs.items
                ],
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_results': audit_logs.total,
                    'total_pages': audit_logs.pages
                }
            }
            logger.info(f"Logs de auditoria retornados para queue_id={queue_id}: {len(audit_logs.items)} logs")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter logs de auditoria para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter logs de auditoria'}), 500

    @app.route('/api/queues/<queue_id>/recommendations', methods=['GET'])
    def queue_recommendations(queue_id):
        """Retorna recomendações personalizadas para uma fila."""
        user_id = request.args.get('user_id')
        user_lat = request.args.get('latitude')
        user_lon = request.args.get('longitude')

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

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

        cache_key = f"cache:queue_recommendations:{queue_id}:{user_id}:{user_lat}:{user_lon}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            recommendations = collaborative_model.get_recommendations(queue_id, user_id, n=5)
            result = []
            for rec_queue_id in recommendations:
                rec_queue = Queue.query.get(rec_queue_id)
                if not rec_queue:
                    continue
                wait_time = QueueService.calculate_wait_time(rec_queue.id, rec_queue.active_tickets + 1, 0, user_lat, user_lon)
                distance = QueueService.calculate_distance(user_lat, user_lon, rec_queue.department.branch) if user_lat and user_lon else None
                quality_score = service_recommendation_predictor.predict(rec_queue, user_id, user_lat, user_lon)
                explanation = []
                if distance is not None:
                    explanation.append(f"Filial a {distance:.2f} km")
                if isinstance(wait_time, (int, float)):
                    explanation.append(f"Espera de {int(wait_time)} min")
                if quality_score > 0.8:
                    explanation.append("Alta qualidade")
                result.append({
                    'queue_id': rec_queue.id,
                    'service': rec_queue.service or "Desconhecido",
                    'branch': rec_queue.department.branch.name or "Desconhecida",
                    'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else 'N/A',
                    'distance': float(distance) if distance is not None else 'Desconhecida',
                    'quality_score': float(quality_score),
                    'explanation': "; ".join(explanation) or "Recomendado com base nas suas preferências"
                })

            response = {'queue_id': queue_id, 'recommendations': result}

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Recomendações retornadas para queue_id={queue_id}: {len(result)} recomendações")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter recomendações para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter recomendações'}), 500
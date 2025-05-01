from flask import jsonify, request, send_file
from flask_socketio import join_room, leave_room, ConnectionRefusedError
from . import db, socketio, redis_client
from .models import AuditLog, Institution, Branch, Queue, Ticket, User, Department, UserRole, InstitutionType, InstitutionService, ServiceCategory, ServiceTag, UserPreference, BranchSchedule, UserBehavior, NotificationLog, Weekday
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

    # Rotas
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

    @app.route('/api/branches/<branch_id>/services', methods=['GET'])
    def services_by_branch(branch_id):
        """Lista serviços disponíveis em uma filial."""
        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial não encontrada: branch_id={branch_id}")
            return jsonify({'error': 'Filial não encontrada'}), 404

        cache_key = f"cache:services_by_branch:{branch_id}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            queues = Queue.query.filter(Queue.department_id.in_(department_ids)).all()
            service_ids = {q.service_id for q in queues}
            services = InstitutionService.query.filter(InstitutionService.id.in_(service_ids)).all()

            result = [
                {
                    'id': s.id,
                    'name': s.name,
                    'category': {
                        'id': s.category.id,
                        'name': s.category.name
                    } if s.category else None,
                    'description': s.description or "Sem descrição",
                    'queues': [
                        {
                            'id': q.id,
                            'prefix': q.prefix,
                            'active_tickets': q.active_tickets,
                            'estimated_wait_time': f"{int(q.estimated_wait_time)} minutos" if q.estimated_wait_time else "N/A"
                        } for q in queues if q.service_id == s.id
                    ]
                } for s in services
            ]

            response = {'branch_id': branch_id, 'services': result}
            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Serviços retornados para branch_id={branch_id}: {len(result)} serviços")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao obter serviços para branch_id={branch_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter serviços'}), 500

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

    @app.route('/api/branches', methods=['GET'])
    def list_branches():
        """Lista filiais com filtros e paginação."""
        institution_id = request.args.get('institution_id')
        neighborhood = request.args.get('neighborhood')
        user_lat = request.args.get('latitude')
        user_lon = request.args.get('longitude')
        page = request.args.get('page', '1')
        per_page = request.args.get('per_page', '20')

        if institution_id and not Institution.query.get(institution_id):
            logger.warning(f"Instituição não encontrada: institution_id={institution_id}")
            return jsonify({'error': 'Instituição não encontrada'}), 404
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

        cache_key = f"cache:branches:{institution_id}:{neighborhood}:{user_lat}:{user_lon}:{page}:{per_page}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            query = Branch.query
            if institution_id:
                query = query.filter_by(institution_id=institution_id)
            if neighborhood:
                query = query.filter_by(neighborhood=neighborhood)

            branches = query.all()
            result = []
            for branch in branches:
                distance = QueueService.calculate_distance(user_lat, user_lon, branch) if user_lat and user_lon else None
                schedules = BranchSchedule.query.filter_by(branch_id=branch.id).all()
                result.append({
                    'id': branch.id,
                    'name': branch.name,
                    'institution': {
                        'id': branch.institution.id,
                        'name': branch.institution.name
                    },
                    'neighborhood': branch.neighborhood,
                    'latitude': float(branch.latitude) if branch.latitude else None,
                    'longitude': float(branch.longitude) if branch.longitude else None,
                    'distance_km': float(distance) if distance is not None else 'Desconhecida',
                    'schedules': [
                        {
                            'weekday': s.weekday.value,
                            'open_time': s.open_time.strftime('%H:%M') if s.open_time else None,
                            'end_time': s.end_time.strftime('%H:%M') if s.end_time else None,
                            'is_closed': s.is_closed
                        } for s in schedules
                    ]
                })

            total_results = len(result)
            start = (page - 1) * per_page
            end = start + per_page
            paginated_result = result[start:end]

            response = {
                'branches': paginated_result,
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

            logger.info(f"Filiais retornadas: {len(paginated_result)} resultados")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar filiais: {str(e)}")
            return jsonify({'error': 'Erro ao listar filiais'}), 500

    @app.route('/api/institution_types', methods=['GET'])
    def list_institution_types():
        """Lista tipos de instituições."""
        cache_key = "cache:institution_types"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            types = InstitutionType.query.all()
            result = [
                {
                    'id': t.id,
                    'name': t.name,
                    'description': t.description or "Sem descrição"
                } for t in types
            ]

            response = {'institution_types': result}
            if redis_client:
                try:
                    redis_client.setex(cache_key, 86400, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Tipos de instituições retornados: {len(result)} tipos")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar tipos de instituições: {str(e)}")
            return jsonify({'error': 'Erro ao listar tipos de instituições'}), 500

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

    # Rotas
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

            # Atualizar comportamento do usuário
            behavior = UserBehavior(
                user_id=user_id,
                action='generate_ticket',
                queue_id=queue_id,
                service_id=queue.service_id,
                institution_id=branch.institution_id,
                timestamp=datetime.utcnow()
            )
            db.session.add(behavior)

            # Registrar auditoria
            AuditLog.create(
                user_id=user_id,
                action="generate_ticket",
                resource_type="ticket",
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} gerado para queue_id={queue_id}"
            )
            db.session.commit()

            # Enviar notificações
            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=branch.institution_id,
                queue_id=queue_id,
                event_type='ticket_issued',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'timestamp': ticket.issued_at.isoformat()
                }
            )

            # Invalidar cache
            if redis_client:
                try:
                    redis_client.delete(f"cache:queue_stats:{queue_id}")
                    redis_client.delete(f"cache:queue_metrics:{queue_id}")
                    redis_client.delete(f"cache:predict_wait_time:{queue_id}")
                    logger.info(f"Cache invalidado para queue_id={queue_id}")
                except Exception as e:
                    logger.warning(f"Erro ao invalidar cache Redis: {e}")

            response = {
                'ticket_id': ticket.id,
                'queue_id': ticket.queue_id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'status': ticket.status,
                'priority': ticket.priority,
                'issued_at': ticket.issued_at.isoformat(),
                'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None,
                'estimated_wait_time': f"{int(queue.estimated_wait_time)} minutos" if queue.estimated_wait_time else "N/A"
            }

            logger.info(f"Ticket gerado: {ticket.queue.prefix}{ticket.ticket_number} para user_id={user_id}")
            return jsonify(response), 201

        except ValueError as e:
            db.session.rollback()
            logger.error(f"Erro ao gerar ticket para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao gerar ticket para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao gerar ticket'}), 500

    @app.route('/api/tickets/trade', methods=['POST'])
    @require_auth
    def trade_ticket():
        """Permite a troca de tickets entre dois usuários."""
        user_id = request.user_id
        data = request.get_json() or {}
        user_ticket_id = data.get('user_ticket_id')
        target_ticket_id = data.get('target_ticket_id')

        if not user_ticket_id or not target_ticket_id:
            logger.warning(f"Dados insuficientes para troca de tickets: user_id={user_id}")
            return jsonify({'error': 'user_ticket_id e target_ticket_id são obrigatórios'}), 400

        user_ticket = Ticket.query.get(user_ticket_id)
        target_ticket = Ticket.query.get(target_ticket_id)

        if not user_ticket or not target_ticket:
            logger.warning(f"Ticket não encontrado: user_ticket_id={user_ticket_id}, target_ticket_id={target_ticket_id}")
            return jsonify({'error': 'Um ou ambos os tickets não foram encontrados'}), 404

        if user_ticket.user_id != user_id:
            logger.warning(f"Tentativa não autorizada de trocar ticket {user_ticket_id} por user_id={user_id}")
            return jsonify({'error': 'Você não possui permissão para este ticket'}), 403

        if user_ticket.queue_id != target_ticket.queue_id:
            logger.warning(f"Tickets de filas diferentes: user_ticket_id={user_ticket_id}, target_ticket_id={target_ticket_id}")
            return jsonify({'error': 'Os tickets devem ser da mesma fila'}), 400

        if user_ticket.status != 'Pendente' or target_ticket.status != 'Pendente':
            logger.warning(f"Tickets não estão pendentes: user_ticket_id={user_ticket_id}, target_ticket_id={target_ticket_id}")
            return jsonify({'error': 'Ambos os tickets devem estar pendentes'}), 400

        if not target_ticket.trade_available:
            logger.warning(f"Ticket alvo não disponível para troca: target_ticket_id={target_ticket_id}")
            return jsonify({'error': 'O ticket alvo não está disponível para troca'}), 400

        try:
            # Trocar os números dos tickets
            user_ticket_number = user_ticket.ticket_number
            target_ticket_number = target_ticket.ticket_number

            user_ticket.ticket_number = target_ticket_number
            target_ticket.ticket_number = user_ticket_number

            # Atualizar prioridades, se necessário
            user_priority = user_ticket.priority
            target_priority = target_ticket.priority
            user_ticket.priority = target_priority
            target_ticket.priority = user_priority

            db.session.commit()

            # Registrar auditoria para ambos os tickets
            AuditLog.create(
                user_id=user_id,
                action="trade_ticket",
                resource_type="ticket",
                resource_id=user_ticket_id,
                details=f"Ticket {user_ticket.queue.prefix}{user_ticket.ticket_number} trocado com ticket {target_ticket.queue.prefix}{target_ticket.ticket_number}"
            )
            AuditLog.create(
                user_id=target_ticket.user_id,
                action="trade_ticket",
                resource_type="ticket",
                resource_id=target_ticket_id,
                details=f"Ticket {target_ticket.queue.prefix}{target_ticket.ticket_number} trocado com ticket {user_ticket.queue.prefix}{user_ticket.ticket_number}"
            )

            # Enviar notificações
            emit_ticket_update(user_ticket)
            emit_ticket_update(target_ticket)
            QueueService.send_notification(
                fcm_token=User.query.get(user_id).fcm_token,
                message=f"Ticket {user_ticket.queue.prefix}{user_ticket.ticket_number} trocado com sucesso",
                ticket_id=user_ticket.id,
                via_websocket=True,
                user_id=user_id
            )
            QueueService.send_notification(
                fcm_token=User.query.get(target_ticket.user_id).fcm_token,
                message=f"Ticket {target_ticket.queue.prefix}{target_ticket.ticket_number} trocado com sucesso",
                ticket_id=target_ticket.id,
                via_websocket=True,
                user_id=target_ticket.user_id
            )

            # Invalidar cache
            if redis_client:
                try:
                    redis_client.delete(f"cache:queue_stats:{user_ticket.queue_id}")
                    redis_client.delete(f"cache:queue_metrics:{user_ticket.queue_id}")
                    redis_client.delete(f"cache:predict_wait_time:{user_ticket.queue_id}")
                    logger.info(f"Cache invalidado para queue_id={user_ticket.queue_id}")
                except Exception as e:
                    logger.warning(f"Erro ao invalidar cache Redis: {e}")

            logger.info(f"Tickets trocados: user_ticket_id={user_ticket_id}, target_ticket_id={target_ticket_id}")
            return jsonify({
                'message': 'Tickets trocados com sucesso',
                'user_ticket': {
                    'id': user_ticket.id,
                    'ticket_number': f"{user_ticket.queue.prefix}{user_ticket.ticket_number}",
                    'priority': user_ticket.priority
                },
                'target_ticket': {
                    'id': target_ticket.id,
                    'ticket_number': f"{target_ticket.queue.prefix}{target_ticket.ticket_number}",
                    'priority': target_ticket.priority
                }
            }), 200

        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao trocar tickets: user_ticket_id={user_ticket_id}, target_ticket_id={target_ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro ao trocar tickets'}), 500

    @app.route('/api/queues/<queue_id>', methods=['GET'])
    def get_queue_details(queue_id):
        """Retorna detalhes completos de uma fila."""
        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        user_lat = request.args.get('latitude')
        user_lon = request.args.get('longitude')

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

        cache_key = f"cache:queue_details:{queue_id}:{user_lat}:{user_lon}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            branch = queue.department.branch
            distance = QueueService.calculate_distance(user_lat, user_lon, branch) if user_lat and user_lon else None
            schedules = BranchSchedule.query.filter_by(branch_id=branch.id).all()

            response = {
                'queue_id': queue.id,
                'prefix': queue.prefix,
                'service': {
                    'id': queue.service.id,
                    'name': queue.service.name,
                    'category': {
                        'id': queue.service.category.id,
                        'name': queue.service.category.name
                    } if queue.service.category else None
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
                    'id': branch.institution.id,
                    'name': branch.institution.name
                },
                'active_tickets': queue.active_tickets,
                'estimated_wait_time': f"{int(queue.estimated_wait_time)} minutos" if queue.estimated_wait_time else "N/A",
                'avg_service_time': f"{int(queue.last_service_time)} minutos" if queue.last_service_time else "N/A",
                'current_ticket': f"{queue.prefix}{queue.current_ticket}" if queue.current_ticket else "N/A",
                'predicted_demand': float(demand_model.predict(queue_id, hours_ahead=1)),
                'quality_score': float(service_recommendation_predictor.predict(queue)),
                'schedules': [
                    {
                        'weekday': s.weekday.value,
                        'open_time': s.open_time.strftime('%H:%M') if s.open_time else None,
                        'end_time': s.end_time.strftime('%H:%M') if s.end_time else None,
                        'is_closed': s.is_closed
                    } for s in schedules
                ]
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Detalhes da fila retornados para queue_id={queue_id}")
            return jsonify(response), 200

        except Exception as e:
            logger.error(f"Erro ao obter detalhes da fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter detalhes da fila'}), 500

    @app.route('/api/branches/<branch_id>/queues', methods=['GET'])
    def list_queues_by_branch(branch_id):
        """Lista todas as filas de uma filial."""
        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial não encontrada: branch_id={branch_id}")
            return jsonify({'error': 'Filial não encontrada'}), 404

        user_lat = request.args.get('latitude')
        user_lon = request.args.get('longitude')
        page = request.args.get('page', '1')
        per_page = request.args.get('per_page', '20')

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
                return jsonify({'error': 'Longitude deve ser um  Longitude deve ser um número'}), 400
        try:
            page = int(page)
            per_page = int(per_page)
            if page < 1 or per_page < 1:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
            return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

        cache_key = f"cache:queues_by_branch:{branch_id}:{user_lat}:{user_lon}:{page}:{per_page}"
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    logger.info(f"Cache hit para {cache_key}")
                    return jsonify(json.loads(cached)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar cache Redis: {e}")

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            queues = Queue.query.filter(Queue.department_id.in_(department_ids)).paginate(
                page=page, per_page=per_page, error_out=False
            )

            distance = QueueService.calculate_distance(user_lat, user_lon, branch) if user_lat and user_lon else None
            result = [
                {
                    'queue_id': q.id,
                    'prefix': q.prefix,
                    'service': {
                        'id': q.service.id,
                        'name': q.service.name,
                        'category': {
                            'id': q.service.category.id,
                            'name': q.service.category.name
                        } if q.service.category else None
                    },
                    'department': {
                        'id': q.department.id,
                        'name': q.department.name
                    },
                    'active_tickets': q.active_tickets,
                    'estimated_wait_time': f"{int(q.estimated_wait_time)} minutos" if q.estimated_wait_time else "N/A",
                    'avg_service_time': f"{int(q.last_service_time)} minutos" if q.last_service_time else "N/A",
                    'current_ticket': f"{q.prefix}{q.current_ticket}" if q.current_ticket else "N/A",
                    'predicted_demand': float(demand_model.predict(q.id, hours_ahead=1)),
                    'quality_score': float(service_recommendation_predictor.predict(q))
                } for q in queues.items
            ]

            response = {
                'branch_id': branch_id,
                'queues': result,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_results': queues.total,
                    'total_pages': queues.pages
                }
            }

            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Filas retornadas para branch_id={branch_id}: {len(result)} filas")
            return jsonify(response), 200

        except Exception as e:
            logger.error(f"Erro ao listar filas para branch_id={branch_id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar filas'}), 500
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
import logging
from sqlalchemy import and_, or_
from geopy.distance import geodesic
from firebase_admin import auth
from sqlalchemy.exc import SQLAlchemyError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_queue_routes(app):
    def emit_ticket_update(ticket):
        try:
            wait_time = QueueService.calculate_wait_time(
                ticket.queue.id, ticket.ticket_number, ticket.priority
            )
            socketio.emit('ticket_update', {
                'ticket_id': ticket.id,
                'user_id': ticket.user_id,
                'status': ticket.status,
                'counter': f"{ticket.counter:02d}" if ticket.counter else None,
                'position': max(0, ticket.ticket_number - ticket.queue.current_ticket),
                'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
                'number': f"{ticket.queue.prefix}{ticket.ticket_number}"
            }, room=ticket.user_id, namespace='/tickets')
            logger.info(f"Atualização de ticket emitida via WebSocket: ticket_id={ticket.id}, user_id={ticket.user_id}")
            QueueService.send_notification(
                fcm_token=None,
                message=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} atualizado: {ticket.status}",
                ticket_id=ticket.id,
                via_websocket=True,
                user_id=ticket.user_id
            )
        except Exception as e:
            logger.error(f"Erro ao emitir atualização via WebSocket: {e}")

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

        # Validações
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
            # Inferir institution_id se restrict_to_preferred for True
            if not institution_id and restrict_to_preferred and user_id:
                pref = UserPreference.query.filter_by(user_id=user_id, is_client=True).first()
                if pref and pref.institution_id:
                    institution_id = pref.institution_id
                    logger.debug(f"Inferiu institution_id={institution_id} de UserPreference (is_client=True)")
                else:
                    recent_ticket = Ticket.query.filter_by(user_id=user_id).join(Queue).join(Department).join(Branch).order_by(Ticket.issued_at.desc()).first()
                    if recent_ticket:
                        institution_id = recent_ticket.queue.department.branch.institution_id
                        logger.debug(f"Inferiu institution_id={institution_id} do histórico de tickets")

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

            # Aprimorar explicações
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

            logger.info(f"Sugestões geradas para user_id={user_id}: {len(suggestions['services'])} resultados")
            return jsonify(suggestions), 200
        except Exception as e:
            logger.error(f"Erro ao gerar sugestões: {e}")
            return jsonify({'error': "Erro ao gerar sugestões."}), 500

    @app.route('/api/update_location', methods=['POST'])
    def update_location():
        """Atualiza a localização do usuário."""
        data = request.get_json() or {}
        user_id = data.get('user_id')
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
    def create_queue():
        """Cria uma nova fila (mantida sem alterações)."""
        user_id = request.args.get('user_id')
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de criar fila por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        data = request.get_json() or {}
        required = ['service', 'prefix', 'department_id', 'daily_limit', 'num_counters', 'branch_id']
        if not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de fila.")
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
            logger.warning(f"Fila já existe para o serviço {data['service']} no departamento {data['department_id']}.")
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
    def update_queue(id):
        """Atualiza uma fila (mantida sem alterações)."""
        user_id = request.args.get('user_id')
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
    def delete_queue(id):
        """Exclui uma fila (mantida sem alterações)."""
        user_id = request.args.get('user_id')
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
    def get_ticket(service):
        """Emite um ticket para uma fila (mantida sem alterações)."""
        data = request.get_json() or {}
        user_id = data.get('user_id')
        fcm_token = data.get('fcm_token')
        priority = data.get('priority', 0)
        is_physical = data.get('is_physical', False)
        branch_id = data.get('branch_id')
        user_lat = data.get('user_lat')
        user_lon = data.get('user_lon')

        if not user_id:
            logger.warning("user_id não fornecido")
            return jsonify({'error': 'user_id é obrigatório'}), 400
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

            institution_id = ticket.queue.department.branch.institution_id if ticket.queue.department and ticket.queue.department.branch else None
            alternatives = clustering_model.get_alternatives(ticket.queue.id, n=3, institution_id=institution_id)
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
    def download_ticket_pdf(ticket_id):
        """Baixa o PDF de um ticket (mantida sem alterações)."""
        ticket = Ticket.query.get_or_404(ticket_id)
        user_id = request.args.get('user_id')
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
    def ticket_status(ticket_id):
        """Consulta o status de um ticket (mantida sem alterações)."""
        ticket = Ticket.query.get_or_404(ticket_id)
        user_id = request.args.get('user_id')
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
    def call_next_ticket(service):
        """Chama o próximo ticket (mantida sem alterações)."""
        user_id = request.args.get('user_id')
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
    def call_ticket(ticket_id):
        """Chama um ticket específico (mantida sem alterações)."""
        user_id = request.args.get('user_id')
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
    def offer_trade(ticket_id):
        """Oferece um ticket para troca (mantida sem alterações)."""
        user_id = request.args.get('user_id')
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
    def trade_ticket(ticket_to_id):
        """Realiza a troca de tickets (mantida sem alterações)."""
        user_id = request.args.get('user_id')
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
        """Valida a presença de um ticket (mantida sem alterações)."""
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
        """Lista todas as filas (mantida sem alterações)."""
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

            logger.info(f"Lista de filas retornada: {len(result)} instituições encontradas.")
            return jsonify(result), 200
        except Exception as e:
            logger.error(f"Erro ao listar filas: {str(e)}")
            return jsonify({'error': f'Erro ao listar filas: {str(e)}'}), 500

    @app.route('/api/tickets', methods=['GET'])
    def list_user_tickets():
        """Lista os tickets de um usuário (mantida sem alterações)."""
        user_id = request.args.get('user_id')
        if not user_id:
            logger.warning("user_id não fornecido")
            return jsonify({'error': 'user_id é obrigatório'}), 400

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
    def list_trade_available_tickets():
        """Lista tickets disponíveis para troca (mantida sem alterações)."""
        user_id = request.args.get('user_id')
        if not user_id:
            logger.warning("user_id não fornecido")
            return jsonify({'error': 'user_id é obrigatório'}), 400

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
    def cancel_ticket(ticket_id):
        """Cancela um ticket (mantida sem alterações)."""
        user_id = request.args.get('user_id')
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

    @app.route('/api/tickets/admin', methods=['GET'])
    def list_all_tickets():
        """Lista todos os tickets para administradores (mantida sem alterações)."""
        user_id = request.args.get('user_id')
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de listar tickets por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        try:
            if user.user_role == UserRole.DEPARTMENT_ADMIN:
                tickets = Ticket.query.join(Queue).filter(Queue.department_id == user.department_id).all()
            elif user.user_role == UserRole.INSTITUTION_ADMIN:
                tickets = Ticket.query.join(Queue).join(Department).join(Branch).filter(
                    Branch.institution_id == user.institution_id
                ).all()
            else:
                tickets = Ticket.query.all()

            result = []
            for ticket in tickets:
                queue = ticket.queue
                wait_time = QueueService.calculate_wait_time(queue.id, ticket.ticket_number, ticket.priority)
                quality_score = service_recommendation_predictor.predict(queue, ticket.user_id)
                predicted_demand = demand_model.predict(queue.id, hours_ahead=1)

                result.append({
                    'id': ticket.id,
                    'service': queue.service or "Desconhecido",
                    'institution': {
                        'name': queue.department.branch.institution.name if queue.department and queue.department.branch and queue.department.branch.institution else "Desconhecida",
                        'type': {
                            'id': queue.department.branch.institution.type.id if queue.department and queue.department.branch and queue.department.branch.institution and queue.department.branch.institution.type else None,
                            'name': queue.department.branch.institution.type.name if queue.department and queue.department.branch and queue.department.branch.institution and queue.department.branch.institution.type else "Desconhecido"
                        }
                    },
                    'branch': queue.department.branch.name if queue.department and queue.department.branch else "Desconhecida",
                    'department': queue.department.name if queue.department else "Desconhecido",
                    'number': f"{queue.prefix}{ticket.ticket_number}",
                    'status': ticket.status,
                    'counter': f"{ticket.counter:02d}" if ticket.counter else None,
                    'position': max(0, ticket.ticket_number - queue.current_ticket) if ticket.status == 'Pendente' else 0,
                    'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
                    'priority': ticket.priority,
                    'is_physical': ticket.is_physical,
                    'user_id': ticket.user_id,
                    'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None,
                    'qr_code': ticket.qr_code,
                    'trade_available': ticket.trade_available,
                    'quality_score': float(quality_score),
                    'predicted_demand': float(predicted_demand)
                })

            logger.info(f"Lista de tickets retornada para user_id={user.id}: {len(result)} tickets encontrados")
            return jsonify(result), 200
        except Exception as e:
            logger.error(f"Erro ao listar tickets para admin user_id={user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar tickets'}), 500

    @app.route('/api/queue/<queue_id>/schedule', methods=['POST'])
    def create_queue_schedule(queue_id):
        """Cria um horário para uma fila (mantida sem alterações)."""
        user_id = request.args.get('user_id')
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de criar horário para fila {queue_id} por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get_or_404(queue_id)
        if user.user_role == UserRole.DEPARTMENT_ADMIN and queue.department_id != user.department_id:
            logger.warning(f"Usuário {user.id} não tem permissão para criar horário na fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para criar horário na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        data = request.get_json() or {}
        required = ['weekday', 'open_time', 'end_time']
        if not all(f in data for f in required):
            logger.warning(f"Campos obrigatórios faltando para criar horário na fila {queue_id}")
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400

        try:
            weekday = data['weekday'].upper()
            if weekday not in Weekday.__members__:
                logger.warning(f"Dia da semana inválido: {weekday}")
                return jsonify({'error': 'Dia da semana inválido'}), 400
            weekday_enum = Weekday[weekday]

            open_time = datetime.strptime(data['open_time'], '%H:%M').time()
            end_time = datetime.strptime(data['end_time'], '%H:%M').time()
            is_closed = data.get('is_closed', False)

            if QueueSchedule.query.filter_by(queue_id=queue_id, weekday=weekday_enum).first():
                logger.warning(f"Já existe um horário para {weekday} na fila {queue_id}")
                return jsonify({'error': f'Horário já existe para {weekday}'}), 400

            schedule = QueueSchedule(
                queue_id=queue_id,
                weekday=weekday_enum,
                open_time=open_time,
                end_time=end_time,
                is_closed=is_closed
            )
            db.session.add(schedule)
            db.session.commit()
            logger.info(f"Horário criado para fila {queue_id} no dia {weekday}")
            return jsonify({'message': f'Horário criado para {weekday}', 'schedule_id': schedule.id}), 201
        except ValueError as e:
            logger.error(f"Erro ao processar horário para fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Formato de horário inválido'}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao criar horário para fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao criar horário'}), 500

    @app.route('/api/queue/<queue_id>/schedule', methods=['PUT'])
    def update_queue_schedule(queue_id):
        """Atualiza um horário de uma fila (mantida sem alterações)."""
        user_id = request.args.get('user_id')
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de atualizar horário para fila {queue_id} por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get_or_404(queue_id)
        if user.user_role == UserRole.DEPARTMENT_ADMIN and queue.department_id != user.department_id:
            logger.warning(f"Usuário {user.id} não tem permissão para atualizar horário na fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para atualizar horário na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        data = request.get_json() or {}
        if 'weekday' not in data:
            logger.warning(f"Campo 'weekday' faltando para atualizar horário na fila {queue_id}")
            return jsonify({'error': 'Dia da semana é obrigatório'}), 400

        try:
            weekday = data['weekday'].upper()
            if weekday not in Weekday.__members__:
                logger.warning(f"Dia da semana inválido: {weekday}")
                return jsonify({'error': 'Dia da semana inválido'}), 400
            weekday_enum = Weekday[weekday]

            schedule = QueueSchedule.query.filter_by(queue_id=queue_id, weekday=weekday_enum).first()
            if not schedule:
                logger.warning(f"Horário não encontrado para {weekday} na fila {queue_id}")
                return jsonify({'error': f'Horário não encontrado para {weekday}'}), 404

            if 'open_time' in data:
                schedule.open_time = datetime.strptime(data['open_time'], '%H:%M').time()
            if 'end_time' in data:
                schedule.end_time = datetime.strptime(data['end_time'], '%H:%M').time()
            if 'is_closed' in data:
                schedule.is_closed = data['is_closed']

            db.session.commit()
            logger.info(f"Horário atualizado para fila {queue_id} no dia {weekday}")
            return jsonify({'message': f'Horário atualizado para {weekday}'}), 200
        except ValueError as e:
            logger.error(f"Erro ao processar atualização de horário para fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Formato de horário inválido'}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao atualizar horário para fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao atualizar horário'}), 500

    @app.route('/api/queue/<queue_id>/schedule', methods=['GET'])
    def get_queue_schedule(queue_id):
        """Lista os horários de uma fila (mantida sem alterações)."""
        queue = Queue.query.get_or_404(queue_id)
        try:
            schedules = QueueSchedule.query.filter_by(queue_id=queue_id).all()
            result = [{
                'weekday': schedule.weekday.name,
                'open_time': schedule.open_time.strftime('%H:%M') if schedule.open_time else None,
                'end_time': schedule.end_time.strftime('%H:%M') if schedule.end_time else None,
                'is_closed': schedule.is_closed
            } for schedule in schedules]

            logger.info(f"Horários retornados para fila {queue_id}: {len(result)} horários encontrados")
            return jsonify(result), 200
        except Exception as e:
            logger.error(f"Erro ao listar horários para fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar horários'}), 500

    @app.route('/api/queue/<queue_id>/stats', methods=['GET'])
    def queue_stats(queue_id):
        """Retorna estatísticas de uma fila (mantida sem alterações)."""
        user_id = request.args.get('user_id')
        user = User.query.get(user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar estatísticas da fila {queue_id} por user_id={user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get_or_404(queue_id)
        if user.user_role == UserRole.DEPARTMENT_ADMIN and queue.department_id != user.department_id:
            logger.warning(f"Usuário {user.id} não tem permissão para acessar estatísticas da fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para acessar estatísticas na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        try:
            tickets = Ticket.query.filter_by(queue_id=queue_id).all()
            total_tickets = len(tickets)
            pending_tickets = len([t for t in tickets if t.status == 'Pendente'])
            attended_tickets = len([t for t in tickets if t.status == 'Atendido'])
            avg_service_time = sum(t.service_time for t in tickets if t.service_time) / attended_tickets if attended_tickets else 0
            wait_time = QueueService.calculate_wait_time(queue_id, queue.current_ticket + 1, 0)
            quality_score = service_recommendation_predictor.predict(queue)
            predicted_demand = demand_model.predict(queue_id, hours_ahead=1)

            result = {
                'queue_id': queue_id,
                'service': queue.service or "Desconhecido",
                'total_tickets': total_tickets,
                'pending_tickets': pending_tickets,
                'attended_tickets': attended_tickets,
                'avg_service_time': f"{int(avg_service_time)} minutos" if avg_service_time else "N/A",
                'current_wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
                'active_tickets': queue.active_tickets,
                'daily_limit': queue.daily_limit,
                'num_counters': queue.num_counters,
                'quality_score': float(quality_score),
                'predicted_demand': float(predicted_demand)
            }

            cache_key = f"stats:queue:{queue_id}"
            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(result, default=str))
                    logger.info(f"Estatísticas armazenadas no cache para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache para {cache_key}: {e}")

            logger.info(f"Estatísticas retornadas para fila {queue_id}")
            return jsonify(result), 200
        except Exception as e:
            logger.error(f"Erro ao obter estatísticas para fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter estatísticas'}), 500


    @app.route('/api/services/search', methods=['GET'])
    def search_all_services():
        """Busca todos os serviços com filtros e paginação."""
        user_id = request.args.get('user_id')
        institution_id = request.args.get('institution_id')
        branch_id = request.args.get('branch_id')
        query = request.args.get('query', '').strip()
        user_lat = request.args.get('latitude')
        user_lon = request.args.get('longitude')
        neighborhood = request.args.get('neighborhood')
        category_id = request.args.get('category_id')
        tags = request.args.get('tags')
        max_wait_time = request.args.get('max_wait_time')
        min_quality_score = request.args.get('min_quality_score')
        sort_by = request.args.get('sort_by', 'score')  # score, distance, wait_time, quality_score
        page = request.args.get('page', '1')
        per_page = request.args.get('per_page', '20')
        institution_type_id = request.args.get('institution_type_id')
        restrict_to_preferred = request.args.get('restrict_to_preferred', 'false').lower() == 'true'

        # Validações
        if query and not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', query):
            logger.warning(f"Query inválida: {query}")
            return jsonify({'error': 'Query inválida'}), 400
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
        if category_id and not ServiceCategory.query.get(category_id):
            logger.warning(f"category_id não encontrado: {category_id}")
            return jsonify({'error': 'Categoria de serviço não encontrada'}), 404
        if tags:
            tags = tags.split(',')
            if not all(re.match(r'^[A-Za-zÀ-ÿ\s]{1,50}$', tag.strip()) for tag in tags):
                logger.warning(f"Tags inválidas: {tags}")
                return jsonify({'error': 'Tags inválidas'}), 400
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
        if institution_id and not Institution.query.get(institution_id):
            logger.warning(f"institution_id não encontrado: {institution_id}")
            return jsonify({'error': 'Instituição não encontrada'}), 404
        if branch_id and not Branch.query.get(branch_id):
            logger.warning(f"branch_id não encontrado: {branch_id}")
            return jsonify({'error': 'Filial não encontrada'}), 404
        if institution_type_id and not InstitutionType.query.get(institution_type_id):
            logger.warning(f"institution_type_id não encontrado: {institution_type_id}")
            return jsonify({'error': 'Tipo de instituição não encontrado'}), 404
        if sort_by not in ['score', 'distance', 'wait_time', 'quality_score']:
            logger.warning(f"sort_by inválido: {sort_by}")
            return jsonify({'error': 'sort_by deve ser score, distance, wait_time ou quality_score'}), 400
        try:
            page = int(page)
            per_page = int(per_page)
            if page < 1 or per_page < 1:
                raise ValueError
        except (ValueError, TypeError):
            logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
            return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

        try:
            # Inferir institution_id se restrict_to_preferred for True
            if not institution_id and restrict_to_preferred and user_id:
                pref = UserPreference.query.filter_by(user_id=user_id, is_client=True).first()
                if pref and pref.institution_id:
                    institution_id = pref.institution_id
                    logger.debug(f"Inferiu institution_id={institution_id} de UserPreference (is_client=True)")
                else:
                    recent_ticket = Ticket.query.filter_by(user_id=user_id).join(Queue).join(Department).join(Branch).order_by(Ticket.issued_at.desc()).first()
                    if recent_ticket:
                        institution_id = recent_ticket.queue.department.branch.institution_id
                        logger.debug(f"Inferiu institution_id={institution_id} do histórico de tickets")

            # Chave de cache
            cache_key = f"cache:services:search:{query}:{user_id}:{institution_id}:{branch_id}:{user_lat}:{user_lon}:{neighborhood}:{category_id}:{tags}:{max_wait_time}:{min_quality_score}:{sort_by}:{page}:{per_page}:{institution_type_id}"
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        logger.info(f"Cache hit para {cache_key}")
                        return jsonify(json.loads(cached)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar cache Redis: {e}")

            # Busca de serviços
            suggestions = RecommendationService.search_services(
                query=query,
                user_id=user_id,
                user_lat=user_lat,
                user_lon=user_lon,
                neighborhood=neighborhood,
                max_results=per_page,
                max_distance_km=10.0,
                category_id=category_id,
                tags=tags,
                max_wait_time=max_wait_time,
                min_quality_score=min_quality_score,
                institution_type_id=institution_type_id,
                institution_id=institution_id,
                branch_id=branch_id,
                sort_by=sort_by,
                offset=(page - 1) * per_page
            )

            # Aprimorar explicações
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

            # Paginação
            total_results = suggestions.get('total_results', len(suggestions['services']))
            response = {
                'services': suggestions['services'],
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_results': total_results,
                    'total_pages': (total_results + per_page - 1) // per_page
                }
            }

            # Armazenar no cache
            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Busca de serviços retornada para user_id={user_id}: {len(suggestions['services'])} resultados")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao buscar serviços: {str(e)}")
            return jsonify({'error': 'Erro ao buscar serviços'}), 500


        
    @app.route('/api/institutions', methods=['GET'])
    def list_institutions():
        """Lista instituições com filtros e ordenação."""
        try:
            institution_type_id = request.args.get('institution_type_id') or request.args.get('type_id')  # Suporte a type_id
            user_lat = request.args.get('latitude')
            user_lon = request.args.get('longitude')
            sort_by = request.args.get('sort_by', 'quality_score')
            page = request.args.get('page', '1')
            per_page = request.args.get('per_page', '20')

            # Validações
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
            if institution_type_id and not InstitutionType.query.get(institution_type_id):
                logger.warning(f"institution_type_id não encontrado: {institution_type_id}")
                return jsonify({'error': 'Tipo de instituição não encontrado'}), 404
            if sort_by not in ['quality_score', 'distance', 'name']:
                logger.warning(f"sort_by inválido: {sort_by}")
                return jsonify({'error': 'sort_by deve ser quality_score, distance ou name'}), 400
            try:
                page = int(page)
                per_page = int(per_page)
                if page < 1 or per_page < 1:
                    raise ValueError
            except (ValueError, TypeError):
                logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

            # Chave de cache
            cache_key = f"cache:institutions:{institution_type_id}:{user_lat}:{user_lon}:{sort_by}:{page}:{per_page}"
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        logger.info(f"Cache hit para {cache_key}")
                        return jsonify(json.loads(cached)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar cache Redis: {e}")

            # Consulta
            query = Institution.query
            if institution_type_id:
                query = query.filter_by(institution_type_id=institution_type_id)

            institutions = query.all()
            result = []

            for inst in institutions:
                branches = Branch.query.filter_by(institution_id=inst.id).all()
                min_distance = None
                if user_lat and user_lon and branches:
                    min_distance = min(
                        geodesic((user_lat, user_lon), (b.latitude, b.longitude)).km
                        for b in branches if b.latitude and b.longitude
                    )

                department_ids = [d.id for d in Department.query.filter(Department.branch_id.in_([b.id for b in branches])).all()]
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
                    'branches_count': len(branches),
                    'distance_km': float(min_distance) if min_distance is not None else 'Desconhecida',
                    'quality_score': float(avg_quality_score)
                })

            if sort_by == 'distance' and user_lat and user_lon:
                result = sorted(result, key=lambda x: float(x['distance_km']) if x['distance_km'] != 'Desconhecida' else float('inf'))
            elif sort_by == 'name':
                result = sorted(result, key=lambda x: x['name'].lower())
            else:
                result = sorted(result, key=lambda x: x['quality_score'], reverse=True)

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
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Lista de instituições retornada: {len(paginated_result)} resultados")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar instituições: {str(e)}")
            return jsonify({'error': 'Erro ao listar instituições'}), 500

    @app.route('/api/institution_types', methods=['GET'])
    def list_institution_types():
        """Lista tipos de instituições com cache."""
        try:
            cache_key = "cache:institution_types"
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        logger.info(f"Cache hit para {cache_key}")
                        return jsonify(json.loads(cached)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar cache Redis: {e}")

            types = InstitutionType.query.all()
            result = [{
                'id': t.id,
                'name': t.name or "Desconhecido",
                'icon': t.icon_url if hasattr(t, 'icon_url') else 'https://www.bancobai.ao/media/1635/icones-104.png'
            } for t in types]

            response = {'types': result}  # Alterado para retornar um mapa

            if redis_client:
                try:
                    redis_client.setex(cache_key, 3600, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Lista de tipos de instituições retornada: {len(result)} tipos")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar tipos de instituições: {str(e)}")
            return jsonify({'error': 'Erro ao listar tipos de instituições'}), 500
        
    @app.route('/api/branches', methods=['GET'])
    def list_branches():
        """Lista filiais com filtros e ordenação."""
        try:
            institution_id = request.args.get('institution_id')
            user_lat = request.args.get('latitude')
            user_lon = request.args.get('longitude')
            neighborhood = request.args.get('neighborhood')
            sort_by = request.args.get('sort_by', 'distance')  # distance, quality_score, name
            page = request.args.get('page', '1')
            per_page = request.args.get('per_page', '20')

            # Validações
            if institution_id and not Institution.query.get(institution_id):
                logger.warning(f"institution_id não encontrado: {institution_id}")
                return jsonify({'error': 'Instituição não encontrada'}), 404
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
            if sort_by not in ['distance', 'quality_score', 'name']:
                logger.warning(f"sort_by inválido: {sort_by}")
                return jsonify({'error': 'sort_by deve ser distance, quality_score ou name'}), 400
            try:
                page = int(page)
                per_page = int(per_page)
                if page < 1 or per_page < 1:
                    raise ValueError
            except (ValueError, TypeError):
                logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

            # Chave de cache
            cache_key = f"cache:branches:{institution_id}:{user_lat}:{user_lon}:{neighborhood}:{sort_by}:{page}:{per_page}"
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        logger.info(f"Cache hit para {cache_key}")
                        return jsonify(json.loads(cached)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar cache Redis: {e}")

            # Consulta
            query = Branch.query
            if institution_id:
                query = query.filter_by(institution_id=institution_id)
            if neighborhood:
                query = query.filter(Branch.neighborhood.ilike(f'%{neighborhood}%'))

            branches = query.all()
            result = []

            for branch in branches:
                distance = None
                if user_lat and user_lon and branch.latitude and branch.longitude:
                    distance = geodesic((user_lat, user_lon), (branch.latitude, branch.longitude)).km

                # Média de wait_time e quality_score
                department_ids = [d.id for d in Department.query.filter_by(branch_id=branch.id).all()]
                queues = Queue.query.filter(Queue.department_id.in_(department_ids)).all()
                wait_times = [
                    QueueService.calculate_wait_time(q.id, q.current_ticket + 1, 0)
                    for q in queues
                ]
                wait_times = [wt for wt in wait_times if isinstance(wt, (int, float))]
                avg_wait_time = sum(wait_times) / len(wait_times) if wait_times else None
                quality_scores = [
                    service_recommendation_predictor.predict(q) for q in queues
                ]
                avg_quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

                result.append({
                    'id': branch.id,
                    'name': branch.name or "Desconhecida",
                    'location': branch.location or "Desconhecida",
                    'neighborhood': branch.neighborhood or "Desconhecido",
                    'latitude': float(branch.latitude) if branch.latitude else None,
                    'longitude': float(branch.longitude) if branch.longitude else None,
                    'institution_id': branch.institution_id,
                    'distance_km': float(distance) if distance is not None else 'Desconhecida',
                    'avg_wait_time': f"{int(avg_wait_time)} minutos" if avg_wait_time else "N/A",
                    'quality_score': float(avg_quality_score)
                })

            # Ordenação
            if sort_by == 'distance' and user_lat and user_lon:
                result = sorted(result, key=lambda x: float(x['distance_km']) if x['distance_km'] != 'Desconhecida' else float('inf'))
            elif sort_by == 'name':
                result = sorted(result, key=lambda x: x['name'].lower())
            else:  # quality_score
                result = sorted(result, key=lambda x: x['quality_score'], reverse=True)

            # Paginação
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

            # Armazenar no cache
            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Lista de filiais retornada: {len(paginated_result)} resultados")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar filiais: {str(e)}")
            return jsonify({'error': 'Erro ao listar filiais'}), 500

    @app.route('/api/recommendation/search_structured', methods=['GET'])
    def search_structured():
        """Busca estruturada para a página principal, com resultados para o mapa."""
        try:
            query = request.args.get('query', '').strip()
            user_id = request.args.get('user_id')
            user_lat = request.args.get('latitude')
            user_lon = request.args.get('longitude')
            neighborhood = request.args.get('neighborhood')
            institution_type_id = request.args.get('institution_type_id')
            institution_id = request.args.get('institution_id')
            branch_id = request.args.get('branch_id')
            service_category_id = request.args.get('service_category_id')
            max_wait_time = request.args.get('max_wait_time')
            min_quality_score = request.args.get('min_quality_score')
            sort_by = request.args.get('sort_by', 'score')  # score, distance, wait_time, quality_score
            page = request.args.get('page', '1')
            per_page = request.args.get('per_page', '20')

            # Validações
            if query and not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', query):
                logger.warning(f"Query inválida: {query}")
                return jsonify({'error': 'Query inválida'}), 400
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
            if institution_type_id and not InstitutionType.query.get(institution_type_id):
                logger.warning(f"institution_type_id não encontrado: {institution_type_id}")
                return jsonify({'error': 'Tipo de instituição não encontrado'}), 404
            if institution_id and not Institution.query.get(institution_id):
                logger.warning(f"institution_id não encontrado: {institution_id}")
                return jsonify({'error': 'Instituição não encontrada'}), 404
            if branch_id and not Branch.query.get(branch_id):
                logger.warning(f"branch_id não encontrado: {branch_id}")
                return jsonify({'error': 'Filial não encontrada'}), 404
            if service_category_id and not ServiceCategory.query.get(service_category_id):
                logger.warning(f"service_category_id não encontrado: {service_category_id}")
                return jsonify({'error': 'Categoria de serviço não encontrada'}), 404
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
            if sort_by not in ['score', 'distance', 'wait_time', 'quality_score']:
                logger.warning(f"sort_by inválido: {sort_by}")
                return jsonify({'error': 'sort_by deve ser score, distance, wait_time ou quality_score'}), 400
            try:
                page = int(page)
                per_page = int(per_page)
                if page < 1 or per_page < 1:
                    raise ValueError
            except (ValueError, TypeError):
                logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

            # Chave de cache
            cache_key = f"cache:search_structured:{query}:{user_id}:{user_lat}:{user_lon}:{neighborhood}:{institution_type_id}:{institution_id}:{branch_id}:{service_category_id}:{max_wait_time}:{min_quality_score}:{sort_by}:{page}:{per_page}"
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        logger.info(f"Cache hit para {cache_key}")
                        return jsonify(json.loads(cached)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar cache Redis: {e}")

            # Busca de serviços
            suggestions = RecommendationService.search_services(
                query=query,
                user_id=user_id,
                user_lat=user_lat,
                user_lon=user_lon,
                neighborhood=neighborhood,
                max_results=per_page,
                max_distance_km=10.0,
                category_id=service_category_id,
                tags=None,
                max_wait_time=max_wait_time,
                min_quality_score=min_quality_score,
                institution_type_id=institution_type_id,
                institution_id=institution_id,
                branch_id=branch_id,
                sort_by=sort_by,
                offset=(page - 1) * per_page
            )

            # Aprimorar explicações
            for service in suggestions['services']:
                explanation = []
                if service['institution']['id'] == institution_id:
                    explanation.append(f"Você prefere {service['institution']['name']}")
                if service['queue']['distance'] != 'Desconhecida':
                    explanation.append(f"Filial a {service['queue']['distance']:.2f} km")
                if service['queue']['wait_time'] != "N/A":
                    wait_time = int(float(service['queue']['wait_time'].split()[0]))
                    explanation.append(f"Espera de {wait_time} min")
                if service['queue']['quality_score'] > 0.8:
                    explanation.append("Alta qualidade")
                service['queue']['explanation'] = "; ".join(explanation) or "Recomendado com base na sua busca"

            # Paginação
            total_results = suggestions.get('total_results', len(suggestions['services']))
            response = {
                'services': suggestions['services'],
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_results': total_results,
                    'total_pages': (total_results + per_page - 1) // per_page
                }
            }

            # Armazenar no cache
            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Busca estruturada retornada para user_id={user_id}: {len(suggestions['services'])} resultados")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao realizar busca estruturada: {str(e)}")
            return jsonify({'error': 'Erro ao realizar busca estruturada'}), 500

    @app.route('/api/recommendation/autocomplete', methods=['GET'])
    def autocomplete():
        """Sugestões de autocompletar para a barra de pesquisa."""
        try:
            query = request.args.get('query', '').strip()
            user_id = request.args.get('user_id')
            user_lat = request.args.get('latitude')
            user_lon = request.args.get('longitude')
            limit = request.args.get('limit', '10')

            # Validações
            if query and not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', query):
                logger.warning(f"Query inválida: {query}")
                return jsonify({'error': 'Query inválida'}), 400
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
                logger.warning(f"limit inválido: {limit}")
                return jsonify({'error': 'limit deve ser um número positivo'}), 400

            # Chave de cache
            cache_key = f"cache:autocomplete:{query}:{user_id}:{user_lat}:{user_lon}:{limit}"
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        logger.info(f"Cache hit para {cache_key}")
                        return jsonify(json.loads(cached)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar cache Redis: {e}")

            result = {
                'institution_types': [],
                'institutions': [],
                'services': [],
                'neighborhoods': []
            }

            if query:
                # Tipos de instituições
                institution_types = InstitutionType.query.filter(
                    InstitutionType.name.ilike(f'%{query}%')
                ).limit(limit).all()
                result['institution_types'] = [{
                    'id': t.id,
                    'name': t.name,
                    'icon': t.icon_url if hasattr(t, 'icon_url') else 'https://www.bancobai.ao/media/1635/icones-104.png'
                } for t in institution_types]

                # Instituições
                institutions = Institution.query.filter(
                    Institution.name.ilike(f'%{query}%')
                ).limit(limit).all()
                for inst in institutions:
                    distance = None
                    if user_lat and user_lon:
                        branches = Branch.query.filter_by(institution_id=inst.id).all()
                        distances = [
                            geodesic((user_lat, user_lon), (b.latitude, b.longitude)).km
                            for b in branches if b.latitude and b.longitude
                        ]
                        distance = min(distances) if distances else None
                    result['institutions'].append({
                        'id': inst.id,
                        'name': inst.name,
                        'type_id': inst.institution_type_id,
                        'distance_km': float(distance) if distance is not None else 'Desconhecida'
                    })

                # Serviços
                services = RecommendationService.search_services(
                    query=query,
                    user_id=user_id,
                    user_lat=user_lat,
                    user_lon=user_lon,
                    max_results=limit,
                    max_distance_km=10.0
                )['services']
                result['services'] = [{
                    'queue_id': s['queue']['id'],
                    'service': s['queue']['service'],
                    'institution_id': s['institution']['id'],
                    'institution_name': s['institution']['name'],
                    'branch_id': s['queue']['branch_id'],
                    'branch_name': s['queue']['branch'],
                    'distance_km': s['queue']['distance'],
                    'wait_time': s['queue']['wait_time']
                } for s in services]

                # Bairros
                neighborhoods = Branch.query.filter(
                    Branch.neighborhood.ilike(f'%{query}%')
                ).distinct(Branch.neighborhood).limit(limit).all()
                result['neighborhoods'] = [n.neighborhood for n in neighborhoods if n.neighborhood]

            # Armazenar no cache
            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(result, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Autocompletar retornado para query={query}: {len(result['services'])} serviços")
            return jsonify(result), 200
        except Exception as e:
            logger.error(f"Erro ao gerar autocompletar: {str(e)}")
            return jsonify({'error': 'Erro ao gerar autocompletar'}), 500

    @app.route('/api/recommendation/featured', methods=['GET'])
    def featured_recommendations():
        """Recomendações personalizadas para a seção 'Recomendado para Você'."""
        try:
            user_id = request.args.get('user_id')
            user_lat = request.args.get('latitude')
            user_lon = request.args.get('longitude')
            limit = request.args.get('limit', '5')

            # Validações
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
                logger.warning(f"limit inválido: {limit}")
                return jsonify({'error': 'limit deve ser um número positivo'}), 400

            # Chave de cache
            cache_key = f"cache:featured:{user_id}:{user_lat}:{user_lon}:{limit}"
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        logger.info(f"Cache hit para {cache_key}")
                        return jsonify(json.loads(cached)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar cache Redis: {e}")

            # Busca recomendações personalizadas
            suggestions = RecommendationService.search_services(
                query='',
                user_id=user_id,
                user_lat=user_lat,
                user_lon=user_lon,
                max_results=limit,
                max_distance_km=5.0,
                sort_by='score'
            )

            # Aprimorar explicações
            for service in suggestions['services']:
                explanation = []
                if user_id and UserPreference.query.filter_by(user_id=user_id, institution_id=service['institution']['id']).first():
                    explanation.append(f"Você prefere {service['institution']['name']}")
                if service['queue']['distance'] != 'Desconhecida':
                    explanation.append(f"Filial a {service['queue']['distance']:.2f} km")
                if service['queue']['wait_time'] != "N/A":
                    wait_time = int(float(service['queue']['wait_time'].split()[0]))
                    explanation.append(f"Espera de {wait_time} min")
                if service['queue']['quality_score'] > 0.8:
                    explanation.append("Alta qualidade")
                service['queue']['explanation'] = "; ".join(explanation) or "Recomendado para você"

            # Armazenar no cache
            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(suggestions['services'], default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Recomendações destacadas retornadas para user_id={user_id}: {len(suggestions['services'])} resultados")
            return jsonify(suggestions['services']), 200
        except Exception as e:
            logger.error(f"Erro ao gerar recomendações destacadas: {str(e)}")
            return jsonify({'error': 'Erro ao gerar recomendações destacadas'}), 500

    @app.route('/api/services/by_branch', methods=['GET'])
    def services_by_branch():
        """Busca serviços oferecidos por uma filial específica."""
        try:
            branch_id = request.args.get('branch_id')
            user_id = request.args.get('user_id')
            user_lat = request.args.get('latitude')
            user_lon = request.args.get('longitude')
            query = request.args.get('query', '').strip()
            service_category_id = request.args.get('service_category_id')
            max_wait_time = request.args.get('max_wait_time')
            min_quality_score = request.args.get('min_quality_score')
            sort_by = request.args.get('sort_by', 'quality_score')  # quality_score, wait_time, name
            page = request.args.get('page', '1')
            per_page = request.args.get('per_page', '20')

            # Validações
            if not branch_id:
                logger.warning("branch_id não fornecido")
                return jsonify({'error': 'branch_id é obrigatório'}), 400
            if not Branch.query.get(branch_id):
                logger.warning(f"branch_id não encontrado: {branch_id}")
                return jsonify({'error': 'Filial não encontrada'}), 404
            if query and not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', query):
                logger.warning(f"Query inválida: {query}")
                return jsonify({'error': 'Query inválida'}), 400
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
            if service_category_id and not ServiceCategory.query.get(service_category_id):
                logger.warning(f"service_category_id não encontrado: {service_category_id}")
                return jsonify({'error': 'Categoria de serviço não encontrada'}), 404
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
            if sort_by not in ['quality_score', 'wait_time', 'name']:
                logger.warning(f"sort_by inválido: {sort_by}")
                return jsonify({'error': 'sort_by deve ser quality_score, wait_time ou name'}), 400
            try:
                page = int(page)
                per_page = int(per_page)
                if page < 1 or per_page < 1:
                    raise ValueError
            except (ValueError, TypeError):
                logger.warning(f"page ou per_page inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'page e per_page devem ser números positivos'}), 400

            # Chave de cache
            cache_key = f"cache:services_by_branch:{branch_id}:{user_id}:{user_lat}:{user_lon}:{query}:{service_category_id}:{max_wait_time}:{min_quality_score}:{sort_by}:{page}:{per_page}"
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        logger.info(f"Cache hit para {cache_key}")
                        return jsonify(json.loads(cached)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar cache Redis: {e}")

            # Busca de serviços
            suggestions = RecommendationService.search_services(
                query=query,
                user_id=user_id,
                user_lat=user_lat,
                user_lon=user_lon,
                max_results=per_page,
                max_distance_km=0.0,  # Restrito à filial
                category_id=service_category_id,
                tags=None,
                max_wait_time=max_wait_time,
                min_quality_score=min_quality_score,
                branch_id=branch_id,
                sort_by=sort_by,
                offset=(page - 1) * per_page
            )

            # Adicionar recommendation_level
            for service in suggestions['services']:
                score = service['queue']['quality_score']
                wait_time = service['queue']['wait_time']
                wait_time_min = int(float(wait_time.split()[0])) if wait_time != "N/A" else float('inf')
                if score > 0.8 and wait_time_min < 15:
                    service['recommendation_level'] = 'high'
                elif score > 0.6 and wait_time_min < 30:
                    service['recommendation_level'] = 'medium'
                else:
                    service['recommendation_level'] = 'low'

                # Explicação
                explanation = []
                if wait_time != "N/A":
                    explanation.append(f"Espera de {wait_time_min} min")
                if score > 0.8:
                    explanation.append("Alta qualidade")
                service['queue']['explanation'] = "; ".join(explanation) or "Disponível nesta filial"

            # Paginação
            total_results = suggestions.get('total_results', len(suggestions['services']))
            response = {
                'services': suggestions['services'],
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_results': total_results,
                    'total_pages': (total_results + per_page - 1) // per_page
                }
            }

            # Armazenar no cache
            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(response, default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Serviços por filial retornados para branch_id={branch_id}: {len(suggestions['services'])} resultados")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao buscar serviços por filial: {str(e)}")
            return jsonify({'error': 'Erro ao buscar serviços por filial'}), 500

    @app.route('/api/services/similar', methods=['GET'])
    def similar_services():
        """Retorna serviços similares a um serviço específico, restritos à mesma instituição."""
        try:
            queue_id = request.args.get('queue_id')
            user_id = request.args.get('user_id')
            user_lat = request.args.get('latitude')
            user_lon = request.args.get('longitude')
            limit = request.args.get('limit', '5')

            # Validações
            if not queue_id:
                logger.warning("queue_id não fornecido")
                return jsonify({'error': 'queue_id é obrigatório'}), 400
            queue = Queue.query.get(queue_id)
            if not queue:
                logger.warning(f"queue_id não encontrado: {queue_id}")
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
                limit = int(limit)
                if limit < 1:
                    raise ValueError
            except (ValueError, TypeError):
                logger.warning(f"limit inválido: {limit}")
                return jsonify({'error': 'limit deve ser um número positivo'}), 400

            # Chave de cache
            cache_key = f"cache:similar_services:{queue_id}:{user_id}:{user_lat}:{user_lon}:{limit}"
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        logger.info(f"Cache hit para {cache_key}")
                        return jsonify(json.loads(cached)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar cache Redis: {e}")

            # Obter instituição
            institution_id = queue.department.branch.institution_id if queue.department and queue.department.branch else None
            if not institution_id:
                logger.warning(f"Instituição não encontrada para queue_id={queue_id}")
                return jsonify({'error': 'Instituição não encontrada'}), 404

            # Buscar serviços similares
            similar_queue_ids = clustering_model.get_alternatives(queue_id, n=limit, institution_id=institution_id)
            suggestions = RecommendationService.search_services(
                query='',
                user_id=user_id,
                user_lat=user_lat,
                user_lon=user_lon,
                max_results=limit,
                max_distance_km=10.0,
                queue_ids=similar_queue_ids,
                institution_id=institution_id
            )

            # Aprimorar explicações
            for service in suggestions['services']:
                explanation = []
                if service['queue']['distance'] != 'Desconhecida':
                    explanation.append(f"Filial a {service['queue']['distance']:.2f} km")
                if service['queue']['wait_time'] != "N/A":
                    wait_time = int(float(service['queue']['wait_time'].split()[0]))
                    explanation.append(f"Espera de {wait_time} min")
                if service['queue']['quality_score'] > 0.8:
                    explanation.append("Alta qualidade")
                service['queue']['explanation'] = "; ".join(explanation) or "Serviço similar"

            # Armazenar no cache
            if redis_client:
                try:
                    redis_client.setex(cache_key, 300, json.dumps(suggestions['services'], default=str))
                    logger.info(f"Cache armazenado para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache Redis: {e}")

            logger.info(f"Serviços similares retornados para queue_id={queue_id}: {len(suggestions['services'])} resultados")
            return jsonify(suggestions['services']), 200
        except Exception as e:
            logger.error(f"Erro ao buscar serviços similares: {str(e)}")
            return jsonify({'error': 'Erro ao buscar serviços similares'}), 500

# Fechar a função init_queue_routes
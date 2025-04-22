from flask import jsonify, request, send_file
from flask_socketio import join_room, leave_room, ConnectionRefusedError
from . import db, socketio, redis_client
from .models import AuditLog, Institution, Branch, Queue, Ticket, User, Department, UserRole, QueueSchedule, Weekday, ServiceCategory, ServiceTag, UserPreference, InstitutionType
from .auth import require_auth
from .services import QueueService
from .ml_models import wait_time_predictor, service_recommendation_predictor, collaborative_model, demand_model, clustering_model
import uuid
from datetime import datetime, timedelta
import io
import json
import re
import logging
from sqlalchemy import and_, or_
from geopy.distance import geodesic
from firebase_admin import auth

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
    @require_auth
    def suggest_service():
        service = request.args.get('service', '').strip()
        user_lat = request.args.get('lat')
        user_lon = request.args.get('lon')
        neighborhood = request.args.get('neighborhood')
        max_wait_time = request.args.get('max_wait_time')
        min_quality_score = request.args.get('min_quality_score')
        category_id = request.args.get('category_id')
        tags = request.args.get('tags')
        institution_type_id = request.args.get('institution_type_id')

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

        try:
            user_id = request.user_id
            suggestions = QueueService.search_services(
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
                sort_by='score'
            )
            logger.info(f"Sugestões geradas para user_id={user_id}: {len(suggestions['services'])} resultados")
            return jsonify(suggestions), 200
        except Exception as e:
            logger.error(f"Erro ao gerar sugestões: {e}")
            return jsonify({'error': "Erro ao gerar sugestões."}), 500

    @app.route('/api/update_location', methods=['POST'])
    @require_auth
    def update_location():
        user_id = request.user_id
        data = request.get_json() or {}
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        email = data.get('email')
        institution_type_id = data.get('institution_type_id')

        if latitude is None or longitude is None:
            logger.error(f"Latitude ou longitude não fornecidos por user_id={user_id}")
            return jsonify({'error': 'Latitude e longitude são obrigatórios'}), 400

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
                logger.error(f"Email não encontrado para user_id={user_id}")
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
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de criar fila por user_id={request.user_id}")
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
    @require_auth
    def update_queue(id):
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de atualizar fila por user_id={request.user_id}")
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
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de excluir fila por user_id={request.user_id}")
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
        data = request.get_json() or {}
        user_id = data.get('user_id', request.user_id)
        fcm_token = data.get('fcm_token')
        priority = data.get('priority', 0)
        is_physical = data.get('is_physical', False)
        branch_id = data.get('branch_id')
        user_lat = data.get('user_lat')
        user_lon = data.get('user_lon')

        if not isinstance(service, str) or not service.strip():
            logger.warning(f"Serviço inválido: {service}")
            return jsonify({'error': 'Serviço deve ser uma string válida'}), 400
        if not isinstance(user_id, str):
            logger.warning(f"user_id inválido: {user_id}")
            return jsonify({'error': 'user_id deve ser uma string'}), 400
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

            alternatives = clustering_model.get_alternatives(ticket.queue.id, n=3)
            alternative_queues = Queue.query.filter(Queue.id.in_(alternatives)).all()
            alternatives_data = [
                {
                    'queue_id': alt_queue.id,
                    'service': alt_queue.service or "Desconhecido",
                    'wait_time': QueueService.calculate_wait_time(alt_queue.id, alt_queue.active_tickets + 1, 0, user_lat, user_lon),
                    'quality_score': service_recommendation_predictor.predict(alt_queue, user_id, user_lat, user_lon)
                } for alt_queue in alternative_queues
            ]

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
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != request.user_id and ticket.user_id != 'PRESENCIAL':
            logger.warning(f"Tentativa não autorizada de baixar PDF do ticket {ticket_id} por user_id={request.user_id}")
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
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != request.user_id and ticket.user_id != 'PRESENCIAL':
            logger.warning(f"Tentativa não autorizada de visualizar status do ticket {ticket_id} por user_id={request.user_id}")
            return jsonify({'error': 'Não autorizado'}), 403

        queue = ticket.queue
        wait_time = QueueService.calculate_wait_time(queue.id, ticket.ticket_number, ticket.priority)
        quality_score = service_recommendation_predictor.predict(queue, request.user_id)
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
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de chamar ticket por user_id={request.user_id}")
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
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de chamar ticket {ticket_id} por user_id={request.user_id}")
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
        try:
            ticket = QueueService.offer_trade(ticket_id, request.user_id)
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
        data = request.get_json() or {}
        ticket_from_id = data.get('ticket_from_id')
        if not ticket_from_id:
            logger.warning("ticket_from_id não fornecido para troca")
            return jsonify({'error': 'ticket_from_id é obrigatório'}), 400

        try:
            result = QueueService.trade_tickets(ticket_from_id, ticket_to_id, request.user_id)
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
    @require_auth
    def list_user_tickets():
        try:
            tickets = Ticket.query.filter_by(user_id=request.user_id).all()
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
                'quality_score': float(service_recommendation_predictor.predict(t.queue, request.user_id)),
                'predicted_demand': float(demand_model.predict(t.queue.id, hours_ahead=1))
            } for t in tickets]), 200
        except Exception as e:
            logger.error(f"Erro ao listar tickets do usuário {request.user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar tickets'}), 500

    @app.route('/api/tickets/trade_available', methods=['GET'])
    @require_auth
    def list_trade_available_tickets():
        try:
            user_id = request.user_id
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
            logger.error(f"Erro ao listar tickets disponíveis para troca para user_id={request.user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar tickets para troca'}), 500

    @app.route('/api/ticket/<ticket_id>/cancel', methods=['POST'])
    @require_auth
    def cancel_ticket(ticket_id):
        try:
            ticket = QueueService.cancel_ticket(ticket_id, request.user_id)
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
    @require_auth
    def list_all_tickets():
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de listar tickets por user_id={request.user_id}")
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
            logger.error(f"Erro ao listar tickets para admin user_id={request.user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar tickets'}), 500

    @app.route('/api/queue/<queue_id>/schedule', methods=['POST'])
    @require_auth
    def create_queue_schedule(queue_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de criar horário para fila {queue_id} por user_id={request.user_id}")
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
    @require_auth
    def update_queue_schedule(queue_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de atualizar horário para fila {queue_id} por user_id={request.user_id}")
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
    @require_auth
    def get_queue_schedule(queue_id):
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
    @require_auth
    def queue_stats(queue_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar estatísticas da fila {queue_id} por user_id={request.user_id}")
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
    @require_auth
    def search_all_services():
        try:
            user_id = request.user_id if hasattr(request, 'user_id') else None
            email = request.args.get('email')
            if email and not user_id:
                user = User.query.filter_by(email=email).first()
                user_id = user.id if user else None

            query = request.args.get('query', '').strip()
            user_lat = request.args.get('latitude')
            user_lon = request.args.get('longitude')
            neighborhood = request.args.get('neighborhood')
            category_id = request.args.get('category_id')
            tags = request.args.get('tags')
            max_wait_time = request.args.get('max_wait_time')
            min_quality_score = request.args.get('min_quality_score')
            sort_by = request.args.get('sort_by', 'score')
            page = request.args.get('page', '1')
            per_page = request.args.get('per_page', '20')
            institution_type_id = request.args.get('institution_type_id')

            if query and not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', query):
                logger.warning(f"Query inválida: {query}")
                return jsonify({'error': 'Query inválida'}), 400
            if neighborhood and not re.match(r'^[A-Za-zÀ-ÿ\s,]{1,100}$', neighborhood):
                logger.warning(f"Bairro inválido: {neighborhood}")
                return jsonify({'error': 'Bairro inválido'}), 400
            if user_lat and user_lon:
                try:
                    user_lat = float(user_lat)
                    user_lon = float(user_lon)
                except (ValueError, TypeError):
                    logger.warning(f"Latitude ou longitude inválidos: lat={user_lat}, lon={user_lon}")
                    return jsonify({'error': 'Latitude e longitude devem ser números'}), 400
            if category_id and not isinstance(category_id, str):
                logger.warning(f"category_id inválido: {category_id}")
                return jsonify({'error': 'category_id deve ser uma string'}), 400
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
            if sort_by not in ['score', 'wait_time', 'distance', 'quality_score']:
                logger.warning(f"sort_by inválido: {sort_by}")
                return jsonify({'error': 'sort_by deve ser score, wait_time, distance ou quality_score'}), 400
            try:
                page = int(page)
                per_page = int(per_page)
                if page < 1 or per_page < 1:
                    raise ValueError
            except (ValueError, TypeError):
                logger.warning(f"Página ou per_page inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'Página e itens por página devem ser números inteiros positivos'}), 400
            if per_page > 100:
                logger.warning(f"Per_page excede o máximo: {per_page}")
                return jsonify({'error': 'Máximo de itens por página é 100'}), 400
            if institution_type_id and not isinstance(institution_type_id, str):
                logger.warning(f"institution_type_id inválido: {institution_type_id}")
                return jsonify({'error': 'institution_type_id deve ser uma string'}), 400

            cache_key = f"services:{query}:{neighborhood}:{category_id}:{tags}:{max_wait_time}:{min_quality_score}:{sort_by}:{page}:{per_page}:{institution_type_id}"
            cached_data = None
            if redis_client:
                try:
                    cached_data = redis_client.get(cache_key)
                    if cached_data:
                        logger.info(f"Retornando resultado do cache para {cache_key}")
                        return jsonify(json.loads(cached_data)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar Redis para {cache_key}: {e}")

            queues_query = Queue.query.join(Department).join(Branch).join(Institution).join(InstitutionType).outerjoin(ServiceTag).outerjoin(QueueSchedule).outerjoin(ServiceCategory)

            if query:
                queues_query = queues_query.filter(
                    or_(
                        Queue.service.ilike(f'%{query}%'),
                        ServiceCategory.name.ilike(f'%{query}%'),
                        Branch.name.ilike(f'%{query}%'),
                        Institution.name.ilike(f'%{query}%'),
                        InstitutionType.name.ilike(f'%{query}%')
                    )
                )
            if category_id:
                queues_query = queues_query.filter(ServiceCategory.id == category_id)
            if tags:
                queues_query = queues_query.filter(ServiceTag.tag.in_(tags))
            if neighborhood:
                queues_query = queues_query.filter(Branch.neighborhood.ilike(f'%{neighborhood}%'))
            if institution_type_id:
                queues_query = queues_query.filter(Institution.institution_type_id == institution_type_id)

            now = datetime.utcnow()
            current_weekday = now.strftime('%A').upper()
            try:
                weekday_enum = getattr(Weekday, current_weekday)
                queues_query = queues_query.filter(
                    and_(
                        QueueSchedule.weekday == weekday_enum,
                        QueueSchedule.is_closed == False,
                        QueueSchedule.open_time <= now.time(),
                        QueueSchedule.end_time >= now.time(),
                        Queue.active_tickets < Queue.daily_limit
                    )
                )
            except AttributeError:
                logger.error(f"Dia da semana inválido: {current_weekday}")
                return jsonify({'error': 'Dia da semana inválido'}), 500

            queues = queues_query.all()
            result = {'branches': [], 'total': len(queues)}
            branch_data = {}

            user_prefs = UserPreference.query.filter_by(user_id=user_id).all() if user_id else []
            preferred_categories = {p.service_category_id for p in user_prefs if p.service_category_id}
            preferred_neighborhoods = {p.neighborhood for p in user_prefs if p.neighborhood}
            preferred_institution_types = {p.institution_type_id for p in user_prefs if p.institution_type_id}

            for queue in queues:
                branch = queue.department.branch
                institution = branch.institution if branch else None
                institution_type = institution.type if institution else None

                if not (queue.department and branch and institution and institution_type):
                    logger.warning(f"Dados incompletos para queue_id={queue.id}")
                    continue

                wait_time = QueueService.calculate_wait_time(queue.id, queue.active_tickets + 1, 0, user_lat, user_lon)
                if max_wait_time and isinstance(wait_time, (int, float)) and wait_time > max_wait_time:
                    continue

                quality_score = service_recommendation_predictor.predict(queue, user_id, user_lat, user_lon)
                if min_quality_score and quality_score < min_quality_score:
                    continue

                distance = QueueService.calculate_distance(user_lat, user_lon, branch) if user_lat and user_lon else float('inf')
                predicted_demand = demand_model.predict(queue.id, hours_ahead=1)

                composite_score = (
                    (1 / (1 + distance)) * 0.4 +
                    quality_score * 0.3 +
                    (1 / (1 + wait_time / 10)) * 0.2 +
                    (1 / (1 + predicted_demand / 10)) * 0.1
                )
                if queue.category_id in preferred_categories:
                    composite_score += 0.15
                if branch.neighborhood in preferred_neighborhoods:
                    composite_score += 0.1
                if institution.institution_type_id in preferred_institution_types:
                    composite_score += 0.1

                branch_key = branch.id
                if branch_key not in branch_data:
                    branch_data[branch_key] = {
                        'id': branch.id,
                        'institution': {
                            'name': institution.name or "Desconhecida",
                            'type': {
                                'id': institution_type.id if institution_type else None,
                                'name': institution_type.name if institution_type else "Desconhecido"
                            }
                        },
                        'name': branch.name or "Desconhecida",
                        'location': branch.location or "Desconhecida",
                        'neighborhood': branch.neighborhood or "Desconhecido",
                        'latitude': float(branch.latitude) if branch.latitude else None,
                        'longitude': float(branch.longitude) if branch.longitude else None,
                        'distance': float(distance) if distance != float('inf') else None,
                        'queues': [],
                        'max_composite_score': 0
                    }

                branch_data[branch_key]['queues'].append({
                    'id': queue.id,
                    'service': queue.service or "Desconhecido",
                    'category_id': queue.category_id,
                    'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
                    'quality_score': float(quality_score),
                    'predicted_demand': float(predicted_demand),
                    'composite_score': float(composite_score)
                })
                branch_data[branch_key]['max_composite_score'] = max(
                    branch_data[branch_key]['max_composite_score'], composite_score
                )

            branches = list(branch_data.values())
            if sort_by == 'distance':
                branches.sort(key=lambda x: x['distance'] if x['distance'] is not None else float('inf'))
            elif sort_by == 'wait_time':
                branches.sort(key=lambda x: min(
                    (float(q['wait_time'].split()[0]) if q['wait_time'] != "N/A" else float('inf') for q in x['queues']),
                    default=float('inf')
                ))
            elif sort_by == 'quality_score':
                branches.sort(key=lambda x: max((q['quality_score'] for q in x['queues']), default=0), reverse=True)
            else:
                branches.sort(key=lambda x: x['max_composite_score'], reverse=True)

            start = (page - 1) * per_page
            end = start + per_page
            paginated_branches = branches[start:end]

            result['branches'] = paginated_branches
            result['page'] = page
            result['per_page'] = per_page
            result['total_pages'] = (len(branches) + per_page - 1) // per_page

            if redis_client:
                try:
                    redis_client.setex(cache_key, 30, json.dumps(result, default=str))
                    logger.info(f"Resultado armazenado no cache para {cache_key}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar cache para {cache_key}: {e}")

            logger.info(f"Serviços buscados: {len(branches)} filiais encontradas, {len(queues)} filas totais")
            return jsonify(result), 200
        except Exception as e:
            logger.error(f"Erro ao buscar serviços: {str(e)}")
            return jsonify({'error': f'Erro ao buscar serviços: {str(e)}'}), 500

    # WebSocket handlers
    @socketio.on('connect', namespace='/tickets')
    def handle_connect():
        try:
            token = request.args.get('token')
            if not token:
                logger.warning("Tentativa de conexão WebSocket sem token")
                raise ConnectionRefusedError('Token não fornecido')

            decoded_token = auth.verify_id_token(token)
            user_id = decoded_token.get('uid')
            join_room(user_id)
            logger.info(f"Usuário {user_id} conectado ao WebSocket namespace /tickets")
        except Exception as e:
            logger.error(f"Erro na conexão WebSocket: {str(e)}")
            raise ConnectionRefusedError(str(e))

    @socketio.on('disconnect', namespace='/tickets')
    def handle_disconnect():
        try:
            token = request.args.get('token')
            if token:
                decoded_token = auth.verify_id_token(token)
                user_id = decoded_token.get('uid')
                leave_room(user_id)
                logger.info(f"Usuário {user_id} desconectado do WebSocket namespace /tickets")
        except Exception as e:
            logger.error(f"Erro na desconexão WebSocket: {str(e)}")

    @socketio.on('connect', namespace='/dashboard')
    def handle_dashboard_connect():
        try:
            token = request.args.get('token')
            if not token:
                logger.warning("Tentativa de conexão WebSocket sem token no namespace /dashboard")
                raise ConnectionRefusedError('Token não fornecido')

            decoded_token = auth.verify_id_token(token)
            user_id = decoded_token.get('uid')
            user = User.query.get(user_id)
            if not user or user.user_role not in [UserRole.DEPARTMENT_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
                logger.warning(f"Tentativa não autorizada de conexão ao dashboard por user_id={user_id}")
                raise ConnectionRefusedError('Acesso restrito a administradores')

            if user.user_role == UserRole.INSTITUTION_ADMIN:
                join_room(user.institution_id)
            elif user.user_role == UserRole.DEPARTMENT_ADMIN:
                join_room(user.department_id)
            else:
                join_room('system_admin')
            logger.info(f"Usuário {user_id} conectado ao WebSocket namespace /dashboard")
        except Exception as e:
            logger.error(f"Erro na conexão WebSocket no namespace /dashboard: {str(e)}")
            raise ConnectionRefusedError(str(e))

    @socketio.on('disconnect', namespace='/dashboard')
    def handle_dashboard_disconnect():
        try:
            token = request.args.get('token')
            if token:
                decoded_token = auth.verify_id_token(token)
                user_id = decoded_token.get('uid')
                user = User.query.get(user_id)
                if user:
                    if user.user_role == UserRole.INSTITUTION_ADMIN:
                        leave_room(user.institution_id)
                    elif user.user_role == UserRole.DEPARTMENT_ADMIN:
                        leave_room(user.department_id)
                    else:
                        leave_room('system_admin')
                    logger.info(f"Usuário {user_id} desconectado do WebSocket namespace /dashboard")
        except Exception as e:
            logger.error(f"Erro na desconexão WebSocket no namespace /dashboard: {str(e)}")



    @api.route('/api/institution_types', methods=['GET'])
    def get_institution_types():
        """Lista todos os tipos de instituições."""
        try:
            types = InstitutionType.query.all()
            result = [
                {
                    'id': t.id,
                    'name': t.name,
                    'icon': t.icon_url or 'https://via.placeholder.com/48'
                } for t in types
            ]
            return jsonify({'types': result}), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco ao listar tipos de instituições: {e}")
            return jsonify({'error': 'Erro interno do servidor'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao listar tipos de instituições: {e}")
            return jsonify({'error': 'Erro interno do servidor'}), 500

    @api.route('/api/user/preferences', methods=['GET'])
    def get_user_preferences():
        """Retorna preferências do usuário, incluindo inferências do CollaborativeFilteringModel."""
        try:
            user_id = request.args.get('user_id')
            if not user_id:
                return jsonify({'error': 'user_id é obrigatório'}), 400

            # Preferências explícitas do banco
            preferences = UserPreference.query.filter_by(user_id=user_id).all()
            preference_scores = {
                pref.institution_type_id: pref.preference_score
                for pref in preferences
                if pref.institution_type_id
            }

            # Se poucas preferências, usar CollaborativeFilteringModel para inferir
            if len(preference_scores) < 3:
                try:
                    # Obter todas as filas para inferência
                    queue_ids = [q.id for q in Queue.query.all()]
                    collab_scores = collaborative_model.predict(user_id, queue_ids)
                    # Mapear filas para tipos de instituição
                    for queue_id, score in collab_scores.items():
                        queue = Queue.query.get(queue_id)
                        if queue and queue.department and queue.department.branch:
                            inst = Institution.query.get(queue.department.branch.institution_id)
                            if inst and inst.institution_type_id:
                                # Ponderar score colaborativo (0 a 1) para escala 0-100
                                preference_scores[inst.institution_type_id] = preference_scores.get(
                                    inst.institution_type_id, 0
                                ) + int(score * 50)  # Ajuste de peso
                except Exception as e:
                    logger.warning(f"Erro ao inferir preferências para user_id={user_id}: {e}")

            return jsonify({'preferences': preference_scores}), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco ao carregar preferências para user_id={user_id}: {e}")
            return jsonify({'error': 'Erro interno do servidor'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao carregar preferências para user_id={user_id}: {e}")
            return jsonify({'error': 'Erro interno do servidor'}), 500

    @api.route('/api/institutions', methods=['GET'])
    def get_institutions():
        """Lista instituições por tipo, ordenadas por pontuação de qualidade."""
        try:
            type_id = request.args.get('type_id')
            user_id = request.args.get('user_id')
            user_lat = request.args.get('lat', type=float)
            user_lon = request.args.get('lon', type=float)

            if not type_id:
                return jsonify({'error': 'type_id é obrigatório'}), 400

            # Filtrar instituições por tipo
            institutions = Institution.query.filter_by(institution_type_id=type_id).all()
            if not institutions:
                return jsonify({'institutions': []}), 200

            # Calcular pontuações de qualidade
            result = []
            for inst in institutions:
                # Encontrar uma fila representativa (primeira fila da primeira filial)
                branch = Branch.query.filter_by(institution_id=inst.id).first()
                queue = None
                if branch:
                    queue = Queue.query.join(Department).filter(Department.branch_id == branch.id).first()

                # Pontuação de qualidade usando ServiceRecommendationPredictor
                quality_score = 0.5  # Default
                if queue:
                    try:
                        quality_score = service_recommendation_predictor.predict(
                            queue=queue,
                            user_id=user_id,
                            user_lat=user_lat,
                            user_lon=user_lon
                        )
                    except Exception as e:
                        logger.warning(f"Erro ao prever qualidade para institution_id={inst.id}: {e}")

                # Tempo de espera médio (se houver filas)
                avg_wait_time = None
                if branch:
                    queues = Queue.query.join(Department).filter(Department.branch_id == branch.id).all()
                    if queues:
                        wait_times = [
                            QueueService.calculate_wait_time(
                                queue_id=q.id,
                                ticket_number=q.current_ticket + 1,
                                priority=0,
                                user_lat=user_lat,
                                user_lon=user_lon
                            ) for q in queues
                        ]
                        wait_times = [wt for wt in wait_times if wt != "N/A"]
                        avg_wait_time = round(sum(wait_times) / len(wait_times), 1) if wait_times else None

                result.append({
                    'id': inst.id,
                    'name': inst.name,
                    'logo': inst.logo_url or 'https://via.placeholder.com/40',
                    'description': inst.description or '',
                    'quality_score': round(quality_score, 2),
                    'avg_wait_time': avg_wait_time
                })

            # Ordenar por pontuação de qualidade (descendente)
            result.sort(key=lambda x: x['quality_score'], reverse=True)

            # Adicionar alternativas usando ServiceClusteringModel (se tempo de espera for alto)
            for inst in result[:]:
                if inst['avg_wait_time'] and inst['avg_wait_time'] > 30:  # Limite de 30 minutos
                    branch = Branch.query.filter_by(institution_id=inst['id']).first()
                    if branch:
                        queue = Queue.query.join(Department).filter(Department.branch_id == branch.id).first()
                        if queue:
                            try:
                                alternatives = clustering_model.get_alternatives(queue.id, n=2)
                                alt_institutions = []
                                for alt_queue_id in alternatives:
                                    alt_queue = Queue.query.get(alt_queue_id)
                                    if alt_queue and alt_queue.department and alt_queue.department.branch:
                                        alt_inst = Institution.query.get(alt_queue.department.branch.institution_id)
                                        if alt_inst and alt_inst.institution_type_id == type_id:
                                            alt_institutions.append({
                                                'id': alt_inst.id,
                                                'name': alt_inst.name,
                                                'logo': alt_inst.logo_url or 'https://via.placeholder.com/40',
                                                'description': alt_inst.description or '',
                                                'quality_score': 0.5,  # Pode calcular se necessário
                                                'avg_wait_time': None
                                            })
                                inst['alternatives'] = alt_institutions
                            except Exception as e:
                                logger.warning(f"Erro ao obter alternativas para institution_id={inst['id']}: {e}")

            return jsonify({'institutions': result}), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco ao listar instituições para type_id={type_id}: {e}")
            return jsonify({'error': 'Erro interno do servidor'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao listar instituições para type_id={type_id}: {e}")
            return jsonify({'error': 'Erro interno do servidor'}), 500

    @api.route('/api/branches', methods=['GET'])
    def get_branches():
        """Lista filiais por instituição, ordenadas por pontuação de qualidade."""
        try:
            institution_id = request.args.get('institution_id')
            user_id = request.args.get('user_id')
            user_lat = request.args.get('lat', type=float)
            user_lon = request.args.get('lon', type=float)

            if not institution_id:
                return jsonify({'error': 'institution_id é obrigatório'}), 400

            branches = Branch.query.filter_by(institution_id=institution_id).all()
            if not branches:
                return jsonify({'branches': []}), 200

            result = []
            for branch in branches:
                # Encontrar uma fila representativa
                queue = Queue.query.join(Department).filter(Department.branch_id == branch.id).first()

                # Pontuação de qualidade
                quality_score = 0.5  # Default
                if queue:
                    try:
                        quality_score = service_recommendation_predictor.predict(
                            queue=queue,
                            user_id=user_id,
                            user_lat=user_lat,
                            user_lon=user_lon
                        )
                    except Exception as e:
                        logger.warning(f"Erro ao prever qualidade para branch_id={branch.id}: {e}")

                # Tempo de espera médio
                queues = Queue.query.join(Department).filter(Department.branch_id == branch.id).all()
                avg_wait_time = None
                predicted_demand = None
                if queues:
                    wait_times = [
                        QueueService.calculate_wait_time(
                            queue_id=q.id,
                            ticket_number=q.current_ticket + 1,
                            priority=0,
                            user_lat=user_lat,
                            user_lon=user_lon
                        ) for q in queues
                    ]
                    wait_times = [wt for wt in wait_times if wt != "N/A"]
                    avg_wait_time = round(sum(wait_times) / len(wait_times), 1) if wait_times else None

                    # Previsão de demanda
                    try:
                        demands = [demand_model.predict(q.id, hours_ahead=1) for q in queues]
                        predicted_demand = round(sum(demands) / len(demands), 1) if demands else None
                    except Exception as e:
                        logger.warning(f"Erro ao prever demanda para branch_id={branch.id}: {e}")

                # Distância (se localização fornecida)
                distance_km = None
                if user_lat is not None and user_lon is not None and branch.latitude and branch.longitude:
                    distance_km = QueueService.calculate_distance(user_lat, user_lon, branch)

                branch_data = {
                    'id': branch.id,
                    'name': branch.name,
                    'neighborhood': branch.neighborhood or 'Desconhecido',
                    'logo': branch.logo_url or 'https://via.placeholder.com/40',
                    'latitude': branch.latitude,
                    'longitude': branch.longitude,
                    'quality_score': round(quality_score, 2),
                    'avg_wait_time': avg_wait_time,
                    'predicted_demand': predicted_demand,
                    'distance_km': round(distance_km, 2) if distance_km is not None else None
                }

                # Adicionar alternativas se tempo de espera for alto
                if avg_wait_time and avg_wait_time > 30 and queue:
                    try:
                        alternatives = clustering_model.get_alternatives(queue.id, n=2)
                        alt_branches = []
                        for alt_queue_id in alternatives:
                            alt_queue = Queue.query.get(alt_queue_id)
                            if alt_queue and alt_queue.department and alt_queue.department.branch:
                                alt_branch = alt_queue.department.branch
                                if alt_branch.institution_id == institution_id and alt_branch.id != branch.id:
                                    alt_queues = Queue.query.join(Department).filter(Department.branch_id == alt_branch.id).all()
                                    alt_wait_times = [
                                        QueueService.calculate_wait_time(
                                            queue_id=q.id,
                                            ticket_number=q.current_ticket + 1,
                                            priority=0
                                        ) for q in alt_queues
                                    ]
                                    alt_wait_times = [wt for wt in alt_wait_times if wt != "N/A"]
                                    alt_avg_wait_time = round(sum(alt_wait_times) / len(alt_wait_times), 1) if alt_wait_times else None
                                    alt_branches.append({
                                        'id': alt_branch.id,
                                        'name': alt_branch.name,
                                        'neighborhood': alt_branch.neighborhood or 'Desconhecido',
                                        'logo': alt_branch.logo_url or 'https://via.placeholder.com/40',
                                        'avg_wait_time': alt_avg_wait_time
                                    })
                        branch_data['alternatives'] = alt_branches
                    except Exception as e:
                        logger.warning(f"Erro ao obter alternativas para branch_id={branch.id}: {e}")

                result.append(branch_data)

            # Ordenar por pontuação de qualidade, considerando distância se disponível
            result.sort(key=lambda x: (
                x['quality_score'],
                x['distance_km'] if x['distance_km'] is not None else float('inf')
            ), reverse=True)

            return jsonify({'branches': result}), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco ao listar filiais para institution_id={institution_id}: {e}")
            return jsonify({'error': 'Erro interno do servidor'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao listar filiais para institution_id={institution_id}: {e}")
            return jsonify({'error': 'Erro interno do servidor'}), 500

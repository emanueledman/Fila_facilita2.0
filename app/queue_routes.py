from flask import jsonify, request, send_file
from flask_socketio import join_room, leave_room
from . import db, socketio, redis_client
from .models import Institution, Branch, Queue, Ticket, User, Department, UserRole, QueueSchedule, Weekday, ServiceCategory, ServiceTag, UserPreference
from .auth import require_auth
from .services import QueueService
from .ml_models import wait_time_predictor
import uuid
from datetime import datetime, timedelta
import io
import json
import re
import logging
from sqlalchemy import and_, or_
from geopy.distance import geodesic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_queue_routes(app):
    def emit_ticket_update(ticket):
        """Emite atualização de ticket via WebSocket no namespace /tickets."""
        try:
            wait_time = QueueService.calculate_wait_time(
                ticket.queue.id, ticket.ticket_number, ticket.priority
            )
            socketio.emit('ticket_update', {
                'ticket_id': ticket.id,
                'status': ticket.status,
                'counter': f"{ticket.counter:02d}" if ticket.counter else None,
                'position': max(0, ticket.ticket_number - ticket.queue.current_ticket),
                'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
            }, namespace='/tickets')
            logger.info(f"Atualização de ticket emitida via WebSocket: ticket_id={ticket.id}, wait_time={wait_time}")
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
        """Emite atualização ao painel via WebSocket no namespace /dashboard."""
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
        service = request.args.get('service')
        user_lat = request.args.get('lat')
        user_lon = request.args.get('lon')
        neighborhood = request.args.get('neighborhood')

        if not service or not isinstance(service, str) or not service.strip():
            logger.warning("Parâmetro 'service' não fornecido ou inválido.")
            return jsonify({'error': "O parâmetro 'service' é obrigatório e deve ser uma string."}), 400

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

        try:
            user_id = request.user_id
            suggestions = QueueService.search_services(
                query=service,
                user_id=user_id,
                user_lat=user_lat,
                user_lon=user_lon,
                neighborhood=neighborhood,
                max_results=10
            )
            logger.info(f"Sugestões geradas para o serviço '{service}': {len(suggestions['services'])} resultados.")
            return jsonify(suggestions), 200
        except Exception as e:
            logger.error(f"Erro ao gerar sugestões para o serviço '{service}': {e}")
            return jsonify({'error': "Erro ao gerar sugestões."}), 500

    @app.route('/api/update_location', methods=['POST'])
    @require_auth
    def update_location():
        user_id = request.user_id
        data = request.get_json() or {}
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
        QueueService.check_proactive_notifications()
        return jsonify({'message': 'Localização atualizada com sucesso'}), 200

    @app.route('/api/queue/create', methods=['POST'])
    @require_auth
    def create_queue():
        user = User.query.get(request.user_id)
        if not user or not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
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

        if user.is_department_admin and user.department_id != data['department_id']:
            logger.warning(f"Usuário {user.id} não tem permissão para criar fila no departamento {data['department_id']}")
            return jsonify({'error': 'Sem permissão para este departamento'}), 403
        if user.is_institution_admin and department.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para criar fila na instituição {department.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        if Queue.query.filter_by(service=data['service'], department_id=data['department_id'], branch_id=data['branch_id']).first():
            logger.warning(f"Fila já existe para o serviço {data['service']} no departamento {data['department_id']} e filial {data['branch_id']}.")
            return jsonify({'error': 'Fila já existe'}), 400

        queue = Queue(
            id=str(uuid.uuid4()),
            department_id=data['department_id'],
            branch_id=data['branch_id'],
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
        if not user or not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
            logger.warning(f"Tentativa não autorizada de atualizar fila por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get_or_404(id)
        data = request.get_json() or {}

        if user.is_department_admin and queue.department_id != user.department_id:
            logger.warning(f"Usuário {user.id} não tem permissão para atualizar fila {id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.is_institution_admin and queue.department.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para atualizar fila na instituição {queue.department.institution_id}")
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
        if 'branch_id' in data and not isinstance(data['branch_id'], str):
            logger.warning(f"branch_id inválido: {data['branch_id']}")
            return jsonify({'error': 'branch_id deve ser uma string'}), 400

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
        queue.daily_limit = data.get('daily_limit', queue.daily_limit)
        queue.num_counters = data.get('num_counters', queue.num_counters)
        db.session.commit()
        logger.info(f"Fila atualizada: {queue.service} (ID: {id})")
        return jsonify({'message': 'Fila atualizada'}), 200

    @app.route('/api/queue/<id>', methods=['DELETE'])
    @require_auth
    def delete_queue(id):
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

    @app.route('/api/queue/<service>/ticket', methods=['POST'])
    @require_auth
    def get_ticket(service):
        data = request.get_json() or {}
        user_id = data.get('user_id', request.user_id)
        fcm_token = data.get('fcm_token')
        priority = data.get('priority', 0)
        is_physical = data.get('is_physical', False)
        branch_id = data.get('branch_id')

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

        try:
            ticket, pdf_buffer = QueueService.add_to_queue(
                service=service,
                user_id=user_id,
                priority=priority,
                is_physical=is_physical,
                fcm_token=fcm_token,
                branch_id=branch_id
            )
            emit_ticket_update(ticket)
            wait_time = QueueService.calculate_wait_time(ticket.queue.id, ticket.ticket_number, ticket.priority)

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
                    'branch_id': ticket.queue.branch_id
                }
            }

            if is_physical and pdf_buffer:
                return send_file(
                    io.BytesIO(bytes.fromhex(pdf_buffer.getvalue().hex())),
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
        return jsonify({
            'service': queue.service or "Desconhecido",
            'institution': queue.department.institution.name if queue.department and queue.department.institution else "Desconhecida",
            'branch': queue.branch.name if queue.branch else "Desconhecida",
            'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
            'qr_code': ticket.qr_code,
            'status': ticket.status,
            'counter': f"{ticket.counter:02d}" if ticket.counter else None,
            'position': max(0, ticket.ticket_number - queue.current_ticket),
            'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
            'priority': ticket.priority,
            'is_physical': ticket.is_physical,
            'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None
        }), 200

    @app.route('/api/queue/<service>/call', methods=['POST'])
    @require_auth
    def call_next_ticket(service):
        user = User.query.get(request.user_id)
        if not user or not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
            logger.warning(f"Tentativa não autorizada de chamar ticket por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        try:
            data = request.get_json() or {}
            branch_id = data.get('branch_id')
            ticket = QueueService.call_next(service, branch_id=branch_id)
            if user.is_department_admin and ticket.queue.department_id != user.department_id:
                logger.warning(f"Usuário {user.id} não tem permissão para chamar ticket na fila {ticket.queue_id}")
                return jsonify({'error': 'Sem permissão para esta fila'}), 403
            if user.is_institution_admin and ticket.queue.department.institution_id != user.institution_id:
                logger.warning(f"Usuário {user.id} não tem permissão para chamar ticket na instituição {ticket.queue.department.institution_id}")
                return jsonify({'error': 'Sem permissão para esta instituição'}), 403

            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=ticket.queue.department.institution_id,
                queue_id=ticket.queue_id,
                event_type='new_call',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter,
                    'timestamp': ticket.attended_at.isoformat() if ticket.attended_at else None
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
        if not user or not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
            logger.warning(f"Tentativa não autorizada de chamar ticket {ticket_id} por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.status != 'Pendente':
            logger.warning(f"Tentativa de chamar ticket {ticket_id} com status {ticket.status}")
            return jsonify({'error': f'Ticket já está {ticket.status}'}), 400

        if user.is_department_admin and ticket.queue.department_id != user.department_id:
            logger.warning(f"Usuário {user.id} não tem permissão para chamar ticket {ticket_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.is_institution_admin and ticket.queue.department.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para chamar ticket na instituição {ticket.queue.department.institution_id}")
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
                institution_id=queue.department.institution_id,
                queue_id=queue.id,
                event_type='new_call',
                data={
                    'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter,
                    'timestamp': ticket.attended_at.isoformat() if ticket.attended_at else None
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
                institution_id=ticket.queue.department.institution_id,
                queue_id=ticket.queue_id,
                event_type='call_completed',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter,
                    'timestamp': ticket.attended_at.isoformat() if ticket.attended_at else None
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

                    queue_data.append({
                        'id': q.id,
                        'service': q.service or "Desconhecido",
                        'prefix': q.prefix,
                        'sector': q.department.sector if q.department else None,
                        'department': q.department.name if q.department else None,
                        'branch': q.department.branch.name if q.department and q.department.branch else None,
                        'institution': inst.name or "Desconhecida",
                        'open_time': schedule.open_time.strftime('%H:%M') if schedule and schedule.open_time else None,
                        'end_time': schedule.end_time.strftime('%H:%M') if schedule and schedule.end_time else None,
                        'daily_limit': q.daily_limit or 0,
                        'active_tickets': q.active_tickets or 0,
                        'avg_wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "N/A",
                        'num_counters': q.num_counters or 1,
                        'status': 'Aberto' if is_open else 'Fechado'
                    })

                result.append({
                    'institution': {
                        'id': inst.id,
                        'name': inst.name or "Desconhecida",
                        'description': inst.description or "Sem descrição",
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
                    },
                    'queues': queue_data
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
                'institution': t.queue.department.institution.name if t.queue.department and t.queue.department.institution else "Desconhecida",
                'branch': t.queue.branch.name if t.queue.branch else "Desconhecida",
                'number': f"{t.queue.prefix}{t.ticket_number}",
                'status': t.status,
                'counter': f"{t.counter:02d}" if t.counter else None,
                'position': max(0, t.ticket_number - t.queue.current_ticket) if t.status == 'Pendente' else 0,
                'wait_time': f"{int(wait_time)} minutos" if isinstance((wait_time := QueueService.calculate_wait_time(t.queue.id, t.ticket_number, t.priority)), (int, float)) else "N/A",
                'qr_code': t.qr_code,
                'trade_available': t.trade_available
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
                'institution': t.queue.department.institution.name if t.queue.department and t.queue.department.institution else "Desconhecida",
                'branch': t.queue.branch.name if t.queue.branch else "Desconhecida",
                'number': f"{t.queue.prefix}{t.ticket_number}",
                'position': max(0, t.ticket_number - t.queue.current_ticket),
                'user_id': t.user_id
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
        if not user or not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
            logger.warning(f"Tentativa não autorizada de listar tickets por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        try:
            if user.is_system_admin:
                tickets = Ticket.query.all()
            elif user.is_institution_admin:
                tickets = Ticket.query.join(Queue).join(Department).filter(
                    Department.institution_id == user.institution_id
                ).all()
            else:
                tickets = Ticket.query.filter(
                    Ticket.queue_id.in_(
                        db.session.query(Queue.id).filter_by(department_id=user.department_id)
                    )
                ).all()

            return jsonify([{
                'id': t.id,
                'service': t.queue.service or "Desconhecido",
                'institution': t.queue.department.institution.name if t.queue.department and t.queue.department.institution else "Desconhecida",
                'branch': t.queue.branch.name if t.queue.branch else "Desconhecida",
                'number': f"{t.queue.prefix}{t.ticket_number}",
                'status': t.status,
                'counter': f"{t.counter:02d}" if t.counter else None,
                'position': max(0, t.ticket_number - t.queue.current_ticket) if t.status == 'Pendente' else 0,
                'wait_time': f"{int(wait_time)} minutos" if isinstance((wait_time := QueueService.calculate_wait_time(t.queue.id, t.ticket_number, t.priority)), (int, float)) else "N/A",
                'qr_code': t.qr_code,
                'trade_available': t.trade_available,
                'user_id': t.user_id
            } for t in tickets]), 200
        except Exception as e:
            logger.error(f"Erro ao listar todos os tickets para user_id={request.user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar tickets'}), 500

    @app.route('/api/update_fcm_token', methods=['POST'])
    @require_auth
    def update_fcm_token():
        user_id = request.user_id
        data = request.get_json() or {}
        fcm_token = data.get('fcm_token')
        email = data.get('email')

        if not fcm_token or not email:
            logger.error(f"FCM token ou email não fornecidos por user_id={user_id}")
            return jsonify({'error': 'FCM token e email são obrigatórios'}), 400

        user = User.query.get(user_id)
        if not user:
            user = User(id=user_id, email=email, name="Usuário Desconhecido", active=True)
            db.session.add(user)
            logger.info(f"Novo usuário criado: user_id={user_id}, email={email}")
        else:
            if user.email != email:
                logger.warning(f"Email fornecido ({email}) não corresponde ao user_id={user_id}")
                return jsonify({'error': 'Email não corresponde ao usuário autenticado'}), 403
            user.fcm_token = fcm_token

        db.session.commit()
        logger.info(f"FCM token atualizado para user_id={user_id}, email={email}")
        QueueService.check_proximity_notifications(user_id, user.last_known_lat, user.last_known_lon)
        return jsonify({'message': 'FCM token atualizado com sucesso'}), 200

    @app.route('/api/service/<institution_name>/<service>/current', methods=['GET'])
    @require_auth
    def get_currently_serving(institution_name, service):
        institution = Institution.query.filter_by(name=institution_name).first()
        if not institution:
            logger.error(f"Instituição não encontrada: {institution_name}")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        department = Department.query.filter_by(institution_id=institution.id).first()
        if not department:
            logger.error(f"Departamento não encontrado para institution_name={institution_name}")
            return jsonify({'error': 'Departamento não encontrado'}), 404

        queue = Queue.query.filter_by(department_id=department.id, service=service).first()
        if not queue:
            logger.error(f"Fila não encontrada para institution_name={institution_name}, service={service}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        current_ticket = queue.current_ticket
        if current_ticket == 0:
            return jsonify({'current_ticket': 'N/A'}), 200

        return jsonify({'current_ticket': f"{queue.prefix}{current_ticket:03d}"}), 200

    @app.route('/api/calculate_distance', methods=['POST'])
    @require_auth
    def calculate_distance():
        data = request.get_json() or {}
        user_lat = data.get('latitude')
        user_lon = data.get('longitude')
        institution_id = data.get('institution_id')

        if not all([user_lat, user_lon, institution_id]):
            logger.warning("Requisição de distância sem latitude, longitude ou institution_id")
            return jsonify({'error': 'Latitude, longitude e institution_id são obrigatórios'}), 400

        try:
            user_lat = float(user_lat)
            user_lon = float(user_lon)
        except (ValueError, TypeError):
            logger.warning(f"Latitude ou longitude inválidos: lat={user_lat}, lon={user_lon}")
            return jsonify({'error': 'Latitude e longitude devem ser números'}), 400

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.error(f"Instituição não encontrada para institution_id={institution_id}")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        # Ajustado para usar Branch em vez de Institution
        branch = Branch.query.filter_by(institution_id=institution_id).first()
        if not branch:
            logger.error(f"Filial não encontrada para institution_id={institution_id}")
            return jsonify({'error': 'Filial não encontrada'}), 404

        distance = QueueService.calculate_distance(user_lat, user_lon, branch)
        if distance is None:
            logger.error(f"Erro ao calcular distância para institution_id={institution_id}")
            return jsonify({'error': 'Erro ao calcular distância'}), 500

        logger.info(f"Distância calculada: {distance:.2f} km entre usuário ({user_lat}, {user_lon}) e {institution.name}")
        return jsonify({'distance': distance}), 200

    @app.route('/api/institutions/<string:institution_id>/services/search', methods=['GET'])
    def search_services(institution_id):
        try:
            institution = Institution.query.get_or_404(institution_id)
            user_id = request.user_id if hasattr(request, 'user_id') else None

            service_name = request.args.get('service_name', '').strip()
            if service_name and not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', service_name):
                logger.warning(f"Nome do serviço inválido: {service_name}")
                return jsonify({'error': 'Nome do serviço inválido'}), 400

            neighborhood = request.args.get('neighborhood')
            if neighborhood:
                if not re.match(r'^[A-Za-zÀ-ÿ\s,]{1,100}$', neighborhood):
                    logger.warning(f"Bairro inválido: {neighborhood}")
                    return jsonify({'error': 'Bairro inválido'}), 400

            user_lat = request.args.get('latitude')
            user_lon = request.args.get('longitude')
            if user_lat and user_lon:
                try:
                    user_lat = float(user_lat)
                    user_lon = float(user_lon)
                except (ValueError, TypeError):
                    logger.warning(f"Latitude ou longitude inválidos: lat={user_lat}, lon={user_lon}")
                    return jsonify({'error': 'Latitude e longitude devem ser números'}), 400

            page = request.args.get('page', '1')
            per_page = request.args.get('per_page', '20')
            try:
                page = int(page)
                per_page = int(per_page)
            except (ValueError, TypeError):
                logger.warning(f"Página ou per_page inválidos: page={page}, per_page={per_page}")
                return jsonify({'error': 'Página e itens por página devem ser números inteiros'}), 400

            if per_page > 100:
                logger.warning(f"Per_page excede o máximo: {per_page}")
                return jsonify({'error': 'Máximo de itens por página é 100'}), 400

            result = QueueService.search_services(
                query=service_name,
                user_id=user_id,
                user_lat=user_lat,
                user_lon=user_lon,
                institution_id=institution_id,
                neighborhood=neighborhood,
                page=page,
                per_page=per_page
            )
            logger.info(f"Serviços buscados para institution_id={institution_id}: {result['total']} resultados")
            return jsonify(result), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao buscar serviços para institution_id={institution_id}: {str(e)}")
            return jsonify({'error': f'Erro ao buscar serviços: {str(e)}'}), 500

    @app.route('/api/institutions/<string:institution_id>/physical-ticket', methods=['POST'])
    def generate_physical_ticket(institution_id):
        institution = Institution.query.get_or_404(institution_id)

        data = request.get_json() or {}
        queue_id = data.get('queue_id')
        branch_id = data.get('branch_id')

        if not queue_id or not branch_id:
            logger.warning(f"queue_id ou branch_id inválidos: queue_id={queue_id}, branch_id={branch_id}")
            return jsonify({'error': 'queue_id e branch_id são obrigatórios'}), 400

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.institution_id != institution_id or queue.branch_id != branch_id:
            logger.warning(f"Fila {queue_id} não encontrada ou não pertence à institution_id={institution_id} ou branch_id={branch_id}")
            return jsonify({'error': 'Fila não encontrada ou não pertence à instituição/filial'}), 404

        client_ip = request.remote_addr

        try:
            result = QueueService.generate_physical_ticket_for_totem(queue_id, client_ip)
            ticket = Ticket.query.get(result['ticket']['id'])
            emit_ticket_update(ticket)
            logger.info(f"Ticket físico gerado para queue_id={queue_id}, institution_id={institution_id}")
            return send_file(
                io.BytesIO(bytes.fromhex(result['pdf'])),
                as_attachment=True,
                download_name=f"ticket_{ticket.queue.prefix}{ticket.ticket_number}.pdf",
                mimetype='application/pdf'
            )
        except ValueError as e:
            logger.error(f"Erro ao gerar ticket físico para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao gerar ticket físico para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': f'Erro ao gerar ticket: {str(e)}'}), 500

    @app.route('/api/institutions/<string:institution_id>/dashboard', methods=['GET'])
    def get_dashboard(institution_id):
        try:
            institution = Institution.query.get_or_404(institution_id)

            cache_key = f'dashboard:{institution_id}'
            refresh = request.args.get('refresh', 'false').lower() == 'true'
            if not refresh:
                try:
                    cached_data = redis_client.get(cache_key)
                    if cached_data:
                        return jsonify(json.loads(cached_data))
                except Exception as e:
                    logger.warning(f"Erro ao acessar Redis para dashboard {institution_id}: {str(e)}")

            data = QueueService.get_dashboard_data(institution_id)
            try:
                redis_client.setex(cache_key, 300, json.dumps(data, default=str))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para dashboard {institution_id}: {str(e)}")
            return jsonify(data)
        except ValueError as e:
            logger.error(f"Erro ao obter dashboard para institution_id={institution_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao obter dashboard para institution_id={institution_id}: {str(e)}")
            return jsonify({'error': 'Erro ao obter dados do dashboard'}), 500

    @socketio.on('connect_dashboard', namespace='/dashboard')
    def handle_dashboard_connect(data):
        institution_id = data.get('institution_id')
        if not institution_id or not isinstance(institution_id, str):
            socketio.emit('error', {'message': 'institution_id é obrigatório'}, namespace='/dashboard')
            logger.warning("Tentativa de conexão ao dashboard sem institution_id válido")
            return

        institution = Institution.query.get(institution_id)
        if not institution:
            socketio.emit('error', {'message': 'Instituição não encontrada'}, namespace='/dashboard')
            logger.warning(f"Instituição não encontrada: institution_id={institution_id}")
            return

        join_room(institution_id, namespace='/dashboard')
        logger.info(f"Cliente conectado ao dashboard: institution_id={institution_id}")

        try:
            dashboard_data = QueueService.get_dashboard_data(institution_id)
            socketio.emit('dashboard_update', {
                'institution_id': institution_id,
                'event_type': 'initial_data',
                'data': dashboard_data
            }, room=institution_id, namespace='/dashboard')
            logger.info(f"Dados iniciais do dashboard enviados: institution_id={institution_id}")
        except ValueError as e:
            logger.error(f"Erro ao enviar dados iniciais do dashboard para institution_id={institution_id}: {str(e)}")
            socketio.emit('error', {'message': str(e)}, namespace='/dashboard')
        except Exception as e:
            logger.error(f"Erro inesperado ao enviar dados iniciais do dashboard para institution_id={institution_id}: {str(e)}")
            socketio.emit('error', {'message': 'Erro ao carregar dados iniciais'}, namespace='/dashboard')

    @socketio.on('disconnect', namespace='/dashboard')
    def handle_dashboard_disconnect():
        logger.info("Cliente desconectado do namespace /dashboard")
    
    @socketio.on('connect_dashboard', namespace='/dashboard')
    def handle_dashboard_connect(data):
        institution_id = data.get('institution_id')
        if not institution_id or not isinstance(institution_id, str):
            socketio.emit('error', {'message': 'institution_id é obrigatório'}, namespace='/dashboard')
            logger.warning("Tentativa de conexão ao dashboard sem institution_id válido")
            return

        institution = Institution.query.get(institution_id)
        if not institution:
            socketio.emit('error', {'message': 'Instituição não encontrada'}, namespace='/dashboard')
            logger.warning(f"Instituição não encontrada: institution_id={institution_id}")
            return

        join_room(institution_id, namespace='/dashboard')
        logger.info(f"Cliente conectado ao dashboard: institution_id={institution_id}")

        try:
            dashboard_data = QueueService.get_dashboard_data(institution_id)
            socketio.emit('dashboard_update', {
                'institution_id': institution_id,
                'event_type': 'initial_data',
                'data': dashboard_data
            }, room=institution_id, namespace='/dashboard')
            logger.info(f"Dados iniciais do dashboard enviados: institution_id={institution_id}")
        except Exception as e:
            logger.error(f"Erro ao enviar dados iniciais do dashboard para institution_id={institution_id}: {str(e)}")
            socketio.emit('error', {'message': 'Erro ao carregar dados iniciais'}, namespace='/dashboard')

    @socketio.on('disconnect', namespace='/dashboard')
    def handle_dashboard_disconnect():
        logger.info("Cliente desconectado do namespace /dashboard")
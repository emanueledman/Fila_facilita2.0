from flask import jsonify, request, send_file
from . import db, socketio
from .models import Institution, Queue, Ticket, User, Department, UserRole, QueueSchedule, Weekday
from .auth import require_auth
from .services import QueueService, suggest_service_locations, get_dashboard_data, subscribe_to_dashboard
import uuid
from datetime import datetime, timedelta
import io
import json
import re
import logging
from sqlalchemy import and_

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_queue_routes(app):
    def emit_ticket_update(ticket):
        try:
            wait_time = QueueService.calculate_wait_time(ticket.queue.id, ticket.ticket_number, ticket.priority)
            socketio.emit('ticket_update', {
                'ticket_id': ticket.id,
                'status': ticket.status,
                'counter': f"{ticket.counter:02d}" if ticket.counter else None,
                'position': max(0, ticket.ticket_number - ticket.queue.current_ticket),
                'wait_time': wait_time if wait_time != "N/A" else "N/A",
            }, namespace='/tickets')
            logger.info(f"Atualização de ticket emitida via WebSocket: ticket_id={ticket.id}, wait_time={wait_time}")
        except Exception as e:
            logger.error(f"Erro ao emitir atualização via WebSocket: {e}")

    def emit_dashboard_update(institution_id, queue_id, event_type, data):
        """Função auxiliar para emitir atualizações ao painel via WebSocket."""
        try:
            socketio.emit('dashboard_update', {
                'institution_id': institution_id,
                'queue_id': queue_id,
                'event_type': event_type,
                'data': data
            }, namespace='/dashboard')
            logger.info(f"Atualização de painel emitida: institution_id={institution_id}, event_type={event_type}")
        except Exception as e:
            logger.error(f"Erro ao emitir atualização de painel: {str(e)}")

    @app.route('/api/queues', methods=['GET'])
    def list_queues():
        institutions = Institution.query.all()
        now = datetime.now()
        current_weekday_str = now.strftime('%A')
        
        # Converter a string do dia para o enum correto
        current_weekday_enum = getattr(Weekday, current_weekday_str.upper())
        
        current_time = now.time()
        result = []
        
        for inst in institutions:
            departments = Department.query.filter_by(institution_id=inst.id).all()
            queues = Queue.query.filter(Queue.department_id.in_([d.id for d in departments])).all()
            queue_data = []
            
            for q in queues:
                # Verificar status com QueueSchedule
                schedule = QueueSchedule.query.filter_by(
                    queue_id=q.id, weekday=current_weekday_enum
                ).first()
                
                is_open = False
                if schedule and not schedule.is_closed:
                    is_open = (
                        schedule.open_time and schedule.end_time and
                        current_time >= schedule.open_time and
                        current_time <= schedule.end_time and
                        q.active_tickets < q.daily_limit
                    )
                    
                queue_data.append({
                    'id': q.id,
                    'service': q.service,
                    'prefix': q.prefix,
                    'sector': q.department.sector if q.department else None,
                    'department': q.department.name if q.department else None,
                    'institution': q.department.institution.name if q.department and q.department.institution else None,
                    'open_time': schedule.open_time.strftime('%H:%M') if schedule and schedule.open_time else None,
                    'end_time': schedule.end_time.strftime('%H:%M') if schedule and schedule.end_time else None,
                    'daily_limit': q.daily_limit,
                    'active_tickets': q.active_tickets,
                    'avg_wait_time': q.avg_wait_time,
                    'num_counters': q.num_counters,
                    'status': 'Aberto' if is_open else 'Fechado'
                })
                
            result.append({
                'institution': {
                    'id': inst.id,
                    'name': inst.name,
                    'location': inst.location,
                    'latitude': inst.latitude,
                    'longitude': inst.longitude
                },
                'queues': queue_data
            })
            
        logger.info(f"Lista de filas retornada: {len(result)} instituições encontradas.")
        return jsonify(result), 200

    @app.route('/api/suggest-service', methods=['GET'])
    @require_auth
    def suggest_service():
        service = request.args.get('service')
        user_lat = request.args.get('lat', type=float)
        user_lon = request.args.get('lon', type=float)

        if not service:
            logger.warning("Parâmetro 'service' não fornecido na requisição de sugestão.")
            return jsonify({'error': "O parâmetro 'service' é obrigatório."}), 400

        try:
            suggestions = suggest_service_locations(service, user_lat, user_lon)
            logger.info(f"Sugestões geradas para o serviço '{service}': {len(suggestions)} resultados.")
            return jsonify(suggestions), 200
        except Exception as e:
            logger.error(f"Erro ao gerar sugestões para o serviço '{service}': {e}")
            return jsonify({'error': "Erro ao gerar sugestões."}), 500

    @app.route('/api/update_location', methods=['POST'])
    @require_auth
    def update_location():
        user_id = request.user_id
        data = request.get_json()
        latitude = data.get('latitude', type=float)
        longitude = data.get('longitude', type=float)

        if latitude is None or longitude is None:
            logger.error(f"Latitude ou longitude não fornecidos por user_id={user_id}")
            return jsonify({'error': 'Latitude e longitude são obrigatórios'}), 400

        user = User.query.get(user_id)
        if not user:
            email = data.get('email')
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

        return jsonify({'message': 'Localização atualizada com sucesso'}), 200

    @app.route('/api/queue/create', methods=['POST'])
    @require_auth
    def create_queue():
        user = User.query.get(request.user_id)
        if not user or not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
            logger.warning(f"Tentativa não autorizada de criar fila por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        data = request.get_json()
        required = ['service', 'prefix', 'department_id', 'open_time', 'daily_limit', 'num_counters']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de fila.")
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400

        # Validações adicionais
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
        if not department:
            logger.error(f"Departamento não encontrado: department_id={data['department_id']}")
            return jsonify({'error': 'Departamento não encontrado'}), 404

        # Verificar permissão para o departamento
        if user.is_department_admin and user.department_id != data['department_id']:
            logger.warning(f"Usuário {user.id} não tem permissão para criar fila no departamento {data['department_id']}")
            return jsonify({'error': 'Sem permissão para este departamento'}), 403
        if user.is_institution_admin and department.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para criar fila na instituição {department.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        if Queue.query.filter_by(service=data['service'], department_id=data['department_id']).first():
            logger.warning(f"Fila já existe para o serviço {data['service']} no departamento {data['department_id']}.")
            return jsonify({'error': 'Fila já existe'}), 400

        try:
            open_time = datetime.strptime(data['open_time'], '%H:%M').time()
        except ValueError:
            logger.error(f"Formato de open_time inválido: {data['open_time']}")
            return jsonify({'error': 'Formato de open_time inválido (HH:MM)'}), 400

        queue = Queue(
            id=str(uuid.uuid4()),
            department_id=data['department_id'],
            service=data['service'],
            prefix=data['prefix'],
            open_time=open_time,
            daily_limit=data['daily_limit'],
            num_counters=data['num_counters']
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
        data = request.get_json()

        # Verificar permissão
        if user.is_department_admin and queue.department_id != user.department_id:
            logger.warning(f"Usuário {user.id} não tem permissão para atualizar fila {id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.is_institution_admin and queue.department.institution_id != user.institution_id:
            logger.warning(f"Usuário {user.id} não tem permissão para atualizar fila na instituição {queue.department.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        # Validações
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
        return jsonify({'message': 'Fila excluída'}), 200

    @app.route('/api/queue/<service>/ticket', methods=['POST'])
    @require_auth
    def get_ticket(service):
        data = request.get_json() or {}
        user_id = data.get('user_id', request.user_id)
        fcm_token = data.get('fcm_token')
        priority = data.get('priority', 0)
        is_physical = data.get('is_physical', False)

        try:
            ticket, pdf_buffer = QueueService.add_to_queue(service, user_id, priority, is_physical, fcm_token)
            emit_ticket_update(ticket)
            wait_time = QueueService.calculate_wait_time(ticket.queue.id, ticket.ticket_number, ticket.priority)
            response = {
                'message': 'Senha emitida',
                'ticket': {
                    'id': ticket.id,
                    'number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'qr_code': ticket.qr_code,
                    'wait_time': wait_time if wait_time != "N/A" else "N/A",
                    'receipt': ticket.receipt_data,
                    'priority': ticket.priority,
                    'is_physical': ticket.is_physical,
                    'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None
                }
            }

            if is_physical and pdf_buffer:
                return send_file(
                    pdf_buffer,
                    as_attachment=True,
                    download_name=f"ticket_{ticket.queue.prefix}{ticket.ticket_number}.pdf",
                    mimetype='application/pdf'
                )
            logger.info(f"Senha emitida: {ticket.queue.prefix}{ticket.ticket_number} para user_id={user_id}")
            return jsonify(response), 201
        except ValueError as e:
            logger.error(f"Erro ao emitir senha para serviço {service}: {str(e)}")
            return jsonify({'error': str(e)}), 400

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
            'service': queue.service,
            'institution': queue.department.institution.name if queue.department and queue.department.institution else None,
            'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
            'qr_code': ticket.qr_code,
            'status': ticket.status,
            'counter': f"{ticket.counter:02d}" if ticket.counter else None,
            'position': max(0, ticket.ticket_number - queue.current_ticket),
            'wait_time': wait_time if wait_time != "N/A" else "N/A",
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
            ticket = QueueService.call_next(service)
            emit_ticket_update(ticket)
            if user.is_department_admin and ticket.queue.department_id != user.department_id:
                logger.warning(f"Usuário {user.id} não tem permissão para chamar ticket na fila {ticket.queue_id}")
                return jsonify({'error': 'Sem permissão para esta fila'}), 403
            if user.is_institution_admin and ticket.queue.department.institution_id != user.institution_id:
                logger.warning(f"Usuário {user.id} não tem permissão para chamar ticket na instituição {ticket.queue.department.institution_id}")
                return jsonify({'error': 'Sem permissão para esta instituição'}), 403

            logger.info(f"Senha chamada: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket.id})")
            return jsonify({
                'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} chamada',
                'ticket_id': ticket.id,
                'remaining': ticket.queue.active_tickets
            }), 200
        except ValueError as e:
            logger.error(f"Erro ao chamar próxima senha para serviço {service}: {str(e)}")
            return jsonify({'error': str(e)}), 400

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
                    'timestamp': ticket.attended_at.isoformat()
                }
            )

            logger.info(f"Ticket {ticket_id} chamado com sucesso: {queue.prefix}{ticket.ticket_number}")
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
            return jsonify({'message': 'Senha oferecida para troca', 'ticket_id': ticket.id}), 200
        except ValueError as e:
            logger.error(f"Erro ao oferecer troca para ticket {ticket_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400

    @app.route('/api/ticket/trade/<ticket_to_id>', methods=['POST'])
    @require_auth
    def trade_ticket(ticket_to_id):
        ticket_from_id = request.json.get('ticket_from_id')
        try:
            result = QueueService.trade_tickets(ticket_from_id, ticket_to_id, request.user_id)
            emit_ticket_update(result['ticket_from'])
            emit_ticket_update(result['ticket_to'])
            logger.info(f"Troca realizada entre tickets {ticket_from_id} e {ticket_to_id}")
            return jsonify({'message': 'Troca realizada', 'tickets': {
                'from': {'id': result['ticket_from'].id, 'number': f"{result['ticket_from'].queue.prefix}{result['ticket_from'].ticket_number}"},
                'to': {'id': result['ticket_to'].id, 'number': f"{result['ticket_to'].queue.prefix}{result['ticket_to'].ticket_number}"}
            }}), 200
        except ValueError as e:
            logger.error(f"Erro ao realizar troca entre tickets {ticket_from_id} e {ticket_to_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400

    @app.route('/api/ticket/validate', methods=['POST'])
    def validate_ticket():
        """
        Valida a presença de um ticket físico ou virtual usando QR code ou número do ticket e ID da fila.
        Payload: {
            'qr_code': str (opcional, para validação por QR code),
            'ticket_number': int (opcional, para validação manual),
            'queue_id': str (obrigatório se ticket_number for fornecido)
        }
        Resposta: {
            'message': str,
            'ticket_id': str
        }
        """
        data = request.get_json() or {}
        qr_code = data.get('qr_code')
        ticket_number = data.get('ticket_number', type=int)
        queue_id = data.get('queue_id')

        if not qr_code and not (ticket_number and queue_id):
            logger.warning("Requisição de validação sem qr_code ou ticket_number/queue_id")
            return jsonify({'error': 'Forneça qr_code ou ticket_number e queue_id'}), 400

        try:
            if qr_code:
                # Validação por QR code (autenticada ou pública)
                ticket = QueueService.validate_presence(qr_code)
            else:
                # Validação manual por ticket_number e queue_id
                if not isinstance(queue_id, str) or not re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', queue_id, re.I):
                    logger.warning(f"queue_id inválido: {queue_id}")
                    return jsonify({'error': 'queue_id deve ser um UUID válido'}), 400

                if not isinstance(ticket_number, int) or ticket_number < 1:
                    logger.warning(f"ticket_number inválido: {ticket_number}")
                    return jsonify({'error': 'ticket_number deve ser um número inteiro positivo'}), 400

                # Permitir validação de tickets Pendente ou Chamado para maior flexibilidade
                ticket = Ticket.query.filter_by(queue_id=queue_id, ticket_number=ticket_number).filter(Ticket.status.in_(['Pendente', 'Chamado'])).first()
                if not ticket:
                    logger.warning(f"Ticket não encontrado ou não está Pendente/Chamado: queue_id={queue_id}, ticket_number={ticket_number}")
                    return jsonify({'error': 'Ticket inválido, não está pendente ou chamado'}), 400

                ticket.status = 'attended'
                ticket.attended_at = datetime.utcnow()

                queue = ticket.queue
                last_ticket = Ticket.query.filter_by(queue_id=queue.id, status='attended')\
                    .filter(Ticket.attended_at < ticket.attended_at).order_by(Ticket.attended_at.desc()).first()
                if last_ticket and last_ticket.attended_at:
                    ticket.service_time = (ticket.attended_at - last_ticket.attended_at).total_seconds() / 60.0
                    queue.last_service_time = ticket.service_time

                if ticket.status == 'Pendente':
                    # Se estava Pendente, ajustar contadores da fila
                    queue.active_tickets -= 1
                    queue.current_ticket = ticket.ticket_number
                    ticket.counter = queue.last_counter or 1
                    queue.last_counter = ticket.counter

                db.session.commit()

            emit_ticket_update(ticket)
            emit_dashboard_update(
                institution_id=ticket.queue.department.institution_id,
                queue_id=ticket.queue_id,
                event_type='call_completed',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter,
                    'timestamp': ticket.attended_at.isoformat()
                }
            )

            logger.info(f"Presença validada para ticket {ticket.id}")
            return jsonify({'message': 'Presença validada com sucesso', 'ticket_id': ticket.id}), 200
        except ValueError as e:
            logger.error(f"Erro ao validar ticket (qr_code={qr_code}, ticket_number={ticket_number}): {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao validar ticket: {str(e)}")
            return jsonify({'error': f'Erro ao validar ticket: {str(e)}'}), 500

    @app.route('/api/tickets', methods=['GET'])
    @require_auth
    def list_user_tickets():
        tickets = Ticket.query.filter_by(user_id=request.user_id).all()
        return jsonify([{
            'id': t.id,
            'service': t.queue.service,
            'institution': t.queue.department.institution.name if t.queue.department and t.queue.department.institution else None,
            'number': f"{t.queue.prefix}{t.ticket_number}",
            'status': t.status,
            'counter': f"{t.counter:02d}" if t.counter else None,
            'position': max(0, t.ticket_number - t.queue.current_ticket) if t.status == 'Pendente' else 0,
            'wait_time': QueueService.calculate_wait_time(t.queue.id, t.ticket_number, t.priority) if t.status == 'Pendente' else "N/A",
            'qr_code': t.qr_code,
            'trade_available': t.trade_available
        } for t in tickets]), 200

    @app.route('/api/tickets/trade_available', methods=['GET'])
    @require_auth
    def list_trade_available_tickets():
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
            'service': t.queue.service,
            'institution': t.queue.department.institution.name if t.queue.department and t.queue.department.institution else None,
            'number': f"{t.queue.prefix}{t.ticket_number}",
            'position': max(0, t.ticket_number - t.queue.current_ticket),
            'user_id': t.user_id
        } for t in tickets]), 200

    @app.route('/api/ticket/<ticket_id>/cancel', methods=['POST'])
    @require_auth
    def cancel_ticket(ticket_id):
        try:
            ticket = QueueService.cancel_ticket(ticket_id, request.user_id)
            emit_ticket_update(ticket)
            logger.info(f"Senha cancelada: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket.id})")
            return jsonify({'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} cancelada', 'ticket_id': ticket.id}), 200
        except ValueError as e:
            logger.error(f"Erro ao cancelar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400

    @app.route('/api/tickets/admin', methods=['GET'])
    @require_auth
    def list_all_tickets():
        user = User.query.get(request.user_id)
        if not user or not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
            logger.warning(f"Tentativa não autorizada de listar tickets por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        if user.is_system_admin:
            tickets = Ticket.query.all()
        elif user.is_institution_admin:
            tickets = Ticket.query.join(Queue).join(Department).filter(
                Department.institution_id == user.institution_id
            ).all()
        else:  # DEPARTMENT_ADMIN
            tickets = Ticket.query.filter(
                Ticket.queue_id.in_(
                    db.session.query(Queue.id).filter_by(department_id=user.department_id)
                )
            ).all()

        return jsonify([{
            'id': t.id,
            'service': t.queue.service,
            'institution': t.queue.department.institution.name if t.queue.department and t.queue.department.institution else None,
            'number': f"{t.queue.prefix}{t.ticket_number}",
            'status': t.status,
            'counter': f"{t.counter:02d}" if t.counter else None,
            'position': max(0, t.ticket_number - t.queue.current_ticket) if t.status == 'Pendente' else 0,
            'wait_time': QueueService.calculate_wait_time(t.queue.id, t.ticket_number, t.priority) if t.status == 'Pendente' else "N/A",
            'qr_code': t.qr_code,
            'trade_available': t.trade_available,
            'user_id': t.user_id
        } for t in tickets]), 200

    @app.route('/api/update_fcm_token', methods=['POST'])
    @require_auth
    def update_fcm_token():
        user_id = request.user_id
        data = request.get_json()
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
        data = request.get_json()
        user_lat = data.get('latitude', type=float)
        user_lon = data.get('longitude', type=float)
        institution_id = data.get('institution_id')

        if not all([user_lat, user_lon, institution_id]):
            logger.warning("Requisição de distância sem latitude, longitude ou institution_id")
            return jsonify({'error': 'Latitude, longitude e institution_id são obrigatórios'}), 400

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.error(f"Instituição não encontrada para institution_id={institution_id}")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        distance = QueueService.calculate_distance(user_lat, user_lon, institution)
        if distance is None:
            logger.error(f"Erro ao calcular distância para institution_id={institution_id}")
            return jsonify({'error': 'Erro ao calcular distância'}), 500

        logger.info(f"Distância calculada: {distance:.2f} km entre usuário ({user_lat}, {user_lon}) e {institution.name}")
        return jsonify({'distance': distance}), 200

    @app.route('/api/institutions/<string:institution_id>/services/search', methods=['GET'])
    def search_services(institution_id):
        """
        Busca serviços disponíveis em uma instituição com filtros.
        Query Params:
            - sector: str (ex.: "Saúde")
            - location: str (ex.: "São Paulo")
            - max_wait_time: int (minutos)
            - service_name: str (busca parcial)
            - is_open: bool (apenas filas abertas)
            - page: int (página, padrão=1)
            - per_page: int (itens por página, padrão=20, máx=100)
        Resposta: {
            'services': [
                {
                    'queue_id': str,
                    'name': str,
                    'service': str,
                    'sector': str,
                    'location': str,
                    'description': str,
                    'is_open': bool,
                    'open_time': str,
                    'end_time': str,
                    'daily_limit': int,
                    'available_tickets': int,
                    'wait_time': int,
                    'counter': int,
                    'latitude': float,
                    'longitude': float
                },
                ...
            ],
            'total': int,
            'page': int,
            'per_page': int,
            'suggestions': [{'queue_id': str, 'location': str, 'wait_time': int}, ...]
        }
        """
        institution = Institution.query.get_or_404(institution_id)

        filters = {}
        sector = request.args.get('sector')
        if sector:
            if not re.match(r'^[A-Za-zÀ-ÿ\s]{1,50}$', sector):
                logger.warning(f"Setor inválido: {sector}")
                return jsonify({'error': 'Setor inválido'}), 400
            filters['sector'] = sector

        location = request.args.get('location')
        if location:
            if not re.match(r'^[A-Za-zÀ-ÿ\s,]{1,100}$', location):
                logger.warning(f"Localização inválida: {location}")
                return jsonify({'error': 'Localização inválida'}), 400
            filters['location'] = location

        max_wait_time = request.args.get('max_wait_time', type=int)
        if max_wait_time is not None:
            if max_wait_time < 0 or max_wait_time > 1440:
                logger.warning(f"Tempo de espera inválido: {max_wait_time}")
                return jsonify({'error': 'Tempo de espera inválido'}), 400
            filters['max_wait_time'] = max_wait_time

        service_name = request.args.get('service_name')
        if service_name:
            if not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', service_name):
                logger.warning(f"Nome do serviço inválido: {service_name}")
                return jsonify({'error': 'Nome do serviço inválido'}), 400
            filters['service_name'] = service_name

        is_open = request.args.get('is_open', 'true').lower() == 'true'
        filters['is_open'] = is_open

        filters['page'] = request.args.get('page', 1, type=int)
        filters['per_page'] = request.args.get('per_page', 20, type=int)
        if filters['per_page'] > 100:
            logger.warning(f"Per_page excede o máximo: {filters['per_page']}")
            return jsonify({'error': 'Máximo de itens por página é 100'}), 400

        try:
            result = get_service_search_results(institution_id, filters)
            logger.info(f"Serviços buscados para institution_id={institution_id}: {result['total']} resultados")
            return jsonify(result)
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao buscar serviços para institution_id={institution_id}: {str(e)}")
            return jsonify({'error': f'Erro ao buscar serviços: {str(e)}'}), 500

    @app.route('/api/institutions/<string:institution_id>/physical-ticket', methods=['POST'])
    def generate_physical_ticket(institution_id):
        """
        Gera um ticket físico anônimo para uma fila via mesa digital (totem).
        Payload: {
            'queue_id': str (UUID da fila)
        }
        Resposta: {
            'message': str,
            'ticket': {
                'id': str,
                'queue_id': str,
                'ticket_number': int,
                'qr_code': str,
                'status': str,
                'issued_at': str,
                'expires_at': str
            },
            'pdf': str (base64 do PDF)
        }
        """
        institution = Institution.query.get_or_404(institution_id)

        data = request.get_json()
        queue_id = data.get('queue_id')

        if not queue_id or not isinstance(queue_id, str):
            logger.warning(f"queue_id inválido: {queue_id}")
            return jsonify({'error': 'queue_id é obrigatório e deve ser uma string'}), 400

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.institution_id != institution_id:
            logger.warning(f"Fila {queue_id} não encontrada ou não pertence à institution_id={institution_id}")
            return jsonify({'error': 'Fila não encontrada ou não pertence à instituição'}), 404

        client_ip = request.remote_addr

        try:
            result = QueueService.generate_physical_ticket_for_totem(queue_id, client_ip)
            logger.info(f"Ticket físico gerado para queue_id={queue_id}, institution_id={institution_id}")
            return jsonify({
                'message': 'Ticket físico gerado com sucesso',
                'ticket': result['ticket'],
                'pdf': result['pdf']
            }), 201
        except ValueError as e:
            logger.error(f"Erro ao gerar ticket físico para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao gerar ticket físico para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': f'Erro ao gerar ticket: {str(e)}'}), 500

    @app.route('/api/institutions/<string:institution_id>/dashboard', methods=['GET'])
    def get_dashboard(institution_id):
        """
        Recupera os dados para o painel de chamadas de uma instituição.
        Query Params:
            - refresh: bool (se true, ignora cache)
        Resposta: {
            'queues': [
                {
                    'queue_id': str,
                    'name': str,
                    'service': str,
                    'current_call': {'ticket_number': str, 'counter': int, 'timestamp': str} | None,
                    'recent_calls': [{'ticket_number': str, 'counter': int, 'timestamp': str}, ...]
                },
                ...
            ]
        }
        """
        institution = Institution.query.get_or_404(institution_id)

        cache_key = f'dashboard:{institution_id}'
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        if not refresh:
            try:
                cached_data = app.redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para dashboard {institution_id}: {str(e)}")
                # Continuar sem cache

        data = get_dashboard_data(institution_id)
        try:
            app.redis_client.setex(cache_key, 300, json.dumps(data))  # Cache por 5 minutos
        except Exception as e:
            logger.warning(f"Erro ao salvar cache no Redis para dashboard {institution_id}: {str(e)}")
        return jsonify(data)

    @socketio.on('connect_dashboard')
    def handle_dashboard_connect(data):
        """
        Conecta o cliente ao canal WebSocket do painel.
        Payload: {'institution_id': str}
        """
        institution_id = data.get('institution_id')
        if not institution_id:
            socketio.emit('error', {'message': 'institution_id é obrigatório'}, namespace='/dashboard')
            return

        institution = Institution.query.get(institution_id)
        if not institution:
            socketio.emit('error', {'message': 'Instituição não encontrada'}, namespace='/dashboard')
            return

        pubsub = subscribe_to_dashboard(institution_id)
        try:
            for message in pubsub.listen():
                if message['type'] == 'message':
                    socketio.emit('dashboard_update', json.loads(message['data']), namespace='/dashboard')
        finally:
            pubsub.unsubscribe()
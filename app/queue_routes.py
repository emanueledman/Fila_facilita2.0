# app/queue_routes.py
from flask import jsonify, request
from . import db
from .models import Institution, Queue, Ticket
from .auth import require_auth
from .services import QueueService
import uuid
from datetime import datetime
import logging

def init_queue_routes(app):
    @app.route('/api/queues', methods=['GET'])
    def list_queues():
        institutions = Institution.query.all()
        now = datetime.now().time()
        result = []
        for inst in institutions:
            queues = Queue.query.filter_by(institution_id=inst.id).all()
            result.append({
                'institution': {
                    'id': inst.id,
                    'name': inst.name,
                    'location': inst.location,
                    'latitude': inst.latitude,
                    'longitude': inst.longitude
                },
                'queues': [{
                    'id': q.id,
                    'service': q.service,
                    'prefix': q.prefix,
                    'sector': q.sector,
                    'department': q.department,
                    'institution': q.institution_name,
                    'open_time': q.open_time.strftime('%H:%M'),
                    'daily_limit': q.daily_limit,
                    'active_tickets': q.active_tickets,
                    'status': 'Aberto' if now >= q.open_time and q.active_tickets < q.daily_limit else 'Fechado' if now < q.open_time else 'Lotado'
                } for q in queues]
            })
        return jsonify(result)

    @app.route('/api/queue/create', methods=['POST'])
    @require_auth
    def create_queue():
        data = request.get_json()
        required_fields = ['service', 'prefix', 'sector', 'department', 'institution_id', 'open_time', 'daily_limit', 'num_counters']
        if not data or not all(field in data for field in required_fields):
            return jsonify({'error': 'Campos obrigatórios: service, prefix, sector, department, institution_id, open_time, daily_limit, num_counters'}), 400
        
        institution = Institution.query.get(data['institution_id'])
        if not institution:
            return jsonify({'error': 'Instituição não encontrada'}), 404
        
        service = data['service']
        if Queue.query.filter_by(service=service, institution_id=data['institution_id']).first():
            return jsonify({'error': 'Fila para este serviço já existe nesta instituição'}), 400
        
        try:
            open_time_obj = datetime.strptime(data['open_time'], '%H:%M').time()
        except ValueError:
            return jsonify({'error': 'Formato de open_time inválido (use HH:MM)'}), 400
        
        queue = Queue(
            id=str(uuid.uuid4()),
            institution_id=data['institution_id'],
            service=service,
            prefix=data['prefix'],
            sector=data['sector'],
            department=data['department'],
            institution_name=institution.name,
            open_time=open_time_obj,
            daily_limit=data['daily_limit'],
            num_counters=data['num_counters']
        )
        db.session.add(queue)
        db.session.commit()
        return jsonify({'message': f'Fila para {service} criada', 'queue_id': queue.id}), 201

    @app.route('/api/queue/<service>/ticket', methods=['POST'])
    @require_auth
    def get_ticket(service):
        queue = Queue.query.filter_by(service=service).first()
        if not queue:
            return jsonify({'error': 'Serviço não encontrado'}), 404
        
        now = datetime.now().time()
        if now < queue.open_time:
            return jsonify({'error': f'A fila abre às {queue.open_time.strftime("%H:%M")}'}), 400
        if queue.active_tickets >= queue.daily_limit:
            return jsonify({'error': 'Limite diário atingido'}), 400
        
        user_id = request.json.get('user_id', request.user_id)  # Suporte para presencial
        is_presential = user_id == 'PRESENCIAL'
        if not is_presential:
            existing_ticket = Ticket.query.filter_by(user_id=user_id, queue_id=queue.id, status='pending').first()
            if existing_ticket:
                return jsonify({'error': 'Você já possui uma senha ativa'}), 400
        
        ticket_number = queue.active_tickets + 1
        qr_code = QueueService.generate_qr_code()
        ticket = Ticket(
            id=str(uuid.uuid4()),
            queue_id=queue.id,
            user_id=user_id,
            ticket_number=ticket_number,
            qr_code=qr_code
        )
        queue.active_tickets += 1
        db.session.add(ticket)
        db.session.commit()
        
        wait_time = QueueService.calculate_wait_time(queue.id, ticket_number)
        if not is_presential:
            QueueService.send_notification(
                user_id,
                f"Senha {queue.prefix}{ticket_number} emitida. QR: {qr_code}. Espera: {wait_time} min",
                ticket.id
            )
        
        return jsonify({
            'message': 'Senha emitida com sucesso',
            'ticket': {
                'id': ticket.id,
                'number': f"{queue.prefix}{ticket_number}",
                'qr_code': qr_code,
                'wait_time': f'{wait_time} minutos'
            }
        }), 201

    @app.route('/api/ticket/<ticket_id>', methods=['GET'])
    @require_auth
    def ticket_status(ticket_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != request.user_id and ticket.user_id != 'PRESENCIAL':
            return jsonify({'error': 'Não autorizado'}), 403
        
        queue = ticket.queue
        wait_time = QueueService.calculate_wait_time(queue.id, ticket.ticket_number)
        return jsonify({
            'service': queue.service,
            'institution': queue.institution_name,
            'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
            'qr_code': ticket.qr_code,
            'status': ticket.status,
            'counter': f"{ticket.counter:02d}" if ticket.counter else None,
            'position': max(0, ticket.ticket_number - queue.current_ticket),
            'wait_time': f'{wait_time} minutos'
        })

    @app.route('/api/ticket/trade/offer/<ticket_id>', methods=['POST'])
    @require_auth
    def offer_trade(ticket_id):
        try:
            ticket = QueueService.offer_trade(ticket_id, request.user_id)
            return jsonify({'message': 'Senha oferecida para troca', 'ticket_id': ticket.id})
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/api/ticket/trade/<ticket_to_id>', methods=['POST'])
    @require_auth
    def trade_ticket(ticket_to_id):
        ticket_from_id = request.json.get('ticket_from_id')
        try:
            result = QueueService.trade_tickets(ticket_from_id, ticket_to_id, request.user_id)
            return jsonify({'message': 'Troca realizada', 'tickets': {
                'from': {'id': result['ticket_from'].id, 'number': f"{result['ticket_from'].queue.prefix}{result['ticket_from'].ticket_number}"},
                'to': {'id': result['ticket_to'].id, 'number': f"{result['ticket_to'].queue.prefix}{result['ticket_to'].ticket_number}"}
            }})
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/api/ticket/validate', methods=['POST'])
    @require_auth
    def validate_ticket():
        qr_code = request.json.get('qr_code')
        try:
            ticket = QueueService.validate_presence(qr_code)
            return jsonify({'message': 'Presença validada', 'ticket_id': ticket.id})
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/api/queue/<service>/call', methods=['POST'])
    @require_auth
    def call_next_ticket(service):
        queue = Queue.query.filter_by(service=service).first()
        if not queue or queue.active_tickets == 0:
            return jsonify({'error': 'Fila vazia ou serviço não encontrado'}), 400
        
        queue.current_ticket += 1
        queue.active_tickets -= 1
        queue.last_counter = (queue.last_counter % queue.num_counters) + 1  # Round-robin
        ticket = Ticket.query.filter_by(queue_id=queue.id, ticket_number=queue.current_ticket).first()
        if ticket:
            ticket.status = 'called'
            ticket.counter = queue.last_counter
            if ticket.user_id != 'PRESENCIAL':
                institution = queue.institution
                # Simula a localização do usuário (em um sistema real, seria enviada pelo app)
                user_lat, user_lon = -8.8147, 13.2302  # Exemplo: Luanda Centro
                distance = QueueService.calculate_distance(user_lat, user_lon, institution)
                distance_msg = f" Você está a {distance} km do local." if distance else ""
                message = (f"É a sua vez! {institution.name}, {queue.service}. "
                          f"Senha {queue.prefix}{ticket.ticket_number}. "
                          f"Dirija-se ao guichê {ticket.counter:02d} em {institution.location}.{distance_msg}")
                QueueService.send_notification(ticket.user_id, message, ticket.id)
        db.session.commit()
        return jsonify({'message': f'Senha {queue.prefix}{queue.current_ticket} chamada', 'remaining': queue.active_tickets})

    @app.route('/api/tickets', methods=['GET'])
    @require_auth
    def list_user_tickets():
        tickets = Ticket.query.filter_by(user_id=request.user_id).all()
        return jsonify([{
            'id': t.id,
            'service': t.queue.service,
            'institution': t.queue.institution_name,
            'number': f"{t.queue.prefix}{t.ticket_number}",
            'status': t.status,
            'counter': f"{t.counter:02d}" if t.counter else None,
            'position': max(0, t.ticket_number - t.queue.current_ticket) if t.status == 'pending' else 0,
            'wait_time': f'{QueueService.calculate_wait_time(t.queue.id, t.ticket_number)} minutos' if t.status == 'pending' else 'N/A',
            'qr_code': t.qr_code,
            'trade_available': t.trade_available
        } for t in tickets])

    @app.route('/api/tickets/trade_available', methods=['GET'])
    @require_auth
    def list_trade_available_tickets():
        user_id = request.user_id
        # Busca as filas em que o usuário está (senhas pendentes)
        user_tickets = Ticket.query.filter_by(user_id=user_id, status='pending').all()
        user_queue_ids = {t.queue_id for t in user_tickets}
        
        if not user_queue_ids:
            return jsonify([])  # Usuário não está em nenhuma fila
        
        # Busca tickets disponíveis para troca nas mesmas filas, exceto os do próprio usuário
        tickets = Ticket.query.filter(
            Ticket.queue_id.in_(user_queue_ids),
            Ticket.trade_available == True,
            Ticket.status == 'pending',
            Ticket.user_id != user_id
        ).all()
        
        return jsonify([{
            'id': t.id,
            'service': t.queue.service,
            'institution': t.queue.institution_name,
            'number': f"{t.queue.prefix}{t.ticket_number}",
            'position': max(0, t.ticket_number - t.queue.current_ticket),
            'user_id': t.user_id
        } for t in tickets])

    @app.route('/api/ticket/<ticket_id>/cancel', methods=['POST'])
    @require_auth
    def cancel_ticket(ticket_id):
        try:
            ticket = QueueService.cancel_ticket(ticket_id, request.user_id)
            return jsonify({'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} cancelada', 'ticket_id': ticket.id})
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
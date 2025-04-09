# app/queue_routes.py
from flask import jsonify, request
from . import db
from .models import Queue, Ticket
from .auth import require_auth
from .services import QueueService
import uuid
from datetime import datetime
import logging

def init_queue_routes(app):
    @app.route('/api/queues', methods=['GET'])
    def list_queues():
        queues = Queue.query.all()
        now = datetime.now().time()
        return jsonify([{
            'id': q.id,
            'service': q.service,
            'sector': q.sector,
            'department': q.department,
            'institution': q.institution,
            'open_time': q.open_time.strftime('%H:%M'),
            'daily_limit': q.daily_limit,
            'active_tickets': q.active_tickets,
            'status': 'Aberto' if now >= q.open_time and q.active_tickets < q.daily_limit else 'Fechado' if now < q.open_time else 'Lotado'
        } for q in queues])

    @app.route('/api/queue/create', methods=['POST'])
    @require_auth
    def create_queue():
        data = request.get_json()
        required_fields = ['service', 'sector', 'department', 'institution', 'open_time', 'daily_limit']
        if not data or not all(field in data for field in required_fields):
            return jsonify({'error': 'Campos obrigatórios: service, sector, department, institution, open_time, daily_limit'}), 400
        
        service = data['service']
        if Queue.query.filter_by(service=service).first():
            return jsonify({'error': 'Fila para este serviço já existe'}), 400
        
        try:
            open_time_obj = datetime.strptime(data['open_time'], '%H:%M').time()
        except ValueError:
            return jsonify({'error': 'Formato de open_time inválido (use HH:MM)'}), 400
        
        queue = Queue(
            id=str(uuid.uuid4()),
            service=service,
            sector=data['sector'],
            department=data['department'],
            institution=data['institution'],
            open_time=open_time_obj,
            daily_limit=data['daily_limit']
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
        
        user_id = request.user_id
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
        QueueService.send_notification(user_id, f"Senha #{ticket_number} emitida. QR: {qr_code}. Espera: {wait_time} min")
        return jsonify({
            'message': 'Senha emitida com sucesso',
            'ticket': {
                'id': ticket.id,
                'number': ticket.ticket_number,
                'qr_code': qr_code,
                'wait_time': f'{wait_time} minutos'
            }
        }), 201

    @app.route('/api/ticket/<ticket_id>', methods=['GET'])
    @require_auth
    def ticket_status(ticket_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != request.user_id:
            return jsonify({'error': 'Não autorizado'}), 403
        
        queue = ticket.queue
        wait_time = QueueService.calculate_wait_time(queue.id, ticket.ticket_number)
        return jsonify({
            'service': queue.service,
            'ticket_number': ticket.ticket_number,
            'qr_code': ticket.qr_code,
            'status': ticket.status,
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
                'from': {'id': result['ticket_from'].id, 'number': result['ticket_from'].ticket_number},
                'to': {'id': result['ticket_to'].id, 'number': result['ticket_to'].ticket_number}
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
        ticket = Ticket.query.filter_by(queue_id=queue.id, ticket_number=queue.current_ticket).first()
        if ticket:
            ticket.status = 'called'
            QueueService.send_notification(ticket.user_id, f"Sua senha #{ticket.ticket_number} foi chamada!")
        db.session.commit()
        return jsonify({'message': f'Senha #{queue.current_ticket} chamada', 'remaining': queue.active_tickets})
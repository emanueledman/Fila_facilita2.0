from flask import jsonify, request, send_file
from . import db, socketio
from .models import Institution, Queue, Ticket
from .auth import require_auth
from .services import QueueService
from ..run import suggest_service_locations  # Importar a função de sugestão
import uuid
from datetime import datetime
import io
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_queue_routes(app):
    # Função para emitir atualização de ticket com tratamento de erro
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

    @app.route('/api/queues', methods=['GET'])
    def list_queues():
        institutions = Institution.query.all()
        now = datetime.now().time()
        result = []
        for inst in institutions:
            queues = Queue.query.filter_by(institution_id=inst.id).all()
            result.append({
                'institution': {'id': inst.id, 'name': inst.name, 'location': inst.location,
                                'latitude': inst.latitude, 'longitude': inst.longitude},
                'queues': [{
                    'id': q.id, 'service': q.service, 'prefix': q.prefix, 'sector': q.sector,
                    'department': q.department, 'institution': q.institution_name,
                    'open_time': q.open_time.strftime('%H:%M'), 'daily_limit': q.daily_limit,
                    'active_tickets': q.active_tickets,
                    'status': 'Aberto' if now >= q.open_time and q.active_tickets < q.daily_limit else 'Fechado' if now < q.open_time else 'Lotado'
                } for q in queues]
            })
        return jsonify(result)

    @app.route('/api/suggest-service', methods=['GET'])
    @require_auth
    def suggest_service():
        """
        Sugere locais onde o usuário pode encontrar um serviço.
        Parâmetros esperados na query string:
        - service (obrigatório): Nome do serviço procurado.
        - lat (opcional): Latitude do usuário.
        - lon (opcional): Longitude do usuário.
        """
        service = request.args.get('service')
        user_lat = request.args.get('lat', type=float)
        user_lon = request.args.get('lon', type=float)

        if not service:
            logger.warning("Parâmetro 'service' não fornecido na requisição de sugestão.")
            return jsonify({'error': "O parâmetro 'service' é obrigatório."}), 400

        try:
            suggestions = suggest_service_locations(service, user_lat, user_lon)
            logger.info(f"Sugestões geradas para o serviço '{service}': {len(suggestions)} resultados.")
            return jsonify(suggestions)
        except Exception as e:
            logger.error(f"Erro ao gerar sugestões para o serviço '{service}': {e}")
            return jsonify({'error': "Erro ao gerar sugestões."}), 500

    @app.route('/api/queue/create', methods=['POST'])
    @require_auth
    def create_queue():
        data = request.get_json()
        required = ['service', 'prefix', 'sector', 'department', 'institution_id', 'open_time', 'daily_limit', 'num_counters']
        if not data or not all(f in data for f in required):
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400
        
        institution = Institution.query.get(data['institution_id'])
        if not institution:
            return jsonify({'error': 'Instituição não encontrada'}), 404
        
        if Queue.query.filter_by(service=data['service'], institution_id=data['institution_id']).first():
            return jsonify({'error': 'Fila já existe'}), 400
        
        try:
            open_time = datetime.strptime(data['open_time'], '%H:%M').time()
        except ValueError:
            return jsonify({'error': 'Formato de open_time inválido (HH:MM)'}), 400
        
        queue = Queue(
            id=str(uuid.uuid4()), institution_id=data['institution_id'], service=data['service'],
            prefix=data['prefix'], sector=data['sector'], department=data['department'],
            institution_name=institution.name, open_time=open_time, daily_limit=data['daily_limit'],
            num_counters=data['num_counters']
        )
        db.session.add(queue)
        db.session.commit()
        logger.info(f"Fila criada: {queue.service} (ID: {queue.id})")
        return jsonify({'message': f'Fila {data["service"]} criada', 'queue_id': queue.id}), 201

    @app.route('/api/queue/<id>', methods=['PUT'])
    @require_auth
    def update_queue(id):
        queue = Queue.query.get_or_404(id)
        data = request.get_json()
        queue.service = data.get('service', queue.service)
        queue.prefix = data.get('prefix', queue.prefix)
        queue.sector = data.get('sector', queue.sector)
        queue.department = data.get('department', queue.department)
        queue.institution_id = data.get('institution_id', queue.institution_id)
        queue.institution_name = Institution.query.get(queue.institution_id).name
        if 'open_time' in data:
            try:
                queue.open_time = datetime.strptime(data['open_time'], '%H:%M').time()
            except ValueError:
                return jsonify({'error': 'Formato de open_time inválido (HH:MM)'}), 400
        queue.daily_limit = data.get('daily_limit', queue.daily_limit)
        queue.num_counters = data.get('num_counters', queue.num_counters)
        db.session.commit()
        logger.info(f"Fila atualizada: {queue.service} (ID: {id})")
        return jsonify({'message': 'Fila atualizada'})

    @app.route('/api/queue/<id>', methods=['DELETE'])
    @require_auth
    def delete_queue(id):
        queue = Queue.query.get_or_404(id)
        if Ticket.query.filter_by(queue_id=id, status='Pendente').first():
            logger.warning(f"Tentativa de excluir fila {id} com tickets pendentes")
            return jsonify({'error': 'Não é possível excluir: fila possui tickets pendentes'}), 400
        db.session.delete(queue)
        db.session.commit()
        logger.info(f"Fila excluída: {id}")
        return jsonify({'message': 'Fila excluída'})

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
            'institution': queue.institution_name,
            'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
            'qr_code': ticket.qr_code,
            'status': ticket.status,
            'counter': f"{ticket.counter:02d}" if ticket.counter else None,
            'position': max(0, ticket.ticket_number - queue.current_ticket),
            'wait_time': wait_time if wait_time != "N/A" else "N/A",
            'priority': ticket.priority,
            'is_physical': ticket.is_physical,
            'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None
        })

    @app.route('/api/queue/<service>/call', methods=['POST'])
    @require_auth
    def call_next_ticket(service):
        try:
            ticket = QueueService.call_next(service)
            emit_ticket_update(ticket)
            logger.info(f"Senha chamada: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket.id})")
            return jsonify({
                'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} chamada',
                'ticket_id': ticket.id,
                'remaining': ticket.queue.active_tickets
            })
        except ValueError as e:
            logger.error(f"Erro ao chamar próxima senha para serviço {service}: {str(e)}")
            return jsonify({'error': str(e)}), 400

    @app.route('/api/ticket/trade/offer/<ticket_id>', methods=['POST'])
    @require_auth
    def offer_trade(ticket_id):
        try:
            ticket = QueueService.offer_trade(ticket_id, request.user_id)
            emit_ticket_update(ticket)
            logger.info(f"Senha oferecida para troca: {ticket_id}")
            return jsonify({'message': 'Senha oferecida para troca', 'ticket_id': ticket.id})
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
            }})
        except ValueError as e:
            logger.error(f"Erro ao realizar troca entre tickets {ticket_from_id} e {ticket_to_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400

    @app.route('/api/ticket/validate', methods=['POST'])
    @require_auth
    def validate_ticket():
        qr_code = request.json.get('qr_code')
        try:
            ticket = QueueService.validate_presence(qr_code)
            emit_ticket_update(ticket)
            logger.info(f"Presença validada para ticket {ticket.id}")
            return jsonify({'message': 'Presença validada', 'ticket_id': ticket.id})
        except ValueError as e:
            logger.error(f"Erro ao validar presença com QR {qr_code}: {str(e)}")
            return jsonify({'error': str(e)}), 400

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
            'position': max(0, t.ticket_number - t.queue.current_ticket) if t.status == 'Pendente' else 0,
            'wait_time': QueueService.calculate_wait_time(t.queue.id, t.ticket_number, t.priority) if t.status == 'Pendente' else "N/A",
            'qr_code': t.qr_code,
            'trade_available': t.trade_available
        } for t in tickets])

    @app.route('/api/tickets/trade_available', methods=['GET'])
    @require_auth
    def list_trade_available_tickets():
        user_id = request.user_id
        user_tickets = Ticket.query.filter_by(user_id=user_id, status='Pendente').all()
        user_queue_ids = {t.queue_id for t in user_tickets}
        
        if not user_queue_ids:
            return jsonify([])
        
        tickets = Ticket.query.filter(
            Ticket.queue_id.in_(user_queue_ids),
            Ticket.trade_available == True,
            Ticket.status == 'Pendente',
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
            emit_ticket_update(ticket)
            logger.info(f"Senha cancelada: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket.id})")
            return jsonify({'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} cancelada', 'ticket_id': ticket.id})
        except ValueError as e:
            logger.error(f"Erro ao cancelar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400

    @app.route('/api/tickets/admin', methods=['GET'])
    @require_auth
    def list_all_tickets():
        if request.user_tipo != 'gestor':
            logger.warning(f"Tentativa não autorizada de listar tickets por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        tickets = Ticket.query.all()
        return jsonify([{
            'id': t.id,
            'service': t.queue.service,
            'institution': t.queue.institution_name,
            'number': f"{t.queue.prefix}{t.ticket_number}",
            'status': t.status,
            'counter': f"{t.counter:02d}" if t.counter else None,
            'position': max(0, t.ticket_number - t.queue.current_ticket) if t.status == 'Pendente' else 0,
            'wait_time': QueueService.calculate_wait_time(t.queue.id, t.ticket_number, t.priority) if t.status == 'Pendente' else "N/A",
            'qr_code': t.qr_code,
            'trade_available': t.trade_available,
            'user_id': t.user_id
        } for t in tickets])

    @app.route('/api/update_fcm_token', methods=['POST'])
    @require_auth
    def update_fcm_token():
        user_id = request.user_id
        data = request.get_json()
        fcm_token = data.get('fcm_token')
        
        if not fcm_token:
            logger.error(f"FCM token não fornecido por user_id={user_id}")
            return jsonify({'error': 'FCM token é obrigatório'}), 400
        
        from .models import User
        user = User.query.get(user_id)
        if not user:
            user = User(id=user_id, fcm_token=fcm_token)
            db.session.add(user)
        else:
            user.fcm_token = fcm_token
        db.session.commit()
        logger.info(f"FCM token atualizado para user_id={user_id}")
        return jsonify({'message': 'FCM token atualizado com sucesso'}), 200

    # Rota para obter a senha atual sendo atendida
    @app.route('/api/service/<institution_id>/<service>/current', methods=['GET'])
    @require_auth
    def get_currently_serving(institution_id, service):
        queue = Queue.query.filter_by(institution_id=institution_id, service=service).first()
        if not queue:
            logger.error(f"Fila não encontrada para institution_id={institution_id}, service={service}")
            return jsonify({'error': 'Fila não encontrada'}), 404
        
        current_ticket = queue.current_ticket
        if current_ticket == 0:
            return jsonify({'current_ticket': 'N/A'})
        
        return jsonify({'current_ticket': f"{queue.prefix}{current_ticket:03d}"})
from flask import jsonify, request
from . import db, socketio, redis_client
from .models import AuditLog, User, Queue, Ticket, Department, Branch, Institution
from .auth import require_auth
from .services import QueueService
import logging
import uuid
from datetime import datetime
import json
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_attendant_routes(app):
    def emit_dashboard_update(institution_id, queue_id, event_type, data):
        """Função auxiliar para emitir atualizações ao painel via WebSocket."""
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

    @app.route('/api/attendant/user', methods=['GET'])
    @require_auth
    def get_attendant_user():
        """Retorna informações do usuário atendente autenticado."""
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role != 'ATTENDANT':
            logger.warning(f"Tentativa não autorizada de acessar /api/attendant/user por user_id={request.user_id}, role={user.user_role}")
            return jsonify({'error': 'Acesso restrito a atendentes'}), 403

        try:
            response = {
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'institution_id': user.institution_id,
                'department_id': user.department_id,
                'branch_id': user.branch_id,
                'department_name': user.department.name if user.department else None,
                'branch_name': user.branch.name if user.branch else None
            }
            logger.info(f"Informações do atendente retornadas para user_id={user.id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao buscar informações do atendente para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao buscar informações do usuário'}), 500

    @app.route('/api/attendant/queues', methods=['GET'])
    @require_auth
    def get_attendant_queues():
        """Retorna as filas disponíveis para o atendente."""
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role != 'ATTENDANT':
            logger.warning(f"Tentativa não autorizada de acessar /api/attendant/queues por user_id={request.user_id}, role={user.user_role}")
            return jsonify({'error': 'Acesso restrito a atendentes'}), 403

        cache_key = f"queues:attendant:{user.id}"
        refresh = request.args.get('refresh', 'false').lower() == 'true'

        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    logger.info(f"Retornando filas do cache para user_id={user.id}")
                    return jsonify(json.loads(cached_data)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para filas do atendente {user.id}: {str(e)}")

        try:
            if not user.department_id:
                logger.warning(f"Atendente {user.id} não vinculado a departamento")
                return jsonify({'error': 'Atendente não vinculado a um departamento'}), 403

            queues = Queue.query.filter_by(department_id=user.department_id).all()
            response = [{
                'id': q.id,
                'service': q.service,
                'prefix': q.prefix,
                'active_tickets': q.active_tickets,
                'daily_limit': q.daily_limit,
                'current_ticket': q.current_ticket
            } for q in queues]

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para filas do atendente {user.id}: {str(e)}")

            logger.info(f"Listadas {len(response)} filas para atendente {user.email}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar filas para atendente user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar filas'}), 500

    @app.route('/api/attendant/tickets', methods=['GET'])
    @require_auth
    def get_attendant_tickets():
        """Retorna os tickets associados ao departamento do atendente."""
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role != 'ATTENDANT':
            logger.warning(f"Tentativa não autorizada de acessar /api/attendant/tickets por user_id={request.user_id}, role={user.user_role}")
            return jsonify({'error': 'Acesso restrito a atendentes'}), 403

        cache_key = f"tickets:attendant:{user.id}"
        refresh = request.args.get('refresh', 'false').lower() == 'true'

        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    logger.info(f"Retornando tickets do cache para user_id={user.id}")
                    return jsonify(json.loads(cached_data)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para tickets do atendente {user.id}: {str(e)}")

        try:
            if not user.department_id:
                logger.warning(f"Atendente {user.id} não vinculado a departamento")
                return jsonify({'error': 'Atendente não vinculado a um departamento'}), 403

            queues = Queue.query.filter_by(department_id=user.department_id).all()
            queue_ids = [q.id for q in queues]
            tickets = Ticket.query.filter(Ticket.queue_id.in_(queue_ids)).order_by(Ticket.issued_at.desc()).all()

            response = [{
                'id': t.id,
                'number': f"{t.queue.prefix}{t.ticket_number}",
                'service': t.queue.service,
                'status': t.status,
                'counter': f"Guichê {t.counter:02d}" if t.counter else "N/A",
                'issued_at': t.issued_at.isoformat(),
                'queue_id': t.queue_id
            } for t in tickets]

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para tickets do atendente {user.id}: {str(e)}")

            logger.info(f"Listados {len(response)} tickets para atendente {user.email}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar tickets para atendente user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar tickets'}), 500

    @app.route('/api/attendant/recent-calls', methods=['GET'])
    @require_auth
    def get_recent_calls():
        """Retorna as chamadas recentes do departamento do atendente."""
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role != 'ATTENDANT':
            logger.warning(f"Tentativa não autorizada de acessar /api/attendant/recent-calls por user_id={request.user_id}, role={user.user_role}")
            return jsonify({'error': 'Acesso restrito a atendentes'}), 403

        cache_key = f"recent-calls:attendant:{user.id}"
        refresh = request.args.get('refresh', 'false').lower() == 'true'

        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    logger.info(f"Retornando chamadas recentes do cache para user_id={user.id}")
                    return jsonify(json.loads(cached_data)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para chamadas recentes do atendente {user.id}: {str(e)}")

        try:
            if not user.department_id:
                logger.warning(f"Atendente {user.id} não vinculado a departamento")
                return jsonify({'error': 'Atendente não vinculado a um departamento'}), 403

            queues = Queue.query.filter_by(department_id=user.department_id).all()
            queue_ids = [q.id for q in queues]
            recent_calls = Ticket.query.filter(
                Ticket.queue_id.in_(queue_ids),
                Ticket.status.in_(['Chamado', 'Atendido'])
            ).order_by(Ticket.attended_at.desc()).limit(10).all()

            response = [{
                'ticket_id': t.id,
                'ticket_number': f"{t.queue.prefix}{t.ticket_number}",
                'service': t.queue.service,
                'counter': f"Guichê {t.counter:02d}" if t.counter else "N/A",
                'status': t.status,
                'called_at': t.attended_at.isoformat() if t.attended_at else t.issued_at.isoformat()
            } for t in recent_calls]

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para chamadas recentes do atendente {user.id}: {str(e)}")

            logger.info(f"Listadas {len(response)} chamadas recentes para atendente {user.email}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar chamadas recentes para atendente user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar chamadas recentes'}), 500

    @app.route('/api/ticket/validat', methods=['POST'])
    @require_auth
    def validate_ticket():
        """Valida um ticket por QR code ou código manual."""
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role != 'ATTENDANT':
            logger.warning(f"Tentativa não autorizada de validar ticket por user_id={request.user_id}, role={user.user_role}")
            return jsonify({'error': 'Acesso restrito a atendentes'}), 403

        data = request.get_json()
        if not data or 'qr_code' not in data:
            logger.warning("Campo qr_code faltando na validação de ticket")
            return jsonify({'error': 'Campo qr_code é obrigatório'}), 400

        qr_code = data['qr_code']
        if not re.match(r'^[A-Za-z0-9-]+$', qr_code):
            logger.warning(f"QR code inválido: {qr_code}")
            return jsonify({'error': 'QR code inválido'}), 400

        try:
            ticket = Ticket.query.filter_by(id=qr_code, status='Pendente').first()
            if not ticket:
                logger.warning(f"Ticket não encontrado ou não está pendente: qr_code={qr_code}")
                return jsonify({'error': 'Ticket não encontrado ou não está pendente'}), 404

            if ticket.queue.department_id != user.department_id:
                logger.warning(f"Atendente {user.id} tentou validar ticket de outro departamento: ticket_id={ticket.id}")
                return jsonify({'error': 'Ticket não pertence ao seu departamento'}), 403

            ticket.status = 'Chamado'
            ticket.attended_at = datetime.utcnow()
            ticket.counter = user.counter if hasattr(user, 'counter') else 1
            db.session.commit()

            socketio.emit('ticket_called', {
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'counter': ticket.counter,
                'queue_id': ticket.queue_id,
                'service': ticket.queue.service
            }, namespace='/', room=f"department_{ticket.queue.department_id}")

            emit_dashboard_update(
                institution_id=ticket.queue.department.institution_id,
                queue_id=ticket.queue_id,
                event_type='ticket_called',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter,
                    'timestamp': ticket.attended_at.isoformat()
                }
            )

            AuditLog.create(
                user_id=user.id,
                action='validate_ticket',
                resource_type='ticket',
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} validado por QR code no guichê {ticket.counter}"
            )

            logger.info(f"Ticket validado: {ticket.queue.prefix}{ticket.ticket_number} por atendente {user.email}")
            return jsonify({
                'message': 'Ticket validado com sucesso',
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'counter': ticket.counter
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao validar ticket com qr_code={qr_code}: {str(e)}")
            return jsonify({'error': 'Erro interno ao validar ticket'}), 500
from flask import jsonify, request
from . import db
from .models import User, Queue
from .auth import require_auth
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_admin_routes(app):
    @app.route('/api/admin/queues', methods=['GET'])
    @require_auth
    def list_admin_queues():
        if request.user_tipo != 'gestor':
            logger.warning(f"Tentativa de acesso a /api/admin/queues por usuário não administrador: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        user = User.query.get(request.user_id)
        if not user or not user.institution_id or not user.department:
            logger.warning(f"Gestor {request.user_id} não está vinculado a uma instituição ou departamento")
            return jsonify({'error': 'Gestor não vinculado a uma instituição ou departamento'}), 403

        queues = Queue.query.filter_by(
            institution_id=user.institution_id,
            department=user.department
        ).all()

        return jsonify([{
            'id': q.id,
            'service': q.service,
            'institution_name': q.institution_name,
            'active_tickets': q.active_tickets,
            'daily_limit': q.daily_limit,
            'current_ticket': q.current_ticket,
            'status': 'Aberto' if q.active_tickets < q.daily_limit else 'Lotado'
        } for q in queues])

    @app.route('/api/admin/queue/<queue_id>/call', methods=['POST'])
    @require_auth
    def admin_call_next(queue_id):
        if request.user_tipo != 'gestor':
            logger.warning(f"Tentativa de acesso a /api/admin/queue/{queue_id}/call por usuário não administrador: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        user = User.query.get(request.user_id)
        if not user or not user.institution_id or not user.department:
            logger.warning(f"Gestor {request.user_id} não está vinculado a uma instituição ou departamento")
            return jsonify({'error': 'Gestor não vinculado a uma instituição ou departamento'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila {queue_id} não encontrada")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if queue.institution_id != user.institution_id or queue.department != user.department:
            logger.warning(f"Gestor {request.user_id} tentou acessar uma fila fora de sua instituição ou departamento")
            return jsonify({'error': 'Acesso negado: fila não pertence à sua instituição ou departamento'}), 403

        from .services import QueueService
        try:
            ticket = QueueService.call_next(queue_id)
            return jsonify({
                'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} chamada',
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'counter': ticket.counter,
                'remaining': ticket.queue.active_tickets
            })
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
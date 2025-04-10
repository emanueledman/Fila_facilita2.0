from flask import jsonify, request
from . import db
from .models import User, Queue
from .auth import require_auth
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_admin_routes(app):
    @app.route('/api/admin/queues', methods=['GET'])
    @require_auth
    def list_admin_queues():
        if request.user_tipo != 'gestor':
            logger.warning(f"Tentativa de acesso a /api/admin/queues por usuário não administrador: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queues = Queue.query.all()
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

        from .services import QueueService
        try:
            ticket = QueueService.call_next(queue_id)
            return jsonify({
                'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} chamada',
                'ticket_id': ticket.id,
                'remaining': ticket.queue.active_tickets
            })
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
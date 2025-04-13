from flask import jsonify, request
from . import db
from .models import User, Queue, Ticket
from .auth import require_auth
from .services import QueueService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_admin_routes(app):
    @app.route('/api/admin/queues', methods=['GET'])
    @require_auth
    def list_admin_queues():
        """
        Lista as filas administradas pelo gestor autenticado.
        Retorna apenas as filas do departamento específico do gestor.
        """
        if request.user_tipo != 'gestor':
            logger.warning(f"Tentativa de acesso a /api/admin/queues por usuário não administrador: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        if not user.institution_id or not user.department:
            logger.warning(f"Gestor {request.user_id} não vinculado a instituição ou departamento")
            return jsonify({'error': 'Gestor não vinculado a uma instituição ou departamento'}), 403

        queues = Queue.query.filter_by(
            institution_id=user.institution_id,
            department=user.department
        ).all()

        response = [{
            'id': q.id,
            'service': q.service,
            'prefix': q.prefix,
            'institution_name': q.institution_name,
            'active_tickets': q.active_tickets,
            'daily_limit': q.daily_limit,
            'current_ticket': q.current_ticket,
            'status': 'Aberto' if q.active_tickets < q.daily_limit else 'Lotado',
            'institution_id': q.institution_id,
            'department': q.department
        } for q in queues]

        logger.info(f"Gestor {user.email} listou {len(response)} filas do departamento {user.department}: {[q['id'] for q in response]}")
        return jsonify(response), 200

    @app.route('/api/admin/queue/<queue_id>/call', methods=['POST'])
    @require_auth
    def admin_call_next(queue_id):
        """
        Chama o próximo ticket de uma fila específica, validando permissões do gestor.
        Retorna informações básicas do ticket chamado.
        """
        if request.user_tipo != 'gestor':
            logger.warning(f"Tentativa de acesso a /api/admin/queue/{queue_id}/call por usuário não administrador: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        if not user.institution_id or not user.department:
            logger.warning(f"Gestor {request.user_id} não vinculado a instituição ou departamento")
            return jsonify({'error': 'Gestor não vinculado a uma instituição ou departamento'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila {queue_id} não encontrada")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if queue.institution_id != user.institution_id or queue.department != user.department:
            logger.warning(f"Gestor {request.user_id} tentou acessar fila {queue_id} fora de seu departamento")
            return jsonify({'error': 'Acesso negado: fila não pertence ao seu departamento'}), 403

        try:
            ticket = QueueService.call_next(queue.service)
            response = {
                'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} chamada',
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'counter': ticket.counter,
                'remaining': ticket.queue.active_tickets
            }
            logger.info(f"Gestor {user.email} chamou ticket {ticket.id} da fila {queue_id}")
            return jsonify(response), 200
        except ValueError as e:
            logger.error(f"Erro ao chamar próxima senha na fila {queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400

    @app.route('/api/tickets/admin', methods=['GET'])
    @require_auth
    def list_admin_tickets():
        """
        Lista os tickets das filas do departamento do gestor autenticado, usando as filas válidas.
        """
        if request.user_tipo != 'gestor':
            logger.warning(f"Tentativa de acesso a /api/tickets/admin por usuário não administrador: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        if not user.institution_id or not user.department:
            logger.warning(f"Gestor {request.user_id} não vinculado a instituição ou departamento")
            return jsonify({'error': 'Gestor não vinculado a uma instituição ou departamento'}), 403

        # Obter as filas válidas do departamento do gestor (mesma lógica de /api/admin/queues)
        queues = Queue.query.filter_by(
            institution_id=user.institution_id,
            department=user.department
        ).all()

        if not queues:
            logger.info(f"Gestor {user.email} (departamento: {user.department}) não encontrou filas")
            return jsonify([]), 200

        queue_ids = [q.id for q in queues]
        logger.info(f"Gestor {user.email} encontrou {len(queue_ids)} filas para tickets: {queue_ids}")

        # Filtrar tickets apenas para as filas válidas
        tickets = Ticket.query.filter(
            Ticket.queue_id.in_(queue_ids)
        ).all()

        # Criar log com as senhas encontradas
        ticket_numbers = [f"{t.queue.prefix}{t.ticket_number}" for t in tickets]
        logger.info(
            f"Gestor {user.email} (departamento: {user.department}) encontrou "
            f"{len(ticket_numbers)} senhas na fila: {', '.join(ticket_numbers) if ticket_numbers else 'Nenhuma senha'}"
        )

        response = [{
            'id': t.id,
            'queue_id': t.queue_id,
            'ticket_number': f"{t.queue.prefix}{t.ticket_number}",
            'number': f"{t.queue.prefix}{t.ticket_number}",
            'service': t.queue.service,
            'status': t.status,
            'wait_time': QueueService.calculate_wait_time(t.queue_id, t.ticket_number, t.priority) or 'N/A',
            'counter': f"{t.counter:02d}" if t.counter is not None else 'N/A',
            'issued_at': t.issued_at.isoformat()
        } for t in tickets]

        return jsonify(response), 200
from flask import jsonify, request
from . import db
from .models import User, Queue
from .auth import require_auth
from .services import QueueService
import jwt
import os
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_admin_routes(app):
    @app.route('/api/admin/login', methods=['POST'])
    def admin_login():
        """
        Autentica um gestor com email e senha, retornando um JWT.
        """
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            logger.warning("Requisição de login sem email ou senha")
            return jsonify({'error': 'Email e senha são obrigatórios'}), 400

        user = User.query.filter_by(email=email, user_tipo='gestor').first()
        if not user or not user.check_password(password):
            logger.warning(f"Tentativa de login inválida para email: {email}")
            return jsonify({'error': 'Credenciais inválidas'}), 401

        token = jwt.encode({
            'user_id': user.id,
            'user_tipo': user.user_tipo,
            'email': user.email,
            'exp': datetime.utcnow() + timedelta(hours=1)
        }, os.getenv('JWT_SECRET_KEY', '974655'), algorithm='HS256')

        logger.info(f"Gestor autenticado: {email}")
        return jsonify({
            'message': 'Login bem-sucedido',
            'token': token,
            'user_id': user.id,
            'email': user.email
        }), 200

    @app.route('/api/admin/queues', methods=['GET'])
    @require_auth
    def list_admin_queues():
        """
        Lista as filas administradas pelo gestor autenticado.
        Retorna apenas as filas da instituição e departamento do gestor.
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
            'prefix': q.prefix,  # Incluído para frontend
            'institution_name': q.institution_name,
            'active_tickets': q.active_tickets,
            'daily_limit': q.daily_limit,
            'current_ticket': q.current_ticket,
            'status': 'Aberto' if q.active_tickets < q.daily_limit else 'Lotado'
        } for q in queues]

        logger.info(f"Gestor {request.user_id} listou {len(response)} filas")
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
            logger.warning(f"Gestor {request.user_id} tentou acessar fila {queue_id} fora de sua instituição ou departamento")
            return jsonify({'error': 'Acesso negado: fila não pertence à sua instituição ou departamento'}), 403

        try:
            ticket = QueueService.call_next(queue.service)  # Usar service para compatibilidade com QueueService
            response = {
                'message': f'Senha {ticket.queue.prefix}{ticket.ticket_number} chamada',
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'counter': ticket.counter,
                'remaining': ticket.queue.active_tickets
            }
            logger.info(f"Gestor {request.user_id} chamou ticket {ticket.id} da fila {queue_id}")
            return jsonify(response), 200
        except ValueError as e:
            logger.error(f"Erro ao chamar próxima senha na fila {queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
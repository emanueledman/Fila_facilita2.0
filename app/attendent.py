from flask import jsonify, request
from . import db, socketio, redis_client
from .models import AuditLog, User, Queue, Ticket, Department, Branch, Institution, UserRole, AttendantQueue
from .auth import require_auth
from .services import QueueService
from .queue_reco import emit_ticket_update  # Importar a função
import logging
import uuid
from datetime import datetime
import json
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Função movida para o nível do módulo
def emit_dashboard_update(institution_id, queue_id, event_type, data):
    """Emite atualizações ao painel via WebSocket."""
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

def init_attendant_routes(app):
    @app.route('/api/attendant/user', methods=['GET'])
    @require_auth
    def get_attendant_user():
        """Retorna informações do usuário atendente autenticado."""
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role != UserRole.ATTENDANT:
            logger.warning(f"Tentativa não autorizada de acessar /api/attendant/user por user_id={request.user_id}, role={user.user_role}")
            return jsonify({'error': 'Acesso restrito a atendentes'}), 403

        try:
            response = {
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'institution_id': user.institution_id,
                'branch_id': user.branch_id,
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
        """Retorna as filas atribuídas ao atendente."""
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role != UserRole.ATTENDANT:
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
            # Buscar filas atribuídas ao atendente via AttendantQueue
            queues = user.queues.all()
            if not queues:
                logger.warning(f"Atendente {user.id} não vinculado a nenhuma fila")
                return jsonify({'error': 'Atendente não vinculado a nenhuma fila'}), 403

            response = [{
                'id': q.id,
                'service': q.service.name if q.service else 'N/A',
                'prefix': q.prefix,
                'active_tickets': q.active_tickets,
                'daily_limit': q.daily_limit,
                'current_ticket': q.current_ticket,
                'department_name': q.department.name if q.department else 'N/A'
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
        """Retorna os tickets das filas atribuídas ao atendente, filtrando por status Pendente e Chamado."""
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role != UserRole.ATTENDANT:
            logger.warning(f"Tentativa não autorizada de acessar /api/attendant/tickets por user_id={request.user_id}, role={user.user_role}")
            return jsonify({'error': 'Acesso restrito a atendentes'}), 403

        cache_key = f"tickets:attendant:{user.id}"
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        queue_id = request.args.get('queue_id')
        status = request.args.get('status', 'pending,called').split(',')

        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    logger.info(f"Retornando tickets do cache para user_id={user.id}")
                    return jsonify(json.loads(cached_data)), 200
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para tickets do atendente {user.id}: {str(e)}")

        try:
            # Buscar filas atribuídas ao atendente
            query = AttendantQueue.query.filter_by(user_id=user.id)
            if queue_id:
                query = query.filter_by(queue_id=queue_id)
            queue_ids = [aq.queue_id for aq in query.all()]
            if not queue_ids:
                logger.warning(f"Atendente {user.id} não vinculado a nenhuma fila")
                return jsonify({'error': 'Atendente não vinculado a nenhuma fila'}), 403

            # Filtrar tickets por status
            ticket_query = Ticket.query.filter(
                Ticket.queue_id.in_(queue_ids),
                Ticket.status.in_(status)
            ).order_by(Ticket.issued_at.asc())
            tickets = ticket_query.all()

            response = [{
                'id': t.id,
                'number': f"{t.queue.prefix}{t.ticket_number}",
                'service': t.queue.service.name if t.queue.service else 'N/A',
                'status': t.status,
                'counter': f"Guichê {t.counter:02d}" if t.counter else "N/A",
                'issued_at': t.issued_at.isoformat(),
                'queue_id': t.queue_id,
                'department_name': t.queue.department.name if t.queue.department else 'N/A'
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
        """Retorna as chamadas recentes das filas atribuídas ao atendente."""
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role != UserRole.ATTENDANT:
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
            # Buscar filas atribuídas ao atendente
            queue_ids = [q.id for q in user.queues.all()]
            if not queue_ids:
                logger.warning(f"Atendente {user.id} não vinculado a nenhuma fila")
                return jsonify({'error': 'Atendente não vinculado a nenhuma fila'}), 403

            recent_calls = Ticket.query.filter(
                Ticket.queue_id.in_(queue_ids),
                Ticket.status.in_(['Chamado', 'Atendido'])
            ).order_by(Ticket.attended_at.desc()).limit(10).all()

            response = [{
                'ticket_id': t.id,
                'ticket_number': f"{t.queue.prefix}{t.ticket_number}",
                'service': t.queue.service.name if t.queue.service else 'N/A',
                'counter': f"Guichê {t.counter:02d}" if t.counter else 'N/A',
                'status': t.status,
                'called_at': t.attended_at.isoformat() if t.attended_at else t.issued_at.isoformat(),
                'department_name': t.queue.department.name if t.queue.department else 'N/A'
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

    @app.route('/api/attendant/assign-queue', methods=['POST'])
    @require_auth
    def assign_queue():
        """Atribui uma fila a um atendente."""
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role not in [UserRole.SYSTEM_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.BRANCH_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar /api/attendant/assign-queue por user_id={request.user_id}, role={user.user_role}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        data = request.get_json()
        attendant_id = data.get('attendant_id')
        queue_id = data.get('queue_id')

        if not attendant_id or not queue_id:
            return jsonify({'error': 'attendant_id e queue_id são obrigatórios'}), 400

        attendant = User.query.get(attendant_id)
        if not attendant or attendant.user_role != UserRole.ATTENDANT:
            return jsonify({'error': 'Atendente inválido'}), 400

        queue = Queue.query.get(queue_id)
        if not queue:
            return jsonify({'error': 'Fila inválida'}), 400

        try:
            # Verificar se a associação já existe
            existing = AttendantQueue.query.filter_by(user_id=attendant_id, queue_id=queue_id).first()
            if existing:
                return jsonify({'message': 'Fila já atribuída ao atendente'}), 200

            # Criar nova associação
            association = AttendantQueue(user_id=attendant_id, queue_id=queue_id)
            db.session.add(association)
            db.session.commit()

            logger.info(f"Fila {queue_id} atribuída ao atendente {attendant_id}")
            return jsonify({'message': 'Fila atribuída com sucesso'}), 200
        except Exception as e:
            logger.error(f"Erro ao atribuir fila {queue_id} ao atendente {attendant_id}: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Erro interno ao atribuir fila'}), 500

    @app.route('/api/attendant/call-next', methods=['POST'])
    @require_auth
    def call_next_ticket():
        """Chama o próximo ticket de uma fila para o atendente."""
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role != UserRole.ATTENDANT:
            logger.warning(f"Tentativa não autorizada de acessar /api/attendant/call-next por user_id={request.user_id}, role={user.user_role}")
            return jsonify({'error': 'Acesso restrito a atendentes'}), 403

        data = request.get_json() or {}
        queue_id = data.get('queue_id')
        counter = data.get('counter', 1)  # Guichê padrão como 1

        if not queue_id:
            logger.warning("queue_id é obrigatório")
            return jsonify({'error': 'queue_id é obrigatório'}), 400

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        # Verificar se o atendente está associado à fila
        attendant_queue = AttendantQueue.query.filter_by(user_id=user.id, queue_id=queue_id).first()
        if not attendant_queue:
            logger.warning(f"Atendente {user.id} não vinculado à fila {queue_id}")
            return jsonify({'error': 'Atendente não vinculado a esta fila'}), 403

        try:
            # Chamar o próximo ticket usando QueueService
            ticket = QueueService.call_next(queue.service.name, branch_id=queue.department.branch_id)
            if not ticket:
                logger.info(f"Nenhum ticket pendente para chamar na fila {queue_id}")
                return jsonify({'message': 'Nenhum ticket pendente para chamar'}), 200

            # Notificar usuário
            emit_ticket_update(ticket)

            # Emitir evento para dashboard
            socketio.emit('ticket_called', {
                'id': ticket.id,
                'number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'service': ticket.queue.service.name if ticket.queue.service else 'N/A',
                'counter': ticket.counter,
                'avg_wait_time': ticket.queue.estimated_wait_time,
                'department_name': ticket.queue.department.name if ticket.queue.department else 'N/A'
            }, namespace='/dashboard')

            emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue_id,
                event_type='ticket_called',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter,
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            # Invalidar cache
            cache_key = f"tickets:attendant:{user.id}"
            try:
                redis_client.delete(cache_key)
                logger.info(f"Cache invalidado para {cache_key}")
            except Exception as e:
                logger.warning(f"Erro ao invalidar cache Redis: {e}")

            AuditLog.create(
                user_id=user.id,
                action="call_ticket",
                resource_type="ticket",
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} chamado no guichê {ticket.counter}"
            )

            logger.info(f"Ticket chamado: {ticket.queue.prefix}{ticket.ticket_number} no guichê {ticket.counter} (queue_id={queue_id})")
            return jsonify({
                'id': ticket.id,
                'number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'service': ticket.queue.service.name if ticket.queue.service else 'N/A',
                'counter': ticket.counter,
                'avg_wait_time': ticket.queue.estimated_wait_time,
                'department_name': ticket.queue.department.name if ticket.queue.department else 'N/A'
            }), 200
        except ValueError as e:
            logger.error(f"Erro ao chamar próximo ticket na fila {queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao chamar próximo ticket na fila {queue_id}: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Erro interno ao chamar ticket'}), 500

    @app.route('/api/attendant/complete', methods=['POST'])
    @require_auth
    def complete_attendant_ticket():
        """Marca um ticket como atendido pelo atendente."""
        user_id = request.user_id
        user = User.query.get(user_id)
        if not user:
            logger.error(f"Usuário não encontrado: user_id={user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role != UserRole.ATTENDANT:
            logger.warning(f"Tentativa não autorizada de completar ticket por user_id={user_id}, role={user.user_role}")
            return jsonify({'error': 'Acesso restrito a atendentes'}), 403

        data = request.get_json() or {}
        ticket_id = data.get('ticket_id')
        if not ticket_id:
            logger.warning("ticket_id é obrigatório")
            return jsonify({'error': 'ticket_id é obrigatório'}), 400

        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            logger.warning(f"Ticket não encontrado: ticket_id={ticket_id}")
            return jsonify({'error': 'Ticket não encontrado'}), 404

        # Verificar se o atendente está associado à fila do ticket
        attendant_queue = AttendantQueue.query.filter_by(user_id=user_id, queue_id=ticket.queue_id).first()
        if not attendant_queue:
            logger.warning(f"Atendente {user_id} não vinculado à fila {ticket.queue_id}")
            return jsonify({'error': 'Atendente não vinculado a esta fila'}), 403

        try:
            ticket = QueueService.complete_ticket(ticket_id, user_id=user_id)
            emit_ticket_update(ticket)  # Notificar usuário
            emit_dashboard_update(
                institution_id=ticket.queue.department.branch.institution_id,
                queue_id=ticket.queue.id,
                event_type='ticket_completed',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            # Invalidar cache
            cache_key = f"tickets:attendant:{user_id}"
            try:
                redis_client.delete(cache_key)
                logger.info(f"Cache invalidado para {cache_key}")
            except Exception as e:
                logger.warning(f"Erro ao invalidar cache Redis: {e}")

            AuditLog.create(
                user_id=user_id,
                action="complete_ticket",
                resource_type="ticket",
                resource_id=ticket_id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} marcado como atendido por atendente"
            )

            logger.info(f"Ticket completado: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket_id}) por atendente {user_id}")
            return jsonify({
                'message': 'Ticket marcado como atendido',
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}"
            }), 200
        except ValueError as e:
            logger.error(f"Erro ao completar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro inesperado ao completar ticket {ticket_id}: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Erro interno ao completar ticket'}), 500

    @app.route('/api/attendant/unassign-queue', methods=['POST'])
    @require_auth
    def unassign_queue():
        """Remove a atribuição de uma fila de um atendente."""
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        if user.user_role not in [UserRole.SYSTEM_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.BRANCH_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar /api/attendant/unassign-queue por user_id={request.user_id}, role={user.user_role}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        data = request.get_json()
        attendant_id = data.get('attendant_id')
        queue_id = data.get('queue_id')

        if not attendant_id or not queue_id:
            return jsonify({'error': 'attendant_id e queue_id são obrigatórios'}), 400

        attendant = User.query.get(attendant_id)
        if not attendant or attendant.user_role != UserRole.ATTENDANT:
            return jsonify({'error': 'Atendente inválido'}), 400

        queue = Queue.query.get(queue_id)
        if not queue:
            return jsonify({'error': 'Fila inválida'}), 400

        try:
            # Verificar se a associação existe
            association = AttendantQueue.query.filter_by(user_id=attendant_id, queue_id=queue_id).first()
            if not association:
                return jsonify({'message': 'Fila não está atribuída ao atendente'}), 200

            # Remover a associação
            db.session.delete(association)
            db.session.commit()

            logger.info(f"Fila {queue_id} removida do atendente {attendant_id}")
            return jsonify({'message': 'Fila removida com sucesso'}), 200
        except Exception as e:
            logger.error(f"Erro ao remover fila {queue_id} do atendente {attendant_id}: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Erro interno ao remover fila'}), 500
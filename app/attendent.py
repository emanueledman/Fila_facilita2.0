from flask import jsonify, request
from flask_socketio import emit

from app.utils.websocket_utils import emit_ticket_update
from . import db, socketio, redis_client
from .models import AuditLog, User, Queue, Ticket, Department, Branch, Institution, UserRole, AttendantQueue
from .auth import require_auth
from .services import QueueService
from sqlalchemy.orm import joinedload
import logging
import uuid
from datetime import datetime
import json
from firebase_admin import auth
from sqlalchemy.exc import SQLAlchemyError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def emit_dashboard_event(event_name, data, institution_id, queue_id):
    """Emite eventos para o dashboard via WebSocket."""
    try:
        socketio.emit(event_name, data, room=str(institution_id), namespace='/dashboard')
        logger.info(f"Evento {event_name} emitido para institution_id={institution_id}, queue_id={queue_id}")
    except Exception as e:
        logger.error(f"Erro ao emitir evento {event_name}: {str(e)}")

def init_attendant_routes(app):
    @app.route('/api/attendant/user', methods=['GET'])
    @require_auth
    def get_attendant_user():
        """Retorna informações do usuário atendente autenticado."""
        try:
            user = User.query.get(request.user_id)
            if not user:
                logger.error(f"Usuário não encontrado: user_id={request.user_id}")
                return jsonify({'error': 'Usuário não encontrado'}), 404
            if user.user_role != UserRole.ATTENDANT:
                logger.warning(f"Tentativa não autorizada: user_id={request.user_id}, role={user.user_role}")
                return jsonify({'error': 'Acesso restrito a atendentes'}), 403

            response = {
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'institution_id': user.institution_id,
                'branch_id': user.branch_id,
                'branch_name': user.branch.name if user.branch else None
            }
            logger.info(f"Informações retornadas para user_id={user.id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao buscar informações: user_id={request.user_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao buscar informações do usuário'}), 500

    @app.route('/api/attendant/queues', methods=['GET'])
    @require_auth
    def get_attendant_queues():
        """Retorna as filas atribuídas ao atendente."""
        try:
            user = User.query.get(request.user_id)
            if not user:
                logger.error(f"Usuário não encontrado: user_id={request.user_id}")
                return jsonify({'error': 'Usuário não encontrado'}), 404
            if user.user_role != UserRole.ATTENDANT:
                logger.warning(f"Tentativa não autorizada: user_id={request.user_id}, role={user.user_role}")
                return jsonify({'error': 'Acesso restrito a atendentes'}), 403

            cache_key = f"queues:attendant:{user.id}"
            refresh = request.args.get('refresh', 'false').lower() == 'true'

            if not refresh:
                try:
                    cached_data = redis_client.get(cache_key)
                    if cached_data:
                        logger.info(f"Retornando filas do cache: user_id={user.id}")
                        return jsonify(json.loads(cached_data)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar Redis: user_id={user.id}: {str(e)}")

            queues = user.queues.options(joinedload(Queue.service), joinedload(Queue.department)).all()
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
                logger.warning(f"Erro ao salvar cache: user_id={user.id}: {str(e)}")

            logger.info(f"Listadas {len(response)} filas para atendente {user.email}")
            return jsonify(response), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro de banco de dados ao listar filas: user_id={request.user_id}: {str(e)}")
            return jsonify({'error': 'Erro de banco de dados ao listar filas'}), 503
        except Exception as e:
            logger.error(f"Erro ao listar filas: user_id={request.user_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar filas'}), 500

    @app.route('/api/attendant/tickets', methods=['GET'])
    @require_auth
    def get_attendant_tickets():
        """Retorna os tickets das filas atribuídas ao atendente."""
        try:
            user = User.query.get(request.user_id)
            if not user:
                logger.error(f"Usuário não encontrado: user_id={request.user_id}")
                return jsonify({'error': 'Usuário não encontrado'}), 404
            if user.user_role != UserRole.ATTENDANT:
                logger.warning(f"Tentativa não autorizada: user_id={request.user_id}, role={user.user_role}")
                return jsonify({'error': 'Acesso restrito a atendentes'}), 403

            cache_key = f"tickets:attendant:{user.id}"
            refresh = request.args.get('refresh', 'false').lower() == 'true'
            queue_id = request.args.get('queue_id')
            status = request.args.get('status', 'pending,called').split(',')

            if not refresh:
                try:
                    cached_data = redis_client.get(cache_key)
                    if cached_data:
                        logger.info(f"Retornando tickets do cache: user_id={user.id}")
                        return jsonify(json.loads(cached_data)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar Redis: user_id={user.id}: {str(e)}")

            query = AttendantQueue.query.filter_by(user_id=user.id)
            if queue_id:
                query = query.filter_by(queue_id=queue_id)
            queue_ids = [aq.queue_id for aq in query.all()]
            if not queue_ids:
                logger.warning(f"Atendente {user.id} não vinculado a nenhuma fila")
                return jsonify({'error': 'Atendente não vinculado a nenhuma fila'}), 403

            ticket_query = Ticket.query.filter(
                Ticket.queue_id.in_(queue_ids),
                Ticket.status.in_(status)
            ).options(joinedload(Ticket.queue).joinedload(Queue.department)).order_by(Ticket.issued_at.asc())
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
                logger.warning(f"Erro ao salvar cache: user_id={user.id}: {str(e)}")

            logger.info(f"Listados {len(response)} tickets para atendente {user.email}")
            return jsonify(response), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro de banco de dados ao listar tickets: user_id={request.user_id}: {str(e)}")
            return jsonify({'error': 'Erro de banco de dados ao listar tickets'}), 503
        except Exception as e:
            logger.error(f"Erro ao listar tickets: user_id={request.user_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar tickets'}), 500

    @app.route('/api/attendant/recent-calls', methods=['GET'])
    @require_auth
    def get_recent_calls():
        """Retorna as chamadas recentes das filas atribuídas ao atendente."""
        try:
            user = User.query.get(request.user_id)
            if not user:
                logger.error(f"Usuário não encontrado: user_id={request.user_id}")
                return jsonify({'error': 'Usuário não encontrado'}), 404
            if user.user_role != UserRole.ATTENDANT:
                logger.warning(f"Tentativa não autorizada: user_id={request.user_id}, role={user.user_role}")
                return jsonify({'error': 'Acesso restrito a atendentes'}), 403

            cache_key = f"recent-calls:attendant:{user.id}"
            refresh = request.args.get('refresh', 'false').lower() == 'true'

            if not refresh:
                try:
                    cached_data = redis_client.get(cache_key)
                    if cached_data:
                        logger.info(f"Retornando chamadas recentes do cache: user_id={user.id}")
                        return jsonify(json.loads(cached_data)), 200
                except Exception as e:
                    logger.warning(f"Erro ao acessar Redis: user_id={user.id}: {str(e)}")

            queue_ids = [q.id for q in user.queues.all()]
            if not queue_ids:
                logger.warning(f"Atendente {user.id} não vinculado a nenhuma fila")
                return jsonify({'error': 'Atendente não vinculado a nenhuma fila'}), 403

            recent_calls = Ticket.query.filter(
                Ticket.queue_id.in_(queue_ids),
                Ticket.status.in_(['Chamado', 'Atendido'])
            ).options(joinedload(Ticket.queue).joinedload(Queue.department)).order_by(Ticket.attended_at.desc()).limit(10).all()

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
                logger.warning(f"Erro ao salvar cache: user_id={user.id}: {str(e)}")

            logger.info(f"Listadas {len(response)} chamadas recentes para atendente {user.email}")
            return jsonify(response), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro de banco de dados ao listar chamadas recentes: user_id={request.user_id}: {str(e)}")
            return jsonify({'error': 'Erro de banco de dados ao listar chamadas recentes'}), 503
        except Exception as e:
            logger.error(f"Erro ao listar chamadas recentes: user_id={request.user_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar chamadas recentes'}), 500

    @app.route('/api/attendant/assign-queue', methods=['POST'])
    @require_auth
    def assign_queue():
        """Atribui uma fila a um atendente."""
        try:
            user = User.query.get(request.user_id)
            if not user:
                logger.error(f"Usuário não encontrado: user_id={request.user_id}")
                return jsonify({'error': 'Usuário não encontrado'}), 404
            if user.user_role not in [UserRole.SYSTEM_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.BRANCH_ADMIN]:
                logger.warning(f"Tentativa não autorizada: user_id={request.user_id}, role={user.user_role}")
                return jsonify({'error': 'Acesso restrito a administradores'}), 403

            data = request.get_json()
            if not data or 'attendant_id' not in data or 'queue_id' not in data:
                logger.warning("attendant_id e queue_id são obrigatórios")
                return jsonify({'error': 'attendant_id e queue_id são obrigatórios'}), 400

            attendant_id = data['attendant_id']
            queue_id = data['queue_id']

            attendant = User.query.get(attendant_id)
            if not attendant or attendant.user_role != UserRole.ATTENDANT:
                logger.warning(f"Atendente inválido: attendant_id={attendant_id}")
                return jsonify({'error': 'Atendente inválido'}), 400

            queue = Queue.query.get(queue_id)
            if not queue:
                logger.warning(f"Fila inválida: queue_id={queue_id}")
                return jsonify({'error': 'Fila inválida'}), 400

            existing = AttendantQueue.query.filter_by(user_id=attendant_id, queue_id=queue_id).first()
            if existing:
                logger.info(f"Fila {queue_id} já atribuída ao atendente {attendant_id}")
                return jsonify({'message': 'Fila já atribuída ao atendente'}), 200

            association = AttendantQueue(user_id=attendant_id, queue_id=queue_id)
            db.session.add(association)
            db.session.commit()

            logger.info(f"Fila {queue_id} atribuída ao atendente {attendant_id}")
            return jsonify({'message': 'Fila atribuída com sucesso'}), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro de banco de dados ao atribuir fila: attendant_id={attendant_id}, queue_id={queue_id}: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Erro de banco de dados ao atribuir fila'}), 503
        except Exception as e:
            logger.error(f"Erro ao atribuir fila: attendant_id={attendant_id}, queue_id={queue_id}: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Erro interno ao atribuir fila'}), 500

    @app.route('/api/attendant/call-next', methods=['POST'])
    @require_auth
    def call_next_tickett():
        """Chama o próximo ticket de uma fila para o atendente."""
        try:
            user = User.query.get(request.user_id)
            if not user:
                logger.error(f"Usuário não encontrado: user_id={request.user_id}")
                return jsonify({'error': 'Usuário não encontrado'}), 404
            if user.user_role != UserRole.ATTENDANT:
                logger.warning(f"Tentativa não autorizada: user_id={request.user_id}, role={user.user_role}")
                return jsonify({'error': 'Acesso restrito a atendentes'}), 403

            data = request.get_json() or {}
            queue_id = data.get('queue_id')
            counter = data.get('counter', 1)

            if not queue_id:
                logger.warning("queue_id é obrigatório")
                return jsonify({'error': 'queue_id é obrigatório'}), 400

            queue = Queue.query.get(queue_id)
            if not queue:
                logger.warning(f"Fila não encontrada: queue_id={queue_id}")
                return jsonify({'error': 'Fila não encontrada'}), 404

            attendant_queue = AttendantQueue.query.filter_by(user_id=user.id, queue_id=queue_id).first()
            if not attendant_queue:
                logger.warning(f"Atendente {user.id} não vinculado à fila {queue_id}")
                return jsonify({'error': 'Atendente não vinculado a esta fila'}), 403

            ticket = QueueService.call_next(queue.service.name, branch_id=queue.department.branch_id)
            if not ticket:
                logger.info(f"Nenhum ticket pendente para chamar: queue_id={queue_id}")
                return jsonify({'message': 'Nenhum ticket pendente para chamar'}), 200

            emit_ticket_update(ticket)
            emit_dashboard_event('ticket_called', {
                'id': ticket.id,
                'number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'service': ticket.queue.service.name if ticket.queue.service else 'N/A',
                'counter': ticket.counter,
                'avg_wait_time': ticket.queue.estimated_wait_time,
                'department_name': ticket.queue.department.name if ticket.queue.department else 'N/A'
            }, queue.department.branch.institution_id, queue_id)

            cache_key = f"tickets:attendant:{user.id}"
            try:
                redis_client.delete(cache_key)
                logger.info(f"Cache invalidado: {cache_key}")
            except Exception as e:
                logger.warning(f"Erro ao invalidar cache: {e}")

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
            logger.error(f"Erro ao chamar próximo ticket: queue_id={queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except SQLAlchemyError as e:
            logger.error(f"Erro de banco de dados ao chamar ticket: queue_id={queue_id}: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Erro de banco de dados ao chamar ticket'}), 503
        except Exception as e:
            logger.error(f"Erro inesperado ao chamar ticket: queue_id={queue_id}: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Erro interno ao chamar ticket'}), 500

    @app.route('/api/attendant/complete', methods=['POST'])
    @require_auth
    def complete_attendant_ticket():
        """Marca um ticket como atendido pelo atendente."""
        try:
            user_id = request.user_id
            user = User.query.get(user_id)
            if not user:
                logger.error(f"Usuário não encontrado: user_id={user_id}")
                return jsonify({'error': 'Usuário não encontrado'}), 404
            if user.user_role != UserRole.ATTENDANT:
                logger.warning(f"Tentativa não autorizada: user_id={user_id}, role={user.user_role}")
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

            attendant_queue = AttendantQueue.query.filter_by(user_id=user_id, queue_id=ticket.queue_id).first()
            if not attendant_queue:
                logger.warning(f"Atendente {user_id} não vinculado à fila {ticket.queue_id}")
                return jsonify({'error': 'Atendente não vinculado a esta fila'}), 403

            ticket = QueueService.complete_ticket(ticket_id, user_id=user_id)
            emit_ticket_update(ticket)
            emit_dashboard_event('ticket_completed', {
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'timestamp': datetime.utcnow().isoformat()
            }, ticket.queue.department.branch.institution_id, ticket.queue.id)

            cache_key = f"tickets:attendant:{user_id}"
            try:
                redis_client.delete(cache_key)
                logger.info(f"Cache invalidado: {cache_key}")
            except Exception as e:
                logger.warning(f"Erro ao invalidar cache: {e}")

            AuditLog.create(
                user_id=user_id,
                action="complete_ticket",
                resource_type="ticket",
                resource_id=ticket_id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} marcado como atendido"
            )

            logger.info(f"Ticket completado: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket_id}) por atendente {user_id}")
            return jsonify({
                'message': 'Ticket marcado como atendido',
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}"
            }), 200
        except ValueError as e:
            logger.error(f"Erro ao completar ticket: ticket_id={ticket_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except SQLAlchemyError as e:
            logger.error(f"Erro de banco de dados ao completar ticket: ticket_id={ticket_id}: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Erro de banco de dados ao completar ticket'}), 503
        except Exception as e:
            logger.error(f"Erro inesperado ao completar ticket: ticket_id={ticket_id}: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Erro interno ao completar ticket'}), 500

    @app.route('/api/attendant/unassign-queue', methods=['POST'])
    @require_auth
    def unassign_queue():
        """Remove a atribuição de uma fila de um atendente."""
        try:
            user = User.query.get(request.user_id)
            if not user:
                logger.error(f"Usuário não encontrado: user_id={request.user_id}")
                return jsonify({'error': 'Usuário não encontrado'}), 404
            if user.user_role not in [UserRole.SYSTEM_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.BRANCH_ADMIN]:
                logger.warning(f"Tentativa não autorizada: user_id={request.user_id}, role={user.user_role}")
                return jsonify({'error': 'Acesso restrito a administradores'}), 403

            data = request.get_json()
            if not data or 'attendant_id' not in data or 'queue_id' not in data:
                logger.warning("attendant_id e queue_id são obrigatórios")
                return jsonify({'error': 'attendant_id e queue_id são obrigatórios'}), 400

            attendant_id = data['attendant_id']
            queue_id = data['queue_id']

            attendant = User.query.get(attendant_id)
            if not attendant or attendant.user_role != UserRole.ATTENDANT:
                logger.warning(f"Atendente inválido: attendant_id={attendant_id}")
                return jsonify({'error': 'Atendente inválido'}), 400

            queue = Queue.query.get(queue_id)
            if not queue:
                logger.warning(f"Fila inválida: queue_id={queue_id}")
                return jsonify({'error': 'Fila inválida'}), 400

            association = AttendantQueue.query.filter_by(user_id=attendant_id, queue_id=queue_id).first()
            if not association:
                logger.info(f"Fila {queue_id} não está atribuída ao atendente {attendant_id}")
                return jsonify({'message': 'Fila não está atribuída ao atendente'}), 200

            db.session.delete(association)
            db.session.commit()

            logger.info(f"Fila {queue_id} removida do atendente {attendant_id}")
            return jsonify({'message': 'Fila removida com sucesso'}), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro de banco de dados ao remover fila: attendant_id={attendant_id}, queue_id={queue_id}: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Erro de banco de dados ao remover fila'}), 503
        except Exception as e:
            logger.error(f"Erro ao remover fila: attendant_id={attendant_id}, queue_id={queue_id}: {str(e)}")
            db.session.rollback()
            return jsonify({'error': 'Erro interno ao remover fila'}), 500

    @app.route('/api/attendant/recall', methods=['POST'])
    @require_auth
    def recall_ticket():
        """Rechama um ticket previamente chamado."""
        try:
            user = User.query.get(request.user_id)
            if not user:
                logger.error(f"Usuário não encontrado: user_id={request.user_id}")
                return jsonify({'error': 'Usuário não encontrado'}), 404
            if user.user_role != UserRole.ATTENDANT:
                logger.warning(f"Tentativa não autorizada: user_id={request.user_id}, role={user.user_role}")
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

            if ticket.status != 'Chamado':
                logger.warning(f"Ticket não está no status Chamado: ticket_id={ticket_id}, status={ticket.status}")
                return jsonify({'error': 'Ticket não está no status Chamado'}), 400

            attendant_queue = AttendantQueue.query.filter_by(user_id=user.id, queue_id=ticket.queue_id).first()
            if not attendant_queue:
                logger.warning(f"Atendente {user.id} não vinculado à fila {ticket.queue_id}")
                return jsonify({'error': 'Atendente não vinculado a esta fila'}), 403

            emit_ticket_update(ticket)
            emit_dashboard_event('ticket_recalled', {
                'id': ticket.id,
                'number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'service': ticket.queue.service.name if ticket.queue.service else 'N/A',
                'counter': ticket.counter,
                'avg_wait_time': ticket.queue.estimated_wait_time,
                'department_name': ticket.queue.department.name if ticket.queue.department else 'N/A'
            }, ticket.queue.department.branch.institution_id, ticket.queue_id)

            AuditLog.create(
                user_id=user.id,
                action="recall_ticket",
                resource_type="ticket",
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} rechamado no guichê {ticket.counter}"
            )

            logger.info(f"Ticket rechamado: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket_id})")
            return jsonify({
                'message': 'Ticket rechamado com sucesso',
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}"
            }), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro de banco de dados ao rechamar ticket: ticket_id={ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro de banco de dados ao rechamar ticket'}), 503
        except Exception as e:
            logger.error(f"Erro ao rechamar ticket: ticket_id={ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao rechamar ticket'}), 500
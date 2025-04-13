from flask import jsonify, request
from . import db
from .models import User, Queue, Ticket, Department
from .auth import require_auth
from .services import QueueService
import logging
from datetime import datetime, timedelta
from sqlalchemy import func

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_admin_routes(app):
    @app.route('/api/admin/queues', methods=['GET'])
    @require_auth
    def list_admin_queues():
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        if not user.is_department_admin:
            logger.warning(f"Tentativa de acesso a /api/admin/queues por usuário não administrador: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        if not user.department_id:
            logger.warning(f"Gestor {request.user_id} não vinculado a departamento")
            return jsonify({'error': 'Gestor não vinculado a um departamento'}), 403

        queues = Queue.query.filter_by(department_id=user.department_id).all()

        response = [{
            'id': q.id,
            'service': q.service,
            'prefix': q.prefix,
            'institution_name': q.department.institution.name if q.department and q.department.institution else 'N/A',
            'active_tickets': q.active_tickets,
            'daily_limit': q.daily_limit,
            'current_ticket': q.current_ticket,
            'status': 'Aberto' if q.active_tickets < q.daily_limit else 'Lotado',
            'institution_id': q.department.institution_id if q.department else None,
            'department': q.department.name if q.department else 'N/A'
        } for q in queues]

        logger.info(f"Gestor {user.email} listou {len(response)} filas do departamento {user.department.name if user.department else 'N/A'}: {[q['id'] for q in response]}")
        return jsonify(response), 200

    @app.route('/api/admin/queue/<queue_id>/call', methods=['POST'])
    @require_auth
    def admin_call_next(queue_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        if not user.is_department_admin:
            logger.warning(f"Tentativa de acesso a /api/admin/queue/{queue_id}/call por usuário não administrador: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        if not user.department_id:
            logger.warning(f"Gestor {request.user_id} não vinculado a departamento")
            return jsonify({'error': 'Gestor não vinculado a um departamento'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila {queue_id} não encontrada")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if queue.department_id != user.department_id:
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
            socketio.emit('notification', {
                'message': f"Senha {ticket.queue.prefix}{ticket.ticket_number} chamada no guichê {ticket.counter:02d}",
                'department_id': queue.department_id
            }, namespace='/', room=f"department_{queue.department_id}")
            logger.info(f"Gestor {user.email} chamou ticket {ticket.id} da fila {queue_id}")
            return jsonify(response), 200
        except ValueError as e:
            logger.error(f"Erro ao chamar próxima senha na fila {queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        
    @app.route('/api/tickets/admin', methods=['GET'])
    @require_auth
    def list_admin_tickets():
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        if not user.is_department_admin:
            logger.warning(f"Tentativa de acesso a /api/tickets/admin por usuário não administrador: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        if not user.department_id:
            logger.warning(f"Gestor {request.user_id} não vinculado a departamento")
            return jsonify({'error': 'Gestor não vinculado a um departamento'}), 403

        queues = Queue.query.filter_by(department_id=user.department_id).all()
        
        if not queues:
            logger.info(f"Nenhuma fila encontrada para o gestor {user.email} no departamento {user.department.name if user.department else 'N/A'}")
            return jsonify([]), 200
        
        queue_ids = [queue.id for queue in queues]
        
        tickets = Ticket.query.filter(Ticket.queue_id.in_(queue_ids)).order_by(
            Ticket.status.asc(),
            Ticket.issued_at.desc()
        ).limit(50).all()
        
        response = []
        for ticket in tickets:
            queue = Queue.query.get(ticket.queue_id)
            ticket_data = {
                'id': ticket.id,
                'number': f"{queue.prefix}{ticket.ticket_number}" if queue else ticket.ticket_number,
                'queue_id': ticket.queue_id,
                'service': queue.service if queue else 'N/A',
                'status': ticket.status,
                'issued_at': ticket.issued_at.isoformat() if ticket.issued_at else None,
                'attended_at': ticket.attended_at.isoformat() if ticket.attended_at else None,
                'counter': ticket.counter,
                'user_id': ticket.user_id
            }
            response.append(ticket_data)
        
        logger.info(f"Gestor {user.email} listou {len(response)} tickets de seu departamento '{user.department.name if user.department else 'N/A'}")
        return jsonify(response), 200

    @app.route('/api/admin/report', methods=['GET'])
    @require_auth
    def admin_report():
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        if not user.is_department_admin:
            logger.warning(f"Tentativa de acesso a /api/admin/report por usuário não administrador: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        if not user.department_id:
            logger.warning(f"Gestor {request.user_id} não vinculado a departamento")
            return jsonify({'error': 'Gestor não vinculado a um departamento'}), 403

        date_str = request.args.get('date')
        try:
            report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            logger.warning(f"Data inválida fornecida para relatório: {date_str}")
            return jsonify({'error': 'Data inválida. Use o formato AAAA-MM-DD'}), 400

        queues = Queue.query.filter_by(department_id=user.department_id).all()
        queue_ids = [q.id for q in queues]

        start_time = datetime.combine(report_date, datetime.min.time())
        end_time = start_time + timedelta(days=1)

        report = []
        for queue in queues:
            tickets = Ticket.query.filter(
                Ticket.queue_id == queue.id,
                Ticket.issued_at >= start_time,
                Ticket.issued_at < end_time
            ).all()

            issued = len(tickets)
            attended = len([t for t in tickets if t.status == 'attended'])
            service_times = [
                (t.attended_at - t.issued_at).total_seconds() / 60.0
                for t in tickets
                if t.status == 'attended' and t.attended_at and t.issued_at
            ]
            avg_time = sum(service_times) / len(service_times) if service_times else None

            report.append({
                'service': queue.service,
                'issued': issued,
                'attended': attended,
                'avg_time': avg_time,
            })

        logger.info(f"Relatório gerado para {user.email} em {date_str}: {len(report)} serviços")
        return jsonify(report), 200
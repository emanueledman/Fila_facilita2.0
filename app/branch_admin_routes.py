import io
from flask import jsonify, request, send_file
from sqlalchemy import and_, String, func
from sqlalchemy.orm import joinedload
from . import db, socketio, redis_client
from .models import AuditLog, User, Queue, Ticket, Branch, UserRole, Department, BranchSchedule, AttendantQueue, DisplayQueue, InstitutionService
from .auth import require_auth
from .services import QueueService
from sqlalchemy.exc import SQLAlchemyError
import logging
import json
import re
from flask import jsonify, request
from sqlalchemy import desc
from datetime import datetime
from flask_socketio import emit
from .utils.websocket_utils import emit_dashboard_update, emit_display_update

import uuid
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_branch_admin_routes(app):

    def emit_ticket_update(ticket):
        try:
            branch_id = ticket.queue.department.branch_id
            data = {
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'queue_id': ticket.queue_id,
                'counter': f"Guichê {ticket.counter:02d}" if ticket.counter else 'N/A',
                'status': ticket.status,
                'service_name': ticket.queue.service.name if ticket.queue.service else 'N/A'
            }
            socketio.emit('ticket_updated', data, room=f'branch_{branch_id}', namespace='/branch_admin')
            emit_display_update(branch_id, 'ticket_updated', data)
            logger.info(f"Ticket atualizado: ticket_id={ticket.id}, status={ticket.status}")
        except Exception as e:
            logger.error(f"Erro ao emitir atualização de ticket: {str(e)}")

    # Perfil do Administrador
    @app.route('/api/branch_admin/profile', methods=['GET'])
    @require_auth
    def get_branch_admin_profile():
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN:
            logger.warning(f"Tentativa não autorizada de acessar perfil por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        try:
            response = {
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'branch_id': user.branch_id,
                'branch_name': user.branch.name if user.branch else 'N/A',
                'notification_enabled': user.notification_enabled,
                'notification_preferences': user.notification_preferences or {}
            }
            logger.info(f"Perfil retornado para user_id={user.id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao buscar perfil para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro ao buscar perfil'}), 500

    @app.route('/api/branch_admin/profile', methods=['PUT'])
    @require_auth
    def update_branch_admin_profile():
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN:
            logger.warning(f"Tentativa não autorizada de atualizar perfil por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        data = request.get_json()
        if not data:
            logger.warning("Nenhum dado fornecido para atualização de perfil")
            return jsonify({'error': 'Nenhum dado fornecido'}), 400

        try:
            if 'email' in data:
                if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', data['email']):
                    return jsonify({'error': 'Email inválido'}), 400
                if User.query.filter_by(email=data['email']).filter(User.id != user.id).first():
                    return jsonify({'error': 'Email já está em uso'}), 400
                user.email = data['email']

            if 'name' in data:
                if not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', data['name']):
                    return jsonify({'error': 'Nome inválido'}), 400
                user.name = data['name']

            if 'password' in data:
                if len(data['password']) < 8:
                    return jsonify({'error': 'A senha deve ter pelo menos 8 caracteres'}), 400
                if 'current_password' not in data or not user.check_password(data['current_password']):
                    return jsonify({'error': 'Senha atual incorreta'}), 400
                user.set_password(data['password'])

            if 'notification_enabled' in data:
                if not isinstance(data['notification_enabled'], bool):
                    return jsonify({'error': 'O campo notification_enabled deve ser um booleano'}), 400
                user.notification_enabled = data['notification_enabled']

            if 'notification_preferences' in data:
                user.notification_preferences = data['notification_preferences']

            db.session.commit()
            socketio.emit('profile_updated', {
                'user_id': user.id,
                'email': user.email,
                'name': user.name
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='update_profile',
                resource_type='user',
                resource_id=user.id,
                details=f"Perfil atualizado por {user.email}"
            )
            logger.info(f"Perfil atualizado por user_id={user.id}")
            return jsonify({'message': 'Perfil atualizado com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar perfil para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro ao atualizar perfil'}), 500

    # Listar Departamentos
    @app.route('/api/branch_admin/branches/<branch_id>/departments', methods=['GET'])
    @require_auth
    def list_branch_departments(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de listar departamentos por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        cache_key = f'departments:{branch_id}'
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para departamentos {branch_id}: {str(e)}")

        try:
            departments = Department.query.filter_by(branch_id=branch_id).all()
            response = [{
                'id': d.id,
                'name': d.name,
                'description': d.description
            } for d in departments]

            try:
                redis_client.setex(cache_key, 3600, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para departamentos {branch_id}: {str(e)}")

            logger.info(f"Departamentos listados por user_id={user.id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar departamentos: {str(e)}")
            return jsonify({'error': 'Erro ao listar departamentos'}), 500

    # Criar Departamento
    @app.route('/api/branch_admin/branches/<branch_id>/departments', methods=['POST'])
    @require_auth
    def create_branch_department(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de criar departamento por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        data = request.get_json()
        if not data or 'name' not in data:
            logger.warning("Campo name faltando na criação de departamento")
            return jsonify({'error': 'Campo obrigatório faltando: name'}), 400

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        try:
            department = Department(
                id=str(uuid.uuid4()),
                branch_id=branch_id,
                name=data['name'],
                description=data.get('description')
            )
            db.session.add(department)
            db.session.commit()

            redis_client.delete(f"cache:departments:{branch_id}")
            AuditLog.create(
                user_id=user.id,
                action='create_department',
                resource_type='department',
                resource_id=department.id,
                details=f"Departamento {department.name} criado por {user.email}"
            )
            logger.info(f"Departamento {department.name} criado por user_id={user.id}")
            return jsonify({
                'id': department.id,
                'name': department.name,
                'description': department.description
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao criar departamento: {str(e)}")
            return jsonify({'error': 'Erro ao criar departamento'}), 500

    # Listar Filas
    @app.route('/api/branch_admin/branches/<branch_id>/queues', methods=['GET'])
    @require_auth
    def list_branch_queues(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de listar filas por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        cache_key = f'queues:{branch_id}'
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para filas {branch_id}: {str(e)}")

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            queues = Queue.query.filter(Queue.department_id.in_(department_ids)).options(
                joinedload(Queue.department), joinedload(Queue.service)
            ).all()

            now = datetime.now()
            current_weekday = now.strftime('%A').upper()
            current_time = now.time()
            # Correção: Usar BranchSchedule.query para filtrar o horário
            schedule = BranchSchedule.query.filter_by(branch_id=branch_id, weekday=current_weekday).first()

            response = []
            for q in queues:
                is_open = False
                is_paused = q.daily_limit == 0
                if schedule and not schedule.is_closed:
                    is_open = (
                        schedule.open_time and schedule.end_time and
                        current_time >= schedule.open_time and
                        current_time <= schedule.end_time and
                        q.active_tickets < q.daily_limit
                    )
                status = 'Pausado' if is_paused else (
                    'Aberto' if is_open else ('Lotado' if q.active_tickets >= q.daily_limit else 'Fechado')
                )

                response.append({
                    'id': q.id,
                    'department_id': q.department_id,
                    'department_name': q.department.name if q.department else 'N/A',
                    'service_id': q.service_id,
                    'service_name': q.service.name if q.service else 'N/A',
                    'prefix': q.prefix,
                    'daily_limit': q.daily_limit,
                    'active_tickets': q.active_tickets,
                    'current_ticket': q.current_ticket,
                    'num_counters': q.num_counters,
                    'status': status,
                    'avg_wait_time': round(q.avg_wait_time, 2) if q.avg_wait_time else None,
                    'estimated_wait_time': round(q.estimated_wait_time, 2) if q.estimated_wait_time else None
                })

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para filas {branch_id}: {str(e)}")

            logger.info(f"Filas listadas por user_id={user.id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar filas: {str(e)}")
            return jsonify({'error': 'Erro ao listar filas'}), 500
        
    # Listar Tickets
    @app.route('/api/branch_admin/branches/<branch_id>/tickets', methods=['GET'])
    @require_auth
    def list_branch_tickets(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de listar tickets por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        status = request.args.get('status')
        queue_id = request.args.get('queue_id')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        refresh = request.args.get('refresh', 'false').lower() == 'true'

        cache_key = f'tickets:{branch_id}:{status}:{queue_id}:{page}:{per_page}'
        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para tickets {branch_id}: {str(e)}")

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            query = Ticket.query.filter(
                Ticket.queue_id.in_([q.id for q in Queue.query.filter(Queue.department_id.in_(department_ids)).all()])
            ).options(joinedload(Ticket.queue).joinedload(Queue.department))

            if status:
                query = query.filter(Ticket.status == status)
            if queue_id:
                query = query.filter(Ticket.queue_id == queue_id)

            tickets = query.order_by(Ticket.issued_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
            response = {
                'tickets': [{
                    'id': t.id,
                    'queue_id': t.queue_id,
                    'queue_prefix': t.queue.prefix if t.queue else 'N/A',
                    'ticket_number': t.ticket_number,
                    'status': t.status,
                    'priority': t.priority,
                    'is_physical': t.is_physical,
                    'issued_at': t.issued_at.isoformat() if t.issued_at else None,
                    'attended_at': t.attended_at.isoformat() if t.attended_at else None,
                    'counter': t.counter,
                    'service_time': t.service_time
                } for t in tickets.items],
                'total': tickets.total,
                'pages': tickets.pages,
                'page': page
            }

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para tickets {branch_id}: {str(e)}")

            logger.info(f"Tickets listados por user_id={user.id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar tickets: {str(e)}")
            return jsonify({'error': 'Erro ao listar tickets'}), 500

    # Cancelar Ticket
    @app.route('/api/branch_admin/branches/<branch_id>/tickets/<ticket_id>/cancel', methods=['POST'])
    @require_auth
    def cancel_branch_ticket(branch_id, ticket_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de cancelar ticket por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        ticket = Ticket.query.get(ticket_id)
        if not ticket or ticket.queue.department.branch_id != branch_id:
            logger.warning(f"Ticket {ticket_id} não encontrado")
            return jsonify({'error': 'Ticket não encontrado'}), 404

        if ticket.status != 'Pendente':
            logger.warning(f"Ticket {ticket_id} não está pendente")
            return jsonify({'error': 'Apenas tickets pendentes podem ser cancelados'}), 400

        try:
            ticket.status = 'Cancelado'
            ticket.cancelled_at = datetime.utcnow()
            ticket.queue.active_tickets -= 1
            db.session.commit()

            socketio.emit('ticket_cancelled', {
                'ticket_id': ticket.id,
                'queue_id': ticket.queue_id,
                'branch_id': branch_id
            }, namespace='/branch_admin')
            emit_display_update(branch_id, 'ticket_cancelled', {
                'ticket_id': ticket.id,
                'queue_id': ticket.queue_id
            })
            redis_client.delete(f"cache:tickets:{branch_id}")
            AuditLog.create(
                user_id=user.id,
                action='cancel_ticket',
                resource_type='ticket',
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} cancelado por {user.email}"
            )
            logger.info(f"Ticket {ticket_id} cancelado por user_id={user.id}")
            return jsonify({'message': 'Ticket cancelado com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao cancelar ticket: {str(e)}")
            return jsonify({'error': 'Erro ao cancelar ticket'}), 500

    # Listar Atendentes
    @app.route('/api/branch_admin/branches/<branch_id>/attendants', methods=['GET'])
    @require_auth
    def list_branch_attendants(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de listar atendentes por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        cache_key = f'attendants:{branch_id}'
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para atendentes {branch_id}: {str(e)}")

        try:
            attendants = User.query.filter_by(branch_id=branch_id, user_role=UserRole.ATTENDANT, active=True).all()
            response = [{
                'id': a.id,
                'name': a.name,
                'email': a.email,
                'queues': [q.prefix for q in a.queues.all()]
            } for a in attendants]

            try:
                redis_client.setex(cache_key, 3600, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para atendentes {branch_id}: {str(e)}")

            logger.info(f"Atendentes listados por user_id={user.id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar atendentes: {str(e)}")
            return jsonify({'error': 'Erro ao listar atendentes'}), 500

    # Configurar Horários da Filial
    @app.route('/api/branch_admin/branches/<branch_id>/schedules', methods=['POST'])
    @require_auth
    def configure_branch_schedule(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de configurar horários por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        data = request.get_json()
        required_fields = ['weekday', 'is_closed']
        if not data or not all(field in data for field in required_fields):
            logger.warning("Campos obrigatórios faltando na configuração de horário")
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        try:
            schedule = BranchSchedule.query.filter_by(branch_id=branch_id, weekday=data['weekday']).first()
            if not schedule:
                schedule = BranchSchedule(
                    id=str(uuid.uuid4()),
                    branch_id=branch_id,
                    weekday=data['weekday']
                )
                db.session.add(schedule)

            schedule.is_closed = data['is_closed']
            if not data['is_closed']:
                if 'open_time' not in data or 'end_time' not in data:
                    logger.warning("Campos open_time e end_time obrigatórios para horário aberto")
                    return jsonify({'error': 'Campos open_time e end_time obrigatórios'}), 400
                schedule.open_time = datetime.strptime(data['open_time'], '%H:%M:%S').time()
                schedule.end_time = datetime.strptime(data['end_time'], '%H:%M:%S').time()

            db.session.commit()
            redis_client.delete(f"cache:schedules:{branch_id}")
            AuditLog.create(
                user_id=user.id,
                action='configure_schedule',
                resource_type='branch_schedule',
                resource_id=schedule.id,
                details=f"Horário {schedule.weekday} configurado por {user.email}"
            )
            logger.info(f"Horário configurado por user_id={user.id}")
            return jsonify({
                'id': schedule.id,
                'weekday': schedule.weekday,
                'is_closed': schedule.is_closed,
                'open_time': schedule.open_time.strftime('%H:%M:%S') if schedule.open_time else None,
                'end_time': schedule.end_time.strftime('%H:%M:%S') if schedule.end_time else None
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao configurar horário: {str(e)}")
            return jsonify({'error': 'Erro ao configurar horário'}), 500

    # Exportar Relatório
    @app.route('/api/branch_admin/branches/<branch_id>/report/export', methods=['GET'])
    @require_auth
    def export_branch_report(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de exportar relatório por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            query = Ticket.query.filter(
                Ticket.queue_id.in_([q.id for q in Queue.query.filter(Queue.department_id.in_(department_ids)).all()])
            ).options(joinedload(Ticket.queue).joinedload(Queue.department))

            if start_date:
                query = query.filter(Ticket.issued_at >= datetime.strptime(start_date, '%Y-%m-%d'))
            if end_date:
                query = query.filter(Ticket.issued_at <= datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))

            tickets = query.all()
            report = [{
                'ticket_id': t.id,
                'queue_prefix': t.queue.prefix if t.queue else 'N/A',
                'ticket_number': t.ticket_number,
                'status': t.status,
                'issued_at': t.issued_at.isoformat() if t.issued_at else None,
                'attended_at': t.attended_at.isoformat() if t.attended_at else None,
                'service_time': t.service_time
            } for t in tickets]

            logger.info(f"Relatório exportado por user_id={user.id}")
            return jsonify({'report': report}), 200
        except Exception as e:
            logger.error(f"Erro ao exportar relatório: {str(e)}")
            return jsonify({'error': 'Erro ao exportar relatório'}), 500


    # Rechamar Ticket
    @app.route('/api/branch_admin/branches/<branch_id>/tickets/<ticket_id>/recall', methods=['POST'])
    @require_auth
    def recall_branch_ticket(branch_id, ticket_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de rechamar ticket por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        ticket = Ticket.query.get(ticket_id)
        if not ticket or ticket.queue.department.branch_id != branch_id:
            logger.warning(f"Ticket {ticket_id} não encontrado ou não pertence à filial {branch_id}")
            return jsonify({'error': 'Ticket não encontrado ou não pertence à filial'}), 404

        if ticket.status != 'Chamado':
            logger.warning(f"Ticket {ticket_id} não está no status Chamado")
            return jsonify({'error': 'Apenas tickets no status Chamado podem ser rechamados'}), 400

        try:
            emit_ticket_update(ticket)
            emit_dashboard_update(branch_id, ticket.queue_id, 'ticket_recalled', {
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'service': ticket.queue.service.name if ticket.queue.service else 'N/A',
                'counter': ticket.counter,
                'department_name': ticket.queue.department.name if ticket.queue.department else 'N/A'
            })

            AuditLog.create(
                user_id=user.id,
                action='recall_ticket',
                resource_type='ticket',
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} rechamado no guichê {ticket.counter} por admin"
            )
            redis_client.delete(f"cache:tickets:{branch_id}")
            logger.info(f"Ticket {ticket.queue.prefix}{ticket.ticket_number} rechamado por user_id={user.id}")
            return jsonify({
                'message': 'Ticket rechamado com sucesso',
                'ticket': {
                    'id': ticket.id,
                    'number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter
                }
            }), 200
        except Exception as e:
            logger.error(f"Erro ao rechamar ticket: {str(e)}")
            return jsonify({'error': 'Erro ao rechamar ticket'}), 500

    # Busca Avançada de Filas
    @app.route('/api/branch_admin/branches/<branch_id>/queues/search', methods=['GET'])
    @require_auth
    def search_branch_queues(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de buscar filas por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        department_id = request.args.get('department_id')
        service_id = request.args.get('service_id')
        status = request.args.get('status')
        sort_by = request.args.get('sort_by', 'prefix')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        refresh = request.args.get('refresh', 'false').lower() == 'true'

        cache_key = f'queues_search:{branch_id}:{department_id}:{service_id}:{status}:{sort_by}:{page}:{per_page}'
        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para busca de filas {branch_id}: {str(e)}")

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            query = Queue.query.filter(Queue.department_id.in_(department_ids)).options(
                joinedload(Queue.department), joinedload(Queue.service)
            )

            if department_id:
                query = query.filter(Queue.department_id == department_id)
            if service_id:
                query = query.filter(Queue.service_id == service_id)

            now = datetime.now()
            current_weekday = now.strftime('%A').upper()
            current_time = now.time()
            queues = query.all()
            response_queues = []

            for q in queues:
                schedule = BranchSchedule.query.filter_by(branch_id=branch_id, weekday=current_weekday).first()
                is_open = False
                is_paused = q.daily_limit == 0
                if schedule and not schedule.is_closed:
                    is_open = (
                        schedule.open_time and schedule.end_time and
                        current_time >= schedule.open_time and
                        current_time <= schedule.end_time and
                        q.active_tickets < q.daily_limit
                    )
                queue_status = 'Pausado' if is_paused else (
                    'Aberto' if is_open else ('Lotado' if q.active_tickets >= q.daily_limit else 'Fechado')
                )

                if status and queue_status != status:
                    continue

                response_queues.append({
                    'id': q.id,
                    'department_id': q.department_id,
                    'department_name': q.department.name if q.department else 'N/A',
                    'service_id': q.service_id,
                    'service_name': q.service.name if q.service else 'N/A',
                    'prefix': q.prefix,
                    'daily_limit': q.daily_limit,
                    'active_tickets': q.active_tickets,
                    'current_ticket': q.current_ticket,
                    'num_counters': q.num_counters,
                    'status': queue_status,
                    'avg_wait_time': round(q.avg_wait_time, 2) if q.avg_wait_time else None,
                    'estimated_wait_time': round(q.estimated_wait_time, 2) if q.estimated_wait_time else None
                })

            if sort_by == 'active_tickets':
                response_queues.sort(key=lambda x: x['active_tickets'], reverse=True)
            elif sort_by == 'estimated_wait_time':
                response_queues.sort(key=lambda x: x['estimated_wait_time'] or float('inf'))
            else:
                response_queues.sort(key=lambda x: x['prefix'])

            total = len(response_queues)
            start = (page - 1) * per_page
            end = start + per_page
            paginated_queues = response_queues[start:end]

            response = {
                'queues': paginated_queues,
                'total': total,
                'pages': (total + per_page - 1) // per_page,
                'page': page
            }

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para busca de filas {branch_id}: {str(e)}")

            logger.info(f"Admin {user.email} buscou {len(paginated_queues)} filas da filial {branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao buscar filas para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro ao buscar filas'}), 500

    # Busca Avançada de Tickets
    @app.route('/api/branch_admin/branches/<branch_id>/tickets/search', methods=['GET'])
    @require_auth
    def search_branch_tickets(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de buscar tickets por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        status = request.args.get('status')
        queue_id = request.args.get('queue_id')
        priority = request.args.get('priority')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        ticket_number = request.args.get('ticket_number')
        qr_code = request.args.get('qr_code')
        attendant_id = request.args.get('attendant_id')
        group_by = request.args.get('group_by')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        refresh = request.args.get('refresh', 'false').lower() == 'true'

        cache_key = f'tickets_search:{branch_id}:{status}:{queue_id}:{priority}:{start_date}:{end_date}:{ticket_number}:{qr_code}:{attendant_id}:{group_by}:{page}:{per_page}'
        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para busca de tickets {branch_id}: {str(e)}")

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            query = Ticket.query.filter(
                Ticket.queue_id.in_([q.id for q in Queue.query.filter(Queue.department_id.in_(department_ids)).all()])
            ).options(joinedload(Ticket.queue).joinedload(Queue.department))

            if status:
                query = query.filter(Ticket.status == status)
            if queue_id:
                query = query.filter(Ticket.queue_id == queue_id)
            if priority:
                query = query.filter(Ticket.priority == int(priority))
            if start_date:
                query = query.filter(Ticket.issued_at >= datetime.strptime(start_date, '%Y-%m-%d'))
            if end_date:
                query = query.filter(Ticket.issued_at <= datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1))
            if ticket_number:
                query = query.join(Queue).filter(
                    (Queue.prefix + Ticket.ticket_number.cast(String)).ilike(f'%{ticket_number}%')
                )
            if qr_code:
                query = query.filter(Ticket.qr_code.ilike(f'%{qr_code}%'))
            if attendant_id:
                query = query.join(AttendantQueue, Ticket.queue_id == AttendantQueue.queue_id).filter(
                    AttendantQueue.user_id == attendant_id
                )

            if group_by:
                tickets = query.all()
                grouped_response = {}
                for t in tickets:
                    key = t.queue_id if group_by == 'queue' else t.queue.department_id
                    if key not in grouped_response:
                        grouped_response[key] = {
                            'id': key,
                            'name': (t.queue.prefix if group_by == 'queue' else t.queue.department.name),
                            'tickets': []
                        }
                    grouped_response[key]['tickets'].append({
                        'id': t.id,
                        'ticket_number': f"{t.queue.prefix}{t.ticket_number}",
                        'status': t.status,
                        'priority': t.priority,
                        'issued_at': t.issued_at.isoformat() if t.issued_at else None,
                        'attended_at': t.attended_at.isoformat() if t.attended_at else None,
                        'counter': t.counter
                    })
                response = {
                    'groups': list(grouped_response.values()),
                    'total': len(tickets),
                    'pages': 1,
                    'page': 1
                }
            else:
                tickets = query.order_by(Ticket.issued_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
                response = {
                    'tickets': [{
                        'id': t.id,
                        'queue_id': t.queue_id,
                        'queue_prefix': t.queue.prefix if t.queue else 'N/A',
                        'ticket_number': t.ticket_number,
                        'status': t.status,
                        'priority': t.priority,
                        'is_physical': t.is_physical,
                        'issued_at': t.issued_at.isoformat() if t.issued_at else None,
                        'attended_at': t.attended_at.isoformat() if t.attended_at else None,
                        'counter': t.counter,
                        'service_time': t.service_time
                    } for t in tickets.items],
                    'total': tickets.total,
                    'pages': tickets.pages,
                    'page': page
                }

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para busca de tickets {branch_id}: {str(e)}")

            logger.info(f"Admin {user.email} buscou {response['total']} tickets da filial {branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao buscar tickets para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro ao buscar tickets'}), 500

    # Visão Consolidada
    @app.route('/api/branch_admin/branches/<branch_id>/overview', methods=['GET'])
    @require_auth
    def branch_overview(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de acessar visão geral por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        department_id = request.args.get('department_id')
        service_id = request.args.get('service_id')
        refresh = request.args.get('refresh', 'false').lower() == 'true'

        cache_key = f'overview:{branch_id}:{department_id}:{service_id}'
        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para visão geral {branch_id}: {str(e)}")

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            query = Queue.query.filter(Queue.department_id.in_(department_ids)).options(
                joinedload(Queue.department), joinedload(Queue.service)
            )
            if department_id:
                query = query.filter(Queue.department_id == department_id)
            if service_id:
                query = query.filter(Queue.service_id == service_id)

            queues = query.all()
            queue_ids = [q.id for q in queues]
            now = datetime.now()
            current_weekday = now.strftime('%A').upper()
            current_time = now.time()

            queue_status = []
            for q in queues:
                schedule = BranchSchedule.query.filter_by(branch_id=branch_id, weekday=current_weekday).first()
                is_open = False
                is_paused = q.daily_limit == 0
                if schedule and not schedule.is_closed:
                    is_open = (
                        schedule.open_time and schedule.end_time and
                        current_time >= schedule.open_time and
                        current_time <= schedule.end_time and
                        q.active_tickets < q.daily_limit
                    )
                queue_status.append({
                    'queue_id': q.id,
                    'service_name': q.service.name if q.service else 'N/A',
                    'department_name': q.department.name if q.department else 'N/A',
                    'prefix': q.prefix,
                    'active_tickets': q.active_tickets,
                    'status': 'Pausado' if is_paused else (
                        'Aberto' if is_open else ('Lotado' if q.active_tickets >= q.daily_limit else 'Fechado')
                    ),
                    'estimated_wait_time': round(q.estimated_wait_time, 2) if q.estimated_wait_time else None
                })

            ticket_stats = {
                'pending': Ticket.query.filter(Ticket.queue_id.in_(queue_ids), Ticket.status == 'Pendente').count(),
                'called': Ticket.query.filter(Ticket.queue_id.in_(queue_ids), Ticket.status == 'Chamado').count(),
                'attended': Ticket.query.filter(Ticket.queue_id.in_(queue_ids), Ticket.status == 'Atendido').count(),
                'cancelled': Ticket.query.filter(Ticket.queue_id.in_(queue_ids), Ticket.status == 'Cancelado').count()
            }

            attendants = User.query.filter_by(
                branch_id=branch_id, user_role=UserRole.ATTENDANT, active=True
            ).all()
            attendants_data = [{
                'attendant_id': a.id,
                'name': a.name,
                'queues': [q.prefix for q in a.queues.all()]
            } for a in attendants]

            response = {
                'branch_id': branch_id,
                'branch_name': branch.name,
                'queues': queue_status,
                'ticket_stats': ticket_stats,
                'attendants': attendants_data
            }

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para visão geral {branch_id}: {str(e)}")

            logger.info(f"Visão geral retornada para {user.email} na filial {branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao gerar visão geral para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro ao gerar visão geral'}), 500

    # Cancelamento em Massa de Tickets
    @app.route('/api/branch_admin/branches/<branch_id>/tickets/bulk-cancel', methods=['POST'])
    @require_auth
    def bulk_cancel_tickets(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de cancelar tickets em massa por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        data = request.get_json() or {}
        queue_id = data.get('queue_id')
        reason = data.get('reason', 'Cancelamento em massa pelo administrador')

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            query = Ticket.query.filter(
                Ticket.queue_id.in_([q.id for q in Queue.query.filter(Queue.department_id.in_(department_ids)).all()]),
                Ticket.status == 'Pendente'
            )
            if queue_id:
                queue = Queue.query.get(queue_id)
                if not queue or queue.department.branch_id != branch_id:
                    logger.warning(f"Fila {queue_id} não encontrada ou não pertence à filial {branch_id}")
                    return jsonify({'error': 'Fila não encontrada ou não pertence à filial'}), 404
                query = query.filter(Ticket.queue_id == queue_id)

            tickets = query.all()
            if not tickets:
                logger.info(f"Nenhum ticket pendente para cancelar na filial {branch_id}")
                return jsonify({'message': 'Nenhum ticket pendente para cancelar'}), 200

            cancelled_count = 0
            for ticket in tickets:
                ticket.status = 'Cancelado'
                ticket.cancelled_at = datetime.utcnow()
                ticket.queue.active_tickets -= 1
                cancelled_count += 1
                socketio.emit('ticket_cancelled', {
                    'ticket_id': ticket.id,
                    'queue_id': ticket.queue_id,
                    'branch_id': branch_id
                }, namespace='/branch_admin')
                emit_display_update(branch_id, 'ticket_cancelled', {
                    'ticket_id': ticket.id,
                    'queue_id': ticket.queue_id
                })
                AuditLog.create(
                    user_id=user.id,
                    action='bulk_cancel_ticket',
                    resource_type='ticket',
                    resource_id=ticket.id,
                    details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} cancelado em massa: {reason}"
                )
                if ticket.user_id:
                    QueueService.send_fcm_notification(
                        ticket.user_id,
                        f"Seu ticket {ticket.queue.prefix}{ticket.ticket_number} foi cancelado: {reason}"
                    )

            db.session.commit()
            redis_client.delete(f"cache:tickets:{branch_id}")
            if queue_id:
                redis_client.delete(f"cache:queues:{branch_id}")
            logger.info(f"{cancelled_count} tickets cancelados em massa por user_id={user.id} na filial {branch_id}")
            return jsonify({
                'message': f'{cancelled_count} tickets cancelados com sucesso',
                'cancelled_count': cancelled_count
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao cancelar tickets em massa: {str(e)}")
            return jsonify({'error': 'Erro ao cancelar tickets'}), 500

    # Configurar Notificações Automáticas
    @app.route('/api/branch_admin/branches/<branch_id>/alerts/setup', methods=['POST'])
    @require_auth
    def setup_admin_alerts(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de configurar alertas por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        data = request.get_json()
        if not data or 'alert_preferences' not in data:
            logger.warning("Campo alert_preferences faltando na configuração de alertas")
            return jsonify({'error': 'Campo obrigatório faltando: alert_preferences'}), 400

        valid_alert_types = ['queue_full', 'long_wait_time', 'system_error']
        preferences = data['alert_preferences']
        if not isinstance(preferences, dict):
            logger.warning("Formato inválido para alert_preferences")
            return jsonify({'error': 'alert_preferences deve ser um objeto'}), 400

        for alert_type in preferences:
            if alert_type not in valid_alert_types:
                logger.warning(f"Tipo de alerta inválido: {alert_type}")
                return jsonify({'error': f'Tipo de alerta inválido: {alert_type}'}), 400
            if not isinstance(preferences[alert_type], dict) or 'enabled' not in preferences[alert_type]:
                logger.warning(f"Configuração inválida para alerta {alert_type}")
                return jsonify({'error': f'Configuração inválida para alerta {alert_type}'}), 400

        try:
            user.notification_preferences = user.notification_preferences or {}
            user.notification_preferences['admin_alerts'] = preferences
            user.notification_enabled = True
            db.session.commit()

            AuditLog.create(
                user_id=user.id,
                action='setup_alerts',
                resource_type='user',
                resource_id=user.id,
                details=f"Configuração de alertas atualizada: {json.dumps(preferences)}"
            )
            logger.info(f"Alertas configurados por user_id={user.id} na filial {branch_id}")
            return jsonify({
                'message': 'Configuração de alertas atualizada com sucesso',
                'alert_preferences': preferences
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao configurar alertas: {str(e)}")
            return jsonify({'error': 'Erro ao configurar alertas'}), 500

    # Tela de Acompanhamento
    @app.route('/api/branch_admin/branches/<branch_id>/display', methods=['GET'])
    @require_auth
    def get_branch_display(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de acessar tela de acompanhamento por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        cache_key = f'display:{branch_id}'
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para tela {branch_id}: {str(e)}")

        try:
            display_queues = DisplayQueue.query.filter_by(branch_id=branch_id).options(
                joinedload(DisplayQueue.queue)
                    .joinedload(Queue.department)
                    .joinedload(Queue.service)
            ).order_by(DisplayQueue.display_order).all()

            now = datetime.now()
            current_weekday = now.strftime('%A').upper()
            current_time = now.time()
            schedule = Branch.query.get(branch_id).schedules.filter_by(weekday=current_weekday).first()

            response = {
                'branch_id': branch_id,
                'branch_name': branch.name,
                'queues': []
            }

            for dq in display_queues:
                queue = dq.queue
                is_open = False
                is_paused = queue.daily_limit == 0
                if schedule and not schedule.is_closed:
                    is_open = (
                        schedule.open_time and schedule.end_time and
                        current_time >= schedule.open_time and
                        current_time <= schedule.end_time and
                        queue.active_tickets < queue.daily_limit
                    )
                status = 'Pausado' if is_paused else (
                    'Aberto' if is_open else ('Lotado' if queue.active_tickets >= queue.daily_limit else 'Fechado')
                )

                current_ticket = Ticket.query.filter_by(queue_id=queue.id, status='Chamado').order_by(Ticket.issued_at.desc()).first()
                if not current_ticket:
                    current_ticket = Ticket.query.filter_by(queue_id=queue.id, status='Atendido').order_by(Ticket.attended_at.desc()).first()

                response['queues'].append({
                    'queue_id': queue.id,
                    'prefix': queue.prefix,
                    'service_name': queue.service.name if queue.service else 'N/A',
                    'department_name': queue.department.name if queue.department else 'N/A',
                    'status': status,
                    'active_tickets': queue.active_tickets,
                    'current_ticket': {
                        'ticket_number': f"{queue.prefix}{current_ticket.ticket_number}" if current_ticket else 'N/A',
                        'counter': f"Guichê {current_ticket.counter:02d}" if current_ticket and current_ticket.counter else 'N/A',
                        'status': current_ticket.status if current_ticket else 'N/A'
                    } if current_ticket else None,
                    'estimated_wait_time': round(queue.estimated_wait_time, 2) if queue.estimated_wait_time else None,
                    'display_order': dq.display_order
                })

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para tela {branch_id}: {str(e)}")

            logger.info(f"Tela de acompanhamento retornada para user_id={user.id} na filial {branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao buscar tela de acompanhamento para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro ao buscar tela de acompanhamento'}), 500

    # Adicionar Fila à Tela de Acompanhamento
    @app.route('/api/branch_admin/branches/<branch_id>/display/queues', methods=['POST'])
    @require_auth
    def add_queue_to_display(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de adicionar fila à tela por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        data = request.get_json()
        if not data or 'queue_id' not in data:
            logger.warning("Campo queue_id faltando na adição de fila à tela")
            return jsonify({'error': 'Campo obrigatório faltando: queue_id'}), 400

        queue = Queue.query.get(data['queue_id'])
        department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
        if not queue or queue.department_id not in department_ids:
            logger.warning(f"Fila {data['queue_id']} inválida ou não pertence à filial {branch_id}")
            return jsonify({'error': 'Fila inválida ou não pertence à filial'}), 404

        if DisplayQueue.query.filter_by(branch_id=branch_id, queue_id=data['queue_id']).first():
            logger.warning(f"Fila {data['queue_id']} já está na tela da filial {branch_id}")
            return jsonify({'error': 'Fila já está na tela de acompanhamento'}), 400

        try:
            max_order = db.session.query(db.func.max(DisplayQueue.display_order)).filter_by(branch_id=branch_id).scalar() or 0
            display_queue = DisplayQueue(
                id=str(uuid.uuid4()),
                branch_id=branch_id,
                queue_id=data['queue_id'],
                display_order=max_order + 1
            )
            db.session.add(display_queue)
            db.session.commit()

            emit_display_update(branch_id, 'queue_added', {
                'queue_id': queue.id,
                'prefix': queue.prefix,
                'service_name': queue.service.name if queue.service else 'N/A',
                'department_name': queue.department.name if queue.department else 'N/A',
                'display_order': display_queue.display_order
            })

            AuditLog.create(
                user_id=user.id,
                action='add_queue_to_display',
                resource_type='display_queue',
                resource_id=display_queue.id,
                details=f"Fila {queue.prefix} adicionada à tela da filial {branch.name}"
            )
            redis_client.delete(f"cache:display:{branch_id}")
            logger.info(f"Fila {queue.prefix} adicionada à tela por user_id={user.id}")
            return jsonify({
                'message': 'Fila adicionada à tela com sucesso',
                'display_queue': {
                    'id': display_queue.id,
                    'queue_id': queue.id,
                    'branch_id': branch_id,
                    'display_order': display_queue.display_order
                }
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao adicionar fila à tela: {str(e)}")
            return jsonify({'error': 'Erro ao adicionar fila à tela'}), 500


    @app.route('/api/branch_admin/branches/<branch_id>/queues/<queue_id>', methods=['PUT'])
    @require_auth
    def update_branch_queue(branch_id, queue_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de atualizar fila por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.branch_id != branch_id:
            logger.warning(f"Fila {queue_id} não encontrada")
            return jsonify({'error': 'Fila não encontrada'}), 404

        data = request.get_json()
        required_fields = ['department_id', 'service_id', 'prefix', 'daily_limit', 'num_counters']
        if not data or not all(field in data for field in required_fields):
            logger.warning("Campos obrigatórios faltando na atualização de fila")
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400

        try:
            queue.department_id = data['department_id']
            queue.service_id = data['service_id']
            queue.prefix = data['prefix']
            queue.daily_limit = data['daily_limit']
            queue.num_counters = data['num_counters']
            db.session.commit()

            redis_client.delete(f"cache:queues:{branch_id}")
            socketio.emit('queue_updated', {
                'queue_id': queue.id,
                'prefix': queue.prefix
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='update_queue',
                resource_type='queue',
                resource_id=queue.id,
                details=f"Fila {queue.prefix} atualizada por {user.email}"
            )
            logger.info(f"Fila {queue.prefix} atualizada por user_id={user.id}")
            return jsonify({'message': 'Fila atualizada com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar fila: {str(e)}")
            return jsonify({'error': 'Erro ao atualizar fila'}), 500
    # Remover Fila da Tela de Acompanhamento
    @app.route('/api/branch_admin/branches/<branch_id>/display/queues/<queue_id>', methods=['DELETE'])
    @require_auth
    def remove_queue_from_display(branch_id, queue_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de remover fila da tela por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        display_queue = DisplayQueue.query.filter_by(branch_id=branch_id, queue_id=queue_id).first()
        if not display_queue:
            logger.warning(f"Fila {queue_id} não está na tela da filial {branch_id}")
            return jsonify({'error': 'Fila não está na tela de acompanhamento'}), 404

        try:
            queue = Queue.query.get(queue_id)
            db.session.delete(display_queue)
            db.session.commit()

            emit_display_update(branch_id, 'queue_removed', {
                'queue_id': queue_id,
                'prefix': queue.prefix if queue else 'N/A'
            })

            AuditLog.create(
                user_id=user.id,
                action='remove_queue_from_display',
                resource_type='display_queue',
                resource_id=display_queue.id,
                details=f"Fila {queue.prefix if queue else queue_id} removida da tela da filial {branch.name}"
            )
            redis_client.delete(f"cache:display:{branch_id}")
            logger.info(f"Fila {queue_id} removida da tela por user_id={user.id}")
            return jsonify({'message': 'Fila removida da tela com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao remover fila da tela: {str(e)}")
            return jsonify({'error': 'Erro ao remover fila da tela'}), 500
        
    @app.route('/api/branch_admin/branches/<branch_id>/queues/<queue_id>/call', methods=['POST'])
    @require_auth
    def call_next_ticket(branch_id, queue_id):
        """Chama o próximo ticket de uma fila."""
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de chamar ticket por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.branch_id != branch_id:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para chamar ticket na fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para chamar ticket na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        if queue.daily_limit == 0:
            logger.warning(f"Tentativa de chamar ticket em fila pausada {queue_id}")
            return jsonify({'error': 'Fila está pausada'}), 400

        if queue.num_counters < 1:
            logger.warning(f"Fila {queue_id} sem guichês configurados")
            return jsonify({'error': 'Nenhum guichê configurado para esta fila'}), 400

        data = request.get_json() or {}
        counter = data.get('counter')

        # Suporte para atribuição automática de guichê
        if counter == 'auto':
            queue.last_counter = (queue.last_counter % queue.num_counters) + 1
            counter = queue.last_counter
        else:
            try:
                counter = int(counter)
                if counter < 1 or counter > queue.num_counters:
                    logger.warning(f"Guichê inválido: {counter} para fila {queue_id}")
                    return jsonify({'error': f'Guichê inválido: {counter}'}), 400
            except (ValueError, TypeError):
                logger.warning(f"Guichê inválido: {counter} para fila {queue_id}")
                return jsonify({'error': f'Guichê inválido: {counter}'}), 400

        try:
            ticket = QueueService.call_next(queue_id, counter)
            if not ticket:
                logger.info(f"Nenhum ticket pendente para chamar na fila {queue_id}")
                return jsonify({'message': 'Nenhum ticket pendente para chamar'}), 200

            # Ajuste: Não incrementar active_tickets, pois call_next_ticket já decrementa
            queue.current_ticket = ticket.ticket_number
            queue.update_estimated_wait_time()
            db.session.commit()

            redis_client.delete(f"cache:queues:{branch_id}")
            emit_ticket_update(ticket)
            QueueService.emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue_id,
                event_type='ticket_called',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': counter,
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            AuditLog.create(
                user_id=request.user_id,
                action='call_ticket',
                resource_type='ticket',
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} chamado no guichê {counter}"
            )

            # Verificar alertas (mantido do primeiro trecho)
            if queue.active_tickets >= queue.daily_limit and user.notification_enabled:
                alerts = user.notification_preferences.get('admin_alerts', {})
                if alerts.get('queue_full', {}).get('enabled', False):
                    QueueService.send_fcm_notification(
                        user.id,
                        f"Fila {queue.prefix} atingiu o limite diário na filial {queue.department.branch.name}"
                    )
            if queue.estimated_wait_time and queue.estimated_wait_time > 30:
                alerts = user.notification_preferences.get('admin_alerts', {})
                if alerts.get('long_wait_time', {}).get('enabled', False):
                    QueueService.send_fcm_notification(
                        user.id,
                        f"Tempo de espera na fila {queue.prefix} excede 30 minutos"
                    )

            logger.info(f"Ticket chamado: {ticket.queue.prefix}{ticket.ticket_number} no guichê {counter} (queue_id={queue_id})")
            return jsonify({
                'message': 'Ticket chamado com sucesso',
                'ticket': {
                    'id': ticket.id,
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': counter,
                    'queue_id': queue_id,
                    'service_name': queue.service.name
                }
            }), 200
        except ValueError as e:
            logger.error(f"Erro ao chamar próximo ticket na fila {queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao chamar próximo ticket na fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao chamar ticket'}), 500
    
    # Rota para completar um ticket (modificada)
    @app.route('/api/branch_admin/branches/<branch_id>/queues/<queue_id>/tickets/<ticket_id>/complete', methods=['POST'])
    @require_auth
    def complete_ticket(branch_id, queue_id, ticket_id):
        """Marca um ticket como atendido."""
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de completar ticket por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.branch_id != branch_id:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        ticket = Ticket.query.get(ticket_id)
        if not ticket or ticket.queue_id != queue_id:
            logger.warning(f"Ticket não encontrado: ticket_id={ticket_id}")
            return jsonify({'error': 'Ticket não encontrado'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para completar ticket na fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para completar ticket na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        if ticket.status != 'Chamado':
            logger.warning(f"Ticket {ticket_id} não está no status Chamado")
            return jsonify({'error': 'Ticket não está no status Chamado'}), 400

        try:
            ticket.status = 'Concluído'
            ticket.completed_at = datetime.utcnow()
            queue.active_tickets -= 1
            queue.update_estimated_wait_time()
            db.session.commit()

            redis_client.delete(f"cache:queues:{branch_id}")
            emit_ticket_update(ticket)
            QueueService.emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue_id,
                event_type='ticket_completed',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            AuditLog.create(
                user_id=request.user_id,
                action='complete_ticket',
                resource_type='ticket',
                resource_id=ticket_id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} marcado como atendido"
            )

            logger.info(f"Ticket completado: {ticket.queue.prefix}{ticket.ticket_number} (ticket_id={ticket_id})")
            return jsonify({
                'message': f"Ticket {ticket.queue.prefix}{ticket.ticket_number} finalizado com sucesso"
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao completar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro ao completar ticket'}), 500

    # Rota para listar próximos tickets (nova)
    @app.route('/api/branch_admin/branches/<branch_id>/queues/<queue_id>/next_tickets', methods=['GET'])
    @require_auth
    def list_next_tickets(branch_id, queue_id):
        """Lista até 3 tickets pendentes de uma fila."""
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de listar próximos tickets por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.branch_id != branch_id:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para listar tickets na fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para listar tickets na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        tickets = Ticket.query.filter_by(queue_id=queue_id, status='Pendente').order_by(
            Ticket.priority.desc(), Ticket.issued_at.asc()
        ).limit(3).all()

        response = [{
            'id': t.id,
            'ticket_number': f"{queue.prefix}{t.ticket_number}",
            'service_name': queue.service.name,
            'priority': t.priority,
            'issued_at': t.issued_at.isoformat()
        } for t in tickets]

        logger.info(f"Próximos tickets listados para fila {queue_id} por user_id={request.user_id}")
        return jsonify(response), 200

    # Rota para listar chamadas recentes (nova)
    @app.route('/api/branch_admin/branches/<branch_id>/recent_calls', methods=['GET'])
    @require_auth
    def list_recent_calls(branch_id):
        """Lista até 10 chamadas recentes da filial."""
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de listar chamadas recentes por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        if user.user_role == UserRole.BRANCH_ADMIN and user.branch_id != branch_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para listar chamadas na filial {branch_id}")
            return jsonify({'error': 'Sem permissão para esta filial'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN:
            branch = Branch.query.get(branch_id)
            if not branch or branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} não tem permissão para listar chamadas na instituição {branch.institution_id}")
                return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
        tickets = Ticket.query.join(Queue).filter(
            Queue.department_id.in_(department_ids),
            Ticket.status.in_(['Chamado', 'Concluído'])
        ).order_by(desc(Ticket.attended_at)).limit(10).all()

        response = [{
            'ticket_number': f"{t.queue.prefix}{t.ticket_number}",
            'service_name': t.queue.service.name,
            'counter': t.counter,
            'attended_at': t.attended_at.isoformat() if t.attended_at else None,
            'status': t.status
        } for t in tickets]

        logger.info(f"Chamadas recentes listadas para filial {branch_id} por user_id={request.user_id}")
        return jsonify(response), 200

    # Rota para rechamar um ticket (nova)
    @app.route('/api/branch_admin/branches/<branch_id>/queues/<queue_id>/recall', methods=['POST'])
    @require_auth
    def recall_tickett(branch_id, queue_id):
        """Rechama um ticket específico."""
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de rechamar ticket por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.branch_id != branch_id:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para rechamar ticket na fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para rechamar ticket na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        data = request.get_json()
        ticket_id = data.get('ticket_id')
        ticket = Ticket.query.get(ticket_id)
        if not ticket or ticket.queue_id != queue_id or ticket.status != 'Chamado':
            logger.warning(f"Ticket {ticket_id} inválido ou não chamado")
            return jsonify({'error': 'Ticket inválido ou não chamado'}), 400

        try:
            emit_ticket_update(ticket)
            QueueService.emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue_id,
                event_type='ticket_called',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter,
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            AuditLog.create(
                user_id=request.user_id,
                action='recall_ticket',
                resource_type='ticket',
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} rechamado no guichê {ticket.counter}"
            )
            logger.info(f"Ticket {ticket.queue.prefix}{ticket.ticket_number} rechamado por user_id={request.user_id}")
            return jsonify({'message': f"Ticket {ticket.queue.prefix}{ticket.ticket_number} rechamado com sucesso"}), 200
        except Exception as e:
            logger.error(f"Erro ao rechamar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro ao rechamar ticket'}), 500

    # Rota para cancelar um ticket (nova)
    @app.route('/api/branch_admin/branches/<branch_id>/queues/<queue_id>/tickets/<ticket_id>/cancel', methods=['POST'])
    @require_auth
    def cancel_tickett(branch_id, queue_id, ticket_id):
        """Cancela um ticket específico."""
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de cancelar ticket por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.branch_id != branch_id:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        ticket = Ticket.query.get(ticket_id)
        if not ticket or ticket.queue_id != queue_id:
            logger.warning(f"Ticket não encontrado: ticket_id={ticket_id}")
            return jsonify({'error': 'Ticket não encontrado'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para cancelar ticket na fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para cancelar ticket na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        if ticket.status != 'Chamado':
            logger.warning(f"Ticket {ticket_id} não está no status Chamado")
            return jsonify({'error': 'Ticket não está no status Chamado'}), 400

        try:
            ticket.status = 'Cancelado'
            queue.active_tickets -= 1
            queue.update_estimated_wait_time()
            db.session.commit()

            redis_client.delete(f"cache:queues:{branch_id}")
            emit_ticket_update(ticket)
            QueueService.emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue_id,
                event_type='ticket_cancelled',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'timestamp': datetime.utcnow().isoformat()
                }
            )

            AuditLog.create(
                user_id=request.user_id,
                action='cancel_ticket',
                resource_type='ticket',
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} cancelado"
            )
            logger.info(f"Ticket {ticket.queue.prefix}{ticket.ticket_number} cancelado por user_id={request.user_id}")
            return jsonify({'message': f"Ticket {ticket.queue.prefix}{ticket.ticket_number} cancelado com sucesso"}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao cancelar ticket {ticket_id}: {str(e)}")
            return jsonify({'error': 'Erro ao cancelar ticket'}), 500

    # Rota para obter detalhes de um ticket (nova)
    @app.route('/api/branch_admin/branches/<branch_id>/queues/<queue_id>/tickets/<ticket_id>', methods=['GET'])
    @require_auth
    def get_ticket_details(branch_id, queue_id, ticket_id):
        """Obtém detalhes de um ticket específico."""
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de visualizar ticket por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.branch_id != branch_id:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        ticket = Ticket.query.get(ticket_id)
        if not ticket or ticket.queue_id != queue_id:
            logger.warning(f"Ticket não encontrado: ticket_id={ticket_id}")
            return jsonify({'error': 'Ticket não encontrado'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para visualizar ticket na fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para visualizar ticket na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        return jsonify({
            'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
            'service_name': queue.service.name,
            'counter': ticket.counter,
            'status': ticket.status,
            'issued_at': ticket.issued_at.isoformat(),
            'attended_at': ticket.attended_at.isoformat() if ticket.attended_at else None
        }), 200

    # Rota para configurações de chamada (nova)
    @app.route('/api/branch_admin/branches/<branch_id>/call_settings', methods=['GET', 'POST'])
    @require_auth
    def call_settings(branch_id):
        """Gerencia configurações de chamada."""
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de acessar configurações por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        if user.user_role == UserRole.BRANCH_ADMIN and user.branch_id != branch_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para acessar configurações na filial {branch_id}")
            return jsonify({'error': 'Sem permissão para esta filial'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN:
            branch = Branch.query.get(branch_id)
            if not branch or branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} não tem permissão para acessar configurações na instituição {branch.institution_id}")
                return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        if request.method == 'GET':
            settings = {
                'priority': 'fifo',
                'counter_id': 'auto',
                'sound': 'default',
                'interval': 30
            }
            return jsonify(settings), 200

        if request.method == 'POST':
            data = request.get_json()
            required_fields = ['priority', 'counter_id', 'sound', 'interval']
            if not data or not all(field in data for field in required_fields):
                logger.warning("Campos obrigatórios faltando nas configurações")
                return jsonify({'error': 'Campos obrigatórios faltando'}), 400

            logger.info(f"Configurações de chamada atualizadas por user_id={request.user_id}")
            return jsonify({'message': 'Configurações salvas com sucesso'}), 200

    # Rota para criar uma nova fila (modificada)
    @app.route('/api/branch_admin/branches/<branch_id>/queues', methods=['POST'])
    @require_auth
    def create_branch_queue(branch_id):
        """Cria uma nova fila."""
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de criar fila por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        if user.user_role == UserRole.BRANCH_ADMIN and user.branch_id != branch_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para criar fila na filial {branch_id}")
            return jsonify({'error': 'Sem permissão para esta filial'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN:
            branch = Branch.query.get(branch_id)
            if not branch or branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} não tem permissão para criar fila na instituição {branch.institution_id}")
                return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        data = request.get_json()
        required_fields = ['department_id', 'service_id', 'prefix', 'daily_limit', 'num_counters']
        if not data or not all(field in data for field in required_fields):
            logger.warning("Campos obrigatórios faltando na criação de fila")
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400

        if not isinstance(data['num_counters'], int) or data['num_counters'] < 1:
            logger.warning(f"Número de guichês inválido: {data['num_counters']}")
            return jsonify({'error': 'O número de guichês deve ser maior que 0'}), 400

        try:
            department = Department.query.get(data['department_id'])
            if not department or department.branch_id != branch_id:
                logger.warning(f"Departamento {data['department_id']} não encontrado")
                return jsonify({'error': 'Departamento não encontrado'}), 404

            queue = Queue(
                department_id=data['department_id'],
                service_id=data['service_id'],
                prefix=data['prefix'].upper(),
                daily_limit=data['daily_limit'],
                num_counters=data['num_counters'],
                last_counter=0,
                active_tickets=0,
                estimated_wait_time=0
            )
            db.session.add(queue)
            db.session.commit()

            redis_client.delete(f"cache:queues:{branch_id}")
            emit('queue_updated', {
                'queue_id': queue.id,
                'prefix': queue.prefix,
                'daily_limit': queue.daily_limit
            }, namespace='/branch_admin')

            AuditLog.create(
                user_id=user.id,
                action='create_queue',
                resource_type='queue',
                resource_id=queue.id,
                details=f"Fila {queue.prefix} criada por {user.email}"
            )
            logger.info(f"Fila {queue.prefix} criada por user_id={user.id}")
            return jsonify({
                'message': 'Fila criada com sucesso',
                'queue': {
                    'id': queue.id,
                    'department_id': queue.department_id,
                    'service_id': queue.service_id,
                    'prefix': queue.prefix,
                    'daily_limit': queue.daily_limit,
                    'num_counters': queue.num_counters
                }
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao criar fila: {str(e)}")
            return jsonify({'error': 'Erro ao criar fila'}), 500


    @app.route('/api/branch_admin/branches/<branch_id>/queues/totem', methods=['POST'])
    def generate_totem_tickets(branch_id):
        token = request.headers.get('Totem-Token')
        expected_token = app.config.get('TOTEM_TOKEN', 'h0gmVAmsj5kyhyVIlkZFF3lG4GJiqomF')
        if not token or token != expected_token:
            app.logger.warning(f"Token de totem inválido para IP {request.remote_addr}")
            return jsonify({'error': 'Token de totem inválido'}), 401

        branch = db.session.get(Branch, branch_id)
        if not branch:
            app.logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        data = request.get_json() or {}
        queue_id = data.get('queue_id')
        client_ip = request.remote_addr

        if not queue_id:
            app.logger.warning("queue_id não fornecido")
            return jsonify({'error': 'queue_id é obrigatório'}), 400

        # Carregar e validar a fila
        queue = db.session.get(Queue, queue_id)
        if not queue:
            app.logger.warning(f"Fila {queue_id} não encontrada")
            return jsonify({'error': 'Fila não encontrada'}), 404

        department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
        if queue.department_id not in department_ids:
            app.logger.warning(f"Fila {queue_id} não pertence à filial {branch_id}")
            return jsonify({'error': 'Fila não pertence à filial'}), 404

        # Logar o prefix para depuração
        app.logger.info(f"Fila {queue_id} carregada com prefix={queue.prefix}")

        # Verificar se o prefix é válido
        if not queue.prefix or queue.prefix.strip() == '':
            app.logger.warning(f"Fila {queue_id} tem prefix nulo ou vazio; corrigindo para 'A'")
            queue.prefix = 'A'
            db.session.add(queue)
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                app.logger.error(f"Erro ao corrigir prefix para queue_id={queue_id}: {str(e)}")
                return jsonify({'error': 'Erro ao corrigir dados da fila'}), 500

        cache_key = f"totem:throttle:{client_ip}"
        if app.redis_client.get(cache_key):
            app.logger.warning(f"Limite de emissão atingido para IP {client_ip}")
            return jsonify({'error': 'Limite de emissão atingido. Tente novamente em 30 segundos'}), 429
        app.redis_client.setex(cache_key, 30, "1")

        try:
            result = QueueService.generate_physical_ticket_for_totem(
                queue_id=queue_id,
                branch_id=branch_id,
                client_ip=client_ip
            )
            ticket = result['ticket']
            pdf_buffer = io.BytesIO(bytes.fromhex(result['pdf']))

            # Recarregar o ticket para garantir que ticket.queue esteja disponível
            db_ticket = db.session.get(Ticket, ticket['id'])
            if not db_ticket or not db_ticket.queue:
                app.logger.error(f"Relação ticket.queue não carregada para ticket {ticket['id']}")
                return jsonify({'error': 'Erro ao carregar a fila associada ao ticket'}), 500

            ticket_data = {
                'ticket_number': f"{db_ticket.queue.prefix}{ticket['ticket_number']}",
                'timestamp': ticket['issued_at']
            }
            app.logger.info(f"Ticket gerado: {ticket_data['ticket_number']} para queue_id={queue_id}")
            emit_dashboard_update(socketio, branch_id, queue_id, 'ticket_issued', ticket_data)
            emit_display_update(socketio, branch_id, 'ticket_issued', ticket_data)

            AuditLog.create(
                user_id=None,
                action='generate_totem_ticket',
                resource_type='ticket',
                resource_id=ticket['id'],
                details=f"Ticket físico {db_ticket.queue.prefix}{ticket['ticket_number']} emitido via totem (IP: {client_ip})"
            )
            app.logger.info(f"Ticket físico emitido via totem: {db_ticket.queue.prefix}{ticket['ticket_number']} (IP: {client_ip})")
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=f"ticket_{db_ticket.queue.prefix}{ticket['ticket_number']}.pdf",
                mimetype='application/pdf'
            )
        except ValueError as e:
            app.logger.error(f"Erro ao emitir ticket via totem para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except SQLAlchemyError as e:
            app.logger.error(f"Erro no banco de dados ao emitir ticket via totem para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao emitir ticket'}), 500
        except Exception as e:
            app.logger.error(f"Erro inesperado ao emitir ticket via totem para queue_id={queue_id}: {str(e)}", exc_info=True)
            return jsonify({'error': f'Erro interno ao emitir ticket: {str(e)}'}), 500

    # Rota para pausar/retomar fila (modificada)
    @app.route('/api/branch_admin/branches/<branch_id>/queues/<queue_id>/pause', methods=['POST'])
    @require_auth
    def pause_queue(branch_id, queue_id):
        """Pausa ou retoma uma fila."""
        user = User.query.get(request.user_id)
        if not user or user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Tentativa não autorizada de pausar fila por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.branch_id != branch_id:
            logger.warning(f"Fila não encontrada: queue_id={queue_id}")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.user_role == UserRole.BRANCH_ADMIN and queue.department.branch_id != user.branch_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para pausar fila {queue_id}")
            return jsonify({'error': 'Sem permissão para esta fila'}), 403
        if user.user_role == UserRole.INSTITUTION_ADMIN and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Usuário {request.user_id} não tem permissão para pausar fila na instituição {queue.department.branch.institution_id}")
            return jsonify({'error': 'Sem permissão para esta instituição'}), 403

        data = request.get_json()
        daily_limit = data.get('daily_limit')

        try:
            if daily_limit is None:
                queue.daily_limit = 0
                action = 'pause_queue'
                message = f"Fila {queue.prefix} pausada"
            else:
                if not isinstance(daily_limit, int) or daily_limit < 0:
                    return jsonify({'error': 'Limite diário inválido'}), 400
                queue.daily_limit = daily_limit
                action = 'resume_queue'
                message = f"Fila {queue.prefix} retomada"

            db.session.commit()
            redis_client.delete(f"cache:queues:{branch_id}")
            emit('queue_updated', {
                'queue_id': queue_id,
                'prefix': queue.prefix,
                'daily_limit': queue.daily_limit
            }, namespace='/branch_admin')

            AuditLog.create(
                user_id=user.id,
                action=action,
                resource_type='queue',
                resource_id=queue.id,
                details=f"{message} por {user.email}"
            )
            logger.info(f"{message} por user_id={user.id}")
            return jsonify({'message': message}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao pausar/retomar fila {queue_id}: {str(e)}")
            return jsonify({'error': 'Erro ao atualizar status da fila'}), 500
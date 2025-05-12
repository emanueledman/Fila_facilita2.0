from flask import jsonify, request, send_file
from . import db, socketio, redis_client
from .models import AuditLog, User, Queue, Ticket, Department, Institution, UserRole, Branch, BranchSchedule, AttendantQueue, Weekday, InstitutionService
from .auth import require_auth
from .services import QueueService
from .ml_models import wait_time_predictor
from sqlalchemy.exc import SQLAlchemyError
import logging
import uuid
from datetime import datetime, timedelta
import re
import json
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_branch_admin_routes(app):
    def emit_dashboard_update(branch_id, queue_id, event_type, data):
        """Função auxiliar para emitir atualizações ao painel via WebSocket."""
        try:
            socketio.emit('dashboard_update', {
                'branch_id': branch_id,
                'queue_id': queue_id,
                'event_type': event_type,
                'data': data
            }, room=branch_id, namespace='/dashboard')
            logger.info(f"Atualização de painel emitida: branch_id={branch_id}, event_type={event_type}")
        except Exception as e:
            logger.error(f"Erro ao emitir atualização de painel: {str(e)}")

    @app.route('/api/branch_admin/branches/<branch_id>/departments', methods=['POST'])
    @require_auth
    def create_branch_department(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de criar departamento por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        data = request.get_json()
        required = ['name', 'sector']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de departamento")
            return jsonify({'error': 'Campos obrigatórios faltando: name, sector'}), 400

        # Validações
        if not re.match(r'^[A-Za-zÀ-ÿ\s0-9.,-]{1,50}$', data['name']):
            logger.warning(f"Nome inválido para departamento: {data['name']}")
            return jsonify({'error': 'Nome do departamento inválido'}), 400
        if not re.match(r'^[A-Za-zÀ-ÿ\s]{1,50}$', data['sector']):
            logger.warning(f"Setor inválido: {data['sector']}")
            return jsonify({'error': 'Setor inválido'}), 400
        if Department.query.filter_by(branch_id=branch_id, name=data['name']).first():
            logger.warning(f"Departamento com nome {data['name']} já existe na filial {branch_id}")
            return jsonify({'error': 'Departamento com este nome já existe na filial'}), 400

        try:
            department = Department(
                id=str(uuid.uuid4()),
                branch_id=branch_id,
                name=data['name'],
                sector=data['sector']
            )
            db.session.add(department)
            db.session.commit()

            socketio.emit('department_created', {
                'department_id': department.id,
                'name': department.name,
                'sector': department.sector,
                'branch_id': branch_id
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='create_department',
                resource_type='department',
                resource_id=department.id,
                details=f"Criado departamento {department.name} na filial {branch.name}"
            )
            logger.info(f"Departamento {department.name} criado por user_id={user.id}")
            redis_client.delete(f"cache:departments:{branch_id}")
            return jsonify({
                'message': 'Departamento criado com sucesso',
                'department': {
                    'id': department.id,
                    'name': department.name,
                    'sector': department.sector,
                    'branch_id': branch_id
                }
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao criar departamento: {str(e)}")
            return jsonify({'error': 'Erro interno ao criar departamento'}), 500

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
                'sector': d.sector,
                'branch_id': d.branch_id
            } for d in departments]

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para departamentos {branch_id}: {str(e)}")

            logger.info(f"Admin {user.email} listou {len(response)} departamentos da filial {branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar departamentos para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar departamentos'}), 500

    @app.route('/api/branch_admin/branches/<branch_id>/queues', methods=['POST'])
    @require_auth
    def create_branch_queue(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de criar fila por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        data = request.get_json()
        required = ['department_id', 'service_id', 'prefix', 'daily_limit', 'num_counters']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de fila")
            return jsonify({'error': 'Campos obrigatórios faltando: department_id, service_id, prefix, daily_limit, num_counters'}), 400

        # Validações
        department = Department.query.get(data['department_id'])
        if not department or department.branch_id != branch_id:
            logger.warning(f"Departamento {data['department_id']} inválido ou não pertence à filial {branch_id}")
            return jsonify({'error': 'Departamento inválido ou não pertence à filial'}), 400
        service = InstitutionService.query.get(data['service_id'])
        if not service or service.institution_id != branch.institution_id:
            logger.warning(f"Serviço {data['service_id']} inválido ou não pertence à instituição")
            return jsonify({'error': 'Serviço inválido ou não pertence à instituição'}), 400
        if not re.match(r'^[A-Z]{1,10}$', data['prefix']):
            logger.warning(f"Prefixo inválido: {data['prefix']}")
            return jsonify({'error': 'Prefixo deve conter apenas letras maiúsculas e até 10 caracteres'}), 400
        if not isinstance(data['daily_limit'], int) or data['daily_limit'] < 1:
            logger.warning(f"Limite diário inválido: {data['daily_limit']}")
            return jsonify({'error': 'Limite diário deve ser um número inteiro maior que 0'}), 400
        if not isinstance(data['num_counters'], int) or data['num_counters'] < 1:
            logger.warning(f"Número de guichês inválido: {data['num_counters']}")
            return jsonify({'error': 'Número de guichês deve ser um número inteiro maior que 0'}), 400

        try:
            queue = Queue(
                id=str(uuid.uuid4()),
                department_id=data['department_id'],
                service_id=data['service_id'],
                prefix=data['prefix'],
                daily_limit=data['daily_limit'],
                num_counters=data['num_counters'],
                active_tickets=0,
                current_ticket=0
            )
            db.session.add(queue)
            db.session.commit()

            socketio.emit('queue_created', {
                'queue_id': queue.id,
                'department_id': queue.department_id,
                'service_id': queue.service_id,
                'prefix': queue.prefix,
                'daily_limit': queue.daily_limit,
                'num_counters': queue.num_counters,
                'branch_id': branch_id
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='create_queue',
                resource_type='queue',
                resource_id=queue.id,
                details=f"Criada fila {queue.prefix} no departamento {department.name}"
            )
            logger.info(f"Fila {queue.prefix} criada por user_id={user.id}")
            redis_client.delete(f"cache:queues:{branch_id}")
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
            return jsonify({'error': 'Erro interno ao criar fila'}), 500

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
            queues = Queue.query.filter(Queue.department_id.in_(department_ids)).all()
            now = datetime.now()
            current_weekday = now.strftime('%A').upper()
            current_time = now.time()

            response = []
            for q in queues:
                schedule = BranchSchedule.query.filter_by(branch_id=branch_id, weekday=current_weekday).first()
                is_open = False
                if schedule and not schedule.is_closed:
                    is_open = (
                        schedule.open_time and schedule.end_time and
                        current_time >= schedule.open_time and
                        current_time <= schedule.end_time and
                        q.active_tickets < q.daily_limit
                    )
                features = QueueService.get_wait_time_features(q.id, q.current_ticket + 1, 0)
                # Chamar predict com argumentos explícitos
                wait_time = wait_time_predictor.predict(
                    queue_id=q.id,
                    position=features['position'],
                    active_tickets=features['active_tickets'],
                    priority=features['priority'],
                    hour_of_day=features['hour_of_day'],
                    num_counters=features['num_counters'],
                    avg_service_time=features['avg_service_time'],
                    daily_limit=features['daily_limit'],
                    user_id=None,
                    user_lat=None,
                    user_lon=None,
                    user_service_preference=None
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
                    'status': 'Aberto' if is_open else ('Lotado' if q.active_tickets >= q.daily_limit else 'Fechado'),
                    'avg_wait_time': round(q.avg_wait_time, 2) if q.avg_wait_time else None,
                    'estimated_wait_time': round(wait_time, 2) if isinstance(wait_time, (int, float)) else None
                })

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para filas {branch_id}: {str(e)}")

            logger.info(f"Admin {user.email} listou {len(response)} filas da filial {branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar filas para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar filas'}), 500

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

        cache_key = f'tickets:{branch_id}'
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para tickets {branch_id}: {str(e)}")

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            queue_ids = [q.id for q in Queue.query.filter(Queue.department_id.in_(department_ids)).all()]
            tickets = Ticket.query.filter(Ticket.queue_id.in_(queue_ids)).order_by(Ticket.issued_at.desc()).limit(100).all()
            response = [{
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
            } for t in tickets]

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para tickets {branch_id}: {str(e)}")

            logger.info(f"Admin {user.email} listou {len(response)} tickets da filial {branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar tickets para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar tickets'}), 500

    @app.route('/api/branch_admin/branches/<branch_id>/attendants', methods=['POST'])
    @require_auth
    def create_branch_attendant(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de criar atendente por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        data = request.get_json()
        required = ['email', 'name', 'password']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de atendente")
            return jsonify({'error': 'Campos obrigatórios faltando: email, name, password'}), 400

        # Validações
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', data['email']):
            logger.warning(f"Email inválido: {data['email']}")
            return jsonify({'error': 'Email inválido'}), 400
        if len(data['password']) < 8:
            logger.warning("Senha muito curta fornecida na criação de atendente")
            return jsonify({'error': 'A senha deve ter pelo menos 8 caracteres'}), 400
        if not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', data['name']):
            logger.warning(f"Nome inválido: {data['name']}")
            return jsonify({'error': 'Nome inválido'}), 400
        if User.query.filter_by(email=data['email']).first():
            logger.warning(f"Usuário com email {data['email']} já existe")
            return jsonify({'error': 'Usuário com este email já existe'}), 400

        try:
            attendant = User(
                id=str(uuid.uuid4()),
                email=data['email'],
                name=data['name'],
                user_role=UserRole.ATTENDANT,
                branch_id=branch_id,
                institution_id=branch.institution_id,
                active=True
            )
            attendant.set_password(data['password'])
            db.session.add(attendant)
            db.session.commit()

            socketio.emit('attendant_created', {
                'user_id': attendant.id,
                'email': attendant.email,
                'name': attendant.name,
                'branch_id': branch_id
            }, namespace='/branch_admin')
            QueueService.send_fcm_notification(attendant.id, f"Bem-vindo ao Facilita 2.0 como atendente na filial {branch.name}")
            AuditLog.create(
                user_id=user.id,
                action='create_attendant',
                resource_type='user',
                resource_id=attendant.id,
                details=f"Criado atendente {attendant.email} na filial {branch.name}"
            )
            logger.info(f"Atendente {attendant.email} criado por user_id={user.id}")
            redis_client.delete(f"cache:attendants:{branch_id}")
            return jsonify({
                'message': 'Atendente criado com sucesso',
                'user': {
                    'id': attendant.id,
                    'email': attendant.email,
                    'name': attendant.name,
                    'role': attendant.user_role.value,
                    'branch_id': branch_id
                }
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao criar atendente: {str(e)}")
            return jsonify({'error': 'Erro interno ao criar atendente'}), 500

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
            attendants = User.query.filter_by(branch_id=branch_id, user_role=UserRole.ATTENDANT).all()
            response = [{
                'id': a.id,
                'email': a.email,
                'name': a.name,
                'active': a.active,
                'last_location_update': a.last_location_update.isoformat() if a.last_location_update else None
            } for a in attendants]

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para atendentes {branch_id}: {str(e)}")

            logger.info(f"Admin {user.email} listou {len(response)} atendentes da filial {branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar atendentes para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar atendentes'}), 500

    @app.route('/api/branch_admin/branches/<branch_id>/attendants/<attendant_id>/queues', methods=['POST'])
    @require_auth
    def assign_attendant_to_queue(branch_id, attendant_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de atribuir atendente por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        attendant = User.query.get(attendant_id)
        if not attendant or attendant.branch_id != branch_id or attendant.user_role != UserRole.ATTENDANT:
            logger.warning(f"Atendente {attendant_id} não encontrado ou não pertence à filial {branch_id}")
            return jsonify({'error': 'Atendente não encontrado ou não pertence à filial'}), 404

        data = request.get_json()
        if not data or 'queue_id' not in data:
            logger.warning("Campo queue_id faltando na atribuição de atendente")
            return jsonify({'error': 'Campo obrigatório faltando: queue_id'}), 400

        queue = Queue.query.get(data['queue_id'])
        department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
        if not queue or queue.department_id not in department_ids:
            logger.warning(f"Fila {data['queue_id']} inválida ou não pertence à filial {branch_id}")
            return jsonify({'error': 'Fila inválida ou não pertence à filial'}), 404

        if AttendantQueue.query.filter_by(user_id=attendant_id, queue_id=data['queue_id']).first():
            logger.warning(f"Atendente {attendant_id} já está atribuído à fila {data['queue_id']}")
            return jsonify({'error': 'Atendente já está atribuído a esta fila'}), 400

        try:
            attendant_queue = AttendantQueue(user_id=attendant_id, queue_id=data['queue_id'])
            db.session.add(attendant_queue)
            db.session.commit()

            socketio.emit('attendant_queue_assigned', {
                'attendant_id': attendant_id,
                'queue_id': data['queue_id'],
                'branch_id': branch_id
            }, namespace='/branch_admin')
            QueueService.send_fcm_notification(attendant_id, f"Você foi atribuído à fila {queue.prefix} na filial {branch.name}")
            AuditLog.create(
                user_id=user.id,
                action='assign_attendant_queue',
                resource_type='attendant_queue',
                resource_id=f"{attendant_id}:{data['queue_id']}",
                details=f"Atendente {attendant.email} atribuído à fila {queue.prefix}"
            )
            logger.info(f"Atendente {attendant.email} atribuído à fila {queue.prefix} por user_id={user.id}")
            return jsonify({
                'message': 'Atendente atribuído à fila com sucesso',
                'assignment': {
                    'attendant_id': attendant_id,
                    'queue_id': data['queue_id']
                }
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao atribuir atendente à fila: {str(e)}")
            return jsonify({'error': 'Erro interno ao atribuir atendente'}), 500

    @app.route('/api/branch_admin/branches/<branch_id>/schedules', methods=['POST'])
    @require_auth
    def create_branch_schedules(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de criar horário por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        data = request.get_json()
        required = ['weekday', 'open_time', 'end_time', 'is_closed']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de horário")
            return jsonify({'error': 'Campos obrigatórios faltando: weekday, open_time, end_time, is_closed'}), 400

        # Validações
        try:
            weekday = Weekday[data['weekday'].upper()]
        except KeyError:
            logger.warning(f"Dia da semana inválido: {data['weekday']}")
            return jsonify({'error': 'Dia da semana inválido'}), 400
        if not data['is_closed']:
            try:
                open_time = datetime.strptime(data['open_time'], '%H:%M').time()
                end_time = datetime.strptime(data['end_time'], '%H:%M').time()
                if open_time >= end_time:
                    logger.warning(f"Horário de abertura {open_time} posterior ao horário de fechamento {end_time}")
                    return jsonify({'error': 'Horário de abertura deve ser anterior ao horário de fechamento'}), 400
            except ValueError:
                logger.warning(f"Formato de horário inválido: open_time={data['open_time']}, end_time={data['end_time']}")
                return jsonify({'error': 'Formato de horário inválido (use HH:MM)'}), 400
        else:
            open_time = None
            end_time = None

        if BranchSchedule.query.filter_by(branch_id=branch_id, weekday=weekday).first():
            logger.warning(f"Horário já existe para {weekday} na filial {branch_id}")
            return jsonify({'error': f'Horário já existe para {weekday.value}'}), 400

        try:
            schedule = BranchSchedule(
                id=str(uuid.uuid4()),
                branch_id=branch_id,
                weekday=weekday,
                open_time=open_time,
                end_time=end_time,
                is_closed=data['is_closed']
            )
            db.session.add(schedule)
            db.session.commit()

            socketio.emit('schedule_created', {
                'schedule_id': schedule.id,
                'branch_id': branch_id,
                'weekday': schedule.weekday.value,
                'open_time': schedule.open_time.strftime('%H:%M') if schedule.open_time else None,
                'end_time': schedule.end_time.strftime('%H:%M') if schedule.end_time else None,
                'is_closed': schedule.is_closed
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='create_schedule',
                resource_type='branch_schedule',
                resource_id=schedule.id,
                details=f"Criado horário para {schedule.weekday.value} na filial {branch.name}"
            )
            logger.info(f"Horário criado para {schedule.weekday.value} por user_id={user.id}")
            redis_client.delete(f"cache:schedules:{branch_id}")
            return jsonify({
                'message': 'Horário criado com sucesso',
                'schedule': {
                    'id': schedule.id,
                    'weekday': schedule.weekday.value,
                    'open_time': schedule.open_time.strftime('%H:%M') if schedule.open_time else None,
                    'end_time': schedule.end_time.strftime('%H:%M') if schedule.end_time else None,
                    'is_closed': schedule.is_closed
                }
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao criar horário: {str(e)}")
            return jsonify({'error': 'Erro interno ao criar horário'}), 500

    @app.route('/api/branch_admin/branches/<branch_id>/schedules', methods=['GET'])
    @require_auth
    def list_branch_schedules(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de listar horários por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        cache_key = f'schedules:{branch_id}'
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para horários {branch_id}: {str(e)}")

        try:
            schedules = BranchSchedule.query.filter_by(branch_id=branch_id).all()
            response = [{
                'id': s.id,
                'weekday': s.weekday.value,
                'open_time': s.open_time.strftime('%H:%M') if s.open_time else None,
                'end_time': s.end_time.strftime('%H:%M') if s.end_time else None,
                'is_closed': s.is_closed
            } for s in schedules]

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para horários {branch_id}: {str(e)}")

            logger.info(f"Admin {user.email} listou {len(response)} horários da filial {branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar horários para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar horários'}), 500

    @app.route('/api/branch_admin/branches/<branch_id>/report', methods=['GET'])
    @require_auth
    def branch_reports(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de gerar relatório por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        date_str = request.args.get('date')
        try:
            report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            logger.warning(f"Data inválida fornecida para relatório: {date_str}")
            return jsonify({'error': 'Data inválida. Use o formato AAAA-MM-DD'}), 400

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            queues = Queue.query.filter(Queue.department_id.in_(department_ids)).all()
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
                attended = len([t for t in tickets if t.status == 'Atendido'])
                service_times = [
                    t.service_time for t in tickets
                    if t.status == 'Atendido' and t.service_time is not None
                ]
                avg_time = sum(service_times) / len(service_times) if service_times else None

                report.append({
                    'queue_id': queue.id,
                    'service_name': queue.service.name if queue.service else 'N/A',
                    'department_name': queue.department.name if queue.department else 'N/A',
                    'issued': issued,
                    'attended': attended,
                    'avg_time': round(avg_time, 2) if avg_time else None
                })

            logger.info(f"Relatório gerado para {user.email} em {date_str}: {len(report)} filas")
            return jsonify(report), 200
        except Exception as e:
            logger.error(f"Erro ao gerar relatório para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao gerar relatório'}), 500

    @app.route('/api/branch_admin/branches/<branch_id>/dashboard', methods=['GET'])
    @require_auth
    def branch_dashboards(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de acessar painel por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        cache_key = f'dashboard:{branch_id}'
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para painel {branch_id}: {str(e)}")

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            queue_ids = [q.id for q in Queue.query.filter(Queue.department_id.in_(department_ids)).all()]
            now = datetime.now()
            current_weekday = now.strftime('%A').upper()
            current_time = now.time()

            # Status das filas
            queues = Queue.query.filter(Queue.department_id.in_(department_ids)).all()
            queue_status = []
            for q in queues:
                schedule = BranchSchedule.query.filter_by(branch_id=branch_id, weekday=current_weekday).first()
                is_open = False
                if schedule and not schedule.is_closed:
                    is_open = (
                        schedule.open_time and schedule.end_time and
                        current_time >= schedule.open_time and
                        current_time <= schedule.end_time and
                        q.active_tickets < q.daily_limit
                    )
                features = QueueService.get_wait_time_features(q.id, q.current_ticket + 1, 0)
                # Chamar predict com argumentos explícitos
                wait_time = wait_time_predictor.predict(
                    queue_id=q.id,
                    position=features['position'],
                    active_tickets=features['active_tickets'],
                    priority=features['priority'],
                    hour_of_day=features['hour_of_day'],
                    num_counters=features['num_counters'],
                    avg_service_time=features['avg_service_time'],
                    daily_limit=features['daily_limit'],
                    user_id=None,
                    user_lat=None,
                    user_lon=None,
                    user_service_preference=None
                )
                queue_status.append({
                    'queue_id': q.id,
                    'service_name': q.service.name if q.service else 'N/A',
                    'department_name': q.department.name if q.department else 'N/A',
                    'prefix': q.prefix,
                    'active_tickets': q.active_tickets,
                    'current_ticket': q.current_ticket,
                    'status': 'Aberto' if is_open else ('Lotado' if q.active_tickets >= q.daily_limit else 'Fechado'),
                    'avg_wait_time': round(q.avg_wait_time, 2) if q.avg_wait_time else None,
                    'estimated_wait_time': round(wait_time, 2) if isinstance(wait_time, (int, float)) else None
                })

            # Tickets recentes
            recent_tickets = Ticket.query.filter(
                Ticket.queue_id.in_(queue_ids),
                Ticket.status.in_(['Pendente', 'Chamado', 'Atendido'])
            ).order_by(Ticket.issued_at.desc()).limit(10).all()
            tickets_data = [{
                'ticket_id': t.id,
                'ticket_number': f"{t.queue.prefix}{t.ticket_number}" if t.queue else 'N/A',
                'service_name': t.queue.service.name if t.queue and t.queue.service else 'N/A',
                'department_name': t.queue.department.name if t.queue and t.queue.department else 'N/A',
                'status': t.status,
                'issued_at': t.issued_at.isoformat() if t.issued_at else None,
                'attended_at': t.attended_at.isoformat() if t.attended_at else None,
                'counter': f"Guichê {t.counter:02d}" if t.counter else 'N/A'
            } for t in recent_tickets]

            # Status dos atendentes
            attendants = User.query.filter_by(branch_id=branch_id, user_role=UserRole.ATTENDANT, active=True).all()
            attendants_data = [{
                'attendant_id': a.id,
                'name': a.name,
                'queues': [q.queue.prefix for q in AttendantQueue.query.filter_by(user_id=a.id).join(Queue).all()],
                'last_location_update': a.last_location_update.isoformat() if a.last_location_update else None
            } for a in attendants]

            # Métricas gerais
            total_tickets = Ticket.query.filter(Ticket.queue_id.in_(queue_ids)).count()
            pending_tickets = Ticket.query.filter(Ticket.queue_id.in_(queue_ids), Ticket.status == 'Pendente').count()
            attended_tickets = Ticket.query.filter(Ticket.queue_id.in_(queue_ids), Ticket.status == 'Atendido').count()

            response = {
                'branch_id': branch_id,
                'branch_name': branch.name,
                'queues': queue_status,
                'recent_tickets': tickets_data,
                'attendants': attendants_data,
                'metrics': {
                    'total_tickets': total_tickets,
                    'pending_tickets': pending_tickets,
                    'attended_tickets': attended_tickets,
                    'active_attendants': len(attendants)
                }
            }

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para painel {branch_id}: {str(e)}")

            logger.info(f"Painel de acompanhamento retornado para {user.email} na filial {branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao gerar painel para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao gerar painel'}), 500

    @app.route('/api/branch_admin/branches/<branch_id>/queues/totem', methods=['POST'])
    @require_auth
    def generate_totem_tickets(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            logger.warning(f"Tentativa não autorizada de emitir ticket via totem por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            logger.warning(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404

        data = request.get_json() or {}
        queue_id = data.get('queue_id')
        client_ip = request.remote_addr

        if not queue_id:
            logger.warning("queue_id não fornecido")
            return jsonify({'error': 'queue_id é obrigatório'}), 400

        queue = Queue.query.get(queue_id)
        department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
        if not queue or queue.department_id not in department_ids:
            logger.warning(f"Fila {queue_id} não encontrada ou não pertence à filial {branch_id}")
            return jsonify({'error': 'Fila não encontrada ou não pertence à filial'}), 404

        cache_key = f"totem:throttle:{client_ip}"
        if redis_client.get(cache_key):
            logger.warning(f"Limite de emissão atingido para IP {client_ip}")
            return jsonify({'error': 'Limite de emissão atingido. Tente novamente em 30 segundos'}), 429
        redis_client.setex(cache_key, 30, "1")

        try:
            ticket, pdf_buffer = QueueService.generate_physical_ticket_for_totem(queue_id=queue_id)
            emit_dashboard_update(
                branch_id=branch_id,
                queue_id=queue_id,
                event_type='ticket_issued',
                data={
                    'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                    'timestamp': ticket.issued_at.isoformat()
                }
            )
            AuditLog.create(
                user_id=user.id,
                action='generate_totem_ticket',
                resource_type='ticket',
                resource_id=ticket.id,
                details=f"Ticket físico {ticket.queue.prefix}{ticket.ticket_number} emitido via totem por {user.email}"
            )
            logger.info(f"Ticket físico emitido via totem: {ticket.queue.prefix}{ticket.ticket_number} (IP: {client_ip})")
            return send_file(
                io.BytesIO(pdf_buffer.getvalue()),
                as_attachment=True,
                download_name=f"ticket_{ticket.queue.prefix}{ticket.ticket_number}.pdf",
                mimetype='application/pdf'
            )
        except ValueError as e:
            logger.error(f"Erro ao emitir ticket via totem para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao emitir ticket via totem para queue_id={queue_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao emitir ticket'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao emitir ticket via totem: {str(e)}")
            return jsonify({'error': 'Erro interno ao emitir ticket'}), 500

    return app
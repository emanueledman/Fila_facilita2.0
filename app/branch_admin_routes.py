from flask import jsonify, request, send_file
from . import db, socketio, redis_client
from .models import AuditLog, User, Queue, Ticket, Department, Institution, UserRole, Branch, BranchSchedule, AttendantQueue, Weekday, InstitutionService
from .auth import require_auth
from .services import QueueService
from sqlalchemy.exc import SQLAlchemyError
import logging
import uuid
from datetime import datetime, timedelta
import re
import json
import io
import csv
from io import StringIO


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

    # Criar Departamento
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
        if not re.match(r'^[A-Za-zÀ-ÿ\s0-9.,\'-]{1,50}$', data['name']):
            logger.warning(f"Nome inválido para departamento: {data['name']}")
            return jsonify({'error': 'Nome do departamento inválido (use até 50 caracteres, incluindo letras, números e pontuação básica)'}), 400
        if not re.match(r'^[A-Za-zÀ-ÿ\s]{1,50}$', data['sector']):
            logger.warning(f"Setor inválido: {data['sector']}")
            return jsonify({'error': 'Setor inválido (use até 50 caracteres, apenas letras e espaços)'}), 400
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
            return jsonify({'error': f'Falha ao criar departamento: {str(e)}'}), 500

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
            return jsonify({'error': f'Erro ao listar departamentos: {str(e)}'}), 500

    # Editar Departamento
    @app.route('/api/branch_admin/branches/<branch_id>/departments/<department_id>', methods=['PUT'])
    @require_auth
    def update_branch_department(branch_id, department_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        department = Department.query.get(department_id)
        if not department or department.branch_id != branch_id:
            return jsonify({'error': 'Departamento não encontrado ou não pertence à filial'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Nenhum dado fornecido'}), 400

        if 'name' in data:
            if not re.match(r'^[A-Za-zÀ-ÿ\s0-9.,\'-]{1,50}$', data['name']):
                return jsonify({'error': 'Nome do departamento inválido'}), 400
            if Department.query.filter_by(branch_id=branch_id, name=data['name']).filter(Department.id != department_id).first():
                return jsonify({'error': 'Departamento com este nome já existe na filial'}), 400
            department.name = data['name']

        if 'sector' in data:
            if not re.match(r'^[A-Za-zÀ-ÿ\s]{1,50}$', data['sector']):
                return jsonify({'error': 'Setor inválido'}), 400
            department.sector = data['sector']

        try:
            db.session.commit()
            socketio.emit('department_updated', {
                'department_id': department.id,
                'name': department.name,
                'sector': department.sector,
                'branch_id': branch_id
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='update_department',
                resource_type='department',
                resource_id=department.id,
                details=f"Departamento {department.name} atualizado na filial {branch_id}"
            )
            redis_client.delete(f"cache:departments:{branch_id}")
            return jsonify({
                'message': 'Departamento atualizado com sucesso',
                'department': {
                    'id': department.id,
                    'name': department.name,
                    'sector': department.sector,
                    'branch_id': branch_id
                }
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar departamento: {str(e)}")
            return jsonify({'error': f'Erro ao atualizar departamento: {str(e)}'}), 500

    # Excluir Departamento
    @app.route('/api/branch_admin/branches/<branch_id>/departments/<department_id>', methods=['DELETE'])
    @require_auth
    def delete_branch_department(branch_id, department_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        department = Department.query.get(department_id)
        if not department or department.branch_id != branch_id:
            return jsonify({'error': 'Departamento não encontrado ou não pertence à filial'}), 404

        if Queue.query.filter_by(department_id=department_id).first():
            return jsonify({'error': 'Departamento possui filas associadas. Remova as filas primeiro'}), 400

        try:
            db.session.delete(department)
            db.session.commit()
            socketio.emit('department_deleted', {
                'department_id': department.id,
                'branch_id': branch_id
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='delete_department',
                resource_type='department',
                resource_id=department.id,
                details=f"Departamento {department.name} excluído na filial {branch_id}"
            )
            redis_client.delete(f"cache:departments:{branch_id}")
            return jsonify({'message': 'Departamento excluído com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao excluir departamento: {str(e)}")
            return jsonify({'error': f'Erro ao excluir departamento: {str(e)}'}), 500

    # Criar Fila
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
        if not re.match(r'^[A-Z0-9]{1,10}$', data['prefix']):
            logger.warning(f"Prefixo inválido: {data['prefix']}")
            return jsonify({'error': 'Prefixo deve conter letras maiúsculas ou números, até 10 caracteres'}), 400
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
            return jsonify({'error': f'Erro ao criar fila: {str(e)}'}), 500

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
                estimated_wait_time = q.avg_wait_time if q.avg_wait_time else 5.0  # Fallback para 5 minutos
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
                    'estimated_wait_time': round(estimated_wait_time, 2)
                })

            try:
                redis_client.setex(cache_key, 300, json.dumps(response))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para filas {branch_id}: {str(e)}")

            logger.info(f"Admin {user.email} listou {len(response)} filas da filial {branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar filas para user_id={user.id}: {str(e)}")
            return jsonify({'error': f'Erro ao listar filas: {str(e)}'}), 500

    # Editar Fila
    @app.route('/api/branch_admin/branches/<branch_id>/queues/<queue_id>', methods=['PUT'])
    @require_auth
    def update_branch_queue(branch_id, queue_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.branch_id != branch_id:
            return jsonify({'error': 'Fila não encontrada ou não pertence à filial'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Nenhum dado fornecido'}), 400

        if 'prefix' in data:
            if not re.match(r'^[A-Z0-9]{1,10}$', data['prefix']):
                return jsonify({'error': 'Prefixo deve conter letras maiúsculas ou números, até 10 caracteres'}), 400
            queue.prefix = data['prefix']

        if 'daily_limit' in data:
            if not isinstance(data['daily_limit'], int) or data['daily_limit'] < 1:
                return jsonify({'error': 'Limite diário deve ser um número inteiro maior que 0'}), 400
            queue.daily_limit = data['daily_limit']

        if 'num_counters' in data:
            if not isinstance(data['num_counters'], int) or data['num_counters'] < 1:
                return jsonify({'error': 'Número de guichês deve ser um número inteiro maior que 0'}), 400
            queue.num_counters = data['num_counters']

        try:
            db.session.commit()
            socketio.emit('queue_updated', {
                'queue_id': queue.id,
                'prefix': queue.prefix,
                'daily_limit': queue.daily_limit,
                'num_counters': queue.num_counters,
                'branch_id': branch_id
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='update_queue',
                resource_type='queue',
                resource_id=queue.id,
                details=f"Fila {queue.prefix} atualizada na filial {branch_id}"
            )
            redis_client.delete(f"cache:queues:{branch_id}")
            return jsonify({
                'message': 'Fila atualizada com sucesso',
                'queue': {
                    'id': queue.id,
                    'department_id': queue.department_id,
                    'service_id': queue.service_id,
                    'prefix': queue.prefix,
                    'daily_limit': queue.daily_limit,
                    'num_counters': queue.num_counters
                }
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar fila: {str(e)}")
            return jsonify({'error': f'Erro ao atualizar fila: {str(e)}'}), 500

    # Excluir Fila
    @app.route('/api/branch_admin/branches/<branch_id>/queues/<queue_id>', methods=['DELETE'])
    @require_auth
    def delete_branch_queue(branch_id, queue_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.branch_id != branch_id:
            return jsonify({'error': 'Fila não encontrada ou não pertence à filial'}), 404

        if Ticket.query.filter_by(queue_id=queue_id, status='Pendente').first():
            return jsonify({'error': 'Fila possui tickets pendentes. Cancele os tickets primeiro'}), 400

        try:
            db.session.delete(queue)
            db.session.commit()
            socketio.emit('queue_deleted', {
                'queue_id': queue.id,
                'branch_id': branch_id
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='delete_queue',
                resource_type='queue',
                resource_id=queue.id,
                details=f"Fila {queue.prefix} excluída na filial {branch_id}"
            )
            redis_client.delete(f"cache:queues:{branch_id}")
            return jsonify({'message': 'Fila excluída com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao excluir fila: {str(e)}")
            return jsonify({'error': f'Erro ao excluir fila: {str(e)}'}), 500

    # Pausar Fila
    @app.route('/api/branch_admin/branches/<branch_id>/queues/<queue_id>/pause', methods=['POST'])
    @require_auth
    def pause_queue(branch_id, queue_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.branch_id != branch_id:
            return jsonify({'error': 'Fila não encontrada ou não pertence à filial'}), 404

        try:
            queue.daily_limit = 0  # Impede novos tickets
            db.session.commit()
            socketio.emit('queue_paused', {
                'queue_id': queue.id,
                'branch_id': branch_id
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='pause_queue',
                resource_type='queue',
                resource_id=queue.id,
                details=f"Fila {queue.prefix} pausada por {user.email}"
            )
            redis_client.delete(f"cache:queues:{branch_id}")
            return jsonify({'message': 'Fila pausada com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao pausar fila: {str(e)}")
            return jsonify({'error': f'Erro ao pausar fila: {str(e)}'}), 500

    # Reabrir Fila
    @app.route('/api/branch_admin/branches/<branch_id>/queues/<queue_id>/resume', methods=['POST'])
    @require_auth
    def resume_queue(branch_id, queue_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        queue = Queue.query.get(queue_id)
        if not queue or queue.department.branch_id != branch_id:
            return jsonify({'error': 'Fila não encontrada ou não pertence à filial'}), 404

        data = request.get_json() or {}
        daily_limit = data.get('daily_limit', queue.daily_limit)
        if not isinstance(daily_limit, int) or daily_limit < 1:
            return jsonify({'error': 'Limite diário deve ser um número inteiro maior que 0'}), 400

        try:
            queue.daily_limit = daily_limit
            db.session.commit()
            socketio.emit('queue_resumed', {
                'queue_id': queue.id,
                'branch_id': branch_id,
                'daily_limit': queue.daily_limit
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='resume_queue',
                resource_type='queue',
                resource_id=queue.id,
                details=f"Fila {queue.prefix} reaberta por {user.email}"
            )
            redis_client.delete(f"cache:queues:{branch_id}")
            return jsonify({'message': 'Fila reaberta com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao reabrir fila: {str(e)}")
            return jsonify({'error': f'Erro ao reabrir fila: {str(e)}'}), 500

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

        # Parâmetros de filtro e paginação
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
            query = Ticket.query.filter(Ticket.queue_id.in_([q.id for q in Queue.query.filter(Queue.department_id.in_(department_ids)).all()]))
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

            logger.info(f"Admin {user.email} listou {len(response['tickets'])} tickets da filial {branch_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar tickets para user_id={user.id}: {str(e)}")
            return jsonify({'error': f'Erro ao listar tickets: {str(e)}'}), 500

    # Cancelar Ticket
    @app.route('/api/branch_admin/branches/<branch_id>/tickets/<ticket_id>/cancel', methods=['POST'])
    @require_auth
    def cancel_tickets(branch_id, ticket_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        ticket = Ticket.query.get(ticket_id)
        if not ticket or ticket.queue.department.branch_id != branch_id:
            return jsonify({'error': 'Ticket não encontrado ou não pertence à filial'}), 404

        if ticket.status != 'Pendente':
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
            AuditLog.create(
                user_id=user.id,
                action='cancel_ticket',
                resource_type='ticket',
                resource_id=ticket.id,
                details=f"Ticket {ticket.queue.prefix}{ticket.ticket_number} cancelado por {user.email}"
            )
            redis_client.delete(f"cache:tickets:{branch_id}")
            return jsonify({'message': 'Ticket cancelado com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao cancelar ticket: {str(e)}")
            return jsonify({'error': f'Erro ao cancelar ticket: {str(e)}'}), 500

    # Criar Atendente
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
            return jsonify({'error': 'Nome inválido (use até 100 caracteres, apenas letras e espaços)'}), 400
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
            return jsonify({'error': f'Erro ao criar atendente: {str(e)}'}), 500

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
            return jsonify({'error': f'Erro ao listar atendentes: {str(e)}'}), 500

    # Editar Atendente
    @app.route('/api/branch_admin/branches/<branch_id>/attendants/<attendant_id>', methods=['PUT'])
    @require_auth
    def update_branch_attendant(branch_id, attendant_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        attendant = User.query.get(attendant_id)
        if not attendant or attendant.branch_id != branch_id or attendant.user_role != UserRole.ATTENDANT:
            return jsonify({'error': 'Atendente não encontrado ou não pertence à filial'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Nenhum dado fornecido'}), 400

        if 'email' in data:
            if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', data['email']):
                return jsonify({'error': 'Email inválido'}), 400
            if User.query.filter_by(email=data['email']).filter(User.id != attendant_id).first():
                return jsonify({'error': 'Email já está em uso'}), 400
            attendant.email = data['email']

        if 'name' in data:
            if not re.match(r'^[A-Za-zÀ-ÿ\s]{1,100}$', data['name']):
                return jsonify({'error': 'Nome inválido'}), 400
            attendant.name = data['name']

        if 'password' in data:
            if len(data['password']) < 8:
                return jsonify({'error': 'A senha deve ter pelo menos 8 caracteres'}), 400
            attendant.set_password(data['password'])

        if 'active' in data:
            if not isinstance(data['active'], bool):
                return jsonify({'error': 'O campo active deve ser um booleano'}), 400
            attendant.active = data['active']

        try:
            db.session.commit()
            socketio.emit('attendant_updated', {
                'user_id': attendant.id,
                'email': attendant.email,
                'name': attendant.name,
                'active': attendant.active,
                'branch_id': branch_id
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='update_attendant',
                resource_type='user',
                resource_id=attendant.id,
                details=f"Atendente {attendant.email} atualizado na filial {branch_id}"
            )
            redis_client.delete(f"cache:attendants:{branch_id}")
            return jsonify({
                'message': 'Atendente atualizado com sucesso',
                'user': {
                    'id': attendant.id,
                    'email': attendant.email,
                    'name': attendant.name,
                    'active': attendant.active,
                    'branch_id': branch_id
                }
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar atendente: {str(e)}")
            return jsonify({'error': f'Erro ao atualizar atendente: {str(e)}'}), 500

    # Atribuir Atendente à Fila
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
            return jsonify({'error': f'Erro ao atribuir atendente: {str(e)}'}), 500

    # Criar Horário
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
            return jsonify({'error': f'Erro ao criar horário: {str(e)}'}), 500

    # Listar Horários
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
            return jsonify({'error': f'Erro ao listar horários: {str(e)}'}), 500

    # Editar Horário
    @app.route('/api/branch_admin/branches/<branch_id>/schedules/<schedule_id>', methods=['PUT'])
    @require_auth
    def update_branch_schedule(branch_id, schedule_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        schedule = BranchSchedule.query.get(schedule_id)
        if not schedule or schedule.branch_id != branch_id:
            return jsonify({'error': 'Horário não encontrado ou não pertence à filial'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Nenhum dado fornecido'}), 400

        if 'open_time' in data and 'end_time' in data:
            if not data.get('is_closed', schedule.is_closed):
                try:
                    open_time = datetime.strptime(data['open_time'], '%H:%M').time()
                    end_time = datetime.strptime(data['end_time'], '%H:%M').time()
                    if open_time >= end_time:
                        return jsonify({'error': 'Horário de abertura deve ser anterior ao horário de fechamento'}), 400
                    schedule.open_time = open_time
                    schedule.end_time = end_time
                except ValueError:
                    return jsonify({'error': 'Formato de horário inválido (use HH:MM)'}), 400
            else:
                schedule.open_time = None
                schedule.end_time = None

        if 'is_closed' in data:
            if not isinstance(data['is_closed'], bool):
                return jsonify({'error': 'O campo is_closed deve ser um booleano'}), 400
            schedule.is_closed = data['is_closed']
            if data['is_closed']:
                schedule.open_time = None
                schedule.end_time = None

        try:
            db.session.commit()
            socketio.emit('schedule_updated', {
                'schedule_id': schedule.id,
                'branch_id': branch_id,
                'weekday': schedule.weekday.value,
                'open_time': schedule.open_time.strftime('%H:%M') if schedule.open_time else None,
                'end_time': schedule.end_time.strftime('%H:%M') if schedule.end_time else None,
                'is_closed': schedule.is_closed
            }, namespace='/branch_admin')
            AuditLog.create(
                user_id=user.id,
                action='update_schedule',
                resource_type='branch_schedule',
                resource_id=schedule.id,
                details=f"Horário para {schedule.weekday.value} atualizado na filial {branch_id}"
            )
            redis_client.delete(f"cache:schedules:{branch_id}")
            return jsonify({
                'message': 'Horário atualizado com sucesso',
                'schedule': {
                    'id': schedule.id,
                    'weekday': schedule.weekday.value,
                    'open_time': schedule.open_time.strftime('%H:%M') if schedule.open_time else None,
                    'end_time': schedule.end_time.strftime('%H:%M') if schedule.end_time else None,
                    'is_closed': schedule.is_closed
                }
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar horário: {str(e)}")
            return jsonify({'error': f'Erro ao atualizar horário: {str(e)}'}), 500

    # Gerar Relatório
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
            return jsonify({'error': f'Erro ao gerar relatório: {str(e)}'}), 500

    # Exportar Relatório em CSV
    @app.route('/api/branch_admin/branches/<branch_id>/report/export', methods=['GET'])
    @require_auth
    def export_branch_report(branch_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.BRANCH_ADMIN or user.branch_id != branch_id:
            return jsonify({'error': 'Acesso restrito a administradores da filial'}), 403

        branch = Branch.query.get(branch_id)
        if not branch:
            return jsonify({'error': 'Filial não encontrada'}), 404

        date_str = request.args.get('date')
        try:
            report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return jsonify({'error': 'Data inválida. Use o formato AAAA-MM-DD'}), 400

        try:
            department_ids = [d.id for d in Department.query.filter_by(branch_id=branch_id).all()]
            queues = Queue.query.filter(Queue.department_id.in_(department_ids)).all()
            queue_ids = [q.id for q in queues]
            start_time = datetime.combine(report_date, datetime.min.time())
            end_time = start_time + timedelta(days=1)

            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(['Queue ID', 'Service Name', 'Department Name', 'Issued Tickets', 'Attended Tickets', 'Avg Service Time'])
            
            for queue in queues:
                tickets = Ticket.query.filter(
                    Ticket.queue_id == queue.id,
                    Ticket.issued_at >= start_time,
                    Ticket.issued_at < end_time
                ).all()
                issued = len(tickets)
                attended = len([t for t in tickets if t.status == 'Atendido'])
                service_times = [t.service_time for t in tickets if t.status == 'Atendido' and t.service_time is not None]
                avg_time = sum(service_times) / len(service_times) if service_times else None
                writer.writerow([
                    queue.id,
                    queue.service.name if queue.service else 'N/A',
                    queue.department.name if queue.department else 'N/A',
                    issued,
                    attended,
                    round(avg_time, 2) if avg_time else 'N/A'
                ])

            logger.info(f"Relatório CSV exportado para {user.email} em {date_str}")
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                as_attachment=True,
                download_name=f"report_{branch_id}_{date_str}.csv",
                mimetype='text/csv'
            )
        except Exception as e:
            logger.error(f"Erro ao exportar relatório para user_id={user.id}: {str(e)}")
            return jsonify({'error': f'Erro ao exportar relatório: {str(e)}'}), 500

    # Painel de Controle
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
                estimated_wait_time = q.avg_wait_time if q.avg_wait_time else 5.0  # Fallback para 5 minutos
                queue_status.append({
                    'queue_id': q.id,
                    'service_name': q.service.name if q.service else 'N/A',
                    'department_name': q.department.name if q.department else 'N/A',
                    'prefix': q.prefix,
                    'active_tickets': q.active_tickets,
                    'current_ticket': q.current_ticket,
                    'status': 'Aberto' if is_open else ('Lotado' if q.active_tickets >= q.daily_limit else 'Fechado'),
                    'avg_wait_time': round(q.avg_wait_time, 2) if q.avg_wait_time else None,
                    'estimated_wait_time': round(estimated_wait_time, 2)
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
                'queues': [q.prefix for q in a.queues.all()],
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
            return jsonify({'error': f'Erro ao gerar painel: {str(e)}'}), 500


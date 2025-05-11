from flask import jsonify, request, send_file
from . import db, socketio, redis_client
from .models import AuditLog, InstitutionType, User, Queue, Ticket, Department, Institution, UserRole, Branch, ServiceCategory, ServiceTag, UserPreference, BranchSchedule, AttendantQueue, InstitutionService, Weekday
from .auth import require_auth
from .services import QueueService
from .ml_models import wait_time_predictor
import logging
import uuid
from datetime import datetime, timedelta
from sqlalchemy import func
import bcrypt
import io
import json
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_admin_routes(app):
    # Sanitiza entradas
    def sanitize_input(input_str):
        if not isinstance(input_str, str):
            return ''
        return re.sub(r'[<>]', '', input_str).strip()

    # Valida email
    def validate_email(email):
        pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
        return bool(re.match(pattern, email))

    # Valida nome e setor
    def validate_name_or_sector(value, max_length=50):
        pattern = r'^[A-Za-zÀ-ÿ\s0-9.,-]{1,' + str(max_length) + '}$'
        return bool(re.match(pattern, value))

    # Rota para obter informações do usuário
    @app.route('/api/admin/user', methods=['GET'])
    @require_auth
    def get_user_info():
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        logger.info(f"Informações do usuário {user.email} retornadas")
        return jsonify({
            'id': user.id,
            'email': user.email,
            'name': user.name,
            'user_role': user.user_role.value,
            'institution_id': user.institution_id,
            'branch_id': user.branch_id,
            'created_at': user.created_at.isoformat()
        }), 200

    # Rota para listar instituições
    @app.route('/api/admin/institutions', methods=['GET'])
    @require_auth
    def list_institutions():
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role != UserRole.SYSTEM_ADMIN:
            logger.warning(f"Usuário {request.user_id} tentou acessar lista de instituições sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores do sistema'}), 403
        
        institutions = Institution.query.join(InstitutionType).all()
        response = [{
            'id': i.id,
            'name': i.name,
            'type': i.type.name,
            'description': i.description,
            'logo_url': i.logo_url,
            'max_branches': i.max_branches,
            'created_at': i.created_at.isoformat()
        } for i in institutions]
        
        logger.info(f"Listadas {len(institutions)} instituições para usuário {request.user_id}")
        return jsonify(response), 200

    # Rota para criar instituição
    @app.route('/api/admin/institutions', methods=['POST'])
    @require_auth
    def create_institution():
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role != UserRole.SYSTEM_ADMIN:
            logger.warning(f"Usuário {request.user_id} tentou criar instituição sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores do sistema'}), 403
        
        data = request.get_json()
        required = ['name', 'institution_type_id', 'max_branches']
        if not data or not all(f in data for f in required):
            logger.error("Campos obrigatórios faltando na criação de instituição")
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400
        
        name = sanitize_input(data['name'])
        if not validate_name_or_sector(name, 100):
            logger.error(f"Nome inválido fornecido: {name}")
            return jsonify({'error': 'Nome inválido'}), 400
        
        if Institution.query.filter_by(name=name).first():
            logger.error(f"Instituição com nome {name} já existe")
            return jsonify({'error': 'Instituição com este nome já existe'}), 400
        
        institution_type = InstitutionType.query.get(data['institution_type_id'])
        if not institution_type:
            logger.error(f"Tipo de instituição {data['institution_type_id']} inválido")
            return jsonify({'error': 'Tipo de instituição inválido'}), 400
        
        institution = Institution(
            id=str(uuid.uuid4()),
            name=name,
            institution_type_id=data['institution_type_id'],
            description=sanitize_input(data.get('description', '')),
            logo_url=sanitize_input(data.get('logo_url', '')),
            max_branches=int(data['max_branches'])
        )
        db.session.add(institution)
        db.session.commit()
        
        socketio.emit('institution_created', {
            'id': institution.id,
            'name': institution.name
        }, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='create_institution',
            resource_type='institution',
            resource_id=institution.id,
            details=f"Criada instituição {institution.name}"
        )
        
        logger.info(f"Instituição {institution.name} criada por usuário {request.user_id}")
        return jsonify({
            'message': 'Instituição criada com sucesso',
            'institution': {
                'id': institution.id,
                'name': institution.name
            }
        }), 201

    # Rota para listar departamentos
    @app.route('/api/admin/institutions/<institution_id>/departments', methods=['GET'])
    @require_auth
    def list_departments(institution_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou listar departamentos sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        institution = Institution.query.get(institution_id)
        if not institution:
            logger.error(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN and user.institution_id != institution_id:
            logger.warning(f"Usuário {request.user_id} tentou acessar departamentos de outra instituição")
            return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        
        query = Department.query.join(Branch).filter(Branch.institution_id == institution_id)
        if user.user_role == UserRole.BRANCH_ADMIN:
            query = query.filter(Branch.id == user.branch_id)
        
        departments = query.all()
        response = [{
            'id': d.id,
            'name': d.name,
            'sector': d.sector,
            'branch_id': d.branch_id,
            'branch_name': d.branch.name
        } for d in departments]
        
        logger.info(f"Listados {len(departments)} departamentos para instituição {institution_id}")
        return jsonify(response), 200

    # Rota para criar departamento
    @app.route('/api/admin/institutions/<institution_id>/departments', methods=['POST'])
    @require_auth
    def create_department(institution_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou criar departamento sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        institution = Institution.query.get(institution_id)
        if not institution:
            logger.error(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN and user.institution_id != institution_id:
            logger.warning(f"Usuário {request.user_id} tentou criar departamento em outra instituição")
            return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        
        data = request.get_json()
        required = ['name', 'sector', 'branch_id']
        if not data or not all(f in data for f in required):
            logger.error("Campos obrigatórios faltando na criação de departamento")
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400
        
        name = sanitize_input(data['name'])
        sector = sanitize_input(data['sector'])
        branch_id = data['branch_id']
        
        if not validate_name_or_sector(name, 50) or not validate_name_or_sector(sector, 50):
            logger.error(f"Nome ou setor inválido: {name}, {sector}")
            return jsonify({'error': 'Nome ou setor inválido'}), 400
        
        branch = Branch.query.get(branch_id)
        if not branch or branch.institution_id != institution_id:
            logger.error(f"Filial {branch_id} inválida para instituição {institution_id}")
            return jsonify({'error': 'Filial inválida'}), 400
        
        if user.user_role == UserRole.BRANCH_ADMIN and branch_id != user.branch_id:
            logger.warning(f"Usuário {request.user_id} tentou criar departamento em outra filial")
            return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        
        if Department.query.filter_by(branch_id=branch_id, name=name).first():
            logger.error(f"Departamento com nome {name} já existe na filial {branch_id}")
            return jsonify({'error': 'Departamento com este nome já existe na filial'}), 400
        
        department = Department(
            id=str(uuid.uuid4()),
            branch_id=branch_id,
            name=name,
            sector=sector
        )
        db.session.add(department)
        db.session.commit()
        
        socketio.emit('department_created', {
            'department_id': department.id,
            'name': department.name,
            'sector': department.sector,
            'branch_id': department.branch_id
        }, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='create_department',
            resource_type='department',
            resource_id=department.id,
            details=f"Criado departamento {department.name} na filial {branch.name}"
        )
        
        logger.info(f"Departamento {department.name} criado por usuário {request.user_id}")
        return jsonify({
            'message': 'Departamento criado com sucesso',
            'department': {
                'id': department.id,
                'name': department.name,
                'sector': department.sector,
                'branch_id': department.branch_id
            }
        }), 201

    # Rota para atualizar departamento
    @app.route('/api/admin/institutions/<institution_id>/departments/<department_id>', methods=['PUT'])
    @require_auth
    def update_department(institution_id, department_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou atualizar departamento sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        institution = Institution.query.get(institution_id)
        if not institution:
            logger.error(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404
        
        department = Department.query.get(department_id)
        if not department or department.branch.institution_id != institution_id:
            logger.error(f"Departamento {department_id} não encontrado")
            return jsonify({'error': 'Departamento não encontrado'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if user.institution_id != institution_id or department.branch_id != user.branch_id:
                logger.warning(f"Usuário {request.user_id} tentou atualizar departamento de outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        
        data = request.get_json()
        if not data:
            logger.error("Nenhum dado fornecido para atualização de departamento")
            return jsonify({'error': 'Nenhum dado fornecido'}), 400
        
        if 'name' in data:
            name = sanitize_input(data['name'])
            if not validate_name_or_sector(name, 50):
                logger.error(f"Nome inválido: {name}")
                return jsonify({'error': 'Nome inválido'}), 400
            if Department.query.filter_by(branch_id=department.branch_id, name=name).filter(Department.id != department_id).first():
                logger.error(f"Departamento com nome {name} já existe na filial {department.branch_id}")
                return jsonify({'error': 'Departamento com este nome já existe na filial'}), 400
            department.name = name
        
        if 'sector' in data:
            sector = sanitize_input(data['sector'])
            if not validate_name_or_sector(sector, 50):
                logger.error(f"Setor inválido: {sector}")
                return jsonify({'error': 'Setor inválido'}), 400
            department.sector = sector
        
        db.session.commit()
        
        socketio.emit('department_updated', {
            'department_id': department.id,
            'name': department.name,
            'sector': department.sector,
            'branch_id': department.branch_id
        }, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='update_department',
            resource_type='department',
            resource_id=department.id,
            details=f"Atualizado departamento {department.name}"
        )
        
        logger.info(f"Departamento {department.name} atualizado por usuário {request.user_id}")
        return jsonify({
            'message': 'Departamento atualizado com sucesso',
            'department': {
                'id': department.id,
                'name': department.name,
                'sector': department.sector,
                'branch_id': department.branch_id
            }
        }), 200

    # Rota para excluir departamento
    @app.route('/api/admin/institutions/<institution_id>/departments/<department_id>', methods=['DELETE'])
    @require_auth
    def delete_department(institution_id, department_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou excluir departamento sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        institution = Institution.query.get(institution_id)
        if not institution:
            logger.error(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404
        
        department = Department.query.get(department_id)
        if not department or department.branch.institution_id != institution_id:
            logger.error(f"Departamento {department_id} não encontrado")
            return jsonify({'error': 'Departamento não encontrado'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if user.institution_id != institution_id or department.branch_id != user.branch_id:
                logger.warning(f"Usuário {request.user_id} tentou excluir departamento de outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        
        if Queue.query.filter_by(department_id=department_id).first():
            logger.error(f"Departamento {department_id} possui filas associadas")
            return jsonify({'error': 'Não é possível excluir: departamento possui filas associadas'}), 400
        
        db.session.delete(department)
        db.session.commit()
        
        socketio.emit('department_deleted', {
            'department_id': department_id,
            'name': department.name
        }, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='delete_department',
            resource_type='department',
            resource_id=department_id,
            details=f"Excluído departamento {department.name}"
        )
        
        logger.info(f"Departamento {department.name} excluído por usuário {request.user_id}")
        return jsonify({'message': 'Departamento excluído com sucesso'}), 200

    # Rota para listar filas
    @app.route('/api/admin/queues', methods=['GET'])
    @require_auth
    def list_queues():
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou listar filas sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        query = Queue.query.join(Department).join(Branch)
        if user.user_role == UserRole.BRANCH_ADMIN:
            query = query.filter(Branch.id == user.branch_id)
        elif user.user_role == UserRole.INSTITUTION_ADMIN:
            query = query.filter(Branch.institution_id == user.institution_id)
        
        queues = query.all()
        response = [{
            'id': q.id,
            'service': q.service.name,
            'prefix': q.prefix,
            'daily_limit': q.daily_limit,
            'active_tickets': q.active_tickets,
            'current_ticket': q.current_ticket,
            'department_id': q.department_id,
            'department': q.department.name,
            'service_id': q.service_id,
            'status': 'Aberto' if q.active_tickets > 0 else 'Fechado'
        } for q in queues]
        
        logger.info(f"Listadas {len(queues)} filas para usuário {request.user_id}")
        return jsonify(response), 200

    # Rota para criar fila
    @app.route('/api/admin/queues', methods=['POST'])
    @require_auth
    def create_queue():
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou criar fila sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        data = request.get_json()
        required = ['service_id', 'prefix', 'daily_limit', 'department_id']
        if not data or not all(f in data for f in required):
            logger.error("Campos obrigatórios faltando na criação de fila")
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400
        
        department = Department.query.get(data['department_id'])
        if not department:
            logger.error(f"Departamento {data['department_id']} inválido")
            return jsonify({'error': 'Departamento inválido'}), 400
        
        service = InstitutionService.query.get(data['service_id'])
        if not service or service.institution_id != department.branch.institution_id:
            logger.error(f"Serviço {data['service_id']} inválido")
            return jsonify({'error': 'Serviço inválido'}), 400
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if department.branch_id != user.branch_id or department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} tentou criar fila em outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        elif user.user_role == UserRole.INSTITUTION_ADMIN:
            if department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} tentou criar fila em outra instituição")
                return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        
        prefix = sanitize_input(data['prefix'])
        if not re.match(r'^[A-Za-z0-9]{1,10}$', prefix):
            logger.error(f"Prefixo inválido: {prefix}")
            return jsonify({'error': 'Prefixo inválido (máximo 10 caracteres alfanuméricos)'}), 400
        
        daily_limit = int(data['daily_limit'])
        if daily_limit < 1:
            logger.error(f"Limite diário inválido: {daily_limit}")
            return jsonify({'error': 'Limite diário deve ser maior que 0'}), 400
        
        queue = Queue(
            id=str(uuid.uuid4()),
            department_id=data['department_id'],
            service_id=data['service_id'],
            prefix=prefix,
            daily_limit=daily_limit,
            active_tickets=0,
            current_ticket=0
        )
        db.session.add(queue)
        db.session.commit()
        
        socketio.emit('queue_updated', {'queue_id': queue.id}, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='create_queue',
            resource_type='queue',
            resource_id=queue.id,
            details=f"Criada fila {queue.service.name} no departamento {department.name}"
        )
        
        logger.info(f"Fila {queue.service.name} criada por usuário {request.user_id}")
        return jsonify({
            'message': 'Fila criada com sucesso',
            'queue': {
                'id': queue.id,
                'service': queue.service.name,
                'prefix': queue.prefix,
                'daily_limit': queue.daily_limit
            }
        }), 201

    # Rota para atualizar fila
    @app.route('/api/admin/queues/<queue_id>', methods=['PUT'])
    @require_auth
    def update_queue(queue_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou atualizar fila sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        queue = Queue.query.get(queue_id)
        if not queue:
            logger.error(f"Fila {queue_id} não encontrada")
            return jsonify({'error': 'Fila não encontrada'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if queue.department.branch_id != user.branch_id or queue.department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} tentou atualizar fila de outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        elif user.user_role == UserRole.INSTITUTION_ADMIN:
            if queue.department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} tentou atualizar fila de outra instituição")
                return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        
        data = request.get_json()
        if not data:
            logger.error("Nenhum dado fornecido para atualização de fila")
            return jsonify({'error': 'Nenhum dado fornecido'}), 400
        
        if 'prefix' in data:
            prefix = sanitize_input(data['prefix'])
            if not re.match(r'^[A-Za-z0-9]{1,10}$', prefix):
                logger.error(f"Prefixo inválido: {prefix}")
                return jsonify({'error': 'Prefixo inválido (máximo 10 caracteres alfanuméricos)'}), 400
            queue.prefix = prefix
        
        if 'daily_limit' in data:
            daily_limit = int(data['daily_limit'])
            if daily_limit < 1:
                logger.error(f"Limite diário inválido: {daily_limit}")
                return jsonify({'error': 'Limite diário deve ser maior que 0'}), 400
            queue.daily_limit = daily_limit
        
        if 'department_id' in data:
            department = Department.query.get(data['department_id'])
            if not department or department.branch.institution_id != queue.department.branch.institution_id:
                logger.error(f"Departamento {data['department_id']} inválido")
                return jsonify({'error': 'Departamento inválido'}), 400
            queue.department_id = data['department_id']
        
        if 'service_id' in data:
            service = InstitutionService.query.get(data['service_id'])
            if not service or service.institution_id != queue.department.branch.institution_id:
                logger.error(f"Serviço {data['service_id']} inválido")
                return jsonify({'error': 'Serviço inválido'}), 400
            queue.service_id = data['service_id']
        
        db.session.commit()
        
        socketio.emit('queue_updated', {'queue_id': queue.id}, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='update_queue',
            resource_type='queue',
            resource_id=queue.id,
            details=f"Atualizada fila {queue.service.name}"
        )
        
        logger.info(f"Fila {queue.service.name} atualizada por usuário {request.user_id}")
        return jsonify({
            'message': 'Fila atualizada com sucesso',
            'queue': {
                'id': queue.id,
                'service': queue.service.name,
                'prefix': queue.prefix,
                'daily_limit': queue.daily_limit
            }
        }), 200

    # Rota para excluir fila
    @app.route('/api/admin/queues/<queue_id>', methods=['DELETE'])
    @require_auth
    def delete_queue(queue_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou excluir fila sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        queue = Queue.query.get(queue_id)
        if not queue:
            logger.error(f"Fila {queue_id} não encontrada")
            return jsonify({'error': 'Fila não encontrada'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if queue.department.branch_id != user.branch_id or queue.department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} tentou excluir fila de outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        elif user.user_role == UserRole.INSTITUTION_ADMIN:
            if queue.department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} tentou excluir fila de outra instituição")
                return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        
        if Ticket.query.filter_by(queue_id=queue_id, status='Pendente').first():
            logger.error(f"Fila {queue_id} possui tickets pendentes")
            return jsonify({'error': 'Não é possível excluir: fila possui tickets pendentes'}), 400
        
        db.session.delete(queue)
        db.session.commit()
        
        socketio.emit('queue_deleted', {'queue_id': queue_id}, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='delete_queue',
            resource_type='queue',
            resource_id=queue_id,
            details=f"Excluída fila {queue.service.name}"
        )
        
        logger.info(f"Fila {queue.service.name} excluída por usuário {request.user_id}")
        return jsonify({'message': 'Fila excluída com sucesso'}), 200

    # Rota para chamar próximo ticket
    @app.route('/api/admin/queue/<queue_id>/call', methods=['POST'])
    @require_auth
    def call_next_ticket(queue_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        queue = Queue.query.get(queue_id)
        if not queue:
            logger.error(f"Fila {queue_id} não encontrada")
            return jsonify({'error': 'Fila não encontrada'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if queue.department.branch_id != user.branch_id or queue.department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} tentou chamar ticket de outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        elif user.user_role == UserRole.INSTITUTION_ADMIN:
            if queue.department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} tentou chamar ticket de outra instituição")
                return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        elif user.user_role != UserRole.SYSTEM_ADMIN:
            logger.warning(f"Usuário {request.user_id} sem permissão para chamar ticket")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        ticket = QueueService.call_next_ticket(queue)
        if not ticket:
            logger.info(f"Nenhum ticket pendente na fila {queue_id}")
            return jsonify({'error': 'Nenhum ticket pendente na fila'}), 400
        
        ticket.status = 'Atendido'
        ticket.attended_at = datetime.utcnow()
        ticket.counter = (queue.last_counter % queue.num_counters) + 1
        queue.last_counter = ticket.counter
        queue.active_tickets -= 1
        
        service_time = (datetime.utcnow() - ticket.issued_at).total_seconds() / 60.0
        queue.last_service_time = service_time
        queue.estimated_wait_time = wait_time_predictor.predict(queue)
        
        db.session.commit()
        
        socketio.emit('queue_updated', {'queue_id': queue.id}, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='call_ticket',
            resource_type='ticket',
            resource_id=ticket.id,
            details=f"Chamado ticket {ticket.ticket_number} na fila {queue.service.name}"
        )
        
        logger.info(f"Ticket {ticket.ticket_number} chamado na fila {queue_id} por usuário {request.user_id}")
        return jsonify({
            'message': 'Ticket chamado com sucesso',
            'ticket': {
                'id': ticket.id,
                'ticket_number': ticket.ticket_number,
                'counter': ticket.counter
            }
        }), 200

    # Rota para listar gestores
    @app.route('/api/admin/institutions/<institution_id>/managers', methods=['GET'])
    @require_auth
    def list_managers(institution_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou listar gestores sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        institution = Institution.query.get(institution_id)
        if not institution:
            logger.error(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN and user.institution_id != institution_id:
            logger.warning(f"Usuário {request.user_id} tentou listar gestores de outra instituição")
            return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        
        query = User.query.filter(
            User.institution_id == institution_id,
            User.user_role.in_([UserRole.ATTENDANT, UserRole.BRANCH_ADMIN])
        )
        if user.user_role == UserRole.BRANCH_ADMIN:
            query = query.filter(User.branch_id == user.branch_id)
        
        managers = query.all()
        response = [{
            'id': m.id,
            'name': m.name,
            'email': m.email,
            'user_role': m.user_role.value,
            'branch_id': m.branch_id,
            'branch_name': m.branch.name if m.branch else None
        } for m in managers]
        
        logger.info(f"Listados {len(managers)} gestores para instituição {institution_id}")
        return jsonify(response), 200

    # Rota para criar gestor
    @app.route('/api/admin/institutions/<institution_id>/managers', methods=['POST'])
    @require_auth
    def create_manager(institution_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou criar gestor sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        institution = Institution.query.get(institution_id)
        if not institution:
            logger.error(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN and user.institution_id != institution_id:
            logger.warning(f"Usuário {request.user_id} tentou criar gestor em outra instituição")
            return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        
        data = request.get_json()
        required = ['name', 'email', 'password', 'user_role', 'branch_id']
        if not data or not all(f in data for f in required):
            logger.error("Campos obrigatórios faltando na criação de gestor")
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400
        
        name = sanitize_input(data['name'])
        email = sanitize_input(data['email'])
        password = data['password']
        user_role = data['user_role']
        branch_id = data['branch_id']
        
        if not validate_name_or_sector(name, 100):
            logger.error(f"Nome inválido: {name}")
            return jsonify({'error': 'Nome inválido'}), 400
        
        if not validate_email(email):
            logger.error(f"Email inválido: {email}")
            return jsonify({'error': 'Email inválido'}), 400
        
        if len(password) < 8:
            logger.error("Senha muito curta")
            return jsonify({'error': 'A senha deve ter pelo menos 8 caracteres'}), 400
        
        if user_role not in ['attendant', 'branch_admin']:
            logger.error(f"Papel inválido: {user_role}")
            return jsonify({'error': 'Papel inválido'}), 400
        
        branch = Branch.query.get(branch_id)
        if not branch or branch.institution_id != institution_id:
            logger.error(f"Filial {branch_id} inválida")
            return jsonify({'error': 'Filial inválida'}), 400
        
        if user.user_role == UserRole.BRANCH_ADMIN and branch_id != user.branch_id:
            logger.warning(f"Usuário {request.user_id} tentou criar gestor em outra filial")
            return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        
        if User.query.filter_by(email=email).first():
            logger.error(f"Email {email} já registrado")
            return jsonify({'error': 'Email já registrado'}), 400
        
        new_user = User(
            id=str(uuid.uuid4()),
            email=email,
            name=name,
            user_role=UserRole(user_role),
            institution_id=institution_id,
            branch_id=branch_id,
            active=True
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        
        socketio.emit('user_created', {
            'user_id': new_user.id,
            'name': new_user.name,
            'email': new_user.email
        }, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='create_user',
            resource_type='user',
            resource_id=new_user.id,
            details=f"Criado usuário {new_user.email} com papel {new_user.user_role.value}"
        )
        
        logger.info(f"Gestor {new_user.email} criado por usuário {request.user_id}")
        return jsonify({
            'message': 'Gestor criado com sucesso',
            'user': {
                'id': new_user.id,
                'email': new_user.email,
                'name': new_user.name,
                'user_role': new_user.user_role.value
            }
        }), 201

    # Rota para atualizar gestor
    @app.route('/api/admin/institutions/<institution_id>/users/<user_id>', methods=['PUT'])
    @require_auth
    def update_manager(institution_id, user_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou atualizar gestor sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        institution = Institution.query.get(institution_id)
        if not institution:
            logger.error(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404
        
        target_user = User.query.get(user_id)
        if not target_user or target_user.institution_id != institution_id:
            logger.error(f"Usuário {user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if user.institution_id != institution_id or target_user.branch_id != user.branch_id:
                logger.warning(f"Usuário {request.user_id} tentou atualizar gestor de outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        
        data = request.get_json()
        if not data:
            logger.error("Nenhum dado fornecido para atualização de gestor")
            return jsonify({'error': 'Nenhum dado fornecido'}), 400
        
        if 'name' in data:
            name = sanitize_input(data['name'])
            if not validate_name_or_sector(name, 100):
                logger.error(f"Nome inválido: {name}")
                return jsonify({'error': 'Nome inválido'}), 400
            target_user.name = name
        
        if 'email' in data:
            email = sanitize_input(data['email'])
            if not validate_email(email):
                logger.error(f"Email inválido: {email}")
                return jsonify({'error': 'Email inválido'}), 400
            if User.query.filter_by(email=email).filter(User.id != user_id).first():
                logger.error(f"Email {email} já registrado")
                return jsonify({'error': 'Email já registrado'}), 400
            target_user.email = email
        
        if 'password' in data and data['password']:
            password = data['password']
            if len(password) < 8:
                logger.error("Senha muito curta")
                return jsonify({'error': 'A senha deve ter pelo menos 8 caracteres'}), 400
            target_user.set_password(password)
        
        if 'user_role' in data:
            if data['user_role'] not in ['attendant', 'branch_admin']:
                logger.error(f"Papel inválido: {data['user_role']}")
                return jsonify({'error': 'Papel inválido'}), 400
            target_user.user_role = UserRole(data['user_role'])
        
        if 'branch_id' in data:
            branch = Branch.query.get(data['branch_id'])
            if not branch or branch.institution_id != institution_id:
                logger.error(f"Filial {data['branch_id']} inválida")
                return jsonify({'error': 'Filial inválida'}), 400
            if user.user_role == UserRole.BRANCH_ADMIN and data['branch_id'] != user.branch_id:
                logger.warning(f"Usuário {request.user_id} tentou atualizar gestor para outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
            target_user.branch_id = data['branch_id']
        
        db.session.commit()
        
        socketio.emit('user_updated', {
            'user_id': target_user.id,
            'name': target_user.name,
            'email': target_user.email
        }, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='update_user',
            resource_type='user',
            resource_id=target_user.id,
            details=f"Atualizado usuário {target_user.email}"
        )
        
        logger.info(f"Gestor {target_user.email} atualizado por usuário {request.user_id}")
        return jsonify({
            'message': 'Gestor atualizado com sucesso',
            'user': {
                'id': target_user.id,
                'email': target_user.email,
                'name': target_user.name,
                'user_role': target_user.user_role.value
            }
        }), 200

    # Rota para excluir gestor
    @app.route('/api/admin/institutions/<institution_id>/users/<user_id>', methods=['DELETE'])
    @require_auth
    def delete_manager(institution_id, user_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou excluir gestor sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        institution = Institution.query.get(institution_id)
        if not institution:
            logger.error(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404
        
        target_user = User.query.get(user_id)
        if not target_user or target_user.institution_id != institution_id:
            logger.error(f"Usuário {user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if user.institution_id != institution_id or target_user.branch_id != user.branch_id:
                logger.warning(f"Usuário {request.user_id} tentou excluir gestor de outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        
        if target_user.id == request.user_id:
            logger.error(f"Usuário {request.user_id} tentou excluir a própria conta")
            return jsonify({'error': 'Não é possível excluir a própria conta'}), 400
        
        db.session.delete(target_user)
        db.session.commit()
        
        socketio.emit('user_deleted', {
            'user_id': user_id,
            'email': target_user.email
        }, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='delete_user',
            resource_type='user',
            resource_id=user_id,
            details=f"Excluído usuário {target_user.email}"
        )
        
        logger.info(f"Gestor {target_user.email} excluído por usuário {request.user_id}")
        return jsonify({'message': 'Gestor excluído com sucesso'}), 200

    # Rota para listar horários da filial
    @app.route('/api/admin/institutions/<institution_id>/branches/<branch_id>/schedules', methods=['GET'])
    @require_auth
    def list_schedules(institution_id, branch_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou listar horários sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        branch = Branch.query.get(branch_id)
        if not branch or branch.institution_id != institution_id:
            logger.error(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if user.institution_id != institution_id or branch_id != user.branch_id:
                logger.warning(f"Usuário {request.user_id} tentou listar horários de outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        elif user.user_role == UserRole.INSTITUTION_ADMIN:
            if user.institution_id != institution_id:
                logger.warning(f"Usuário {request.user_id} tentou listar horários de outra instituição")
                return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        
        schedules = BranchSchedule.query.filter_by(branch_id=branch_id).all()
        response = [{
            'id': s.id,
            'weekday': s.weekday.value,
            'open_time': s.open_time.strftime('%H:%M') if s.open_time else None,
            'end_time': s.end_time.strftime('%H:%M') if s.end_time else None,
            'is_closed': s.is_closed
        } for s in schedules]
        
        logger.info(f"Listados {len(schedules)} horários para filial {branch_id}")
        return jsonify(response), 200

    # Rota para criar ou atualizar horário da filial
    @app.route('/api/admin/institutions/<institution_id>/branches/<branch_id>/schedules', methods=['POST'])
    @require_auth
    def create_schedule(institution_id, branch_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou criar horário sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        branch = Branch.query.get(branch_id)
        if not branch or branch.institution_id != institution_id:
            logger.error(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if user.institution_id != institution_id or branch_id != user.branch_id:
                logger.warning(f"Usuário {request.user_id} tentou criar horário em outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        elif user.user_role == UserRole.INSTITUTION_ADMIN:
            if user.institution_id != institution_id:
                logger.warning(f"Usuário {request.user_id} tentou criar horário em outra instituição")
                return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        
        data = request.get_json()
        required = ['weekday', 'is_closed']
        if not data or not all(f in data for f in required):
            logger.error("Campos obrigatórios faltando na criação de horário")
            return jsonify({'error': 'Campos obrigatórios faltando'}), 400
        
        weekday = data['weekday']
        if weekday not in Weekday.__members__:
            logger.error(f"Dia da semana inválido: {weekday}")
            return jsonify({'error': 'Dia da semana inválido'}), 400
        
        is_closed = data['is_closed']
        open_time = data.get('open_time')
        end_time = data.get('end_time')
        
        if not is_closed and (not open_time or not end_time):
            logger.error("Horários de abertura e fechamento obrigatórios se não fechado")
            return jsonify({'error': 'Horários de abertura e fechamento são obrigatórios se não estiver fechado'}), 400
        
        try:
            if open_time:
                open_time = datetime.strptime(open_time, '%H:%M').time()
            if end_time:
                end_time = datetime.strptime(end_time, '%H:%M').time()
        except ValueError:
            logger.error("Formato de horário inválido")
            return jsonify({'error': 'Formato de horário inválido (use HH:MM)'}), 400
        
        schedule = BranchSchedule.query.filter_by(branch_id=branch_id, weekday=Weekday[weekday]).first()
        if schedule:
            schedule.open_time = open_time if not is_closed else None
            schedule.end_time = end_time if not is_closed else None
            schedule.is_closed = is_closed
        else:
            schedule = BranchSchedule(
                id=str(uuid.uuid4()),
                branch_id=branch_id,
                weekday=Weekday[weekday],
                open_time=open_time if not is_closed else None,
                end_time=end_time if not is_closed else None,
                is_closed=is_closed
            )
            db.session.add(schedule)
        
        db.session.commit()
        
        socketio.emit('branch_schedule_updated', {
            'schedule_id': schedule.id,
            'branch_id': branch_id,
            'weekday': schedule.weekday.value
        }, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='update_schedule',
            resource_type='branch_schedule',
            resource_id=schedule.id,
            details=f"Atualizado horário para {schedule.weekday.value} na filial {branch.name}"
        )
        
        logger.info(f"Horário para {schedule.weekday.value} criado/atualizado por usuário {request.user_id}")
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

    # Rota para atualizar horário específico
    @app.route('/api/admin/institutions/<institution_id>/branches/<branch_id>/schedules/<schedule_id>', methods=['PUT'])
    @require_auth
    def update_schedule(institution_id, branch_id, schedule_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou atualizar horário sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        branch = Branch.query.get(branch_id)
        if not branch or branch.institution_id != institution_id:
            logger.error(f"Filial {branch_id} não encontrada")
            return jsonify({'error': 'Filial não encontrada'}), 404
        
        schedule = BranchSchedule.query.get(schedule_id)
        if not schedule or schedule.branch_id != branch_id:
            logger.error(f"Horário {schedule_id} não encontrado")
            return jsonify({'error': 'Horário não encontrado'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if user.institution_id != institution_id or branch_id != user.branch_id:
                logger.warning(f"Usuário {request.user_id} tentou atualizar horário de outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        elif user.user_role == UserRole.INSTITUTION_ADMIN:
            if user.institution_id != institution_id:
                logger.warning(f"Usuário {request.user_id} tentou atualizar horário de outra instituição")
                return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        
        data = request.get_json()
        if not data:
            logger.error("Nenhum dado fornecido para atualização de horário")
            return jsonify({'error': 'Nenhum dado fornecido'}), 400
        
        if 'weekday' in data:
            if data['weekday'] not in Weekday.__members__:
                logger.error(f"Dia da semana inválido: {data['weekday']}")
                return jsonify({'error': 'Dia da semana inválido'}), 400
            schedule.weekday = Weekday[data['weekday']]
        
        if 'is_closed' in data:
            schedule.is_closed = data['is_closed']
        
        if 'open_time' in data and data['open_time']:
            try:
                schedule.open_time = datetime.strptime(data['open_time'], '%H:%M').time()
            except ValueError:
                logger.error("Formato de horário inválido para open_time")
                return jsonify({'error': 'Formato de horário inválido (use HH:MM)'}), 400
        elif schedule.is_closed:
            schedule.open_time = None
        
        if 'end_time' in data and data['end_time']:
            try:
                schedule.end_time = datetime.strptime(data['end_time'], '%H:%M').time()
            except ValueError:
                logger.error("Formato de horário inválido para end_time")
                return jsonify({'error': 'Formato de horário inválido (use HH:MM)'}), 400
        elif schedule.is_closed:
            schedule.end_time = None
        
        if not schedule.is_closed and (not schedule.open_time or not schedule.end_time):
            logger.error("Horários de abertura e fechamento obrigatórios se não fechado")
            return jsonify({'error': 'Horários de abertura e fechamento são obrigatórios se não estiver fechado'}), 400
        
        db.session.commit()
        
        socketio.emit('branch_schedule_updated', {
            'schedule_id': schedule.id,
            'branch_id': branch_id,
            'weekday': schedule.weekday.value
        }, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='update_schedule',
            resource_type='branch_schedule',
            resource_id=schedule.id,
            details=f"Atualizado horário para {schedule.weekday.value} na filial {branch.name}"
        )
        
        logger.info(f"Horário {schedule_id} atualizado por usuário {request.user_id}")
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

    # Rota para associar atendente a uma fila
    @app.route('/api/admin/queues/<queue_id>/attendants', methods=['POST'])
    @require_auth
    def assign_attendant(queue_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou associar atendente sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        queue = Queue.query.get(queue_id)
        if not queue:
            logger.error(f"Fila {queue_id} não encontrada")
            return jsonify({'error': 'Fila não encontrada'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if queue.department.branch_id != user.branch_id or queue.department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} tentou associar atendente em outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        elif user.user_role == UserRole.INSTITUTION_ADMIN:
            if queue.department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} tentou associar atendente em outra instituição")
                return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        
        data = request.get_json()
        if not data or 'user_id' not in data:
            logger.error("ID do usuário obrigatório para associação de atendente")
            return jsonify({'error': 'ID do usuário obrigatório'}), 400
        
        attendant = User.query.get(data['user_id'])
        if not attendant or attendant.user_role != UserRole.ATTENDANT or attendant.institution_id != queue.department.branch.institution_id:
            logger.error(f"Atendente {data['user_id']} inválido")
            return jsonify({'error': 'Atendente inválido'}), 400
        
        if AttendantQueue.query.filter_by(user_id=attendant.id, queue_id=queue_id).first():
            logger.error(f"Atendente {attendant.id} já associado à fila {queue_id}")
            return jsonify({'error': 'Atendente já associado a esta fila'}), 400
        
        attendant_queue = AttendantQueue(
            user_id=attendant.id,
            queue_id=queue_id
        )
        db.session.add(attendant_queue)
        db.session.commit()
        
        socketio.emit('queue_updated', {'queue_id': queue_id}, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='assign_attendant',
            resource_type='attendant_queue',
            resource_id=f"{attendant.id}_{queue_id}",
            details=f"Atendente {attendant.email} associado à fila {queue.service.name}"
        )
        
        logger.info(f"Atendente {attendant.email} associado à fila {queue_id} por usuário {request.user_id}")
        return jsonify({
            'message': 'Atendente associado com sucesso',
            'attendant': {
                'user_id': attendant.id,
                'queue_id': queue_id
            }
        }), 201

    # Rota para remover atendente de uma fila
    @app.route('/api/admin/queues/<queue_id>/attendants/<user_id>', methods=['DELETE'])
    @require_auth
    def remove_attendant(queue_id, user_id):
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário {request.user_id} não encontrado")
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if user.user_role not in [UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
            logger.warning(f"Usuário {request.user_id} tentou remover atendente sem permissão")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403
        
        queue = Queue.query.get(queue_id)
        if not queue:
            logger.error(f"Fila {queue_id} não encontrada")
            return jsonify({'error': 'Fila não encontrada'}), 404
        
        if user.user_role == UserRole.BRANCH_ADMIN:
            if queue.department.branch_id != user.branch_id or queue.department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} tentou remover atendente de outra filial")
                return jsonify({'error': 'Acesso restrito à sua filial'}), 403
        elif user.user_role == UserRole.INSTITUTION_ADMIN:
            if queue.department.branch.institution_id != user.institution_id:
                logger.warning(f"Usuário {request.user_id} tentou remover atendente de outra instituição")
                return jsonify({'error': 'Acesso restrito à sua instituição'}), 403
        
        attendant = User.query.get(user_id)
        if not attendant or attendant.institution_id != queue.department.branch.institution_id:
            logger.error(f"Atendente {user_id} não encontrado")
            return jsonify({'error': 'Atendente não encontrado'}), 404
        
        attendant_queue = AttendantQueue.query.filter_by(user_id=user_id, queue_id=queue_id).first()
        if not attendant_queue:
            logger.error(f"Atendente {user_id} não está associado à fila {queue_id}")
            return jsonify({'error': 'Atendente não está associado a esta fila'}), 400
        
        db.session.delete(attendant_queue)
        db.session.commit()
        
        socketio.emit('queue_updated', {'queue_id': queue_id}, namespace='/admin')
        
        AuditLog.create(
            user_id=request.user_id,
            action='remove_attendant',
            resource_type='attendant_queue',
            resource_id=f"{user_id}_{queue_id}",
            details=f"Atendente {attendant.email} removido da fila {queue.service.name}"
        )
        
        logger.info(f"Atendente {attendant.email} removido da fila {queue_id} por usuário {request.user_id}")
        return jsonify({'message': 'Atendente removido com sucesso'}), 200
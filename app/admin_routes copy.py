from flask import jsonify, request, send_file
from . import db, socketio, redis_client
from .models import User, Queue, Ticket, Department, Institution, UserRole, Branch, ServiceCategory, ServiceTag, UserPreference, BranchSchedule, Weekday
from .auth import require_auth
from .services import QueueService
from .ml_models import wait_time_predictor
import logging
import uuid
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
import bcrypt
import io
import json
import re
import pytz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Funções utilitárias para validações
def validate_email(email):
    """Valida o formato de um email."""
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email) is not None

def validate_name(name):
    """Valida o formato de um nome."""
    return re.match(r'^[A-Za-zÀ-ÿ\s0-9.,-]{1,100}$', name) is not None

def validate_password(password):
    """Valida a força de uma senha."""
    return (
        len(password) >= 8 and
        re.search(r'[A-Z]', password) and
        re.search(r'[a-z]', password) and
        re.search(r'[0-9]', password)
    )

def validate_uuid(uuid_str):
    """Valida o formato de um UUID."""
    try:
        uuid.UUID(uuid_str)
        return True
    except ValueError:
        return False

def init_admin_routes(app):
    def emit_dashboard_update(institution_id, queue_id, event_type, data):
        """Emite atualizações ao painel via WebSocket.

        Args:
            institution_id (str): ID da instituição.
            queue_id (str): ID da fila.
            event_type (str): Tipo do evento.
            data (dict): Dados do evento.
        """
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

    @app.route('/api/admin/institutions', methods=['POST'])
    @require_auth
    def create_institution():
        """Cria uma nova instituição.

        Requer: SYSTEM_ADMIN.
        Corpo: {name: str, description: str (opcional)}.
        Retorna: Dados da instituição criada.
        """
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.SYSTEM_ADMIN:
            logger.warning(f"Tentativa não autorizada de criar instituição por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super administradores'}), 403

        data = request.get_json()
        if not data or 'name' not in data:
            logger.warning("Campos obrigatórios faltando na criação de instituição")
            return jsonify({'error': 'Campo "name" é obrigatório'}), 400

        if not validate_name(data['name']):
            logger.warning(f"Nome inválido para instituição: {data['name']}")
            return jsonify({'error': 'Nome da instituição inválido'}), 400

        try:
            if Institution.query.filter_by(name=data['name']).first():
                logger.warning(f"Instituição com nome {data['name']} já existe")
                return jsonify({'error': 'Instituição com este nome já existe'}), 400

            institution = Institution(
                id=str(uuid.uuid4()),
                name=data['name'],
                description=data.get('description')
            )
            db.session.add(institution)
            db.session.commit()

            socketio.emit('institution_created', {
                'institution_id': institution.id,
                'name': institution.name,
                'description': institution.description
            }, namespace='/admin')
            logger.info(f"Instituição {institution.name} criada por user_id={user.id}")
            redis_client.delete(f"cache:search:*")
            return jsonify({
                'message': 'Instituição criada com sucesso',
                'institution': {
                    'id': institution.id,
                    'name': institution.name,
                    'description': institution.description
                }
            }), 201
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao criar instituição: {str(e)}")
            return jsonify({'error': 'Erro ao criar instituição'}), 500

    @app.route('/api/admin/institutions/<institution_id>', methods=['PUT'])
    @require_auth
    def update_institution(institution_id):
        """Atualiza uma instituição existente.

        Requer: SYSTEM_ADMIN.
        Parâmetros: institution_id (UUID).
        Corpo: {name: str (opcional), description: str (opcional)}.
        Retorna: Dados da instituição atualizada.
        """
        if not validate_uuid(institution_id):
            logger.warning(f"ID de instituição inválido: {institution_id}")
            return jsonify({'error': 'ID de instituição inválido'}), 400

        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.SYSTEM_ADMIN:
            logger.warning(f"Tentativa não autorizada de editar instituição por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super administradores'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        data = request.get_json()
        if not data:
            logger.warning("Nenhum dado fornecido para atualização da instituição")
            return jsonify({'error': 'Nenhum dado fornecido'}), 400

        if 'name' in data and not validate_name(data['name']):
            logger.warning(f"Nome inválido para instituição: {data['name']}")
            return jsonify({'error': 'Nome da instituição inválido'}), 400

        try:
            if 'name' in data and data['name'] != institution.name:
                if Institution.query.filter_by(name=data['name']).first():
                    logger.warning(f"Instituição com nome {data['name']} já existe")
                    return jsonify({'error': 'Instituição com este nome já existe'}), 400
                institution.name = data['name']
            institution.description = data.get('description', institution.description)
            db.session.commit()

            socketio.emit('institution_updated', {
                'institution_id': institution.id,
                'name': institution.name,
                'description': institution.description
            }, namespace='/admin')
            logger.info(f"Instituição {institution.name} atualizada por user_id={user.id}")
            redis_client.delete(f"cache:search:*")
            return jsonify({
                'message': 'Instituição atualizada com sucesso',
                'institution': {
                    'id': institution.id,
                    'name': institution.name,
                    'description': institution.description
                }
            }), 200
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar instituição {institution_id}: {str(e)}")
            return jsonify({'error': 'Erro ao atualizar instituição'}), 500

    @app.route('/api/admin/institutions/<institution_id>', methods=['DELETE'])
    @require_auth
    def delete_institution(institution_id):
        """Exclui uma instituição.

        Requer: SYSTEM_ADMIN.
        Parâmetros: institution_id (UUID).
        Retorna: Mensagem de sucesso.
        """
        if not validate_uuid(institution_id):
            logger.warning(f"ID de instituição inválido: {institution_id}")
            return jsonify({'error': 'ID de instituição inválido'}), 400

        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.SYSTEM_ADMIN:
            logger.warning(f"Tentativa não autorizada de excluir instituição por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super administradores'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        if Branch.query.filter_by(institution_id=institution_id).first():
            logger.warning(f"Tentativa de excluir instituição {institution_id} com filiais associadas")
            return jsonify({'error': 'Não é possível excluir: instituição possui filiais associadas'}), 400

        try:
            db.session.delete(institution)
            db.session.commit()

            socketio.emit('institution_deleted', {
                'institution_id': institution_id,
                'name': institution.name
            }, namespace='/admin')
            logger.info(f"Instituição {institution.name} excluída por user_id={user.id}")
            redis_client.delete(f"cache:search:*")
            return jsonify({'message': 'Instituição excluída com sucesso'}), 200
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao excluir instituição {institution_id}: {str(e)}")
            return jsonify({'error': 'Erro ao excluir instituição'}), 500

    @app.route('/api/admin/institutions/<institution_id>/branches', methods=['POST'])
    @require_auth
    def create_branch(institution_id):
        """Cria uma nova filial para uma instituição.

        Requer: SYSTEM_ADMIN ou INSTITUTION_ADMIN.
        Parâmetros: institution_id (UUID).
        Corpo: {name: str, location: str, neighborhood: str, latitude: float, longitude: float}.
        Retorna: Dados da filial criada.
        """
        if not validate_uuid(institution_id):
            logger.warning(f"ID de instituição inválido: {institution_id}")
            return jsonify({'error': 'ID de instituição inválido'}), 400

        user = User.query.get(request.user_id)
        if not user or not (
            user.user_role == UserRole.SYSTEM_ADMIN or
            (user.user_role == UserRole.INSTITUTION_ADMIN and user.institution_id == institution_id)
        ):
            logger.warning(f"Tentativa não autorizada de criar filial por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super admins ou admins da instituição'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        data = request.get_json()
        required = ['name', 'location', 'neighborhood', 'latitude', 'longitude']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de filial")
            return jsonify({'error': 'Campos obrigatórios: name, location, neighborhood, latitude, longitude'}), 400

        if not validate_name(data['name']):
            logger.warning(f"Nome inválido para filial: {data['name']}")
            return jsonify({'error': 'Nome da filial inválido'}), 400
        if not re.match(r'^[A-Za-zÀ-ÿ\s,]{1,100}$', data['neighborhood']):
            logger.warning(f"Bairro inválido: {data['neighborhood']}")
            return jsonify({'error': 'Bairro inválido'}), 400
        if not (-90 <= data['latitude'] <= 90):
            logger.warning(f"Latitude inválida: {data['latitude']}")
            return jsonify({'error': 'Latitude deve estar entre -90 e 90'}), 400
        if not (-180 <= data['longitude'] <= 180):
            logger.warning(f"Longitude inválida: {data['longitude']}")
            return jsonify({'error': 'Longitude deve estar entre -180 e 180'}), 400

        try:
            if Branch.query.filter_by(institution_id=institution_id, name=data['name']).first():
                logger.warning(f"Filial com nome {data['name']} já existe na instituição {institution_id}")
                return jsonify({'error': 'Filial com este nome já existe'}), 400

            branch = Branch(
                id=str(uuid.uuid4()),
                institution_id=institution_id,
                name=data['name'],
                location=data['location'],
                neighborhood=data['neighborhood'],
                latitude=data['latitude'],
                longitude=data['longitude']
            )
            db.session.add(branch)
            db.session.commit()

            socketio.emit('branch_created', {
                'branch_id': branch.id,
                'name': branch.name,
                'location': branch.location,
                'neighborhood': branch.neighborhood,
                'latitude': branch.latitude,
                'longitude': branch.longitude,
                'institution_id': institution_id
            }, namespace='/admin')
            QueueService.send_fcm_notification(user.id, f"Filial {branch.name} criada com sucesso na instituição {institution.name}")
            logger.info(f"Filial {branch.name} criada por user_id={user.id}")
            redis_client.delete(f"cache:search:*")
            return jsonify({
                'message': 'Filial criada com sucesso',
                'branch': {
                    'id': branch.id,
                    'name': branch.name,
                    'location': branch.location,
                    'neighborhood': branch.neighborhood,
                    'latitude': branch.latitude,
                    'longitude': branch.longitude,
                    'institution_id': institution_id
                }
            }), 201
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao criar filial: {str(e)}")
            return jsonify({'error': 'Erro ao criar filial'}), 500

    @app.route('/api/admin/institutions/<institution_id>/branches/<branch_id>', methods=['PUT'])
    @require_auth
    def update_branch(institution_id, branch_id):
        """Atualiza uma filial existente.

        Requer: SYSTEM_ADMIN ou INSTITUTION_ADMIN.
        Parâmetros: institution_id (UUID), branch_id (UUID).
        Corpo: {name: str (opcional), location: str (opcional), neighborhood: str (opcional), latitude: float (opcional), longitude: float (opcional)}.
        Retorna: Dados da filial atualizada.
        """
        if not validate_uuid(institution_id) or not validate_uuid(branch_id):
            logger.warning(f"IDs inválidos: institution_id={institution_id}, branch_id={branch_id}")
            return jsonify({'error': 'ID de instituição ou filial inválido'}), 400

        user = User.query.get(request.user_id)
        if not user or not (
            user.user_role == UserRole.SYSTEM_ADMIN or
            (user.user_role == UserRole.INSTITUTION_ADMIN and user.institution_id == institution_id)
        ):
            logger.warning(f"Tentativa não autorizada de editar filial por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super admins ou admins da instituição'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        branch = Branch.query.get(branch_id)
        if not branch or branch.institution_id != institution_id:
            logger.warning(f"Filial {branch_id} não encontrada ou não pertence à instituição {institution_id}")
            return jsonify({'error': 'Filial não encontrada ou não pertence à instituição'}), 404

        data = request.get_json()
        if not data:
            logger.warning("Nenhum dado fornecido para atualização da filial")
            return jsonify({'error': 'Nenhum dado fornecido'}), 400

        if 'name' in data and not validate_name(data['name']):
            logger.warning(f"Nome inválido para filial: {data['name']}")
            return jsonify({'error': 'Nome da filial inválido'}), 400
        if 'neighborhood' in data and not re.match(r'^[A-Za-zÀ-ÿ\s,]{1,100}$', data['neighborhood']):
            logger.warning(f"Bairro inválido: {data['neighborhood']}")
            return jsonify({'error': 'Bairro inválido'}), 400
        if 'latitude' in data and not (-90 <= data['latitude'] <= 90):
            logger.warning(f"Latitude inválida: {data['latitude']}")
            return jsonify({'error': 'Latitude deve estar entre -90 e 90'}), 400
        if 'longitude' in data and not (-180 <= data['longitude'] <= 180):
            logger.warning(f"Longitude inválida: {data['longitude']}")
            return jsonify({'error': 'Longitude deve estar entre -180 e 180'}), 400

        try:
            if 'name' in data and data['name'] != branch.name:
                if Branch.query.filter_by(institution_id=institution_id, name=data['name']).first():
                    logger.warning(f"Filial com nome {data['name']} já existe na instituição {institution_id}")
                    return jsonify({'error': 'Filial com este nome já existe'}), 400
                branch.name = data['name']
            branch.location = data.get('location', branch.location)
            branch.neighborhood = data.get('neighborhood', branch.neighborhood)
            branch.latitude = data.get('latitude', branch.latitude)
            branch.longitude = data.get('longitude', branch.longitude)
            db.session.commit()

            socketio.emit('branch_updated', {
                'branch_id': branch.id,
                'name': branch.name,
                'location': branch.location,
                'neighborhood': branch.neighborhood,
                'latitude': branch.latitude,
                'longitude': branch.longitude,
                'institution_id': institution_id
            }, namespace='/admin')
            QueueService.send_fcm_notification(user.id, f"Filial {branch.name} atualizada na instituição {institution.name}")
            logger.info(f"Filial {branch.name} atualizada por user_id={user.id}")
            redis_client.delete(f"cache:search:*")
            return jsonify({
                'message': 'Filial atualizada com sucesso',
                'branch': {
                    'id': branch.id,
                    'name': branch.name,
                    'location': branch.location,
                    'neighborhood': branch.neighborhood,
                    'latitude': branch.latitude,
                    'longitude': branch.longitude,
                    'institution_id': institution_id
                }
            }), 200
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar filial {branch_id}: {str(e)}")
            return jsonify({'error': 'Erro ao atualizar filial'}), 500

    @app.route('/api/admin/institutions/<institution_id>/branches', methods=['GET'])
    @require_auth
    def list_branches(institution_id):
        """Lista todas as filiais de uma instituição.

        Requer: SYSTEM_ADMIN ou INSTITUTION_ADMIN.
        Parâmetros: institution_id (UUID), page (int, opcional), per_page (int, opcional).
        Retorna: Lista paginada de filiais.
        """
        if not validate_uuid(institution_id):
            logger.warning(f"ID de instituição inválido: {institution_id}")
            return jsonify({'error': 'ID de instituição inválido'}), 400

        user = User.query.get(request.user_id)
        if not user or not (
            user.user_role == UserRole.SYSTEM_ADMIN or
            (user.user_role == UserRole.INSTITUTION_ADMIN and user.institution_id == institution_id)
        ):
            logger.warning(f"Tentativa não autorizada de listar filiais por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super admins ou admins da instituição'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        try:
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 20))
            branches_query = Branch.query.filter_by(institution_id=institution_id)
            branches_paginated = branches_query.paginate(page=page, per_page=per_page, error_out=False)
            response = [{
                'id': b.id,
                'name': b.name,
                'location': b.location,
                'neighborhood': b.neighborhood,
                'latitude': b.latitude,
                'longitude': b.longitude,
                'institution_id': b.institution_id
            } for b in branches_paginated.items]

            logger.info(f"Admin {user.email} listou {len(response)} filiais da instituição {institution_id}")
            return jsonify({
                'branches': response,
                'total': branches_paginated.total,
                'page': page,
                'per_page': per_page
            }), 200
        except ValueError as e:
            logger.warning(f"Parâmetros de paginação inválidos: {str(e)}")
            return jsonify({'error': 'Parâmetros de paginação inválidos'}), 400
        except SQLAlchemyError as e:
            logger.error(f"Erro ao listar filiais para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar filiais'}), 500

    @app.route('/api/admin/institutions/<institution_id>/admin', methods=['POST'])
    @require_auth
    def create_institution_admin(institution_id):
        """Cria um administrador para uma instituição.

        Requer: SYSTEM_ADMIN.
        Parâmetros: institution_id (UUID).
        Corpo: {email: str, name: str, password: str}.
        Retorna: Dados do administrador criado.
        """
        if not validate_uuid(institution_id):
            logger.warning(f"ID de instituição inválido: {institution_id}")
            return jsonify({'error': 'ID de instituição inválido'}), 400

        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.SYSTEM_ADMIN:
            logger.warning(f"Tentativa não autorizada de criar admin de instituição por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super administradores'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        data = request.get_json()
        required = ['email', 'name', 'password']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de admin de instituição")
            return jsonify({'error': 'Campos obrigatórios: email, name, password'}), 400

        if not validate_email(data['email']):
            logger.warning(f"Email inválido: {data['email']}")
            return jsonify({'error': 'Email inválido'}), 400
        if not validate_password(data['password']):
            logger.warning("Senha inválida fornecida na criação de admin")
            return jsonify({'error': 'A senha deve ter pelo menos 8 caracteres, com letras maiúsculas, minúsculas e números'}), 400
        if not validate_name(data['name']):
            logger.warning(f"Nome inválido: {data['name']}")
            return jsonify({'error': 'Nome inválido'}), 400

        try:
            if User.query.filter_by(email=data['email']).first():
                logger.warning(f"Usuário com email {data['email']} já existe")
                return jsonify({'error': 'Usuário com este email já existe'}), 400

            admin = User(
                id=str(uuid.uuid4()),
                email=data['email'],
                name=data['name'],
                user_role=UserRole.INSTITUTION_ADMIN,
                institution_id=institution_id,
                active=True
            )
            admin.set_password(data['password'])
            db.session.add(admin)
            db.session.commit()

            socketio.emit('user_created', {
                'user_id': admin.id,
                'email': admin.email,
                'role': admin.user_role.value,
                'institution_id': institution_id
            }, namespace='/admin')
            if admin.fcm_token:
                QueueService.send_fcm_notification(admin.id, f"Bem-vindo ao Facilita 2.0 como administrador da instituição {institution.name}")
            logger.info(f"Admin de instituição {admin.email} criado para {institution.name} por user_id={user.id}")
            return jsonify({
                'message': 'Administrador de instituição criado com sucesso',
                'user': {
                    'id': admin.id,
                    'email': admin.email,
                    'name': admin.name,
                    'role': admin.user_role.value
                }
            }), 201
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao criar admin de instituição: {str(e)}")
            return jsonify({'error': 'Erro ao criar administrador'}), 500

    @app.route('/api/admin/institutions/<institution_id>/users/<user_id>', methods=['PUT'])
    @require_auth
    def update_department_admin(institution_id, user_id):
        """Atualiza um administrador de departamento.

        Requer: SYSTEM_ADMIN ou INSTITUTION_ADMIN.
        Parâmetros: institution_id (UUID), user_id (UUID).
        Corpo: {email: str (opcional), name: str (opcional), password: str (opcional), department_id: UUID (opcional), branch_id: UUID (opcional)}.
        Retorna: Dados do administrador atualizado.
        """
        if not validate_uuid(institution_id) or not validate_uuid(user_id):
            logger.warning(f"IDs inválidos: institution_id={institution_id}, user_id={user_id}")
            return jsonify({'error': 'ID de instituição ou usuário inválido'}), 400

        current_user = User.query.get(request.user_id)
        if not current_user or not (
            current_user.user_role == UserRole.SYSTEM_ADMIN or
            (current_user.user_role == UserRole.INSTITUTION_ADMIN and current_user.institution_id == institution_id)
        ):
            logger.warning(f"Tentativa não autorizada de editar gestor por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super admins ou admins da instituição'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        target_user = User.query.get(user_id)
        if not target_user or target_user.institution_id != institution_id or target_user.user_role != UserRole.DEPARTMENT_ADMIN:
            logger.warning(f"Gestor {user_id} não encontrado ou não é DEPARTMENT_ADMIN na instituição {institution_id}")
            return jsonify({'error': 'Gestor não encontrado ou não pertence à instituição'}), 404

        data = request.get_json()
        if not data:
            logger.warning("Nenhum dado fornecido para atualização do gestor")
            return jsonify({'error': 'Nenhum dado fornecido'}), 400

        if 'email' in data and not validate_email(data['email']):
            logger.warning(f"Email inválido: {data['email']}")
            return jsonify({'error': 'Email inválido'}), 400
        if 'password' in data and not validate_password(data['password']):
            logger.warning("Senha inválida fornecida na atualização de gestor")
            return jsonify({'error': 'A senha deve ter pelo menos 8 caracteres, com letras maiúsculas, minúsculas e números'}), 400
        if 'name' in data and not validate_name(data['name']):
            logger.warning(f"Nome inválido: {data['name']}")
            return jsonify({'error': 'Nome inválido'}), 400

        try:
            if 'email' in data and data['email'] != target_user.email:
                if User.query.filter_by(email=data['email']).first():
                    logger.warning(f"Email {data['email']} já está em uso")
                    return jsonify({'error': 'Email já está em uso'}), 400
                target_user.email = data['email']
            target_user.name = data.get('name', target_user.name)
            if 'password' in data:
                target_user.set_password(data['password'])
            if 'department_id' in data:
                department = Department.query.get(data['department_id'])
                if not department or department.branch.institution_id != institution_id:
                    logger.warning(f"Departamento {data['department_id']} inválido ou não pertence à instituição {institution_id}")
                    return jsonify({'error': 'Departamento inválido ou não pertence à instituição'}), 400
                target_user.department_id = data['department_id']
            if 'branch_id' in data:
                branch = Branch.query.get(data['branch_id'])
                if not branch or branch.institution_id != institution_id:
                    logger.warning(f"Filial {data['branch_id']} inválida ou não pertence à instituição {institution_id}")
                    return jsonify({'error': 'Filial inválida ou não pertence à instituição'}), 400
                target_user.branch_id = data['branch_id']

            db.session.commit()

            socketio.emit('user_updated', {
                'user_id': target_user.id,
                'email': target_user.email,
                'name': target_user.name,
                'department_id': target_user.department_id,
                'branch_id': target_user.branch_id,
                'institution_id': institution_id
            }, namespace='/admin')
            if target_user.fcm_token:
                QueueService.send_fcm_notification(target_user.id, f"Seus dados foram atualizados na instituição {institution.name}")
            logger.info(f"Gestor {target_user.email} atualizado por user_id={current_user.id}")
            return jsonify({
                'message': 'Gestor atualizado com sucesso',
                'user': {
                    'id': target_user.id,
                    'email': target_user.email,
                    'name': target_user.name,
                    'role': target_user.user_role.value,
                    'department_id': target_user.department_id,
                    'branch_id': target_user.branch_id
                }
            }), 200
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar gestor {user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao atualizar gestor'}), 500

    @app.route('/api/admin/institutions/<institution_id>/users/<user_id>', methods=['DELETE'])
    @require_auth
    def delete_department_admin(institution_id, user_id):
        """Exclui um administrador de departamento.

        Requer: SYSTEM_ADMIN ou INSTITUTION_ADMIN.
        Parâmetros: institution_id (UUID), user_id (UUID).
        Retorna: Mensagem de sucesso.
        """
        if not validate_uuid(institution_id) or not validate_uuid(user_id):
            logger.warning(f"IDs inválidos: institution_id={institution_id}, user_id={user_id}")
            return jsonify({'error': 'ID de instituição ou usuário inválido'}), 400

        current_user = User.query.get(request.user_id)
        if not current_user or not (
            current_user.user_role == UserRole.SYSTEM_ADMIN or
            (current_user.user_role == UserRole.INSTITUTION_ADMIN and current_user.institution_id == institution_id)
        ):
            logger.warning(f"Tentativa não autorizada de excluir gestor por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super admins ou admins da instituição'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        target_user = User.query.get(user_id)
        if not target_user or target_user.institution_id != institution_id or target_user.user_role != UserRole.DEPARTMENT_ADMIN:
            logger.warning(f"Gestor {user_id} não encontrado ou não é DEPARTMENT_ADMIN na instituição {institution_id}")
            return jsonify({'error': 'Gestor não encontrado ou não pertence à instituição'}), 404

        if target_user.department_id:
            queues = Queue.query.filter_by(department_id=target_user.department_id).all()
            for queue in queues:
                if Ticket.query.filter_by(queue_id=queue.id, status='Pendente').first():
                    logger.warning(f"Gestor {user_id} não pode ser excluído: há tickets pendentes na fila {queue.id}")
                    return jsonify({'error': 'Não é possível excluir: gestor tem filas com tickets pendentes'}), 400

        try:
            db.session.delete(target_user)
            db.session.commit()

            socketio.emit('user_deleted', {
                'user_id': user_id,
                'email': target_user.email,
                'institution_id': institution_id
            }, namespace='/admin')
            if target_user.fcm_token:
                QueueService.send_fcm_notification(target_user.id, f"Sua conta foi removida da instituição {institution.name}")
            logger.info(f"Gestor {target_user.email} excluído por user_id={current_user.id}")
            return jsonify({'message': 'Gestor excluído com sucesso'}), 200
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao excluir gestor {user_id}: {str(e)}")
            return jsonify({'error': 'Erro ao excluir gestor'}), 500

    @app.route('/api/admin/institutions/<institution_id>/departments', methods=['POST'])
    @require_auth
    def create_department(institution_id):
        """Cria um novo departamento em uma instituição.

        Requer: SYSTEM_ADMIN ou INSTITUTION_ADMIN.
        Parâmetros: institution_id (UUID).
        Corpo: {name: str, sector: str, branch_id: UUID}.
        Retorna: Dados do departamento criado.
        """
        if not validate_uuid(institution_id):
            logger.warning(f"ID de instituição inválido: {institution_id}")
            return jsonify({'error': 'ID de instituição inválido'}), 400

        user = User.query.get(request.user_id)
        if not user or not (
            user.user_role == UserRole.SYSTEM_ADMIN or
            (user.user_role == UserRole.INSTITUTION_ADMIN and user.institution_id == institution_id)
        ):
            logger.warning(f"Tentativa não autorizada de criar departamento por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super admins ou admins da instituição'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        data = request.get_json()
        required = ['name', 'sector', 'branch_id']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de departamento")
            return jsonify({'error': 'Campos obrigatórios: name, sector, branch_id'}), 400

        if not validate_name(data['name']):
            logger.warning(f"Nome inválido para departamento: {data['name']}")
            return jsonify({'error': 'Nome do departamento inválido'}), 400
        if not re.match(r'^[A-Za-zÀ-ÿ\s]{1,50}$', data['sector']):
            logger.warning(f"Setor inválido: {data['sector']}")
            return jsonify({'error': 'Setor inválido'}), 400
        if not validate_uuid(data['branch_id']):
            logger.warning(f"ID de filial inválido: {data['branch_id']}")
            return jsonify({'error': 'ID de filial inválido'}), 400

        branch = Branch.query.get(data['branch_id'])
        if not branch or branch.institution_id != institution_id:
            logger.warning(f"Filial {data['branch_id']} inválida ou não pertence à instituição {institution_id}")
            return jsonify({'error': 'Filial inválida ou não pertence à instituição'}), 400

        try:
            if Department.query.filter_by(branch_id=data['branch_id'], name=data['name']).first():
                logger.warning(f"Departamento com nome {data['name']} já existe na filial {data['branch_id']}")
                return jsonify({'error': 'Departamento com este nome já existe na filial'}), 400

            department = Department(
                id=str(uuid.uuid4()),
                branch_id=data['branch_id'],
                name=data['name'],
                sector=data['sector']
            )
            db.session.add(department)
            db.session.commit()

            socketio.emit('department_created', {
                'department_id': department.id,
                'name': department.name,
                'sector': department.sector,
                'branch_id': department.branch_id,
                'institution_id': institution_id
            }, namespace='/admin')
            logger.info(f"Departamento {department.name} criado em {institution.name} por user_id={user.id}")
            redis_client.delete(f"cache:search:*")
            return jsonify({
                'message': 'Departamento criado com sucesso',
                'department': {
                    'id': department.id,
                    'name': department.name,
                    'sector': department.sector,
                    'branch_id': department.branch_id,
                    'institution_id': institution_id
                }
            }), 201
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao criar departamento: {str(e)}")
            return jsonify({'error': 'Erro ao criar departamento'}), 500

    @app.route('/api/admin/departments/<department_id>/users', methods=['POST'])
    @require_auth
    def add_department_user(department_id):
        """Adiciona um usuário a um departamento.

        Requer: SYSTEM_ADMIN ou INSTITUTION_ADMIN.
        Parâmetros: department_id (UUID).
        Corpo: {email: str, name: str, password: str, role: str (USER ou DEPARTMENT_ADMIN)}.
        Retorna: Dados do usuário criado.
        """
        if not validate_uuid(department_id):
            logger.warning(f"ID de departamento inválido: {department_id}")
            return jsonify({'error': 'ID de departamento inválido'}), 400

        user = User.query.get(request.user_id)
        department = Department.query.get(department_id)
        if not department:
            logger.warning(f"Departamento {department_id} não encontrado")
            return jsonify({'error': 'Departamento não encontrado'}), 404

        if not user or not (
            user.user_role == UserRole.SYSTEM_ADMIN or
            (user.user_role == UserRole.INSTITUTION_ADMIN and user.institution_id == department.branch.institution_id)
        ):
            logger.warning(f"Tentativa não autorizada de adicionar usuário ao departamento por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super admins ou admins da instituição'}), 403

        data = request.get_json()
        required = ['email', 'name', 'password', 'role']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de usuário de departamento")
            return jsonify({'error': 'Campos obrigatórios: email, name, password, role'}), 400

        if not validate_email(data['email']):
            logger.warning(f"Email inválido: {data['email']}")
            return jsonify({'error': 'Email inválido'}), 400
        if not validate_password(data['password']):
            logger.warning("Senha inválida fornecida na criação de usuário")
            return jsonify({'error': 'A senha deve ter pelo menos 8 caracteres, com letras maiúsculas, minúsculas e números'}), 400
        if not validate_name(data['name']):
            logger.warning(f"Nome inválido: {data['name']}")
            return jsonify({'error': 'Nome inválido'}), 400

        role = data['role'].upper()
        if role not in [UserRole.USER.value, UserRole.DEPARTMENT_ADMIN.value]:
            logger.warning(f"Role inválido fornecido: {role}")
            return jsonify({'error': 'Role deve ser USER ou DEPARTMENT_ADMIN'}), 400

        try:
            if User.query.filter_by(email=data['email']).first():
                logger.warning(f"Usuário com email {data['email']} já existe")
                return jsonify({'error': 'Usuário com este email já existe'}), 400

            new_user = User(
                id=str(uuid.uuid4()),
                email=data['email'],
                name=data['name'],
                user_role=UserRole[role],
                department_id=department_id,
                branch_id=department.branch_id,
                institution_id=department.branch.institution_id,
                active=True
            )
            new_user.set_password(data['password'])
            db.session.add(new_user)
            db.session.commit()

            socketio.emit('user_created', {
                'user_id': new_user.id,
                'email': new_user.email,
                'role': new_user.user_role.value,
                'department_id': department_id,
                'branch_id': department.branch_id,
                'institution_id': department.branch.institution_id
            }, namespace='/admin')
            if new_user.fcm_token:
                QueueService.send_fcm_notification(new_user.id, f"Bem-vindo ao Facilita 2.0 no departamento {department.name}")
            logger.info(f"Usuário {new_user.email} ({role}) adicionado ao departamento {department.name} por user_id={user.id}")
            return jsonify({
                'message': 'Usuário adicionado ao departamento com sucesso',
                'user': {
                    'id': new_user.id,
                    'email': new_user.email,
                    'name': new_user.name,
                    'role': new_user.user_role.value,
                    'department_id': department_id,
                    'branch_id': department.branch_id
                }
            }), 201
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao adicionar usuário ao departamento: {str(e)}")
            return jsonify({'error': 'Erro ao adicionar usuário'}), 500

    @app.route('/api/institutions/<institution_id>/calls', methods=['GET'])
    @require_auth
    def list_institution_calls(institution_id):
        """Lista chamadas recentes de uma instituição.

        Requer: SYSTEM_ADMIN ou INSTITUTION_ADMIN.
        Parâmetros: institution_id (UUID), refresh (bool, opcional).
        Retorna: Lista de chamadas recentes.
        """
        if not validate_uuid(institution_id):
            logger.warning(f"ID de instituição inválido: {institution_id}")
            return jsonify({'error': 'ID de instituição inválido'}), 400

        user = User.query.get(request.user_id)
        if not user or not (
            user.user_role == UserRole.SYSTEM_ADMIN or
            (user.user_role == UserRole.INSTITUTION_ADMIN and user.institution_id == institution_id)
        ):
            logger.warning(f"Tentativa não autorizada de listar chamadas por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super admins ou admins da instituição'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        cache_key = f'calls:{institution_id}'
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        if not refresh:
            try:
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    return jsonify(json.loads(cached_data))
            except Exception as e:
                logger.warning(f"Erro ao acessar Redis para chamadas {institution_id}: {str(e)}")

        try:
            recent_calls = (
                Ticket.query
                .join(Queue)
                .join(Department)
                .join(Branch)
                .filter(
                    Branch.institution_id == institution_id,
                    Ticket.status.in_(['Chamado', 'Atendido'])
                )
                .order_by(Ticket.attended_at.desc(), Ticket.issued_at.desc())
                .limit(10)
                .all()
            )

            response = []
            for ticket in recent_calls:
                queue = ticket.queue
                call_data = {
                    'ticket_id': ticket.id,
                    'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
                    'service': queue.service.name if queue.service else 'N/A',
                    'department': queue.department.name,
                    'branch': queue.department.branch.name if queue.department.branch else 'N/A',
                    'counter': f"Guichê {ticket.counter:02d}" if ticket.counter else "N/A",
                    'status': ticket.status,
                    'called_at': ticket.attended_at.isoformat() if ticket.attended_at else ticket.issued_at.isoformat()
                }
                response.append(call_data)
                emit_dashboard_update(
                    institution_id=institution_id,
                    queue_id=ticket.queue_id,
                    event_type='call_status',
                    data=call_data
                )

            response_data = {
                'institution_id': institution_id,
                'institution_name': institution.name,
                'calls': response
            }

            try:
                redis_client.setex(cache_key, 300, json.dumps(response_data))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache no Redis para chamadas {institution_id}: {str(e)}")

            logger.info(f"Listadas {len(response)} chamadas recentes para instituição {institution_id}")
            return jsonify(response_data), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro ao listar chamadas para instituição {institution_id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar chamadas'}), 500

    @app.route('/api/admin/queues', methods=['GET'])
    @require_auth
    def list_admin_queues():
        """Lista filas visíveis para o administrador.

        Requer: DEPARTMENT_ADMIN, INSTITUTION_ADMIN ou SYSTEM_ADMIN.
        Parâmetros: page (int, opcional), per_page (int, opcional).
        Retorna: Lista paginada de filas.
        """
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        if not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
            logger.warning(f"Tentativa de acesso a /api/admin/queues por usuário não autorizado: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        try:
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 20))

            if user.is_system_admin:
                queues_query = Queue.query
            elif user.is_institution_admin:
                branch_ids = [b.id for b in Branch.query.filter_by(institution_id=user.institution_id).all()]
                department_ids = [d.id for d in Department.query.filter(Department.branch_id.in_(branch_ids)).all()]
                queues_query = Queue.query.filter(Queue.department_id.in_(department_ids))
            else:  # DEPARTMENT_ADMIN
                if not user.department_id:
                    logger.warning(f"Gestor {request.user_id} não vinculado a departamento")
                    return jsonify({'error': 'Gestor não vinculado a um departamento'}), 403
                queues_query = Queue.query.filter_by(department_id=user.department_id)

            queues_paginated = queues_query.paginate(page=page, per_page=per_page, error_out=False)
            response = []
            for q in queues_paginated.items:
                is_open = QueueService.is_queue_open(q)
                features = QueueService.get_wait_time_features(q.id, q.current_ticket + 1, 0)
                wait_time = wait_time_predictor.predict(q.id, features)
                response.append({
                    'id': q.id,
                    'service': q.service.name if q.service else 'N/A',
                    'prefix': q.prefix,
                    'institution_name': q.department.branch.institution.name if q.department and q.department.branch else 'N/A',
                    'branch_name': q.department.branch.name if q.department.branch else 'N/A',
                    'active_tickets': q.active_tickets,
                    'daily_limit': q.daily_limit,
                    'current_ticket': q.current_ticket,
                    'status': 'Aberto' if is_open else ('Lotado' if q.active_tickets >= q.daily_limit else 'Fechado'),
                    'institution_id': q.department.branch.institution_id if q.department and q.department.branch else None,
                    'department': q.department.name if q.department else 'N/A',
                    'branch_id': q.department.branch_id if q.department else None,
                    'avg_wait_time': f"{int(wait_time)} minutos" if wait_time is not None else "N/A"
                })

            logger.info(f"Usuário {user.email} listou {len(response)} filas")
            return jsonify({
                'queues': response,
                'total': queues_paginated.total,
                'page': page,
                'per_page': per_page
            }), 200
        except ValueError as e:
            logger.warning(f"Parâmetros de paginação inválidos: {str(e)}")
            return jsonify({'error': 'Parâmetros de paginação inválidos'}), 400
        except SQLAlchemyError as e:
            logger.error(f"Erro ao listar filas para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar filas'}), 500

    @app.route('/api/admin/queue/<queue_id>/call', methods=['POST'])
    @require_auth
    def admin_call_next(queue_id):
        """Chama o próximo ticket em uma fila.

        Requer: DEPARTMENT_ADMIN, INSTITUTION_ADMIN ou SYSTEM_ADMIN.
        Parâmetros: queue_id (UUID).
        Retorna: Dados do ticket chamado.
        """
        if not validate_uuid(queue_id):
            logger.warning(f"ID de fila inválido: {queue_id}")
            return jsonify({'error': 'ID de fila inválido'}), 400

        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        if not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
            logger.warning(f"Tentativa de acesso a /api/admin/queue/{queue_id}/call por usuário não autorizado: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        queue = Queue.query.get(queue_id)
        if not queue:
            logger.warning(f"Fila {queue_id} não encontrada")
            return jsonify({'error': 'Fila não encontrada'}), 404

        if user.is_department_admin and queue.department_id != user.department_id:
            logger.warning(f"Gestor {request.user_id} tentou acessar fila {queue_id} fora de seu departamento")
            return jsonify({'error': 'Acesso negado: fila não pertence ao seu departamento'}), 403
        if user.is_institution_admin and queue.department.branch.institution_id != user.institution_id:
            logger.warning(f"Admin {request.user_id} tentou acessar fila {queue_id} fora de sua instituição")
            return jsonify({'error': 'Acesso negado: fila não pertence à sua instituição'}), 403

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
            emit_dashboard_update(
                institution_id=queue.department.branch.institution_id,
                queue_id=queue.id,
                event_type='new_call',
                data={
                    'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
                    'counter': ticket.counter,
                    'timestamp': ticket.attended_at.isoformat() if ticket.attended_at else datetime.utcnow().isoformat()
                }
            )
            if ticket.user_id and ticket.user.fcm_token:
                QueueService.send_fcm_notification(ticket.user_id, f"Ticket {ticket.queue.prefix}{ticket.ticket_number} chamado no guichê {ticket.counter:02d}")
            redis_client.delete(f"calls:{queue.department.branch.institution_id}")
            logger.info(f"Usuário {user.email} chamou ticket {ticket.id} da fila {queue_id}")
            return jsonify(response), 200
        except ValueError as e:
            logger.error(f"Erro ao chamar próxima senha na fila {queue_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except SQLAlchemyError as e:
            logger.error(f"Erro ao chamar próxima senha: {str(e)}")
            return jsonify({'error': 'Erro ao chamar senha'}), 500

    @app.route('/api/admin/report', methods=['GET'])
    @require_auth
    def admin_report():
        """Gera um relatório de atendimento para uma data específica.

        Requer: DEPARTMENT_ADMIN, INSTITUTION_ADMIN ou SYSTEM_ADMIN.
        Parâmetros: date (str, formato AAAA-MM-DD).
        Retorna: Relatório de tickets emitidos e atendidos.
        """
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        if not (user.is_department_admin or user.is_institution_admin or user.is_system_admin):
            logger.warning(f"Tentativa de acesso a /api/admin/report por usuário não autorizado: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        date_str = request.args.get('date')
        try:
            report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            logger.warning(f"Data inválida fornecida para relatório: {date_str}")
            return jsonify({'error': 'Data inválida. Use o formato AAAA-MM-DD'}), 400

        try:
            if user.is_system_admin:
                queues = Queue.query.all()
            elif user.is_institution_admin:
                branch_ids = [b.id for b in Branch.query.filter_by(institution_id=user.institution_id).all()]
                department_ids = [d.id for d in Department.query.filter(Department.branch_id.in_(branch_ids)).all()]
                queues = Queue.query.filter(Queue.department_id.in_(department_ids)).all()
            else:  # DEPARTMENT_ADMIN
                if not user.department_id:
                    logger.warning(f"Gestor {request.user_id} não vinculado a departamento")
                    return jsonify({'error': 'Gestor não vinculado a um departamento'}), 403
                queues = Queue.query.filter_by(department_id=user.department_id).all()

            start_time = datetime.combine(report_date, datetime.min.time())
            end_time = start_time + timedelta(days=1)

            report = []
            for queue in queues:
                if not QueueService.is_queue_open(queue, start_time):
                    continue

                tickets = Ticket.query.filter(
                    Ticket.queue_id == queue.id,
                    Ticket.issued_at >= start_time,
                    Ticket.issued_at < end_time
                ).all()

                issued = len(tickets)
                attended = len([t for t in tickets if t.status == 'Atendido'])
                service_times = [
                    (t.attended_at - t.issued_at).total_seconds() / 60
                    for t in tickets
                    if t.status == 'Atendido' and t.attended_at and t.issued_at
                ]
                avg_time = sum(service_times) / len(service_times) if service_times else None

                report.append({
                    'service': queue.service.name if queue.service else 'N/A',
                    'branch': queue.department.branch.name if queue.department.branch else 'N/A',
                    'issued': issued,
                    'attended': attended,
                    'avg_time': round(avg_time, 2) if avg_time else None,
                })

            logger.info(f"Relatório gerado para {user.email} em {date_str}: {len(report)} serviços")
            return jsonify(report), 200
        except SQLAlchemyError as e:
            logger.error(f"Erro ao gerar relatório para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro ao gerar relatório'}), 500

    @app.route('/api/admin/institutions/<institution_id>/departments', methods=['GET'])
    @require_auth
    def list_departments(institution_id):
        """Lista departamentos de uma instituição.

        Requer: SYSTEM_ADMIN ou INSTITUTION_ADMIN.
        Parâmetros: institution_id (UUID), page (int, opcional), per_page (int, opcional).
        Retorna: Lista paginada de departamentos.
        """
        if not validate_uuid(institution_id):
            logger.warning(f"ID de instituição inválido: {institution_id}")
            return jsonify({'error': 'ID de instituição inválido'}), 400

        user = User.query.get(request.user_id)
        if not user or not (
            user.user_role == UserRole.SYSTEM_ADMIN or
            (user.user_role == UserRole.INSTITUTION_ADMIN and user.institution_id == institution_id)
        ):
            logger.warning(f"Tentativa não autorizada de listar departamentos por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super admins ou admins da instituição'}), 403

        try:
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 20))
            departments_query = (
                Department.query
                .join(Branch)
                .filter(Branch.institution_id == institution_id)
            )
            departments_paginated = departments_query.paginate(page=page, per_page=per_page, error_out=False)
            response = [{
                'id': d.id,
                'name': d.name,
                'sector': d.sector,
                'branch_id': d.branch_id,
                'branch_name': d.branch.name if d.branch else 'N/A'
            } for d in departments_paginated.items]

            logger.info(f"Admin {user.email} listou {len(response)} departamentos da instituição {institution_id}")
            return jsonify({
                'departments': response,
                'total': departments_paginated.total,
                'page': page,
                'per_page': per_page
            }), 200
        except ValueError as e:
            logger.warning(f"Parâmetros de paginação inválidos: {str(e)}")
            return jsonify({'error': 'Parâmetros de paginação inválidos'}), 400
        except SQLAlchemyError as e:
            logger.error(f"Erro ao listar departamentos para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar departamentos'}), 500

    @app.route('/api/admin/institutions/<institution_id>/department_admins', methods=['GET'])
    @require_auth
    def list_department_admins(institution_id):
        """Lista administradores de departamentos de uma instituição.

        Requer: SYSTEM_ADMIN ou INSTITUTION_ADMIN.
        Parâmetros: institution_id (UUID), page (int, opcional), per_page (int, opcional).
        Retorna: Lista paginada de administradores.
        """
        if not validate_uuid(institution_id):
            logger.warning(f"ID de instituição inválido: {institution_id}")
            return jsonify({'error': 'ID de instituição inválido'}), 400

        user = User.query.get(request.user_id)
        if not user or not (
            user.user_role == UserRole.SYSTEM_ADMIN or
            (user.user_role == UserRole.INSTITUTION_ADMIN and user.institution_id == institution_id)
        ):
            logger.warning(f"Tentativa não autorizada de listar gestores por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super admins ou admins da instituição'}), 403

        try:
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 20))
            admins_query = User.query.filter_by(
                institution_id=institution_id,
                user_role=UserRole.DEPARTMENT_ADMIN
            )
            admins_paginated = admins_query.paginate(page=page, per_page=per_page, error_out=False)
            response = [{
                'id': m.id,
                'email': m.email,
                'name': m.name,
                'department_id': m.department_id,
                'department_name': m.department.name if m.department else 'N/A',
                'branch_id': m.branch_id,
                'branch_name': m.branch.name if m.branch else 'N/A'
            } for m in admins_paginated.items]

            logger.info(f"Admin {user.email} listou {len(response)} gestores da instituição {institution_id}")
            return jsonify({
                'department_admins': response,
                'total': admins_paginated.total,
                'page': page,
                'per_page': per_page
            }), 200
        except ValueError as e:
            logger.warning(f"Parâmetros de paginação inválidos: {str(e)}")
            return jsonify({'error': 'Parâmetros de paginação inválidos'}), 400
        except SQLAlchemyError as e:
            logger.error(f"Erro ao listar gestores para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro ao listar gestores'}), 500

    @app.route('/api/admin/institutions/<institution_id>/department_admins', methods=['POST'])
    @require_auth
    def create_department_admin(institution_id):
        """Cria um administrador de departamento.

        Requer: SYSTEM_ADMIN ou INSTITUTION_ADMIN.
        Parâmetros: institution_id (UUID).
        Corpo: {email: str, name: str, password: str, department_id: UUID, branch_id: UUID}.
        Retorna: Dados do administrador criado.
        """
        if not validate_uuid(institution_id):
            logger.warning(f"ID de instituição inválido: {institution_id}")
            return jsonify({'error': 'ID de instituição inválido'}), 400

        user = User.query.get(request.user_id)
        if not user or not (
            user.user_role == UserRole.SYSTEM_ADMIN or
            (user.user_role == UserRole.INSTITUTION_ADMIN and user.institution_id == institution_id)
        ):
            logger.warning(f"Tentativa não autorizada de criar gestor por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super admins ou admins da instituição'}), 403

        data = request.get_json()
        required = ['email', 'name', 'password', 'department_id', 'branch_id']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de gestor")
            return jsonify({'error': 'Campos obrigatórios: email, name, password, department_id, branch_id'}), 400

        if not validate_email(data['email']):
            logger.warning(f"Email inválido: {data['email']}")
            return jsonify({'error': 'Email inválido'}), 400
        if not validate_password(data['password']):
            logger.warning("Senha inválida fornecida na criação de gestor")
            return jsonify({'error': 'A senha deve ter pelo menos 8 caracteres, com letras maiúsculas, minúsculas e números'}), 400
        if not validate_name(data['name']):
            logger.warning(f"Nome inválido: {data['name']}")
            return jsonify({'error': 'Nome inválido'}), 400
        if not validate_uuid(data['department_id']) or not validate_uuid(data['branch_id']):
            logger.warning(f"IDs inválidos: department_id={data['department_id']}, branch_id={data['branch_id']}")
            return jsonify({'error': 'ID de departamento ou filial inválido'}), 400

        department = Department.query.get(data['department_id'])
        if not department or department.branch.institution_id != institution_id:
            logger.warning(f"Departamento {data['department_id']} inválido ou não pertence à instituição {institution_id}")
            return jsonify({'error': 'Departamento inválido ou não pertence à instituição'}), 400

        branch = Branch.query.get(data['branch_id'])
        if not branch or branch.institution_id != institution_id:
            logger.warning(f"Filial {data['branch_id']} inválida ou não pertence à instituição {institution_id}")
            return jsonify({'error': 'Filial inválida ou não pertence à instituição'}), 400

        try:
            if User.query.filter_by(email=data['email']).first():
                logger.warning(f"Usuário com email {data['email']} já existe")
                return jsonify({'error': 'Usuário com este email já existe'}), 400

            manager = User(
                id=str(uuid.uuid4()),
                email=data['email'],
                name=data['name'],
                user_role=UserRole.DEPARTMENT_ADMIN,
                institution_id=institution_id,
                department_id=data['department_id'],
                branch_id=data['branch_id'],
                active=True
            )
            manager.set_password(data['password'])
            db.session.add(manager)
            db.session.commit()

            socketio.emit('user_created', {
                'user_id': manager.id,
                'email': manager.email,
                'name': manager.name,
                'department_id': manager.department_id,
                'branch_id': manager.branch_id,
                'institution_id': institution_id
            }, namespace='/admin')
            if manager.fcm_token:
                QueueService.send_fcm_notification(manager.id, f"Bem-vindo ao Facilita 2.0 como gestor do departamento {department.name}")
            logger.info(f"Gestor {manager.email} criado por user_id={user.id}")
            return jsonify({
                'message': 'Gestor criado com sucesso',
                'user': {
                    'id': manager.id,
                    'email': manager.email,
                    'name': manager.name,
                    'department_id': manager.department_id,
                    'department_name': department.name,
                    'branch_id': manager.branch_id,
                    'branch_name': branch.name
                }
            }), 201
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao criar gestor: {str(e)}")
            return jsonify({'error': 'Erro ao criar gestor'}), 500

    @app.route('/api/admin/user', methods=['GET'])
    @require_auth
    def get_user_info():
        """Obtém informações do usuário autenticado.

        Requer: Qualquer usuário autenticado.
        Retorna: Dados do usuário.
        """
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

       
    @app.route('/api/admin/user', methods=['GET'])
    @require_auth
    def get_user_info():
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        try:
            response = {
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'user_role': user.user_role.value,
                'institution_id': user.institution_id,
                'department_id': user.department_id,
                'branch_id': user.branch_id,
                'department_name': user.department.name if user.department else None,
                'branch_name': user.branch.name if user.branch else None
            }
            logger.info(f"Informações do usuário retornadas para user_id={user.id}")
            QueueService.check_proactive_notifications(user.id)
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao buscar informações do usuário para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao buscar informações do usuário'}), 500
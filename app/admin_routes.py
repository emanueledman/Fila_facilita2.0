from flask import jsonify, request, send_file
from . import db, socketio
from .models import User, Queue, Ticket, Department, Institution, UserRole
from .auth import require_auth
from .services import QueueService
import logging
import uuid
from datetime import datetime, timedelta
from sqlalchemy import func
import bcrypt
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_admin_routes(app):
    @app.route('/api/admin/institutions', methods=['POST'])
    @require_auth
    def create_institution():
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.SYSTEM_ADMIN:
            logger.warning(f"Tentativa não autorizada de criar instituição por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super administradores'}), 403

        data = request.get_json()
        required = ['name', 'location', 'latitude', 'longitude']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de instituição")
            return jsonify({'error': 'Campos obrigatórios faltando: name, location, latitude, longitude'}), 400

        if Institution.query.filter_by(name=data['name']).first():
            logger.warning(f"Instituição com nome {data['name']} já existe")
            return jsonify({'error': 'Instituição com este nome já existe'}), 400

        try:
            institution = Institution(
                id=str(uuid.uuid4()),
                name=data['name'],
                location=data['location'],
                latitude=data['latitude'],
                longitude=data['longitude']
            )
            db.session.add(institution)
            db.session.commit()

            socketio.emit('institution_created', {
                'institution_id': institution.id,
                'name': institution.name,
                'location': institution.location
            }, namespace='/admin')
            logger.info(f"Instituição {institution.name} criada por user_id={user.id}")
            return jsonify({
                'message': 'Instituição criada com sucesso',
                'institution': {
                    'id': institution.id,
                    'name': institution.name,
                    'location': institution.location,
                    'latitude': institution.latitude,
                    'longitude': institution.longitude
                }
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao criar instituição: {str(e)}")
            return jsonify({'error': 'Erro interno ao criar instituição'}), 500

    @app.route('/api/admin/institutions/<institution_id>', methods=['PUT'])
    @require_auth
    def update_institution(institution_id):
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
            return jsonify({'error': 'Nenhum dado fornecido para atualização'}), 400

        try:
            institution.name = data.get('name', institution.name)
            institution.location = data.get('location', institution.location)
            institution.latitude = data.get('latitude', institution.latitude)
            institution.longitude = data.get('longitude', institution.longitude)

            if 'name' in data and data['name'] != institution.name:
                if Institution.query.filter_by(name=data['name']).first():
                    logger.warning(f"Instituição com nome {data['name']} já existe")
                    return jsonify({'error': 'Instituição com este nome já existe'}), 400

            db.session.commit()

            socketio.emit('institution_updated', {
                'institution_id': institution.id,
                'name': institution.name,
                'location': institution.location,
                'latitude': institution.latitude,
                'longitude': institution.longitude
            }, namespace='/admin')
            logger.info(f"Instituição {institution.name} atualizada por user_id={user.id}")
            return jsonify({
                'message': 'Instituição atualizada com sucesso',
                'institution': {
                    'id': institution.id,
                    'name': institution.name,
                    'location': institution.location,
                    'latitude': institution.latitude,
                    'longitude': institution.longitude
                }
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar instituição {institution_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao atualizar instituição'}), 500

    @app.route('/api/admin/institutions/<institution_id>', methods=['DELETE'])
    @require_auth
    def delete_institution(institution_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.SYSTEM_ADMIN:
            logger.warning(f"Tentativa não autorizada de excluir instituição por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super administradores'}), 403

        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        if Department.query.filter_by(institution_id=institution_id).first():
            logger.warning(f"Tentativa de excluir instituição {institution_id} com departamentos associados")
            return jsonify({'error': 'Não é possível excluir: instituição possui departamentos associados'}), 400

        try:
            db.session.delete(institution)
            db.session.commit()

            socketio.emit('institution_deleted', {
                'institution_id': institution_id,
                'name': institution.name
            }, namespace='/admin')
            logger.info(f"Instituição {institution.name} excluída por user_id={user.id}")
            return jsonify({'message': 'Instituição excluída com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao excluir instituição {institution_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao excluir instituição'}), 500

    @app.route('/api/admin/institutions/<institution_id>/admin', methods=['POST'])
    @require_auth
    def create_institution_admin(institution_id):
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
            return jsonify({'error': 'Campos obrigatórios faltando: email, name, password'}), 400

        if User.query.filter_by(email=data['email']).first():
            logger.warning(f"Usuário com email {data['email']} já existe")
            return jsonify({'error': 'Usuário com este email já existe'}), 400

        try:
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
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao criar admin de instituição: {str(e)}")
            return jsonify({'error': 'Erro interno ao criar administrador'}), 500

    @app.route('/api/admin/institutions/<institution_id>/users/<user_id>', methods=['PUT'])
    @require_auth
    def update_department_admin(institution_id, user_id):
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
            return jsonify({'error': 'Nenhum dado fornecido para atualização'}), 400

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
                if not department or department.institution_id != institution_id:
                    logger.warning(f"Departamento {data['department_id']} inválido ou não pertence à instituição {institution_id}")
                    return jsonify({'error': 'Departamento inválido ou não pertence à instituição'}), 400
                target_user.department_id = data['department_id']

            db.session.commit()

            socketio.emit('user_updated', {
                'user_id': target_user.id,
                'email': target_user.email,
                'name': target_user.name,
                'department_id': target_user.department_id,
                'institution_id': institution_id
            }, namespace='/admin')
            logger.info(f"Gestor {target_user.email} atualizado por user_id={current_user.id}")
            return jsonify({
                'message': 'Gestor atualizado com sucesso',
                'user': {
                    'id': target_user.id,
                    'email': target_user.email,
                    'name': target_user.name,
                    'role': target_user.user_role.value,
                    'department_id': target_user.department_id
                }
            }), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao atualizar gestor {user_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao atualizar gestor'}), 500

    @app.route('/api/admin/institutions/<institution_id>/users/<user_id>', methods=['DELETE'])
    @require_auth
    def delete_department_admin(institution_id, user_id):
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
            logger.info(f"Gestor {target_user.email} excluído por user_id={current_user.id}")
            return jsonify({'message': 'Gestor excluído com sucesso'}), 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao excluir gestor {user_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao excluir gestor'}), 500

    @app.route('/api/admin/institutions/<institution_id>/departments', methods=['POST'])
    @require_auth
    def create_department(institution_id):
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
        required = ['name', 'sector']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de departamento")
            return jsonify({'error': 'Campos obrigatórios faltando: name, sector'}), 400

        if Department.query.filter_by(institution_id=institution_id, name=data['name']).first():
            logger.warning(f"Departamento com nome {data['name']} já existe na instituição {institution_id}")
            return jsonify({'error': 'Departamento com este nome já existe'}), 400

        try:
            department = Department(
                id=str(uuid.uuid4()),
                institution_id=institution_id,
                name=data['name'],
                sector=data['sector']
            )
            db.session.add(department)
            db.session.commit()

            socketio.emit('department_created', {
                'department_id': department.id,
                'name': department.name,
                'institution_id': institution_id
            }, namespace='/admin')
            logger.info(f"Departamento {department.name} criado em {institution.name} por user_id={user.id}")
            return jsonify({
                'message': 'Departamento criado com sucesso',
                'department': {
                    'id': department.id,
                    'name': department.name,
                    'sector': department.sector,
                    'institution_id': institution_id
                }
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao criar departamento: {str(e)}")
            return jsonify({'error': 'Erro interno ao criar departamento'}), 500

    @app.route('/api/admin/departments/<department_id>/users', methods=['POST'])
    @require_auth
    def add_department_user(department_id):
        user = User.query.get(request.user_id)
        department = Department.query.get(department_id)
        if not department:
            logger.warning(f"Departamento {department_id} não encontrado")
            return jsonify({'error': 'Departamento não encontrado'}), 404

        if not user or not (
            user.user_role == UserRole.SYSTEM_ADMIN or
            (user.user_role == UserRole.INSTITUTION_ADMIN and user.institution_id == department.institution_id)
        ):
            logger.warning(f"Tentativa não autorizada de adicionar usuário ao departamento por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a super admins ou admins da instituição'}), 403

        data = request.get_json()
        required = ['email', 'name', 'password', 'role']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de usuário de departamento")
            return jsonify({'error': 'Campos obrigatórios faltando: email, name, password, role'}), 400

        role = data['role'].upper()
        if role not in [UserRole.USER.value, UserRole.DEPARTMENT_ADMIN.value]:
            logger.warning(f"Role inválido fornecido: {role}")
            return jsonify({'error': 'Role deve ser USER ou DEPARTMENT_ADMIN'}), 400

        if User.query.filter_by(email=data['email']).first():
            logger.warning(f"Usuário com email {data['email']} já existe")
            return jsonify({'error': 'Usuário com este email já existe'}), 400

        try:
            new_user = User(
                id=str(uuid.uuid4()),
                email=data['email'],
                name=data['name'],
                user_role=UserRole[role],
                department_id=department_id,
                institution_id=department.institution_id,
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
                'institution_id': department.institution_id
            }, namespace='/admin')
            logger.info(f"Usuário {new_user.email} ({role}) adicionado ao departamento {department.name} por user_id={user.id}")
            return jsonify({
                'message': 'Usuário adicionado ao departamento com sucesso',
                'user': {
                    'id': new_user.id,
                    'email': new_user.email,
                    'name': new_user.name,
                    'role': new_user.user_role.value,
                    'department_id': department_id
                }
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao adicionar usuário ao departamento: {str(e)}")
            return jsonify({'error': 'Erro interno ao adicionar usuário'}), 500

    @app.route('/api/institutions/<institution_id>/calls', methods=['GET'])
    def list_institution_calls(institution_id):
        institution = Institution.query.get(institution_id)
        if not institution:
            logger.warning(f"Instituição {institution_id} não encontrada")
            return jsonify({'error': 'Instituição não encontrada'}), 404

        try:
            departments = Department.query.filter_by(institution_id=institution_id).all()
            department_ids = [d.id for d in departments]
            queues = Queue.query.filter(Queue.department_id.in_(department_ids)).all()
            queue_ids = [q.id for q in queues]

            recent_calls = Ticket.query.filter(
                Ticket.queue_id.in_(queue_ids),
                Ticket.status.in_(['Chamado', 'attended'])
            ).order_by(Ticket.attended_at.desc(), Ticket.issued_at.desc()).limit(10).all()

            response = []
            for ticket in recent_calls:
                queue = Queue.query.get(ticket.queue_id)
                if not queue or not queue.department:
                    continue
                response.append({
                    'ticket_id': ticket.id,
                    'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
                    'service': queue.service,
                    'department': queue.department.name,
                    'counter': f"Guichê {ticket.counter:02d}" if ticket.counter else "N/A",
                    'status': ticket.status,
                    'called_at': ticket.attended_at.isoformat() if ticket.attended_at else ticket.issued_at.isoformat()
                })

            logger.info(f"Listadas {len(response)} chamadas recentes para instituição {institution_id}")
            return jsonify({
                'institution_id': institution_id,
                'institution_name': institution.name,
                'calls': response
            }), 200
        except Exception as e:
            logger.error(f"Erro ao listar chamadas para instituição {institution_id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar chamadas'}), 500

    @app.route('/api/physical-ticket', methods=['POST'])
    def generate_physical_ticket():
        data = request.get_json()
        required = ['department_id', 'service']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na geração de senha física")
            return jsonify({'error': 'Campos obrigatórios faltando: department_id, service'}), 400

        department = Department.query.get(data['department_id'])
        if not department:
            logger.warning(f"Departamento {data['department_id']} não encontrado")
            return jsonify({'error': 'Departamento não encontrado'}), 404

        queue = Queue.query.filter_by(department_id=data['department_id'], service=data['service']).first()
        if not queue:
            logger.warning(f"Fila para serviço {data['service']} não encontrada no departamento {data['department_id']}")
            return jsonify({'error': 'Fila não encontrada para o serviço especificado'}), 400

        try:
            ticket, pdf_buffer = QueueService.add_to_queue(
                service=data['service'],
                user_id='PRESENCIAL',
                priority=data.get('priority', 0),
                is_physical=True,
                fcm_token=None
            )

            socketio.emit('ticket_update', {
                'ticket_id': ticket.id,
                'ticket_number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                'service': queue.service,
                'department': department.name,
                'counter': f"Guichê {ticket.counter:02d}" if ticket.counter else None,
                'status': ticket.status
            }, namespace='/tickets')

            logger.info(f"Senha física gerada: {ticket.queue.prefix}{ticket.ticket_number} para serviço {data['service']}")
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=f"ticket_{ticket.queue.prefix}{ticket.ticket_number}.pdf",
                mimetype='application/pdf'
            )
        except ValueError as e:
            logger.error(f"Erro ao gerar senha física para serviço {data['service']}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Erro interno ao gerar senha física: {str(e)}")
            return jsonify({'error': 'Erro interno ao gerar senha'}), 500

    @app.route('/api/admin/queues', methods=['GET'])
    @require_auth
    def list_admin_queues():
        user = User.query.get(request.user_id)
        if not user:
            logger.error(f"Usuário não encontrado no banco para user_id={request.user_id}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        if user.user_role != UserRole.DEPARTMENT_ADMIN:
            logger.warning(f"Tentativa de acesso a /api/admin/queues por usuário não dept_admin: {request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores de departamento'}), 403

        if not user.department_id:
            logger.warning(f"Gestor {request.user_id} não vinculado a departamento")
            return jsonify({'error': 'Gestor não vinculado a um departamento'}), 403

        try:
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
                'department': q.department.name if q.department else 'N/A',
                'open_time': q.open_time.strftime('%H:%M') if q.open_time else None,
                'end_time': q.end_time.strftime('%H:%M') if q.end_time else None
            } for q in queues]

            logger.info(f"Gestor {user.email} listou {len(response)} filas do departamento {user.department.name if user.department else 'N/A'}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar filas para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar filas'}), 500

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
        except Exception as e:
            logger.error(f"Erro interno ao chamar próxima senha: {str(e)}")
            return jsonify({'error': 'Erro interno ao chamar senha'}), 500

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

        try:
            queues = Queue.query.filter_by(department_id=user.department_id).all()
            if not queues:
                logger.info(f"Nenhuma fila encontrada para o gestor {user.email}")
                return jsonify([]), 200

            queue_ids = [queue.id for queue in queues]
            tickets = Ticket.query.filter(Ticket.queue_id.in_(queue_ids)).order_by(
                Ticket.status.asc(),
                Ticket.issued_at.desc()
            ).limit(50).all()

            response = [{
                'id': ticket.id,
                'number': f"{ticket.queue.prefix}{ticket.ticket_number}" if ticket.queue else ticket.ticket_number,
                'queue_id': ticket.queue_id,
                'service': ticket.queue.service if ticket.queue else 'N/A',
                'status': ticket.status,
                'issued_at': ticket.issued_at.isoformat() if ticket.issued_at else None,
                'attended_at': ticket.attended_at.isoformat() if ticket.attended_at else None,
                'counter': ticket.counter,
                'user_id': ticket.user_id
            } for ticket in tickets]

            logger.info(f"Gestor {user.email} listou {len(response)} tickets")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar tickets para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar tickets'}), 500

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

        try:
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
                    'avg_time': round(avg_time, 2) if avg_time else None,
                })

            logger.info(f"Relatório gerado para {user.email} em {date_str}: {len(report)} serviços")
            return jsonify(report), 200
        except Exception as e:
            logger.error(f"Erro ao gerar relatório para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao gerar relatório'}), 500

    @app.route('/api/admin/institutions/<institution_id>/departments', methods=['GET'])
    @require_auth
    def list_departments(institution_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.INSTITUTION_ADMIN or user.institution_id != institution_id:
            logger.warning(f"Tentativa não autorizada de listar departamentos por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da instituição'}), 403

        try:
            departments = Department.query.filter_by(institution_id=institution_id).all()
            response = [{
                'id': d.id,
                'name': d.name,
                'sector': d.sector
            } for d in departments]

            logger.info(f"Admin {user.email} listou {len(response)} departamentos da instituição {institution_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar departamentos para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar departamentos'}), 500

    @app.route('/api/admin/institutions/<institution_id>/managers', methods=['GET'])
    @require_auth
    def list_managers(institution_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.INSTITUTION_ADMIN or user.institution_id != institution_id:
            logger.warning(f"Tentativa não autorizada de listar gestores por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da instituição'}), 403

        try:
            managers = User.query.filter_by(
                institution_id=institution_id,
                user_role=UserRole.DEPARTMENT_ADMIN
            ).all()
            response = [{
                'id': m.id,
                'email': m.email,
                'name': m.name,
                'department_id': m.department_id,
                'department_name': m.department.name if m.department else 'N/A'
            } for m in managers]

            logger.info(f"Admin {user.email} listou {len(response)} gestores da instituição {institution_id}")
            return jsonify(response), 200
        except Exception as e:
            logger.error(f"Erro ao listar gestores para user_id={user.id}: {str(e)}")
            return jsonify({'error': 'Erro interno ao listar gestores'}), 500

    @app.route('/api/admin/institutions/<institution_id>/managers', methods=['POST'])
    @require_auth
    def create_manager(institution_id):
        user = User.query.get(request.user_id)
        if not user or user.user_role != UserRole.INSTITUTION_ADMIN or user.institution_id != institution_id:
            logger.warning(f"Tentativa não autorizada de criar gestor por user_id={request.user_id}")
            return jsonify({'error': 'Acesso restrito a administradores da instituição'}), 403

        data = request.get_json()
        required = ['email', 'name', 'password', 'department_id']
        if not data or not all(f in data for f in required):
            logger.warning("Campos obrigatórios faltando na criação de gestor")
            return jsonify({'error': 'Campos obrigatórios faltando: email, name, password, department_id'}), 400

        department = Department.query.get(data['department_id'])
        if not department or department.institution_id != institution_id:
            logger.warning(f"Departamento {data['department_id']} inválido ou não pertence à instituição {institution_id}")
            return jsonify({'error': 'Departamento inválido ou não pertence à instituição'}), 400

        if User.query.filter_by(email=data['email']).first():
            logger.warning(f"Usuário com email {data['email']} já existe")
            return jsonify({'error': 'Usuário com este email já existe'}), 400

        try:
            manager = User(
                id=str(uuid.uuid4()),
                email=data['email'],
                name=data['name'],
                user_role=UserRole.DEPARTMENT_ADMIN,
                institution_id=institution_id,
                department_id=data['department_id'],
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
                'institution_id': institution_id
            }, namespace='/admin')
            logger.info(f"Gestor {manager.email} criado por user_id={user.id}")
            return jsonify({
                'message': 'Gestor criado com sucesso',
                'user': {
                    'id': manager.id,
                    'email': manager.email,
                    'name': manager.name,
                    'department_id': manager.department_id,
                    'department_name': department.name
                }
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao criar gestor: {str(e)}")
            return jsonify({'error': 'Erro interno ao criar gestor'}), 500
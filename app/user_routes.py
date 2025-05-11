from flask import jsonify, request, make_response
from . import db
from .models import User, UserRole, Queue, Department, Institution, Branch, BranchSchedule, Weekday
from .auth import require_auth
import logging
import jwt
import os
from datetime import datetime, timedelta
import pytz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_user_routes(app):
    @app.route('/api/admin/login', methods=['POST', 'OPTIONS'])
    def admin_login():
        if request.method == 'OPTIONS':
            response = make_response()
            response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
            response.headers['Access-Control-Max-Age'] = '86400'
            return response

        logger.info("Recebida requisição POST para /api/admin/login")
        try:
            data = request.get_json()
            if not data:
                logger.warning("Requisição POST sem corpo JSON")
                return jsonify({"error": "Corpo da requisição inválido"}), 400

            email = data.get('email')
            password = data.get('password')
            if not email or not password:
                logger.warning("Tentativa de login sem email ou senha")
                return jsonify({"error": "Email e senha são obrigatórios"}), 400

            logger.info(f"Buscando usuário com email={email}")
            user = User.query.filter_by(email=email).first()
            if not user:
                logger.warning(f"Usuário não encontrado para email={email}")
                return jsonify({"error": "Credenciais inválidas"}), 401

            if not user.check_password(password):
                logger.warning(f"Senha inválida para email={email}")
                return jsonify({"error": "Credenciais inválidas"}), 401

            if user.user_role not in [UserRole.ATTENDANT, UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
                logger.warning(f"Usuário {email} tem papel inválido: {user.user_role.value}")
                return jsonify({"error": "Acesso restrito a atendentes, administradores ou sistema"}), 403

            secret_key = os.getenv('JWT_SECRET_KEY', '1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0')
            token = jwt.encode({
                'user_id': user.id,
                'user_role': user.user_role.value,
                'exp': datetime.utcnow() + timedelta(days=30)  # Extended to 30 days
            }, secret_key, algorithm='HS256')

            if isinstance(token, bytes):
                token = token.decode('utf-8')

            response_data = {
                "token": token,
                "user_id": user.id,
                "user_role": user.user_role.value,
                "institution_id": user.institution_id,
                "branch_id": user.branch_id,
                "email": user.email
            }

            def get_branch_schedule(branch_id, now=None):
                if not now:
                    local_tz = pytz.timezone('Africa/Luanda')
                    now = datetime.now(local_tz)
                weekday_str = now.strftime('%A').upper()
                try:
                    weekday_enum = Weekday[weekday_str]
                except KeyError:
                    logger.error(f"Dia da semana inválido: {weekday_str}")
                    return None, None
                schedule = BranchSchedule.query.filter_by(
                    branch_id=branch_id,
                    weekday=weekday_enum
                ).first()
                if schedule and not schedule.is_closed:
                    return (
                        schedule.open_time.strftime('%H:%M') if schedule.open_time else None,
                        schedule.end_time.strftime('%H:%M') if schedule.end_time else None
                    )
                return None, None

            if user.user_role == UserRole.ATTENDANT:
                if not user.branch_id:
                    logger.warning(f"Atendente {user.id} não vinculado a filial")
                    return jsonify({"error": "Atendente não vinculado a uma filial"}), 403
                queues = Queue.query.join(Department).filter(Department.branch_id == user.branch_id).all()
                response_data["queues"] = []
                for q in queues:
                    open_time, end_time = get_branch_schedule(user.branch_id)
                    response_data["queues"].append({
                        'id': q.id,
                        'service': q.service.name if q.service else 'N/A',
                        'prefix': q.prefix,
                        'department': q.department.name if q.department else 'N/A',
                        'active_tickets': q.active_tickets,
                        'daily_limit': q.daily_limit,
                        'current_ticket': q.current_ticket,
                        'status': 'Aberto' if q.active_tickets < q.daily_limit else 'Lotado',
                        'open_time': open_time,
                        'end_time': end_time
                    })

            elif user.user_role == UserRole.BRANCH_ADMIN:
                if not user.branch_id:
                    logger.warning(f"Admin de filial {user.id} não vinculado a filial")
                    return jsonify({"error": "Admin não vinculado a uma filial"}), 403
                departments = Department.query.filter_by(branch_id=user.branch_id).all()
                response_data["departments"] = [{
                    'id': d.id,
                    'name': d.name,
                    'sector': d.sector
                } for d in departments]
                queues = Queue.query.join(Department).filter(Department.branch_id=user.branch_id).all()
                response_data["queues"] = []
                for q in queues:
                    open_time, end_time = get_branch_schedule(user.branch_id)
                    response_data["queues"].append({
                        'id': q.id,
                        'service': q.service.name if q.service else 'N/A',
                        'prefix': q.prefix,
                        'department': q.department.name if q.department else 'N/A',
                        'active_tickets': q.active_tickets,
                        'daily_limit': q.daily_limit,
                        'current_ticket': q.current_ticket,
                        'status': 'Aberto' if q.active_tickets < q.daily_limit else 'Lotado',
                        'open_time': open_time,
                        'end_time': end_time
                    })
                attendants = User.query.filter_by(branch_id=user.branch_id, user_role=UserRole.ATTENDANT).all()
                response_data["attendants"] = [{
                    'id': a.id,
                    'email': a.email,
                    'name': a.name,
                    'branch_id': a.branch_id,
                    'branch_name': a.branch.name if a.branch else 'N/A'
                } for a in attendants]

            elif user.user_role == UserRole.INSTITUTION_ADMIN:
                if not user.institution_id:
                    logger.warning(f"Admin {user.id} não vinculado a instituição")
                    return jsonify({"error": "Admin não vinculado a uma instituição"}), 403
                departments = Department.query.join(Branch).filter(Branch.institution_id == user.institution_id).all()
                response_data["departments"] = [{
                    'id': d.id,
                    'name': d.name,
                    'sector': d.sector,
                    'branch_id': d.branch_id,
                    'branch_name': d.branch.name if d.branch else 'N/A'
                } for d in departments]
                branches = Branch.query.filter_by(institution_id=user.institution_id).all()
                response_data["branches"] = [{
                    'id': b.id,
                    'name': b.name,
                    'location': b.location,
                    'neighborhood': b.neighborhood
                } for b in branches]
                attendants = User.query.filter_by(institution_id=user.institution_id, user_role=UserRole.ATTENDANT).all()
                response_data["attendants"] = [{
                    'id': a.id,
                    'email': a.email,
                    'name': a.name,
                    'branch_id': a.branch_id,
                    'branch_name': a.branch.name if a.branch else 'N/A'
                } for a in attendants]
                branch_admins = User.query.filter_by(institution_id=user.institution_id, user_role=UserRole.BRANCH_ADMIN).all()
                response_data["branch_admins"] = [{
                    'id': ba.id,
                    'email': ba.email,
                    'name': ba.name,
                    'branch_id': ba.branch_id,
                    'branch_name': ba.branch.name if ba.branch else 'N/A'
                } for ba in branch_admins]

            elif user.user_role == UserRole.SYSTEM_ADMIN:
                institutions = Institution.query.all()
                response_data["institutions"] = [{
                    'id': i.id,
                    'name': i.name,
                    'type': i.type.name if i.type else 'N/A'
                } for i in institutions]

            response = jsonify(response_data)
            response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
            response.headers.add('Access-Control-Allow-Credentials', 'true')

            logger.info(f"Login bem-sucedido para usuário: {email} ({user.user_role.value})")
            return response, 200

        except Exception as e:
            logger.error(f"Erro ao processar login para email={request.json.get('email', 'unknown')}: {str(e)}")
            return jsonify({"error": "Erro interno no servidor"}), 500

    @app.route('/api/auth/verify-token', methods=['GET', 'OPTIONS'])
    @require_auth
    def verify_token():
        if request.method == 'OPTIONS':
            response = make_response()
            response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
            response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
            response.headers['Access-Control-Max-Age'] = '86400'
            return response

        try:
            user_id = request.user_id
            user = User.query.get(user_id)
            if not user:
                logger.warning(f"Usuário não encontrado para ID={user_id}")
                return jsonify({"error": "Usuário não encontrado"}), 404

            response_data = {
                "user_id": user.id,
                "user_role": user.user_role.value,
                "email": user.email,
                "institution_id": user.institution_id,
                "branch_id": user.branch_id
            }

            logger.info(f"Token verificado para usuário: {user.email} ({user.user_role.value})")
            response = jsonify(response_data)
            response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
            response.headers.add('Access-Control-Allow-Credentials', 'true')
            return response, 200

        except Exception as e:
            logger.error(f"Erro ao verificar token para user_id={request.user_id}: {str(e)}")
            return jsonify({"error": "Erro interno no servidor"}), 500
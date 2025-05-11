from flask import jsonify, request, make_response
from app import db, app
from app.models import User, UserRole, Queue, Department, Institution, Branch, BranchSchedule, Weekday
import logging
from datetime import datetime, timedelta
import pytz
import jwt
import os
from app.auth import generate_tokens, require_auth
from flask_cors import CORS

# Configuração de CORS
CORS(app, resources={r"/api/*": {
    "origins": ["https://fila-facilita2-0-4uzw.onrender.com", "http://localhost:3000"],
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
    "supports_credentials": True
}})

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

def init_user_routes(app):
    @app.route('/api/admin/login', methods=['POST', 'OPTIONS'])
    def admin_login():
        if request.method == 'OPTIONS':
            response = make_response()
            return response

        try:
            data = request.get_json()
            if not data or not isinstance(data, dict):
                logger.warning("Requisição sem corpo JSON válido")
                return jsonify({"error": "Corpo da requisição inválido"}), 400

            email = data.get('email', '').strip()
            password = data.get('password', '')
            if not email or not password:
                logger.warning("Tentativa de login sem email ou senha")
                return jsonify({"error": "Email e senha são obrigatórios"}), 400

            if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
                logger.warning(f"Email inválido: {email}")
                return jsonify({"error": "Formato de email inválido"}), 400

            user = User.query.filter_by(email=email).first()
            if not user or not user.check_password(password):
                logger.warning(f"Credenciais inválidas para email={email}")
                return jsonify({"error": "Credenciais inválidas"}), 401

            if user.user_role not in [UserRole.ATTENDANT, UserRole.BRANCH_ADMIN, UserRole.INSTITUTION_ADMIN, UserRole.SYSTEM_ADMIN]:
                logger.warning(f"Usuário {email} tem papel inválido: {user.user_role.value}")
                return jsonify({"error": "Acesso restrito a administradores"}), 403

            access_token, refresh_token = generate_tokens(user)
            response_data = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "user_id": user.id,
                "user_role": user.user_role.value,
                "email": user.email,
                "institution_id": user.institution_id,
                "branch_id": user.branch_id
            }

            def get_branch_schedule(branch_id, now=None):
                if not now:
                    local_tz = pytz.timezone('Africa/Luanda')
                    now = datetime.now(local_tz)
                try:
                    weekday_str = now.strftime('%A').upper()
                    weekday_enum = Weekday[weekday_str]
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
                except KeyError:
                    logger.error(f"Dia da semana inválido: {weekday_str}")
                    return None, None

            if user.user_role == UserRole.ATTENDANT:
                if not user.branch_id:
                    logger.warning(f"Atendente {user.id} não vinculado a filial")
                    return jsonify({"error": "Atendente não vinculado a uma filial"}), 403
                queues = Queue.query.join(Department).filter(Department.branch_id == user.branch_id).all()
                response_data["queues"] = [
                    {
                        'id': q.id,
                        'service': q.service.name if q.service else 'N/A',
                        'prefix': q.prefix,
                        'department': q.department.name if q.department else 'N/A',
                        'active_tickets': q.active_tickets,
                        'daily_limit': q.daily_limit,
                        'current_ticket': q.current_ticket,
                        'status': 'Aberto' if q.active_tickets < q.daily_limit else 'Lotado',
                        'open_time': get_branch_schedule(user.branch_id)[0],
                        'end_time': get_branch_schedule(user.branch_id)[1]
                    } for q in queues
                ]

            elif user.user_role == UserRole.BRANCH_ADMIN:
                if not user.branch_id:
                    logger.warning(f"Admin de filial {user.id} não vinculado a filial")
                    return jsonify({"error": "Admin não vinculado a uma filial"}), 403
                departments = Department.query.filter_by(branch_id=user.branch_id).all()
                response_data["departments"] = [
                    {'id': d.id, 'name': d.name, 'sector': d.sector} for d in departments
                ]
                queues = Queue.query.join(Department).filter(Department.branch_id == user.branch_id).all()
                response_data["queues"] = [
                    {
                        'id': q.id,
                        'service': q.service.name if q.service else 'N/A',
                        'prefix': q.prefix,
                        'department': q.department.name if q.department else 'N/A',
                        'active_tickets': q.active_tickets,
                        'daily_limit': q.daily_limit,
                        'current_ticket': q.current_ticket,
                        'status': 'Aberto' if q.active_tickets < q.daily_limit else 'Lotado',
                        'open_time': get_branch_schedule(user.branch_id)[0],
                        'end_time': get_branch_schedule(user.branch_id)[1]
                    } for q in queues
                ]
                attendants = User.query.filter_by(branch_id=user.branch_id, user_role=UserRole.ATTENDANT).all()
                response_data["attendants"] = [
                    {
                        'id': a.id,
                        'email': a.email,
                        'name': a.name,
                        'branch_id': a.branch_id,
                        'branch_name': a.branch.name if a.branch else 'N/A'
                    } for a in attendants
                ]

            elif user.user_role == UserRole.INSTITUTION_ADMIN:
                if not user.institution_id:
                    logger.warning(f"Admin {user.id} não vinculado a instituição")
                    return jsonify({"error": "Admin não vinculado a uma instituição"}), 403
                departments = Department.query.join(Branch).filter(Branch.institution_id == user.institution_id).all()
                response_data["departments"] = [
                    {
                        'id': d.id,
                        'name': d.name,
                        'sector': d.sector,
                        'branch_id': d.branch_id,
                        'branch_name': d.branch.name if d.branch else 'N/A'
                    } for d in departments
                ]
                branches = Branch.query.filter_by(institution_id=user.institution_id).all()
                response_data["branches"] = [
                    {
                        'id': b.id,
                        'name': b.name,
                        'location': b.location,
                        'neighborhood': b.neighborhood
                    } for b in branches
                ]
                attendants = User.query.filter_by(institution_id=user.institution_id, user_role=UserRole.ATTENDANT).all()
                response_data["attendants"] = [
                    {
                        'id': a.id,
                        'email': a.email,
                        'name': a.name,
                        'branch_id': a.branch_id,
                        'branch_name': a.branch.name if a.branch else 'N/A'
                    } for a in attendants
                ]
                branch_admins = User.query.filter_by(institution_id=user.institution_id, user_role=UserRole.BRANCH_ADMIN).all()
                response_data["branch_admins"] = [
                    {
                        'id': ba.id,
                        'email': ba.email,
                        'name': ba.name,
                        'branch_id': ba.branch_id,
                        'branch_name': ba.branch.name if ba.branch else 'N/A'
                    } for ba in branch_admins
                ]

            elif user.user_role == UserRole.SYSTEM_ADMIN:
                institutions = Institution.query.all()
                response_data["institutions"] = [
                    {
                        'id': i.id,
                        'name': i.name,
                        'type': i.type.name if i.type else 'N/A'
                    } for i in institutions
                ]

            response = jsonify(response_data)
            response.set_cookie('refresh_token', refresh_token, httponly=True, secure=True, samesite='Strict', max_age=7*24*60*60)
            logger.info(f"Login bem-sucedido: email={email}, role={user.user_role.value}")
            return response, 200

        except Exception as e:
            logger.error(f"Erro ao processar login para email={data.get('email', 'unknown')}: {str(e)}")
            return jsonify({"error": "Erro interno do servidor"}), 500

    @app.route('/api/auth/refresh', methods=['POST'])
    @require_auth
    def refresh_token():
        try:
            refresh_token = request.cookies.get('refresh_token')
            if not refresh_token:
                return jsonify({"error": "Refresh token necessário"}), 401

            payload = jwt.decode(refresh_token, JWT_SECRET, algorithms=['HS256'])
            user = User.query.get(payload['user_id'])
            if not user:
                return jsonify({"error": "Usuário não encontrado"}), 404

            access_token, new_refresh_token = generate_tokens(user)
            response = jsonify({"access_token": access_token})
            response.set_cookie('refresh_token', new_refresh_token, httponly=True, secure=True, samesite='Strict', max_age=7*24*60*60)
            logger.info(f"Token atualizado para user_id={user.id}")
            return response, 200

        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Refresh token expirado"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Refresh token inválido"}), 401
        except Exception as e:
            logger.error(f"Erro ao atualizar token: {str(e)}")
            return jsonify({"error": "Erro interno do servidor"}), 500
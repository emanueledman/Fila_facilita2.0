from flask import request, jsonify, make_response
import jwt
import os
from functools import wraps
import firebase_admin
from firebase_admin import credentials, auth
import json
import logging
from datetime import datetime, timedelta
from . import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

firebase_creds_json = os.getenv('FIREBASE_CREDENTIALS')
if not firebase_creds_json:
    logger.error("Variável de ambiente FIREBASE_CREDENTIALS não encontrada")
    raise ValueError("Credenciais do Firebase não encontradas na variável de ambiente FIREBASE_CREDENTIALS")

try:
    cred_dict = json.loads(firebase_creds_json)
    cred = credentials.Certificate(cred_dict)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    logger.info("Firebase Admin SDK inicializado com sucesso")
except json.JSONDecodeError as e:
    logger.error(f"Erro ao decodificar FIREBASE_CREDENTIALS: {e}")
    raise ValueError("FIREBASE_CREDENTIALS inválido: formato JSON incorreto")
except Exception as e:
    logger.error(f"Erro ao inicializar Firebase Admin SDK: {e}")
    raise ValueError(f"Erro ao inicializar Firebase: {e}")

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            logger.warning("Requisição sem token de autenticação")
            return jsonify({'error': 'Token de autenticação necessário'}), 401
        
        try:
            token = token.replace('Bearer ', '')
            decoded_token = auth.verify_id_token(token)
            request.user_id = decoded_token['uid']
            request.user_tipo = 'user'
            logger.info(f"Token Firebase válido para UID: {request.user_id}")
        except (auth.InvalidIdTokenError, ValueError) as e:
            logger.warning(f"Token Firebase inválido: {e}")
            try:
                payload = jwt.decode(token, os.getenv('JWT_SECRET', '974655'), algorithms=['HS256'])
                request.user_id = payload['user_id']
                request.user_tipo = payload.get('user_tipo', 'user')
                logger.info(f"Token JWT local válido para user_id: {request.user_id}, user_tipo: {request.user_tipo}")
            except jwt.ExpiredSignatureError:
                logger.warning("Token JWT local expirado")
                return jsonify({'error': 'Token expirado'}), 401
            except jwt.InvalidTokenError:
                logger.warning("Token JWT local inválido")
                return jsonify({'error': 'Token inválido'}), 401
        
        return f(*args, **kwargs)
    return decorated

def init_auth_routes(app):
    @app.route('/api/admin/login', methods=['POST', 'OPTIONS'])
    def admin_login():
        if request.method == 'OPTIONS':
            # Resposta para requisição preflight
            response = make_response()
            response.headers['Access-Control-Allow-Origin'] = 'https://glistening-klepon-5ebcce.netlify.app'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Max-Age'] = 86400  # Cache por 24 horas
            logger.info("Resposta OPTIONS enviada para /api/admin/login")
            return response, 200

        logger.info("Recebida requisição POST para /api/admin/login")
        try:
            data = request.get_json()
            if not data or 'email' not in data or 'password' not in data:
                logger.warning("Tentativa de login de admin sem email ou senha")
                return jsonify({'error': 'Email e senha são obrigatórios'}), 400

            email = data['email']
            password = data['password']

            from .models import User
            logger.info(f"Buscando usuário com email={email}")
            user = User.query.filter_by(email=email).first()
            if not user:
                logger.warning(f"Tentativa de login de admin com email não encontrado: {email}")
                return jsonify({'error': 'Usuário não encontrado'}), 404

            if not user.check_password(password):
                logger.warning(f"Tentativa de login de admin com senha incorreta para email: {email}")
                return jsonify({'error': 'Credenciais inválidas'}), 401

            if user.user_tipo != 'gestor':
                logger.warning(f"Tentativa de login de admin por usuário não administrador: {email}")
                return jsonify({'error': 'Acesso restrito a administradores'}), 403

            token = jwt.encode({
                'user_id': user.id,
                'user_tipo': 'gestor',
                'exp': datetime.utcnow() + timedelta(hours=24)
            }, os.getenv('JWT_SECRET', '974655'), algorithm='HS256')
            logger.info(f"Token gerado para admin user_id: {user.id}")
            return jsonify({
                'token': token,
                'user_id': user.id,
                'user_tipo': 'gestor',
                'institution_id': user.institution_id,
                'department': user.department,
                'email': user.email
            }), 200

        except Exception as e:
            logger.error(f"Erro ao processar login para email={email}: {str(e)}")
            return jsonify({'error': 'Erro interno no servidor'}), 500

    @app.route('/api/update_fcm_token', methods=['POST'])
    @require_auth
    def update_fcm_token():
        from .models import User
        data = request.get_json()
        fcm_token = data.get('fcm_token')
        email = data.get('email')

        if not fcm_token or not email:
            logger.warning("Requisição sem FCM token ou email")
            return jsonify({'error': 'FCM token e email são obrigatórios'}), 400

        user = User.query.filter_by(email=email).first()
        if not user:
            logger.warning(f"Usuário não encontrado para email: {email}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        if user.id != request.user_id:
            logger.warning(f"Tentativa de atualização de FCM token com email inválido: {email}")
            return jsonify({'error': 'Acesso não autorizado'}), 403

        user.fcm_token = fcm_token
        db.session.commit()
        logger.info(f"FCM token atualizado para usuário {user.email}")
        return jsonify({'message': 'FCM token atualizado com sucesso'}), 200
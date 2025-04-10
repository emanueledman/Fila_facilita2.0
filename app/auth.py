from flask import request, jsonify
import jwt
import os
from functools import wraps
import firebase_admin
from firebase_admin import credentials, auth
import json
import logging
from datetime import datetime, timedelta

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Carregar e inicializar o Firebase Admin SDK
firebase_creds_json = os.getenv('FIREBASE_CREDENTIALS')
if not firebase_creds_json:
    logger.error("Variável de ambiente FIREBASE_CREDENTIALS não encontrada")
    raise ValueError("Credenciais do Firebase não encontradas na variável de ambiente FIREBASE_CREDENTIALS")

try:
    cred_dict = json.loads(firebase_creds_json)
    cred = credentials.Certificate(cred_dict)
    if not firebase_admin._apps:  # Verificar se o Firebase já foi inicializado
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
            # Tentar verificar como token do Firebase (usuários normais)
            decoded_token = auth.verify_id_token(token)
            request.user_id = decoded_token['uid']  # UID do Firebase
            request.user_tipo = 'user'  # Usuários normais têm user_tipo='user'
            logger.info(f"Token Firebase válido para UID: {request.user_id}")
        except (auth.InvalidIdTokenError, ValueError) as e:
            logger.warning(f"Token Firebase inválido: {e}")
            # Fallback para token JWT local (administradores)
            try:
                payload = jwt.decode(token, os.getenv('JWT_SECRET', '974655'), algorithms=['HS256'])
                request.user_id = payload['user_id']
                request.user_tipo = payload.get('user_tipo', 'user')  # Extrair user_tipo do token JWT
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
    @app.route('/api/admin/login', methods=['POST'])
    def admin_login():
        data = request.get_json()
        if not data or 'email' not in data or 'password' not in data:
            logger.warning("Tentativa de login de admin sem email ou senha")
            return jsonify({'error': 'Email e senha são obrigatórios'}), 400

        email = data['email']
        password = data['password']

        # Verificar as credenciais do administrador no banco de dados
        from .models import User
        user = User.query.filter_by(email=email).first()
        if not user:
            logger.warning(f"Tentativa de login de admin com email não encontrado: {email}")
            return jsonify({'error': 'Usuário não encontrado'}), 404

        # Simulação de verificação de senha (substitua por verificação real com hash)
        # Para este exemplo, assumimos que a senha é 'admin123' (NÃO FAÇA ISSO EM PRODUÇÃO)
        if password != 'admin123':
            logger.warning(f"Tentativa de login de admin com senha incorreta para email: {email}")
            return jsonify({'error': 'Credenciais inválidas'}), 401

        # Verificar se o usuário é um administrador
        if user.user_tipo != 'gestor':
            logger.warning(f"Tentativa de login de admin por usuário não administrador: {email}")
            return jsonify({'error': 'Acesso restrito a administradores'}), 403

        # Gerar token JWT para o administrador
        token = jwt.encode({
            'user_id': user.id,
            'user_tipo': 'gestor',  # Definir como 'gestor' para administradores
            'exp': datetime.utcnow() + timedelta(hours=24)
        }, os.getenv('JWT_SECRET', '974655'), algorithm='HS256')
        logger.info(f"Token gerado para admin user_id: {user.id}")
        return jsonify({
            'token': token,
            'user_id': user.id,
            'user_tipo': 'gestor',
            'institution_id': user.institution_id,
            'department': user.department
        }), 200
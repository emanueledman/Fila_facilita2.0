# app/auth.py
from flask import request, jsonify
import jwt
import os
from functools import wraps
import firebase_admin
from firebase_admin import credentials, auth
import json
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Carregar credenciais do Firebase a partir de uma variável de ambiente
firebase_creds_json = os.getenv('FIREBASE_CREDENTIALS')
if firebase_creds_json:
    try:
        cred_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK inicializado com sucesso")
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar FIREBASE_CREDENTIALS: {e}")
        raise ValueError("FIREBASE_CREDENTIALS inválido: formato JSON incorreto")
    except Exception as e:
        logger.error(f"Erro ao inicializar Firebase Admin SDK: {e}")
        raise ValueError(f"Erro ao inicializar Firebase: {e}")
else:
    logger.error("Variável de ambiente FIREBASE_CREDENTIALS não encontrada")
    raise ValueError("Credenciais do Firebase não encontradas na variável de ambiente FIREBASE_CREDENTIALS")

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            logger.warning("Requisição sem token de autenticação")
            return jsonify({'error': 'Token de autenticação necessário'}), 401
        
        try:
            token = token.replace('Bearer ', '')
            # Verificar token do Firebase
            decoded_token = auth.verify_id_token(token)
            request.user_id = decoded_token['uid']  # UID do Firebase
            logger.info(f"Token Firebase válido para UID: {request.user_id}")
        except (auth.InvalidIdTokenError, ValueError) as e:
            logger.warning(f"Token Firebase inválido: {e}")
            # Fallback para token JWT local
            try:
                payload = jwt.decode(token, os.getenv('JWT_SECRET', '974655'), algorithms=['HS256'])
                request.user_id = payload['user_id']
                logger.info(f"Token JWT local válido para user_id: {request.user_id}")
            except jwt.InvalidTokenError:
                logger.warning("Token JWT local inválido")
                return jsonify({'error': 'Token inválido'}), 401
        
        return f(*args, **kwargs)
    return decorated

def init_auth_routes(app):
    @app.route('/api/login', methods=['POST'])
    def login():
        data = request.get_json()
        user_id = data.get('user_id')
        if not user_id:
            logger.warning("Tentativa de login sem user_id")
            return jsonify({'error': 'user_id necessário'}), 400
        
        token = jwt.encode({
            'user_id': user_id,
            'exp': datetime.utcnow() + timedelta(hours=1)
        }, os.getenv('JWT_SECRET', '974655'), algorithm='HS256')
        logger.info(f"Token gerado para user_id: {user_id}")
        return jsonify({'token': token})
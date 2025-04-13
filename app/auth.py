from flask import request, jsonify
import jwt
import os
from functools import wraps
import firebase_admin
from firebase_admin import auth, credentials
import json
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Use a mesma chave secreta para JWT em todo o sistema
JWT_SECRET = os.getenv('SECRET_KEY', '00974655')

# Configuração do Firebase
try:
    firebase_creds = os.getenv('FIREBASE_CREDENTIALS')
    if not firebase_creds:
        raise ValueError("FIREBASE_CREDENTIALS não encontrado")
    cred_dict = json.loads(firebase_creds)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    logger.info("Firebase inicializado com sucesso")
except Exception as e:
    logger.error(f"Erro ao inicializar Firebase: {e}")
    raise

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            logger.warning("Cabeçalho de autorização ausente")
            return jsonify({'error': 'Token de autenticação necessário'}), 401
        
        try:
            # Extrair token do cabeçalho
            if ' ' in auth_header:
                # Formato: "Bearer token"
                scheme, token = auth_header.split(' ', 1)
                if scheme.lower() != 'bearer':
                    logger.warning(f"Esquema de autorização inválido: {scheme}")
                    return jsonify({'error': 'Formato de token inválido'}), 401
            else:
                # Formato: apenas o token
                token = auth_header
            
            # 1. Tentativa com Firebase
            try:
                decoded_token = auth.verify_id_token(token)
                request.user_id = decoded_token.get('uid')
                request.user_tipo = decoded_token.get('user_tipo', 'user')
                logger.info(f"Autenticado via Firebase - UID: {request.user_id}")
                return f(*args, **kwargs)
            except Exception as firebase_error:
                logger.warning(f"Falha Firebase: {str(firebase_error)}")
                
                # 2. Tentativa com JWT local
                try:
                    payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
                    request.user_id = payload['user_id']
                    request.user_tipo = payload.get('user_tipo', 'user')
                    logger.info(f"Autenticado via JWT - User ID: {request.user_id}")
                    return f(*args, **kwargs)
                except jwt.ExpiredSignatureError:
                    logger.warning("Token JWT expirado")
                    return jsonify({'error': 'Token expirado'}), 401
                except jwt.InvalidTokenError as jwt_error:
                    logger.warning(f"Token JWT inválido: {str(jwt_error)}")
                    return jsonify({'error': 'Token inválido'}), 401
        except Exception as e:
            logger.error(f"Erro de autenticação: {str(e)}")
            return jsonify({'error': 'Falha na autenticação'}), 401
    
    return decorated
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

# Configuração do Firebase
def initialize_firebase():
    firebase_creds_json = os.getenv('FIREBASE_CREDENTIALS')
    if not firebase_creds_json:
        logger.error("Variável de ambiente FIREBASE_CREDENTIALS não encontrada")
        raise ValueError("Credenciais do Firebase não encontradas")

    try:
        cred_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            firebase_app = firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK inicializado com sucesso")
            return firebase_app
    except Exception as e:
        logger.error(f"Erro ao inicializar Firebase: {e}")
        raise

firebase_app = initialize_firebase()

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            logger.warning("Requisição sem cabeçalho de autorização")
            return jsonify({'error': 'Token de autenticação necessário'}), 401

        try:
            # Remove o prefixo 'Bearer ' se existir
            token = auth_header.split(' ')[1] if ' ' in auth_header else auth_header
            
            # Primeiro tenta autenticar com Firebase
            try:
                decoded_token = auth.verify_id_token(token, app=firebase_app)
                request.user_id = decoded_token['uid']
                request.user_tipo = 'user'  # Define um tipo padrão
                logger.info(f"Autenticado via Firebase - UID: {request.user_id}")
                return f(*args, **kwargs)
            except Exception as firebase_error:
                logger.warning(f"Falha na autenticação Firebase: {str(firebase_error)}")
                
                # Se Firebase falhar, tenta autenticação JWT local
                try:
                    secret_key = os.getenv('JWT_SECRET', '974655')
                    payload = jwt.decode(token, secret_key, algorithms=['HS256'])
                    
                    request.user_id = payload['user_id']
                    request.user_tipo = payload.get('user_tipo', 'user')
                    logger.info(f"Autenticado via JWT local - User ID: {request.user_id}, Tipo: {request.user_tipo}")
                    return f(*args, **kwargs)
                except jwt.ExpiredSignatureError:
                    logger.warning("Token JWT expirado")
                    return jsonify({'error': 'Token expirado'}), 401
                except jwt.InvalidTokenError as jwt_error:
                    logger.warning(f"Token JWT inválido: {str(jwt_error)}")
                    return jsonify({'error': 'Token inválido'}), 401

        except Exception as e:
            logger.error(f"Erro durante autenticação: {str(e)}")
            return jsonify({'error': 'Falha na autenticação'}), 401

    return decorated
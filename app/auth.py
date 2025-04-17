from flask import request, jsonify
import jwt
import os
from functools import wraps
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Use a chave secreta para JWT do .env
JWT_SECRET = os.getenv('JWT_SECRET_KEY', '1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0')

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            logger.warning("Cabeçalho de autorização ausente")
            return jsonify({'error': 'Token de autenticação necessário'}), 401
        
        try:
            # Extrair token do cabeçalho
            token = auth_header
            if auth_header.lower().startswith('bearer '):
                token = auth_header[7:]  # Remove o prefixo 'Bearer '
            
            # Autenticação via JWT local
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
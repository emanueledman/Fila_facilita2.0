# app/auth.py
from flask import request, jsonify
import jwt
import os
from functools import wraps

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'Token de autenticação necessário'}), 401
        
        try:
            # Remove "Bearer " do token
            token = token.replace('Bearer ', '')
            # Decodifica o token (assumindo que o Facilita 2.0 usa JWT)
            payload = jwt.decode(token, os.getenv('JWT_SECRET', '974655'), algorithms=['HS256'])
            request.user_id = payload['user_id']  # Extrai o user_id do token
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Token inválido'}), 401
        
        return f(*args, **kwargs)
    return decorated
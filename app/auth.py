# app/auth.py
from flask import request, jsonify
import jwt
import os
from functools import wraps
import firebase_admin
from firebase_admin import credentials, auth

# Inicializar o Firebase Admin SDK
cred = credentials.Certificate('path/to/your-firebase-adminsdk.json')  # Substitua pelo caminho do arquivo JSON
firebase_admin.initialize_app(cred)

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'Token de autenticação necessário'}), 401
        
        try:
            token = token.replace('Bearer ', '')
            # Verificar token do Firebase
            decoded_token = auth.verify_id_token(token)
            request.user_id = decoded_token['uid']  # UID do Firebase
        except (auth.InvalidIdTokenError, ValueError, jwt.InvalidTokenError):
            # Fallback para token JWT local (se ainda usar)
            try:
                payload = jwt.decode(token, os.getenv('JWT_SECRET', '974655'), algorithms=['HS256'])
                request.user_id = payload['user_id']
            except jwt.InvalidTokenError:
                return jsonify({'error': 'Token inválido'}), 401
        
        return f(*args, **kwargs)
    return decorated

def init_auth_routes(app):
    @app.route('/api/login', methods=['POST'])
    def login():
        data = request.get_json()
        user_id = data.get('user_id')
        if not user_id:
            return jsonify({'error': 'user_id necessário'}), 400
        
        token = jwt.encode({
            'user_id': user_id,
            'exp': datetime.utcnow() + timedelta(hours=1)
        }, os.getenv('JWT_SECRET', '974655'), algorithm='HS256')
        
        return jsonify({'token': token})
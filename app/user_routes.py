from flask import jsonify, request, make_response
from . import db
from .models import User, UserRole
import logging
import jwt
import os
from datetime import datetime, timedelta

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_user_routes(app):
    @app.route('/api/admin/login', methods=['POST', 'OPTIONS'])
    def admin_login():
        if request.method == 'OPTIONS':
            # Resposta para requisição preflight
            response = make_response()
            response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Max-Age'] = '86400'
            return response

        # Lógica para POST
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

            if not user.is_department_admin:
                logger.warning(f"Tentativa de login como gestor por usuário não autorizado: {email}")
                return jsonify({"error": "Acesso restrito a gestores"}), 403

            # Gerar token JWT (sem o prefixo Bearer)
            secret_key = os.getenv('SECRET_KEY', '00974655')
            token = jwt.encode({
                'user_id': user.id,
                'user_role': user.user_role.value,
                'exp': datetime.utcnow() + timedelta(hours=24)
            }, secret_key, algorithm='HS256')

            # Se o token for uma string em bytes (Python 3.6 e abaixo com PyJWT antigo)
            if isinstance(token, bytes):
                token = token.decode('utf-8')

            response = jsonify({
                "token": token,
                "user_id": user.id,
                "user_role": user.user_role.value,
                "institution_id": user.institution_id,
                "department": user.department.name if user.department else None,
                "email": user.email
            })

            # Configuração CORS para a resposta
            response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
            response.headers.add('Access-Control-Allow-Credentials', 'true')
            
            logger.info(f"Login bem-sucedido para gestor: {email}")
            return response, 200
            
        except Exception as e:
            logger.error(f"Erro ao processar login para email={request.json.get('email', 'unknown')}: {str(e)}")
            return jsonify({"error": "Erro interno no servidor"}), 500
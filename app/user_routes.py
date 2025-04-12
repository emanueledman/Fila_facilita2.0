from flask import jsonify, request, make_response
from . import db
from .models import User
from .auth import require_auth
import logging
import jwt
import os
from datetime import datetime, timedelta

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_user_routes(app):
    @app.route('/api/update_fcm_token', methods=['POST'], endpoint='update_fcm_token_user')
    @require_auth
    def update_fcm_token():
        data = request.get_json()
        if not data or 'fcm_token' not in data:
            return jsonify({'error': 'FCM token é obrigatório'}), 400

        user_id = request.user_id
        fcm_token = data['fcm_token']

        # Buscar o usuário no banco de dados
        user = User.query.get(user_id)
        if not user:
            # Se o usuário não existir, criar um novo (caso o backend permita)
            user = User(id=user_id, email=f"{user_id}@example.com")  # Email fictício, ajuste conforme necessário
            db.session.add(user)

        # Atualizar o fcm_token do usuário
        user.fcm_token = fcm_token
        db.session.commit()

        logger.info(f"FCM token atualizado para o usuário {user_id}: {fcm_token}")
        return jsonify({'message': 'FCM token atualizado com sucesso'}), 200

    @app.route('/api/user', methods=['GET'])
    @require_auth
    def get_user():
        user_id = request.user_id
        user = User.query.get_or_404(user_id)
        return jsonify({
            'id': user.id,
            'email': user.email,
            'fcm_token': user.fcm_token
        })

    @app.route('/api/admin/login', methods=['POST', 'OPTIONS'])
    def admin_login():
        if request.method == 'OPTIONS':
            # Resposta para requisição preflight
            response = make_response()
            response.headers['Access-Control-Allow-Origin'] = 'https://frontfa.netlify.app/'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Max-Age'] = 86400  # Cache por 24 horas
            logger.info("Resposta OPTIONS enviada para /api/admin/login")
            return response, 200

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

            # Usamos o método check_password em vez de comparar diretamente
            if not user.check_password(password):
                logger.warning(f"Senha inválida para email={email}")
                return jsonify({"error": "Credenciais inválidas"}), 401

            if user.user_tipo != 'gestor':
                logger.warning(f"Tentativa de login como gestor por usuário não autorizado: {email}")
                return jsonify({"error": "Acesso restrito a gestores"}), 403

            # Gerar token JWT
            secret_key = os.getenv('SECRET_KEY', '00974655')
            token = jwt.encode({
                'user_id': user.id,
                'user_tipo': user.user_tipo,
                'exp': datetime.utcnow() + timedelta(hours=24)
            }, secret_key, algorithm='HS256')

            response = {
                "token": token,
                "user_id": user.id,
                "user_tipo": user.user_tipo,
                "institution_id": user.institution_id,
                "department": user.department,
                "email": user.email
            }
            logger.info(f"Login bem-sucedido para gestor: {email}")
            return jsonify(response), 200

        except Exception as e:
            logger.error(f"Erro ao processar login para email={email}: {str(e)}")
            return jsonify({"error": "Erro interno no servidor"}), 500
from flask import jsonify, request
from . import db
from .models import User
from .auth import require_auth
import logging

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
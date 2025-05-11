from flask import request, jsonify
import jwt
import os
from functools import wraps
import firebase_admin
from firebase_admin import auth, credentials
import json
import logging
from datetime import datetime, timedelta
from app import db
from app.models import User, UserRole

# Configuração de logs estruturados
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Chave secreta JWT
JWT_SECRET = os.getenv('JWT_SECRET_KEY', '1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0')

# Inicialização do Firebase com retry
def initialize_firebase():
    if firebase_admin._apps:
        return True
    try:
        firebase_creds = os.getenv('FIREBASE_CREDENTIALS')
        if not firebase_creds:
            logger.warning("FIREBASE_CREDENTIALS não configurado. Usando JWT local.")
            return False
        try:
            cred_dict = json.loads(firebase_creds)
            cred = credentials.Certificate(cred_dict)
        except json.JSONDecodeError:
            if os.path.exists(firebase_creds):
                cred = credentials.Certificate(firebase_creds)
            else:
                logger.error("FIREBASE_CREDENTIALS inválido: não é JSON nem arquivo.")
                return False
        firebase_admin.initialize_app(cred)
        logger.info("Firebase inicializado com sucesso.")
        return True
    except Exception as e:
        logger.error(f"Erro ao inicializar Firebase: {str(e)}")
        return False

# Sincronizar usuário Firebase com banco
def sync_firebase_user(firebase_uid, email, name):
    try:
        user = User.query.get(firebase_uid)
        if not user:
            user = User(
                id=firebase_uid,
                email=email,
                name=name or "Usuário Anônimo",
                user_role=UserRole.USER,
                created_at=datetime.utcnow(),
                active=True
            )
            db.session.add(user)
        else:
            user.email = email
            user.name = name or user.name
            user.active = True
        db.session.commit()
        logger.info(f"Usuário sincronizado: UID={firebase_uid}, email={email}")
        return user
    except Exception as e:
        logger.error(f"Erro ao sincronizar usuário Firebase UID={firebase_uid}: {str(e)}")
        db.session.rollback()
        return None

# Decorador de autenticação
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            logger.warning("Cabeçalho de autorização ausente")
            return jsonify({'error': 'Token de autenticação necessário'}), 401

        token = auth_header.replace('Bearer ', '', 1) if auth_header.lower().startswith('bearer ') else auth_header

        # Tentar autenticação com Firebase
        firebase_initialized = initialize_firebase()
        if firebase_initialized:
            try:
                decoded_token = auth.verify_id_token(token)
                uid = decoded_token.get('uid')
                email = decoded_token.get('email')
                name = decoded_token.get('name')
                user = sync_firebase_user(uid, email, name)
                if not user:
                    logger.error(f"Falha ao sincronizar usuário Firebase UID={uid}")
                    return jsonify({'error': 'Falha ao sincronizar usuário'}), 500
                request.user_id = uid
                request.user_role = user.user_role.value
                logger.info(f"Autenticado via Firebase: UID={uid}, role={request.user_role}")
                return f(*args, **kwargs)
            except auth.InvalidIdTokenError:
                logger.warning("Token Firebase inválido")
            except Exception as e:
                logger.warning(f"Falha na autenticação Firebase: {str(e)}")

        # Fallback para JWT local
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            request.user_id = payload.get('user_id')
            request.user_role = payload.get('user_role', 'user')
            logger.info(f"Autenticado via JWT: user_id={request.user_id}, role={request.user_role}")
            return f(*args, **kwargs)
        except jwt.ExpiredSignatureError:
            logger.warning("Token JWT expirado")
            return jsonify({'error': 'Token expirado'}), 401
        except jwt.InvalidTokenError as e:
            logger.warning(f"Token JWT inválido: {str(e)}")
            return jsonify({'error': 'Token inválido'}), 401
        except Exception as e:
            logger.error(f"Erro de autenticação: {str(e)}")
            return jsonify({'error': 'Falha na autenticação'}), 401

    return decorated

# Função para gerar tokens JWT
def generate_tokens(user):
    access_token = jwt.encode({
        'user_id': user.id,
        'user_role': user.user_role.value,
        'exp': datetime.utcnow() + timedelta(hours=250)
    }, JWT_SECRET, algorithm='HS256')
    refresh_token = jwt.encode({
        'user_id': user.id,
        'user_role': user.user_role.value,
        'exp': datetime.utcnow() + timedelta(days=14)
    }, JWT_SECRET, algorithm='HS256')
    return access_token, refresh_token
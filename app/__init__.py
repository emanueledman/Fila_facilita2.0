import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

# Inicializar extensões
db = SQLAlchemy()
socketio = SocketIO()

def create_app():
    app = Flask(__name__)
    
    # Configurações
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', '00974655')
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        app.logger.error("DATABASE_URL não encontrado nas variáveis de ambiente!")
        database_url = 'sqlite:///facilita.db'  # Fallback apenas para desenvolvimento local
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://')
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Configuração de logging
    logging.basicConfig(level=logging.DEBUG)  # Mantido como DEBUG para facilitar a depuração
    app.logger.setLevel(logging.DEBUG)
    app.logger.info(f"Iniciando com banco de dados: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    # Configurações adicionais para o SocketIO
    app.config['SOCKETIO_LOGGER'] = True
    app.config['SOCKETIO_ENGINEIO_LOGGER'] = True
    
    # Inicializa extensões
    db.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode='eventlet', logger=True, engineio_logger=True)
    
    # Inicializar o Firebase Admin
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate({
                "type": "service_account",
                "project_id": os.getenv("FIREBASE_PROJECT_ID"),
                "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
                "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
                "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
                "client_id": os.getenv("FIREBASE_CLIENT_ID"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL"),
                "universe_domain": "googleapis.com"
            })
            firebase_admin.initialize_app(cred)
            app.logger.info("Firebase Admin inicializado com sucesso")
    except Exception as e:
        app.logger.error(f"Erro ao inicializar o Firebase Admin: {e}")
        raise e

    # Criar tabelas no banco de dados, se não existirem
    with app.app_context():
        from . import models
        db.create_all()
        app.logger.info("Tabelas do banco de dados criadas ou verificadas")

    # Registra rotas
    from .routes import init_routes
    from .queue_routes import init_queue_routes
    from .user_routes import init_user_routes
    from .admin_routes import init_admin_routes  # Adicionado

    init_routes(app)
    init_queue_routes(app)
    init_user_routes(app)
    init_admin_routes(app)  # Adicionado

    # Configuração adicional para produção
    if os.getenv('FLASK_ENV') == 'production':
        app.config['DEBUG'] = False
        app.logger.setLevel(logging.INFO)
        app.logger.info("Aplicação configurada para modo de produção")
    else:
        app.config['DEBUG'] = True
        app.logger.info("Aplicação configurada para modo de desenvolvimento")

    return app
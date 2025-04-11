import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from dotenv import load_dotenv

# Carregar variáveis de ambiente do arquivo .env (apenas para desenvolvimento local)
load_dotenv()

# Inicializar extensões
db = SQLAlchemy()
socketio = SocketIO()
limiter = Limiter(key_func=get_remote_address)

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
    limiter.init_app(app)
    
    # Criar tabelas no banco de dados, se não existirem
    with app.app_context():
        from . import models
        db.create_all()
        app.logger.info("Tabelas do banco de dados criadas ou verificadas")

    # Registra rotas
    from .routes import init_routes
    from .queue_routes import init_queue_routes
    from .user_routes import init_user_routes
    from .admin_routes import init_admin_routes

    init_routes(app)
    init_queue_routes(app)
    init_user_routes(app)
    init_admin_routes(app)

    # Configuração adicional para produção
    if os.getenv('FLASK_ENV') == 'production':
        app.config['DEBUG'] = False
        app.logger.setLevel(logging.INFO)
        app.logger.info("Aplicação configurada para modo de produção")
    else:
        app.config['DEBUG'] = True
        app.logger.info("Aplicação configurada para modo de desenvolvimento")

    return app
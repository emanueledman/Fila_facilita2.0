import logging
import eventlet
eventlet.monkey_patch()  # Chamado antes de qualquer importação

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from dotenv import load_dotenv

# Carregar variáveis de ambiente
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
        database_url = 'sqlite:///facilita.db'  # Fallback para desenvolvimento
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://')
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Configuração de logging unificada
    handler = logging.handlers.RotatingFileHandler(
        'queue_service.log', maxBytes=1024*1024, backupCount=10
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    handler.setLevel(logging.INFO)
    app.logger.handlers = []
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO if os.getenv('FLASK_ENV') == 'production' else logging.DEBUG)
    app.logger.info(f"Iniciando com banco de dados: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    # Configurações do SocketIO
    app.config['SOCKETIO_LOGGER'] = True
    app.config['SOCKETIO_ENGINEIO_LOGGER'] = True
    
    # Inicializa extensões
    db.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode='eventlet', logger=True, engineio_logger=True)
    limiter.init_app(app)
    
    # Importar modelos e criar tabelas
    with app.app_context():
        from .models import Institution, Queue, User, Ticket
        
        # Criar tabelas apenas se não existirem
        db.create_all()
        
        # Limpar o banco apenas em desenvolvimento
        if os.getenv('FLASK_ENV') != 'production':
            db.drop_all()
            db.create_all()
            app.logger.info("Banco limpo e tabelas recriadas (modo desenvolvimento)")
        
        # Verificar se o banco está vazio e popular dados iniciais
        if Institution.query.count() == 0:
            from .data_init import populate_initial_data
            populate_initial_data(app)
            app.logger.info("Dados iniciais inseridos automaticamente")
        else:
            app.logger.info("Banco já contém dados, pulando inicialização")
    
    # Registra rotas
    from .routes import init_routes
    from .queue_routes import init_queue_routes
    from .user_routes import init_user_routes
    from .admin_routes import init_admin_routes

    init_routes(app)
    init_queue_routes(app)
    init_user_routes(app)
    init_admin_routes(app)

    # Configuração para produção/desenvolvimento
    if os.getenv('FLASK_ENV') == 'production':
        app.config['DEBUG'] = False
        app.logger.info("Aplicação configurada para modo de produção")
    else:
        app.config['DEBUG'] = True
        app.logger.info("Aplicação configurada para modo de desenvolvimento")

    return app

# Criar a aplicação para uso com Gunicorn
app = create_app()
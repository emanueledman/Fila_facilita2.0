import logging
import eventlet
eventlet.monkey_patch()

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
import os
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
socketio = SocketIO()
limiter = Limiter(key_func=get_remote_address)

def create_app():
    app = Flask(__name__)
    
    # Configurações básicas
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', '1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0')
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', '1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0')
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        app.logger.error("DATABASE_URL não encontrado nas variáveis de ambiente!")
        database_url = 'sqlite:///facilita.db'
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://')
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Configurar logging
    handler = logging.handlers.RotatingFileHandler(
        'queue_service.log', maxBytes=1024*1024, backupCount=10
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    handler.setLevel(logging.INFO)
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in app.logger.handlers):
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO if os.getenv('FLASK_ENV') == 'production' else logging.DEBUG)
    app.logger.info(f"Iniciando com banco de dados: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    # Configurações do SocketIO
    app.config['SOCKETIO_LOGGER'] = True
    app.config['SOCKETIO_ENGINEIO_LOGGER'] = True
    
    # Inicializar extensões
    db.init_app(app)
    socketio.init_app(
        app,
        cors_allowed_origins=[
            "http://127.0.0.1:5500",
            "https://frontfa.netlify.app",
            "https://courageous-dolphin-66662b.netlify.app"
        ],
        async_mode='eventlet',
        path='/tickets',
        logger=True,
        engineio_logger=True
    )
    limiter.init_app(app)
    
    # Configurar CORS
    CORS(app, resources={r"/api/*": {
        "origins": [
            "http://127.0.0.1:5500",
            "https://frontfa.netlify.app",
            "https://courageous-dolphin-66662b.netlify.app"
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True
    }})
    
    with app.app_context():
        from .models import Institution, Queue, User, Ticket, Department
        
        # Reiniciar banco apenas em desenvolvimento ou se explicitamente solicitado
        reset_db = os.getenv('FLASK_ENV') != 'production' or os.getenv('RESET_DB') == 'true'
        if reset_db:
            db.drop_all()
            db.create_all()
            app.logger.info("Banco limpo e tabelas recriadas")
            
            # Inserir dados iniciais de forma idempotente
            from .data_init import populate_initial_data
            try:
                populate_initial_data(app)
                app.logger.info("Dados iniciais inseridos automaticamente")
            except Exception as e:
                app.logger.error(f"Erro ao inserir dados iniciais: {str(e)}")
        
        # Inicializar modelos de ML (opcional, pode ser comentado se o treinamento for apenas periódico)
        from .ml_models import wait_time_predictor, service_recommendation_predictor
        try:
            queues = Queue.query.all()
            for queue in queues:
                wait_time_predictor.train(queue.id)
            service_recommendation_predictor.train()
            app.logger.info("Modelos de ML inicializados na startup")
        except Exception as e:
            app.logger.error(f"Erro ao inicializar modelos de ML: {str(e)}")
    
    # Registrar rotas
    from .routes import init_routes
    from .queue_routes import init_queue_routes
    from .user_routes import init_user_routes
    from .admin_routes import init_admin_routes

    init_routes(app)
    init_queue_routes(app)
    init_user_routes(app)
    init_admin_routes(app)

    if os.getenv('FLASK_ENV') == 'production':
        app.config['DEBUG'] = False
        app.logger.info("Aplicação configurada para modo de produção")
    else:
        app.config['DEBUG'] = True
        app.logger.info("Aplicação configurada para modo de desenvolvimento")

    return app

app = create_app()
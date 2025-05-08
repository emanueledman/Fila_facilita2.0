import logging
import eventlet
eventlet.monkey_patch()

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from redis import Redis
import os
from dotenv import load_dotenv

from flask import jsonify

from sqlalchemy import text

load_dotenv()

db = SQLAlchemy()
socketio = SocketIO()
limiter = Limiter(key_func=get_remote_address)
redis_client = Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))

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
    
    # Atribuir redis_client ao app
    app.redis_client = redis_client
    
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
    app.config['SOCKETIO_LOGGER'] = os.getenv('FLASK_ENV') != 'production'
    app.config['SOCKETIO_ENGINEIO_LOGGER'] = os.getenv('FLASK_ENV') != 'production'
    
    # Inicializar extensões
    db.init_app(app)
    socketio.init_app(
        app,
        cors_allowed_origins=[
            "http://127.0.0.1:5500",
            "https://frontfa.netlify.app",
            "https://fila-facilita2-0-4uzw.onrender.com"
        ],
        async_mode='eventlet',
        logger=os.getenv('FLASK_ENV') != 'production',
        engineio_logger=os.getenv('FLASK_ENV') != 'production',
        message_queue=os.getenv('REDIS_URL', 'rediss://red-d053vpre5dus738stejg:yUiGYAY9yrGzyXvw2LyUPzoRqkdwY3Og@oregon-keyvalue.render.com:6379/0'),
        manage_session=False
    )
    limiter.init_app(app)
    
    # Configurar CORS apenas para endpoints REST
    from flask_cors import CORS
    CORS(app, resources={r"/api/*": {
        "origins": [
            "http://127.0.0.1:5500",
            "https://frontfa.netlify.app",
            "https://fila-facilita2-0-4uzw.onrender.com"
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True
    }})
    
    # Configurar Flask-Limiter com Redis
    limiter.storage_uri = os.getenv('REDIS_URL', 'rediss://red-d053vpre5dus738stejg:yUiGYAY9yrGzyXvw2LyUPzoRqkdwY3Og@oregon-keyvalue.render.com:6379/0')
    
    # Registrar rotas
    from .routes import init_routes
    from .queue_routes import init_queue_routes
    from .user_routes import init_user_routes
    from .admin_routes import init_admin_routes
    from .queue_reco import init_queue_reco
    from .queue_filial import init_queue_filial

    init_routes(app)
    init_queue_routes(app)
    init_user_routes(app)
    init_admin_routes(app)
    init_queue_reco(app)
    init_queue_filial(app)

    # Rota para inicializar o banco de dados
    
    @app.route('/add-notification-type', methods=['POST'])
    @limiter.limit("5 per minute")
    def add_notification_type():
        try:
            with db.engine.connect() as conn:
                # Verifica se a coluna já existe
                if db.engine.dialect.name == 'postgresql':
                    exists_query = text("SELECT column_name FROM information_schema.columns WHERE table_name='notification_log' AND column_name='type'")
                    result = conn.execute(exists_query).fetchone()
                    if not result:
                        # Adiciona a coluna se não existir
                        conn.execute(text("ALTER TABLE notification_log ADD COLUMN type VARCHAR(50) DEFAULT 'standard' NOT NULL"))
                        conn.commit()
                else:
                    # Para SQLite
                    conn.execute(text("ALTER TABLE notification_log ADD COLUMN type VARCHAR(50) DEFAULT 'standard' NOT NULL"))
                    conn.commit()
                
            return jsonify({"status": "success", "message": "Coluna 'type' adicionada à tabela notification_log"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})

    @app.route('/init-db', methods=['POST'])
    @limiter.limit("5 per minute")  # Limitar a 5 requisições por minuto
    def init_db():
        with app.app_context():
            from .models import Institution, Queue, User, Ticket, Department, UserPreference, UserRole, Branch, ServiceCategory, ServiceTag, AuditLog, BranchSchedule
            from .data_init import populate_initial_data

            try:
                # Obter o engine do banco de dados
                engine = db.get_engine()
                with engine.connect() as conn:
                    # Limpar completamente o banco de dados
                    if engine.dialect.name == 'postgresql':
                        # Para PostgreSQL, dropar o esquema public e recriá-lo
                        conn.execute(text("DROP SCHEMA public CASCADE;"))
                        conn.execute(text("CREATE SCHEMA public;"))
                        conn.commit()
                        app.logger.info("Esquema 'public' do PostgreSQL limpo com DROP SCHEMA CASCADE e recriado.")
                    else:
                        # Para outros bancos (SQLite, MySQL, etc.), usar db.drop_all()
                        db.drop_all()
                        app.logger.info("Todas as tabelas removidas usando db.drop_all().")

                # Recriar todas as tabelas com base nos modelos
                db.create_all()
                app.logger.info("Tabelas criadas com sucesso no banco de dados.")

                # Popular dados iniciais
                populate_initial_data(app)
                app.logger.info("Dados iniciais populados com sucesso usando populate_initial_data().")

                # Opcional: Inicializar modelos de ML
                app.logger.debug("Tentando importar e inicializar preditores de ML.")
                try:
                    from .ml_models import wait_time_predictor, service_recommendation_predictor, collaborative_model, demand_model, clustering_model
                    app.logger.info("Preditores de ML importados com sucesso.")
                    if wait_time_predictor:
                        queues = Queue.query.all()
                        for queue in queues:
                            app.logger.debug(f"Treinando WaitTimePredictor para queue_id={queue.id}")
                            wait_time_predictor.train(queue.id)
                            app.logger.debug(f"Treinando DemandForecastingModel para queue_id={queue.id}")
                            demand_model.train(queue.id)
                        app.logger.debug("Treinando ServiceRecommendationPredictor.")
                        service_recommendation_predictor.train()
                        app.logger.debug("Treinando CollaborativeFilteringModel.")
                        collaborative_model.train()
                        app.logger.debug("Treinando ServiceClusteringModel.")
                        clustering_model.train()
                        app.logger.info("Modelos de ML inicializados com sucesso.")
                except ImportError as e:
                    app.logger.error(f"Erro ao importar preditores de ML: {str(e)}")
                    app.logger.warning("Continuando sem inicialização dos modelos de ML.")
                except Exception as e:
                    app.logger.error(f"Erro ao inicializar modelos de ML: {str(e)}")
                    app.logger.warning("Continuando apesar de erros nos modelos de ML.")

                return jsonify({
                    "status": "success",
                    "message": "Banco de dados limpo, tabelas recriadas e dados iniciais populados com sucesso."
                }), 200

            except Exception as e:
                app.logger.error(f"Erro ao inicializar banco de dados: {str(e)}")
                return jsonify({
                    "status": "error",
                    "message": f"Erro ao inicializar banco de dados: {str(e)}"
                }), 500


    if os.getenv('FLASK_ENV') == 'production':
        app.config['DEBUG'] = False
        app.logger.info("Aplicação configurada para modo de produção")
    else:
        app.config['DEBUG'] = True
        app.logger.info("Aplicação configurada para modo de desenvolvimento")

    return app

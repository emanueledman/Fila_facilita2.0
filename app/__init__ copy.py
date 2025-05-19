import logging
import eventlet
eventlet.monkey_patch()

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from redis import Redis
import os
from dotenv import load_dotenv
from sqlalchemy import text
import json

load_dotenv()

db = SQLAlchemy()
socketio = SocketIO()
limiter = Limiter(key_func=get_remote_address)
redis_client = Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))

# Função para publicar atualizações de fila no Redis
def publish_queue_update(queue_id, data):
    redis_client.publish(f'queue:{queue_id}:updates', json.dumps(data))

# Listener Redis para propagar atualizações via SocketIO
def start_background_listener():
    pubsub = redis_client.pubsub()
    pubsub.psubscribe('queue:*:updates')
    for message in pubsub.listen():
        if message['type'] == 'pmessage':
            queue_id = message['channel'].decode().split(':')[1]
            data = json.loads(message['data'].decode())
            socketio.emit('queue_update', data, namespace='/queue', room=f'queue_{queue_id}')

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
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 20,
        'max_overflow': 10,
        'pool_timeout': 30,
        'pool_pre_ping': True
    }

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

    # Configurar CORS com Totem-Token
    CORS(app, resources={r"/api/*": {
        "origins": [
            "http://127.0.0.1:5500",
            "https://frontfa.netlify.app",
            "https://fila-facilita2-0-juqg.onrender.com",
            "https://totemfacilita.netlify.app",
            "https://fila-facilita2-0-4uzw.onrender.com",
            "null"
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Totem-Token"],
        "supports_credentials": True
    }})

    db.init_app(app)
    socketio.init_app(
        app,
        cors_allowed_origins=[
            "http://127.0.0.1:5500",
            "https://frontfa.netlify.app",
            "https://fila-facilita2-0-juqg.onrender.com",
            "https://totemfacilita.netlify.app",
            "https://fila-facilita2-0-4uzw.onrender.com",
            "null"
        ],
        async_mode='eventlet',
        logger=os.getenv('FLASK_ENV') != 'production',
        engineio_logger=os.getenv('FLASK_ENV') != 'production',
        message_queue=os.getenv('REDIS_URL', 'rediss://red-d0lltobe5dus73cn7du0:9ryeCMKr8tMRoUJgmdKQqzM7OHExeugd@oregon-keyvalue.render.com:6379'),
        manage_session=False,
        namespace='/queue'
    )
    limiter.init_app(app)

    limiter.storage_uri = os.getenv('REDIS_URL', 'rediss://red-d0lltobe5dus73cn7du0:9ryeCMKr8tMRoUJgmdKQqzM7OHExeugd@oregon-keyvalue.render.com:6379')

    # Iniciar listener Redis
    socketio.start_background_task(start_background_listener)

    from .routes import init_routes
    from .queue_routes import init_queue_routes
    from .user_routes import init_user_routes
    from .admin_routes import init_admin_routes
    from .queue_reco import init_queue_reco
    from .totem_routes import init_totem_routes
    from .queue_filial import init_queue_filial
    from .attendent import init_attendant_routes
    from .branch_admin_routes import init_branch_admin_routes

    init_routes(app)
    init_queue_routes(app)
    init_user_routes(app)
    init_admin_routes(app)
    init_queue_reco(app)
    init_queue_filial(app)
    init_totem_routes(app)
    init_attendant_routes(app)
    init_branch_admin_routes(app)

    # Decorador para verificar Totem-Token
    def require_fixed_totem_token(f):
        def decorated(*args, **kwargs):
            token = request.headers.get('Totem-Token')
            if not token or not redis_client.get(f'totem_token:{token}'):
                return jsonify({"status": "error", "message": "Token inválido"}), 401
            return f(*args, **kwargs)
        return decorated

    # Rota para tela de acompanhamento de filas
    @app.route('/api/totem/branches/<branch_id>/display', methods=['GET'])
    @require_fixed_totem_token
    def display_queues(branch_id):
        queues = Queue.query.filter_by(branch_id=branch_id).all()
        return jsonify([{
            'id': q.id,
            'name': q.name,
            'current_number': q.current_number
        } for q in queues])

    # Rota para adicionar coluna de notificação
    @app.route('/add-notification-type', methods=['POST'])
    @limiter.limit("5 per minute")
    def add_notification_type():
        try:
            with db.engine.connect() as conn:
                if db.engine.dialect.name == 'postgresql':
                    exists_query = text("SELECT column_name FROM information_schema.columns WHERE table_name='notification_log' AND column_name='type'")
                    result = conn.execute(exists_query).fetchone()
                    if not result:
                        conn.execute(text("ALTER TABLE notification_log ADD COLUMN type VARCHAR(50) DEFAULT 'standard' NOT NULL"))
                        conn.commit()
                else:
                    conn.execute(text("ALTER TABLE notification_log ADD COLUMN type VARCHAR(50) DEFAULT 'standard' NOT NULL"))
                    conn.commit()
            return jsonify({"status": "success", "message": "Coluna 'type' adicionada à tabela notification_log"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})

    # Rota para inicializar o banco de dados
    @app.route('/init-db', methods=['POST'])
    @limiter.limit("5 per minute")
    def init_db():
        with app.app_context():
            from .models import Institution, Queue, User, Ticket, Department, UserPreference, UserRole, Branch, ServiceCategory, ServiceTag, AuditLog, BranchSchedule
            from .data_init import populate_initial_data

            try:
                engine = db.get_engine()
                with engine.connect() as conn:
                    if engine.dialect.name == 'postgresql':
                        conn.execute(text("DROP SCHEMA public CASCADE;"))
                        conn.execute(text("CREATE SCHEMA public;"))
                        conn.commit()
                        app.logger.info("Esquema 'public' do PostgreSQL limpo com DROP SCHEMA CASCADE e recriado.")
                    else:
                        db.drop_all()
                        app.logger.info("Todas as tabelas removidas usando db.drop_all().")

                db.create_all()
                app.logger.info("Tabelas criadas com sucesso no banco de dados.")
                populate_initial_data(app)
                app.logger.info("Dados iniciais populados com sucesso usando populate_initial_data().")

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
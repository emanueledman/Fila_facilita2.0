import logging
import eventlet
eventlet.monkey_patch()

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from redis import Redis
import os
from dotenv import load_dotenv
from flask_cors import CORS

# Carregar variáveis de ambiente
load_dotenv()

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inicializar extensões
db = SQLAlchemy()
socketio = SocketIO()
limiter = Limiter(key_func=get_remote_address)

def init_redis():
    """Inicializa o cliente Redis com tratamento de erro e fallback."""
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    try:
        client = Redis.from_url(redis_url, decode_responses=True)
        client.ping()
        logger.info(f"Conectado ao Redis em {redis_url}")
        return client
    except Exception as e:
        logger.error(f"Erro ao conectar ao Redis ({redis_url}): {str(e)}")
        logger.warning("Redis desativado; cache será desabilitado")
        return None

def create_app():
    app = Flask(__name__)
    
    # Configurações básicas
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', '1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0')
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', '1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0')
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        app.logger.error("DATABASE_URL não encontrado nas variáveis de ambiente! Usando SQLite como fallback.")
        database_url = 'sqlite:///facilita.db'
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://')
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Atribuir redis_client ao app
    app.redis_client = init_redis()
    
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
        path='/tickets',
        logger=os.getenv('FLASK_ENV') != 'production',
        engineio_logger=os.getenv('FLASK_ENV') != 'production',
        manage_session=False
    )
    limiter.init_app(app)
    
    # Configurar CORS apenas para endpoints REST
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
    
    with app.app_context():
        from .models import Institution, Queue, User, Ticket, Department, UserPreference, UserRole, Branch, ServiceCategory, ServiceTag, QueueSchedule, AuditLog
        
        # Verificar conexão com o banco de dados antes de criar tabelas
        try:
            db.session.execute('SELECT 1')
            app.logger.info("Conexão com o banco de dados verificada")
        except Exception as e:
            app.logger.error(f"Erro ao conectar ao banco de dados: {str(e)}")
            raise
        
        # Criar tabelas, se necessário
        try:
            db.create_all()
            app.logger.info("Tabelas criadas ou verificadas no banco de dados")
        except Exception as e:
            app.logger.error(f"Erro ao criar tabelas no banco de dados: {str(e)}")
            raise
        
        # Inserir dados iniciais (descomentado se necessário)
        # from .data_init import populate_initial_data
        # try:
        #     populate_initial_data(app)
        #     app.logger.info("Dados iniciais inseridos automaticamente")
        # except Exception as e:
        #     app.logger.error(f"Erro ao inserir dados iniciais: {str(e)}")
        
        # Inicializar modelos de ML
        app.logger.debug("Tentando importar preditores de ML")
        try:
            from .ml_models import wait_time_predictor, service_recommendation_predictor, collaborative_model, demand_model, clustering_model
            app.logger.info("Preditores de ML importados com sucesso")
        except ImportError as e:
            app.logger.error(f"Erro ao importar preditores de ML: {e}")
            app.logger.warning("Continuando inicialização sem modelos de ML")
            wait_time_predictor = service_recommendation_predictor = collaborative_model = demand_model = clustering_model = None
        
        if wait_time_predictor:  # Verificar se os modelos foram importados
            app.logger.debug("Iniciando treinamento dos modelos de ML")
            try:
                queues = Queue.query.all()
                for queue in queues:
                    app.logger.debug(f"Treinando WaitTimePredictor para queue_id={queue.id}")
                    wait_time_predictor.train(queue.id)
                    app.logger.debug(f"Treinando DemandForecastingModel para queue_id={queue.id}")
                    demand_model.train(queue.id)
                app.logger.debug("Treinando ServiceRecommendationPredictor")
                service_recommendation_predictor.train()
                app.logger.debug("Treinando CollaborativeFilteringModel")
                collaborative_model.train()
                app.logger.debug("Treinando ServiceClusteringModel")
                clustering_model.train()
                app.logger.info("Modelos de ML inicializados na startup")
            except Exception as e:
                app.logger.error(f"Erro ao inicializar modelos de ML: {str(e)}")
                app.logger.warning("Continuando inicialização apesar de erros nos modelos de ML")
    
    # Registrar rotas
    from .routes import init_routes
    from .queue_routes import init_queue_routes
    from .user_routes import init_user_routes
    from .admin_routes import init_admin_routes

    init_routes(app)
    init_queue_routes(app)
    init_user_routes(app)
    init_admin_routes(app)

    # Configurar manipuladores de erro
    @app.errorhandler(404)
    def not_found(error):
        app.logger.warning(f"Rota não encontrada: {request.url}")
        return jsonify({'error': 'Recurso não encontrado'}), 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"Erro interno do servidor: {str(error)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

    # Rota de saúde
    @app.route('/health', methods=['GET'])
    def health_check():
        try:
            db.session.execute('SELECT 1')
            db_status = 'OK'
        except Exception as e:
            app.logger.error(f"Erro ao verificar banco de dados: {str(e)}")
            db_status = 'ERROR'

        redis_status = 'OK' if app.redis_client and app.redis_client.ping() else 'ERROR'

        return jsonify({
            'status': 'healthy' if db_status == 'OK' and redis_status == 'OK' else 'unhealthy',
            'database': db_status,
            'redis': redis_status,
            'timestamp': datetime.utcnow().isoformat()
        }), 200

    if os.getenv('FLASK_ENV') == 'production':
        app.config['DEBUG'] = False
        app.logger.info("Aplicação configurada para modo de produção")
    else:
        app.config['DEBUG'] = True
        app.logger.info("Aplicação configurada para modo de desenvolvimento")

    return app

app = create_app()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)

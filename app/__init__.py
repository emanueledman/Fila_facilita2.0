import logging
from venv import logger

from flask import jsonify, request, send_file
from sqlalchemy.exc import SQLAlchemyError
import io
import logging
from .services import QueueService  # Importação do QueueService


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
            "https://fila-facilita2-0-4uzw.onrender.com",
            "null"
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
            "https://fila-facilita2-0-4uzw.onrender.com",
            "null"
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
    from .attendent import init_attendant_routes
    from .branch_admin_routes import init_branch_admin_routes

    init_routes(app)
    init_queue_routes(app)
    init_user_routes(app)
    init_admin_routes(app)
    init_queue_reco(app)
    init_queue_filial(app)
    init_attendant_routes(app)
    init_branch_admin_routes(app)

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


    @app.route('/api/branch_admin/branches/<branch_id>/queues/totem', methods=['POST'])
    @limiter.limit("10 per minute")  # Limite de 10 requisições por minuto por IP
    def generate_totem_tickets(branch_id):
        """Gera um ticket físico via totem para um serviço em uma filial."""
        try:
            # Validar token do totem
            token = request.headers.get('Totem-Token')
            expected_token = app.config.get('TOTEM_TOKEN', 'default-totem-token')
            if not token or token != expected_token:
                logger.warning(f"Token de totem inválido para IP {request.remote_addr}")
                return jsonify({'error': 'Token de totem inválido'}), 401

            # Validar entrada
            data = request.get_json() or {}
            service = data.get('service')
            if not service or not isinstance(service, str) or not service.strip():
                logger.warning("Serviço não fornecido ou inválido")
                return jsonify({'error': 'Serviço é obrigatório e deve ser uma string válida'}), 400

            client_ip = request.remote_addr
            if not client_ip:
                logger.error("IP do cliente não detectado")
                return jsonify({'error': 'IP do cliente não detectado'}), 400

            # Verificar limite de emissões por IP
            cache_key = f"totem:throttle:{client_ip}:{branch_id}"
            if app.redis_client.get(cache_key):
                logger.warning(f"Limite de emissão atingido para IP {client_ip} na filial {branch_id}")
                return jsonify({'error': 'Limite de emissão atingido. Tente novamente em 30 segundos'}), 429
            app.redis_client.setex(cache_key, 30, "1")

            # Gerar ticket físico
            result = QueueService.generate_physical_ticket_for_totem(service, branch_id, client_ip)
            ticket = result['ticket']
            pdf_buffer = io.BytesIO(bytes.fromhex(result['pdf']))

            # Emitir evento WebSocket para o dashboard
            branch = ticket['queue'].department.branch if ticket['queue'] and ticket['queue'].department else None
            if branch and app.socketio:
                app.socketio.emit('dashboard_update', {
                    'branch_id': branch_id,
                    'queue_id': ticket['queue_id'],
                    'event_type': 'ticket_issued',
                    'data': {
                        'ticket_number': f"{ticket['queue'].prefix}{ticket['ticket_number']}",
                        'timestamp': ticket['issued_at']
                    }
                }, room=branch_id, namespace='/dashboard')

            # Registrar auditoria
            from .models import AuditLog
            AuditLog.create(
                user_id=None,
                action='generate_totem_ticket',
                resource_type='ticket',
                resource_id=ticket['id'],
                details=f"Ticket físico {ticket['queue'].prefix}{ticket['ticket_number']} emitido via totem (IP: {client_ip}, Filial: {branch_id})"
            )

            logger.info(f"Ticket físico emitido via totem: {ticket['queue'].prefix}{ticket['ticket_number']} (IP: {client_ip}, Filial: {branch_id})")
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=f"ticket_{ticket['queue'].prefix}{ticket['ticket_number']}.pdf",
                mimetype='application/pdf'
            )

        except ValueError as e:
            logger.error(f"Erro de validação ao emitir ticket via totem para serviço {service}, branch_id={branch_id}: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except SQLAlchemyError as e:
            logger.error(f"Erro no banco de dados ao emitir ticket via totem para serviço {service}, branch_id={branch_id}: {str(e)}")
            return jsonify({'error': 'Erro no banco de dados ao emitir ticket'}), 500
        except Exception as e:
            logger.error(f"Erro inesperado ao emitir ticket via totem para serviço {service}, branch_id={branch_id}: {str(e)}")
            return jsonify({'error': f'Erro interno ao emitir ticket: {str(e)}'}), 500


    return app

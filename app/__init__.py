# app/__init__.py
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO  # Adicionado
import os
from dotenv import load_dotenv

load_dotenv()
db = SQLAlchemy()
socketio = SocketIO()  # Inicializa o SocketIO

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
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)
    app.logger.info(f"Iniciando com banco de dados: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    # Inicializa extensões
    db.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*")  # Inicializa o SocketIO com o app
    
    # Registra rotas
    from .routes import init_routes
    from .queue_routes import init_queue_routes
    init_routes(app)
    init_queue_routes(app)
    
    return app
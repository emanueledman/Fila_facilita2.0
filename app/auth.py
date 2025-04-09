# app/__init__.py
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os
from dotenv import load_dotenv
from threading import Thread
import time
from .services import QueueService

load_dotenv()
db = SQLAlchemy()

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
    
    db.init_app(app)
    
    from .routes import init_routes
    from .queue_routes import init_queue_routes
    init_routes(app)
    init_queue_routes(app)
    
    # Tarefa periódica para notificações proativas
    def run_proactive_notifications():
        while True:
            with app.app_context():
                try:
                    QueueService.check_proactive_notifications()
                except Exception as e:
                    app.logger.error(f"Erro ao verificar notificações proativas: {e}")
            time.sleep(60)  # Executa a cada 60 segundos
    
    # Inicia a tarefa em uma thread separada
    notification_thread = Thread(target=run_proactive_notifications)
    notification_thread.daemon = True
    notification_thread.start()
    
    return app
import eventlet
eventlet.monkey_patch()
from app import create_app, socketio
import os
import logging

app = create_app()
logger = logging.getLogger(__name__)

# Removido o bloco if __name__ == "__main__": para evitar socketio.run em produção
# O Gunicorn gerencia a execução, vinculando à porta $PORT
logger.info(f"Servidor WSGI configurado para vincular em 0.0.0.0:{os.getenv('PORT', '10000')} via Gunicorn")

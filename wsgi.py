import eventlet
eventlet.monkey_patch()
from app import create_app, socketio
import os
import logging

app = create_app()
application = app  # Para garantir que o Gunicorn encontre a aplicação

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV') != 'production'
    logger.info(f"Iniciando servidor WSGI em {host}:{port} (debug={debug})")
    socketio.run(app, host=host, port=port, debug=debug)
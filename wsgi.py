import eventlet
eventlet.monkey_patch()
from app import create_app, socketio
import os
import logging

app = create_app()
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 10000))
    debug = os.getenv('FLASK_ENV') != 'production'
    logger.info(f"Iniciando servidor WSGI em {host}:{port} (debug={debug})")
    if os.getenv('FLASK_ENV') == 'production':
        # Em produção, espera-se que Gunicorn + Eventlet seja usado
        logger.warning("Executando socketio.run diretamente em produção não é recomendado. Use Gunicorn + Eventlet.")
    socketio.run(app, host=host, port=port, debug=debug)
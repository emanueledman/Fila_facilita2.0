import eventlet
eventlet.monkey_patch()
from app import create_app, socketio
import os
import logging

app = create_app()
logger = logging.getLogger(__name__)

# Configurar host e porta
host = os.getenv('HOST', '0.0.0.0')
port = int(os.getenv('PORT', 5000))
debug = os.getenv('FLASK_ENV') != 'production'

# Isso garante que o app seja vinculado à porta mesmo quando importado
if __name__ == "__main__":
    logger.info(f"Iniciando servidor WSGI em {host}:{port} (debug={debug})")
    socketio.run(app, host=host, port=port, debug=debug)
else:
    # Para uso com servidores WSGI ou quando importado (como no caso do Render)
    socketio.run(app, host=host, port=port, debug=debug)
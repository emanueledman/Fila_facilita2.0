import eventlet
eventlet.monkey_patch()
from app import create_app, socketio
import os
import logging

# Criar a aplicação
app = create_app()
logger = logging.getLogger(__name__)

# Esta variável "app" precisa ser exposta para o Gunicorn
# Quando usando Flask-SocketIO com Gunicorn, podemos precisar
# encapsular o aplicativo usando socketio.wsgi_app
application = socketio.wsgi_app

# Para uso em desenvolvimento local
if __name__ == "__main__":
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV') != 'production'
    logger.info(f"Iniciando servidor WSGI em {host}:{port} (debug={debug})")
    socketio.run(app, host=host, port=port, debug=debug)
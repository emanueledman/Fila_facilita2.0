import eventlet
eventlet.monkey_patch()

from app import create_app, socketio
import os
import logging

app = create_app()
logger = logging.getLogger(__name__)

# Configuração específica para o Render
def create_wsgi_app():
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV') != 'production'
    
    logger.info(f"Configurando aplicação Socket.IO em {host}:{port}")
    return socketio.WSGIServer((host, port), app)

if __name__ == "__main__":
    wsgi_app = create_wsgi_app()
    logger.info("Servidor Socket.IO iniciado")
    wsgi_app.serve_forever()
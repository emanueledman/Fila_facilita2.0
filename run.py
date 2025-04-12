import eventlet
eventlet.monkey_patch()

from app import app, socketio
from flask_cors import CORS
from app.ml_models import wait_time_predictor, service_recommendation_predictor
import os

# Configurar CORS
CORS(app, resources={r"/api/*": {
    "origins": [
        "http://127.0.0.1:5500",  # Frontend local
        "https://frontfa.netlify.app",  # Frontend principal
        "https://courageous-dolphin-66662b.netlify.app"  # Outro frontend
    ],
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"]
}})

# Configurar SocketIO com caminho explícito
socketio.init_app(
    app,
    cors_allowed_origins=[
        "http://127.0.0.1:5500",
        "https://frontfa.netlify.app",
        "https://courageous-dolphin-66662b.netlify.app"
    ],
    async_mode='eventlet',
    path='/tickets',  # Corrige erros 404
    logger=True,
    engineio_logger=True
)

def train_ml_model_periodically():
    while True:
        with app.app_context():
            try:
                app.logger.info("Iniciando treinamento periódico do modelo de previsão de tempo de espera.")
                wait_time_predictor.train()
                app.logger.info("Iniciando treinamento periódico do modelo de recomendação de serviços.")
                service_recommendation_predictor.train()
            except Exception as e:
                app.logger.error(f"Erro ao treinar modelos de ML: {str(e)}")
        eventlet.sleep(3600)

if __name__ == "__main__":
    if os.getenv('FLASK_ENV') != 'production':
        eventlet.spawn(train_ml_model_periodically)
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
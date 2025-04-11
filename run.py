import eventlet
eventlet.monkey_patch()  # Chamado antes de qualquer importação

from app import app, socketio
from app.ml_models import wait_time_predictor, service_recommendation_predictor

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
    eventlet.spawn(train_ml_model_periodically)
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
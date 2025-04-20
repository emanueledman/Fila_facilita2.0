import eventlet
eventlet.monkey_patch()
from app import app, socketio, db
from app.ml_models import wait_time_predictor, service_recommendation_predictor, collaborative_model, demand_model, clustering_model
from app.models import Queue
import os
import logging

logger = logging.getLogger(__name__)

def train_ml_model_periodically():
    """Treina os modelos de ML periodicamente para todas as filas."""
    while True:
        with app.app_context():
            try:
                logger.info("Iniciando treinamento periódico dos modelos de ML.")
                queues = Queue.query.all()
                for queue in queues:
                    logger.info(f"Treinando WaitTimePredictor para queue_id={queue.id}")
                    wait_time_predictor.train(queue.id)
                logger.info("Treinando ServiceRecommendationPredictor")
                service_recommendation_predictor.train()
                logger.info("Treinando CollaborativeFilteringModel")
                collaborative_model.train()
                logger.info("Treinando DemandForecastingModel")
                demand_model.train()
                logger.info("Treinando ServiceClusteringModel")
                clustering_model.train()
                logger.info("Treinamento periódico concluído.")
            except Exception as e:
                logger.error(f"Erro ao treinar modelos de ML: {str(e)}")
        eventlet.sleep(3600)  # Treinar a cada hora

if __name__ == "__main__":
    # Iniciar treinamento periódico apenas em desenvolvimento
    if os.getenv('FLASK_ENV') != 'production':
        eventlet.spawn(train_ml_model_periodically)
    
    # Configurar host e port
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 10000))
    
    # Ajustar debug com base no ambiente
    debug = os.getenv('FLASK_ENV') != 'production'
    logger.info(f"Iniciando servidor Flask-SocketIO em {host}:{port} (debug={debug})")
    socketio.run(app, host=host, port=port, debug=debug)
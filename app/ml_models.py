import logging
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import joblib
import os
from datetime import datetime, timedelta
from . import db
from .models import Ticket, Queue, Department
from geopy.distance import geodesic
from flask import current_app

logger = logging.getLogger(__name__)
logger.debug("Iniciando carregamento do módulo ml_models")

try:
    class WaitTimePredictor:
        MIN_SAMPLES = 10
        MAX_DAYS = 30

        def __init__(self):
            self.models = {}
            self.scalers = {}
            self.is_trained = {}
            self.fallback_times = {}
            self.sector_mapping = {}
            self.next_sector_id = 1

        def get_model_path(self, queue_id):
            return f"wait_time_model_{queue_id}.joblib"

        def get_scaler_path(self, queue_id):
            return f"wait_time_scaler_{queue_id}.joblib"

        def load_model(self):
            """Carrega os modelos e scalers salvos para cada fila."""
            try:
                queues = Queue.query.all()
                for queue in queues:
                    model_path = self.get_model_path(queue.id)
                    scaler_path = self.get_scaler_path(queue.id)
                    if os.path.exists(model_path) and os.path.exists(scaler_path):
                        self.models[queue.id] = joblib.load(model_path)
                        self.scalers[queue.id] = joblib.load(scaler_path)
                        self.is_trained[queue.id] = True
                        logger.info(f"Modelo carregado para queue_id={queue.id}")
                    else:
                        self.is_trained[queue.id] = False
                self._compute_fallback_times()
                logger.info(f"Modelos carregados para {len(self.models)} filas")
            except Exception as e:
                logger.error(f"Erro ao carregar modelos: {e}")
                self.is_trained = {}

        def save_model(self, queue_id):
            """Salva o modelo e o scaler para uma fila específica."""
            try:
                joblib.dump(self.models.get(queue_id, RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)), self.get_model_path(queue_id))
                joblib.dump(self.scalers.get(queue_id, StandardScaler()), self.get_scaler_path(queue_id))
                logger.info(f"Modelo salvo para queue_id={queue_id}")
            except Exception as e:
                logger.error(f"Erro ao salvar modelo para queue_id={queue_id}: {e}")

        def _compute_fallback_times(self):
            """Calcula tempos médios de espera por fila para uso como fallback."""
            try:
                queues = Queue.query.all()
                for queue in queues:
                    tickets = Ticket.query.filter(
                        Ticket.queue_id == queue.id,
                        Ticket.status == 'Atendido',
                        Ticket.service_time.isnot(None),
                        Ticket.service_time > 0
                    ).limit(100).all()
                    if tickets:
                        avg_time = np.mean([t.service_time for t in tickets])
                        self.fallback_times[queue.id] = round(avg_time, 1)
                    else:
                        self.fallback_times[queue.id] = queue.avg_wait_time or 30
                logger.debug(f"Fallback times computados para {len(self.fallback_times)} filas")
            except Exception as e:
                logger.error(f"Erro ao computar fallback times: {e}")

        def get_sector_id(self, sector):
            """Mapeia setores para IDs consistentes."""
            if not sector:
                return 0
            if sector not in self.sector_mapping:
                self.sector_mapping[sector] = self.next_sector_id
                self.next_sector_id += 1
            return self.sector_mapping[sector]

        def prepare_data(self, queue_id, days=MAX_DAYS, batch_size=1000):
            """Prepara os dados históricos para treinamento por fila com paginação."""
            try:
                queue = Queue.query.get(queue_id)
                if not queue:
                    logger.error(f"Fila não encontrada: queue_id={queue_id}")
                    return None, None

                start_date = datetime.utcnow() - timedelta(days=days)
                data = []
                offset = 0

                while True:
                    tickets = Ticket.query.filter(
                        Ticket.queue_id == queue_id,
                        Ticket.status == 'Atendido',
                        Ticket.issued_at >= start_date,
                        Ticket.service_time.isnot(None),
                        Ticket.service_time > 0
                    ).offset(offset).limit(batch_size).all()

                    if not tickets:
                        break

                    for ticket in tickets:
                        position = max(0, ticket.ticket_number - queue.current_ticket)
                        hour_of_day = ticket.issued_at.hour
                        sector_encoded = self.get_sector_id(queue.department.sector if queue.department else None)
                        data.append({
                            'position': position,
                            'active_tickets': queue.active_tickets,
                            'priority': ticket.priority or 0,
                            'hour_of_day': hour_of_day,
                            'num_counters': queue.num_counters or 1,
                            'daily_limit': queue.daily_limit or 100,
                            'sector_encoded': sector_encoded,
                            'service_time': ticket.service_time
                        })

                    offset += batch_size

                if len(data) < self.MIN_SAMPLES:
                    logger.warning(f"Dados insuficientes para queue_id={queue_id}: {len(data)} amostras")
                    return None, None

                df = pd.DataFrame(data)
                X = df[['position', 'active_tickets', 'priority', 'hour_of_day', 'num_counters', 'daily_limit', 'sector_encoded']]
                y = df['service_time']
                logger.debug(f"Dados preparados para queue_id={queue_id}: {len(data)} amostras")
                return X, y
            except Exception as e:
                logger.error(f"Erro ao preparar dados para queue_id={queue_id}: {e}")
                return None, None

        def train(self, queue_id):
            """Treina o modelo com dados históricos de uma fila específica."""
            try:
                X, y = self.prepare_data(queue_id)
                if X is None or y is None:
                    self.is_trained[queue_id] = False
                    return False

                X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
                scaler = StandardScaler()
                X_train_scaled = scaler.fit_transform(X_train)
                X_test_scaled = scaler.transform(X_test)

                model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
                model.fit(X_train_scaled, y_train)

                self.models[queue_id] = model
                self.scalers[queue_id] = scaler
                self.is_trained[queue_id] = True

                score = model.score(X_test_scaled, y_test)
                predictions = model.predict(X_test_scaled)
                mae = np.mean(np.abs(predictions - y_test))
                logger.info(f"Modelo treinado para queue_id={queue_id}. R²: {score:.2f}, MAE: {mae:.2f} minutos")
                
                if score < 0.5 or mae > 10:
                    logger.warning(f"Desempenho do modelo para queue_id={queue_id} abaixo do esperado. Recomenda-se retreinamento.")
                
                self.save_model(queue_id)
                self._compute_fallback_times()
                return True
            except Exception as e:
                logger.error(f"Erro ao treinar modelo para queue_id={queue_id}: {e}")
                self.is_trained[queue_id] = False
                return False

        def predict(self, queue_id, position, active_tickets, priority, hour_of_day):
            """Faz uma previsão do tempo de espera para uma fila."""
            try:
                if not isinstance(queue_id, str) or not queue_id:
                    raise ValueError(f"queue_id inválido: {queue_id}")

                queue = Queue.query.get(queue_id)
                if not queue:
                    raise ValueError(f"Fila não encontrada: queue_id={queue_id}")

                if queue_id not in self.is_trained or not self.is_trained[queue_id]:
                    logger.warning(f"Modelo não treinado para queue_id={queue_id}. Usando fallback.")
                    return self.fallback_times.get(queue_id, queue.avg_wait_time or 30)

                # Validar features
                position = max(0, float(position) if isinstance(position, (int, float)) else 0)
                active_tickets = max(0, float(active_tickets) if isinstance(active_tickets, (int, float)) else 0)
                priority = float(priority or 0) if isinstance(priority, (int, float)) else 0
                hour_of_day = max(0, min(23, float(hour_of_day) if isinstance(hour_of_day, (int, float)) else datetime.utcnow().hour))

                sector_encoded = self.get_sector_id(queue.department.sector if queue.department else None)
                features = np.array([[
                    position,
                    active_tickets,
                    priority,
                    hour_of_day,
                    float(queue.num_counters or 1),
                    float(queue.daily_limit or 100),
                    float(sector_encoded)
                ]])
                features_scaled = self.scalers[queue_id].transform(features)
                predicted_time = self.models[queue_id].predict(features_scaled)[0]
                predicted_time = max(0, predicted_time)
                logger.debug(f"Previsão de tempo de espera para queue_id={queue_id}: {predicted_time:.1f} minutos")
                return round(predicted_time, 1)
            except Exception as e:
                logger.error(f"Erro ao prever tempo de espera para queue_id={queue_id}: {e}")
                return self.fallback_times.get(queue_id, queue.avg_wait_time or 30)

    class ServiceRecommendationPredictor:
        MODEL_PATH = "recommendation_model.joblib"
        SCALER_PATH = "recommendation_scaler.joblib"
        MIN_SAMPLES = 5
        DEFAULT_SCORE = 0.5

        def __init__(self):
            self.model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
            self.scaler = StandardScaler()
            self.is_trained = False
            self.fallback_scores = {}
            self.sector_mapping = {}
            self.next_sector_id = 1

        def get_sector_id(self, sector):
            """Mapeia setores para IDs consistentes."""
            if not sector:
                return 0
            if sector not in self.sector_mapping:
                self.sector_mapping[sector] = self.next_sector_id
                self.next_sector_id += 1
            return self.sector_mapping[sector]

        def load_model(self):
            """Carrega o modelo e o scaler salvos, se existirem."""
            try:
                if os.path.exists(self.MODEL_PATH) and os.path.exists(self.SCALER_PATH):
                    self.model = joblib.load(self.MODEL_PATH)
                    self.scaler = joblib.load(self.SCALER_PATH)
                    self.is_trained = True
                    logger.info("Modelo de recomendação de serviços carregado com sucesso.")
                else:
                    logger.info("Modelo de recomendação não encontrado. Será treinado na primeira execução.")
                self._compute_fallback_scores()
            except Exception as e:
                logger.error(f"Erro ao carregar o modelo de recomendação: {e}")
                self.is_trained = False

        def save_model(self):
            """Salva o modelo e o scaler em disco."""
            try:
                joblib.dump(self.model, self.MODEL_PATH)
                joblib.dump(self.scaler, self.SCALER_PATH)
                logger.info("Modelo de recomendação de serviços salvo com sucesso.")
            except Exception as e:
                logger.error(f"Erro ao salvar o modelo de recomendação: {e}")

        def _compute_fallback_scores(self):
            """Calcula pontuações médias de qualidade por fila para uso como fallback."""
            try:
                queues = Queue.query.all()
                for queue in queues:
                    tickets = Ticket.query.filter(
                        Ticket.queue_id == queue.id,
                        Ticket.status == 'Atendido',
                        Ticket.service_time.isnot(None),
                        Ticket.service_time > 0
                    ).limit(100).all()
                    if tickets:
                        service_times = [t.service_time for t in tickets]
                        avg_time = np.mean(service_times)
                        availability = max(0, queue.daily_limit - queue.active_tickets) / max(1, queue.daily_limit)
                        score = (1 / (1 + avg_time / 60)) * availability
                        self.fallback_scores[queue.id] = max(0, min(1, round(score, 2)))
                    else:
                        self.fallback_scores[queue.id] = self.DEFAULT_SCORE
                logger.debug(f"Fallback scores computados para {len(self.fallback_scores)} filas")
            except Exception as e:
                logger.error(f"Erro ao computar fallback scores: {e}")

        def prepare_data(self, batch_size=1000):
            """Prepara os dados históricos para treinamento do modelo de recomendação com paginação."""
            try:
                queues = Queue.query.all()
                if not queues:
                    logger.warning("Nenhuma fila disponível para treinamento do modelo de recomendação.")
                    return None, None

                data = []
                for queue in queues:
                    offset = 0
                    while True:
                        tickets = Ticket.query.filter(
                            Ticket.queue_id == queue.id,
                            Ticket.status == 'Atendido',
                            Ticket.service_time.isnot(None),
                            Ticket.service_time > 0
                        ).offset(offset).limit(batch_size).all()
                        if not tickets:
                            break

                        service_times = [t.service_time for t in tickets]
                        avg_service_time = np.mean(service_times) if service_times else 30
                        std_service_time = np.std(service_times) if len(service_times) > 1 else 0
                        service_time_per_counter = avg_service_time / max(1, queue.num_counters or 1)
                        occupancy_rate = queue.active_tickets / max(1, queue.daily_limit or 100)
                        availability = max(0, queue.daily_limit - queue.active_tickets)
                        sector_encoded = self.get_sector_id(queue.department.sector if queue.department else None)
                        quality_score = (availability / max(1, queue.daily_limit)) * (1 / (1 + avg_service_time / 60))
                        quality_score = max(0, min(1, quality_score))

                        data.append({
                            'avg_service_time': avg_service_time,
                            'std_service_time': std_service_time,
                            'service_time_per_counter': service_time_per_counter,
                            'occupancy_rate': occupancy_rate,
                            'availability': availability,
                            'sector_encoded': sector_encoded,
                            'hour_of_day': datetime.utcnow().hour,
                            'day_of_week': datetime.utcnow().weekday(),
                            'quality_score': quality_score
                        })

                        offset += batch_size

                if len(data) < self.MIN_SAMPLES:
                    logger.warning(f"Dados insuficientes para treinamento do modelo de recomendação: {len(data)} amostras")
                    return None, None

                df = pd.DataFrame(data)
                X = df[['avg_service_time', 'std_service_time', 'service_time_per_counter', 'occupancy_rate', 'availability', 'sector_encoded', 'hour_of_day', 'day_of_week']]
                y = df['quality_score']
                logger.debug(f"Dados preparados para modelo de recomendação: {len(data)} amostras")
                return X, y
            except Exception as e:
                logger.error(f"Erro ao preparar dados para treinamento do modelo de recomendação: {e}")
                return None, None

        def train(self):
            """Treina o modelo com dados históricos."""
            try:
                X, y = self.prepare_data()
                if X is None or y is None:
                    self.is_trained = False
                    return

                X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
                X_train_scaled = self.scaler.fit_transform(X_train)
                X_test_scaled = self.scaler.transform(X_test)
                self.model.fit(X_train_scaled, y_train)
                self.is_trained = True
                score = self.model.score(X_test_scaled, y_test)
                predictions = self.model.predict(X_test_scaled)
                mae = np.mean(np.abs(predictions - y_test))
                logger.info(f"Modelo de recomendação treinado com sucesso. R²: {score:.2f}, MAE: {mae:.2f}")
                if score < 0.5 or mae > 0.2:
                    logger.warning("Desempenho do modelo de recomendação abaixo do esperado. Recomenda-se retreinamento.")
                self.save_model()
                self._compute_fallback_scores()
            except Exception as e:
                logger.error(f"Erro ao treinar o modelo de recomendação: {e}")
                self.is_trained = False

        def predict(self, queue):
            """Faz uma previsão da pontuação de qualidade de atendimento para uma fila."""
            try:
                if not queue or not hasattr(queue, 'id'):
                    logger.error("Objeto queue inválido")
                    return self.fallback_scores.get(queue.id, self.DEFAULT_SCORE) if queue else self.DEFAULT_SCORE

                if not self.is_trained:
                    logger.warning("Modelo de recomendação não treinado. Usando fallback.")
                    return self.fallback_scores.get(queue.id, self.DEFAULT_SCORE)

                tickets = Ticket.query.filter(
                    Ticket.queue_id == queue.id,
                    Ticket.status == 'Atendido',
                    Ticket.service_time.isnot(None),
                    Ticket.service_time > 0
                ).all()
                service_times = [t.service_time for t in tickets]
                avg_service_time = np.mean(service_times) if service_times else 30
                std_service_time = np.std(service_times) if len(service_times) > 1 else 0
                service_time_per_counter = avg_service_time / max(1, queue.num_counters or 1)
                occupancy_rate = queue.active_tickets / max(1, queue.daily_limit or 100)
                availability = max(0, queue.daily_limit - queue.active_tickets)
                sector_encoded = self.get_sector_id(queue.department.sector if queue.department else None)

                features = np.array([[
                    avg_service_time,
                    std_service_time,
                    service_time_per_counter,
                    occupancy_rate,
                    availability,
                    sector_encoded,
                    datetime.utcnow().hour,
                    datetime.utcnow().weekday()
                ]])
                features_scaled = self.scaler.transform(features)
                quality_score = self.model.predict(features_scaled)[0]
                quality_score = max(0, min(1, quality_score))
                logger.debug(f"Previsão de qualidade para queue_id={queue.id}: {quality_score:.2f}")
                return quality_score
            except Exception as e:
                logger.error(f"Erro ao prever qualidade para queue_id={queue.id}: {e}")
                return self.fallback_scores.get(queue.id, self.DEFAULT_SCORE)

    logger.debug("Instanciando wait_time_predictor e service_recommendation_predictor")
    wait_time_predictor = WaitTimePredictor()
    service_recommendation_predictor = ServiceRecommendationPredictor()
    logger.debug("Instâncias criadas com sucesso")

    def initialize_models(app):
        """Inicializa os modelos dentro do contexto da aplicação."""
        with app.app_context():
            logger.info("Inicializando modelos de ML dentro do contexto da aplicação")
            wait_time_predictor.load_model()
            service_recommendation_predictor.load_model()
            logger.info("Modelos de ML inicializados com sucesso dentro do contexto da aplicação")

except Exception as e:
    logger.error(f"Erro ao carregar o módulo ml_models: {e}")
    raise

logger.debug("Módulo ml_models carregado com sucesso")
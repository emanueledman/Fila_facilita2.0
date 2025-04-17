import logging
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import joblib
import os
from datetime import datetime, timedelta
from . import db
from .models import Ticket, Queue, Institution, Department
from geopy.distance import geodesic

logger = logging.getLogger(__name__)
logger.debug("Iniciando carregamento do módulo ml_models")

try:
    class WaitTimePredictor:
        MODEL_PATH = "wait_time_model.joblib"
        SCALER_PATH = "wait_time_scaler.joblib"

        def __init__(self):
            self.model = RandomForestRegressor(n_estimators=100, random_state=42)
            self.scaler = StandardScaler()
            self.is_trained = {}
            self.load_model()

        def load_model(self):
            """Carrega o modelo e o scaler salvos, se existirem."""
            try:
                if os.path.exists(self.MODEL_PATH) and os.path.exists(self.SCALER_PATH):
                    self.model = joblib.load(self.MODEL_PATH)
                    self.scaler = joblib.load(self.SCALER_PATH)
                    self.is_trained = {queue.id: True for queue in Queue.query.all()}
                    logger.info("Modelo de previsão de tempo de espera carregado com sucesso.")
                else:
                    logger.info("Modelo de espera não encontrado. Será treinado por fila na primeira execução.")
            except Exception as e:
                logger.error(f"Erro ao carregar o modelo de espera: {e}")

        def save_model(self):
            """Salva o modelo e o scaler em disco."""
            try:
                joblib.dump(self.model, self.MODEL_PATH)
                joblib.dump(self.scaler, self.SCALER_PATH)
                logger.info("Modelo de previsão de tempo de espera salvo com sucesso.")
            except Exception as e:
                logger.error(f"Erro ao salvar o modelo de espera: {e}")

        def prepare_data(self, queue_id, days=30):
            """Prepara os dados históricos para treinamento por fila."""
            try:
                queue = Queue.query.get(queue_id)
                if not queue:
                    logger.error(f"Fila não encontrada: queue_id={queue_id}")
                    return None, None

                start_date = datetime.utcnow() - timedelta(days=days)
                tickets = Ticket.query.filter(
                    Ticket.queue_id == queue_id,
                    Ticket.status == 'attended',
                    Ticket.issued_at >= start_date,
                    Ticket.service_time.isnot(None),
                    Ticket.service_time > 0
                ).all()

                if not tickets:
                    logger.warning(f"Nenhum ticket válido para queue_id={queue_id} nos últimos {days} dias")
                    return None, None

                data = []
                for ticket in tickets:
                    position = max(0, ticket.ticket_number - queue.current_ticket)
                    hour_of_day = ticket.issued_at.hour
                    sector_encoded = hash(ticket.queue.department.sector) % 100 if ticket.queue.department else 0
                    data.append({
                        'position': position,
                        'active_tickets': queue.active_tickets,
                        'priority': ticket.priority,
                        'hour_of_day': hour_of_day,
                        'num_counters': queue.num_counters,
                        'daily_limit': queue.daily_limit,
                        'sector_encoded': sector_encoded,
                        'service_time': ticket.service_time
                    })

                if len(data) < 10:
                    logger.warning(f"Dados insuficientes para queue_id={queue_id}: apenas {len(data)} amostras")
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
                X_train_scaled = self.scaler.fit_transform(X_train)
                X_test_scaled = self.scaler.transform(X_test)
                self.model.fit(X_train_scaled, y_train)
                self.is_trained[queue_id] = True
                score = self.model.score(X_test_scaled, y_test)
                logger.info(f"Modelo treinado para queue_id={queue_id}. Score R²: {score:.2f}")
                self.save_model()
                return True
            except Exception as e:
                logger.error(f"Erro ao treinar modelo para queue_id={queue_id}: {e}")
                self.is_trained[queue_id] = False
                return False

        def predict(self, queue_id, position, active_tickets, priority, hour_of_day):
            """Faz uma previsão do tempo de espera para uma fila."""
            try:
                queue = Queue.query.get(queue_id)
                if not queue:
                    logger.error(f"Fila não encontrada: queue_id={queue_id}")
                    return None

                if queue_id not in self.is_trained or not self.is_trained[queue_id]:
                    logger.warning(f"Modelo não treinado para queue_id={queue_id}. Usando estimativa padrão.")
                    return queue.avg_wait_time if queue.avg_wait_time else 30

                sector_encoded = hash(queue.department.sector) % 100 if queue.department else 0
                features = np.array([[
                    position,
                    active_tickets,
                    priority,
                    hour_of_day,
                    queue.num_counters,
                    queue.daily_limit,
                    sector_encoded
                ]])
                features_scaled = self.scaler.transform(features)
                predicted_time = self.model.predict(features_scaled)[0]
                predicted_time = max(0, predicted_time)
                logger.debug(f"Previsão de tempo de espera para queue_id={queue_id}: {predicted_time:.1f} minutos")
                return round(predicted_time, 1)
            except Exception as e:
                logger.error(f"Erro ao prever tempo de espera para queue_id={queue_id}: {e}")
                return None

    class ServiceRecommendationPredictor:
        MODEL_PATH = "recommendation_model.joblib"
        SCALER_PATH = "recommendation_scaler.joblib"

        def __init__(self):
            self.model = RandomForestRegressor(n_estimators=100, random_state=42)
            self.scaler = StandardScaler()
            self.is_trained = False
            self.load_model()

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

        def prepare_data(self):
            """Prepara os dados históricos para treinamento do modelo de recomendação."""
            try:
                queues = Queue.query.all()
                if not queues:
                    logger.warning("Nenhuma fila disponível para treinamento do modelo de recomendação.")
                    return None, None

                data = []
                for queue in queues:
                    tickets = Ticket.query.filter_by(queue_id=queue.id, status='attended').all()
                    if not tickets:
                        continue

                    service_times = [t.service_time for t in tickets if t.service_time is not None and t.service_time > 0]
                    if not service_times:
                        continue

                    avg_service_time = np.mean(service_times)
                    std_service_time = np.std(service_times) if len(service_times) > 1 else 0
                    service_time_per_counter = avg_service_time / max(1, queue.num_counters)
                    occupancy_rate = queue.active_tickets / max(1, queue.daily_limit)
                    availability = max(0, queue.daily_limit - queue.active_tickets)
                    sector_encoded = hash(queue.department.sector) % 100 if queue.department else 0

                    quality_score = (availability / queue.daily_limit) * (1 / (1 + avg_service_time)) * (1 / (1 + std_service_time))
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

                if len(data) < 5:
                    logger.warning(f"Dados insuficientes para treinamento do modelo de recomendação: apenas {len(data)} amostras válidas.")
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
                logger.info(f"Modelo de recomendação treinado com sucesso. Score R²: {score:.2f}")
                self.save_model()
            except Exception as e:
                logger.error(f"Erro ao treinar o modelo de recomendação: {e}")
                self.is_trained = False

        def predict(self, queue):
            """Faz uma previsão da pontuação de qualidade de atendimento para uma fila."""
            try:
                if not self.is_trained:
                    logger.warning("Modelo de recomendação não treinado. Usando pontuação padrão.")
                    return 0.5

                tickets = Ticket.query.filter_by(queue_id=queue.id, status='attended').all()
                service_times = [t.service_time for t in tickets if t.service_time is not None and t.service_time > 0]
                avg_service_time = np.mean(service_times) if service_times else 30
                std_service_time = np.std(service_times) if len(service_times) > 1 else 0
                service_time_per_counter = avg_service_time / max(1, queue.num_counters)
                occupancy_rate = queue.active_tickets / max(1, queue.daily_limit)
                availability = max(0, queue.daily_limit - queue.active_tickets)
                sector_encoded = hash(queue.department.sector) % 100 if queue.department else 0

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
                return 0.5

        def suggest_for_totem(self, institution_id, user_lat=None, user_lon=None, max_distance_km=50, max_results=10):
            """Sugerir filas otimizadas para totens, considerando disponibilidade, tempo de espera e distância."""
            try:
                queues = Queue.query.join(Department).filter(
                    Department.institution_id == institution_id,
                    Queue.active_tickets < Queue.daily_limit
                ).all()

                suggestions = []
                user_location = (user_lat, user_lon) if user_lat is not None and user_lon is not None else None

                for queue in queues:
                    institution = queue.department.institution
                    availability = max(0, queue.daily_limit - queue.active_tickets)
                    quality_score = self.predict(queue)

                    distance = None
                    if user_location and institution.latitude and institution.longitude:
                        inst_location = (institution.latitude, institution.longitude)
                        distance = geodesic(user_location, inst_location).kilometers
                        if distance > max_distance_km:
                            continue

                    wait_time = wait_time_predictor.predict(
                        queue.id,
                        position=queue.active_tickets + 1,
                        active_tickets=queue.active_tickets,
                        priority=0,
                        hour_of_day=datetime.utcnow().hour
                    ) or queue.avg_wait_time or 30

                    score = (
                        0.4 * quality_score +
                        0.3 * (availability / queue.daily_limit) +
                        0.3 * (1 / (1 + wait_time / 60))
                    )
                    if distance:
                        score *= (1 - distance / max_distance_km)

                    suggestions.append({
                        'queue_id': queue.id,
                        'service': queue.service,
                        'institution': institution.name,
                        'location': institution.location,
                        'latitude': institution.latitude,
                        'longitude': institution.longitude,
                        'distance_km': round(distance, 2) if distance else None,
                        'wait_time': round(wait_time, 2),
                        'availability': availability,
                        'quality_score': round(quality_score, 2),
                        'score': round(score, 3)
                    })

                suggestions = sorted(suggestions, key=lambda x: x['score'], reverse=True)[:max_results]
                logger.info(f"Sugestões para totem em institution_id={institution_id}: {len(suggestions)} resultados")
                return suggestions
            except Exception as e:
                logger.error(f"Erro ao sugerir filas para totem em institution_id={institution_id}: {e}")
                return []

    # Instanciar os preditores globalmente
    logger.debug("Instanciando wait_time_predictor e service_recommendation_predictor")
    wait_time_predictor = WaitTimePredictor()
    service_recommendation_predictor = ServiceRecommendationPredictor()
    logger.debug("Instâncias criadas com sucesso")

except Exception as e:
    logger.error(f"Erro ao carregar o módulo ml_models: {e}")
    raise

logger.debug("Módulo ml_models carregado com sucesso")
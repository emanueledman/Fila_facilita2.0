# app/ml_models.py

import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import joblib
import os
import logging
from datetime import datetime
from . import db
from .models import Ticket, Queue

logger = logging.getLogger(__name__)

class WaitTimePredictor:
    MODEL_PATH = "wait_time_model.joblib"
    SCALER_PATH = "wait_time_scaler.joblib"

    def __init__(self):
        self.model = LinearRegression()
        self.scaler = StandardScaler()
        self.is_trained = False
        self.load_model()

    def load_model(self):
        """Carrega o modelo e o scaler salvos, se existirem."""
        if os.path.exists(self.MODEL_PATH) and os.path.exists(self.SCALER_PATH):
            self.model = joblib.load(self.MODEL_PATH)
            self.scaler = joblib.load(self.SCALER_PATH)
            self.is_trained = True
            logger.info("Modelo de previsão de tempo de espera carregado com sucesso.")
        else:
            logger.info("Modelo de espera não encontrado. Será treinado na primeira execução.")

    def save_model(self):
        """Salva o modelo e o scaler em disco."""
        joblib.dump(self.model, self.MODEL_PATH)
        joblib.dump(self.scaler, self.SCALER_PATH)
        logger.info("Modelo de previsão de tempo de espera salvo com sucesso.")

    def prepare_data(self):
        """Prepara os dados históricos para treinamento."""
        tickets = Ticket.query.filter_by(status='attended').all()
        if not tickets:
            logger.warning("Nenhum dado histórico disponível para treinamento do modelo de espera.")
            return None, None

        data = []
        for ticket in tickets:
            if ticket.service_time is None or ticket.service_time <= 0:
                continue
            queue = ticket.queue
            position = max(0, ticket.ticket_number - queue.current_ticket)
            hour_of_day = ticket.issued_at.hour
            data.append({
                'position': position,
                'active_tickets': queue.active_tickets,
                'priority': ticket.priority,
                'hour_of_day': hour_of_day,
                'service_time': ticket.service_time
            })

        if not data:
            logger.warning("Nenhum dado válido para treinamento do modelo de espera após filtragem.")
            return None, None

        df = pd.DataFrame(data)
        X = df[['position', 'active_tickets', 'priority', 'hour_of_day']]
        y = df['service_time']
        return X, y

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
            logger.info(f"Modelo de espera treinado com sucesso. Score R²: {score:.2f}")
            self.save_model()
        except Exception as e:
            logger.error(f"Erro ao treinar o modelo de espera: {e}")
            self.is_trained = False

    def predict(self, position, active_tickets, priority, hour_of_day):
        """Faz uma previsão do tempo de espera."""
        try:
            if not self.is_trained:
                logger.warning("Modelo de espera não treinado. Usando estimativa padrão.")
                return None

            features = np.array([[position, active_tickets, priority, hour_of_day]])
            features_scaled = self.scaler.transform(features)
            predicted_time = self.model.predict(features_scaled)[0]
            predicted_time = max(0, predicted_time)
            logger.debug(f"Previsão de tempo de espera: {predicted_time:.1f} minutos (position={position}, active_tickets={active_tickets}, priority={priority}, hour_of_day={hour_of_day})")
            return round(predicted_time, 1)
        except Exception as e:
            logger.error(f"Erro ao fazer previsão de espera: {e}")
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

                # Pontuação de qualidade: menor tempo médio e menor variabilidade = melhor
                # Fórmula: quality_score = (1 / avg_service_time) - (std_service_time / avg_service_time)
                quality_score = (1 / avg_service_time) - (std_service_time / avg_service_time) if avg_service_time > 0 else 0
                quality_score = max(0, quality_score)  # Garantir que a pontuação não seja negativa

                data.append({
                    'avg_service_time': avg_service_time,
                    'std_service_time': std_service_time,
                    'service_time_per_counter': service_time_per_counter,
                    'occupancy_rate': occupancy_rate,
                    'hour_of_day': datetime.utcnow().hour,
                    'day_of_week': datetime.utcnow().weekday(),
                    'quality_score': quality_score
                })

            if len(data) < 5:
                logger.warning(f"Dados insuficientes para treinamento do modelo de recomendação: apenas {len(data)} amostras válidas.")
                return None, None

            df = pd.DataFrame(data)
            X = df[['avg_service_time', 'std_service_time', 'service_time_per_counter', 'occupancy_rate', 'hour_of_day', 'day_of_week']]
            y = df['quality_score']
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

    def predict(self, avg_service_time, std_service_time, service_time_per_counter, occupancy_rate, hour_of_day, day_of_week):
        """Faz uma previsão da pontuação de qualidade de atendimento."""
        try:
            if not self.is_trained:
                logger.warning("Modelo de recomendação não treinado. Usando pontuação padrão.")
                return None

            features = np.array([[avg_service_time, std_service_time, service_time_per_counter, occupancy_rate, hour_of_day, day_of_week]])
            features_scaled = self.scaler.transform(features)
            quality_score = self.model.predict(features_scaled)[0]
            quality_score = max(0, quality_score)
            logger.debug(f"Previsão de qualidade de atendimento: {quality_score:.2f} (avg_service_time={avg_service_time}, std_service_time={std_service_time}, service_time_per_counter={service_time_per_counter}, occupancy_rate={occupancy_rate})")
            return quality_score
        except Exception as e:
            logger.error(f"Erro ao fazer previsão de recomendação: {e}")
            return None

# Instanciar os preditores globalmente
wait_time_predictor = WaitTimePredictor()
service_recommendation_predictor = ServiceRecommendationPredictor()
import logging
import uuid
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import TruncatedSVD
from sklearn.cluster import KMeans
try:
    from prophet import Prophet
except ImportError as e:
    logger.error(f"Erro ao importar Prophet: {e}")
    Prophet = None
from sqlalchemy import and_
from datetime import datetime, timedelta
from app import db
from app.models import Queue, Ticket, Department, ServiceTag, UserPreference, QueueSchedule, Branch, Weekday
from geopy.distance import geodesic
import joblib
import os

logger = logging.getLogger(__name__)

class WaitTimePredictor:
    """Modelo para prever tempo de espera por fila."""
    MIN_SAMPLES = 10
    MAX_DAYS = 30
    MODEL_PATH = "wait_time_model_{queue_id}.joblib"
    FALLBACK_TIME = 5

    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.is_trained = {}
        self.sector_mapping = {}
        self.category_mapping = {}
        self.next_sector_id = 1
        self.next_category_id = 1

    def get_sector_id(self, sector):
        if not sector:
            return 0
        if sector not in self.sector_mapping:
            self.sector_mapping[sector] = self.next_sector_id
            self.next_sector_id += 1
        return self.sector_mapping[sector]

    def get_category_id(self, category_id):
        if not category_id:
            return 0
        if category_id not in self.category_mapping:
            self.category_mapping[category_id] = self.next_category_id
            self.next_category_id += 1
        return self.category_mapping[category_id]

    def calculate_distance(self, user_lat, user_lon, branch):
        try:
            if not all(isinstance(x, (int, float)) for x in [user_lat, user_lon, branch.latitude, branch.longitude]):
                return 0
            return geodesic((user_lat, user_lon), (branch.latitude, branch.longitude)).kilometers
        except Exception as e:
            logger.error(f"Erro ao calcular distância: {e}")
            return 0

    def prepare_data(self, queue_id, days=MAX_DAYS, batch_size=1000):
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
                    category_encoded = self.get_category_id(queue.category_id)
                    data.append({
                        'position': position,
                        'active_tickets': queue.active_tickets,
                        'priority': ticket.priority or 0,
                        'hour_of_day': hour_of_day,
                        'num_counters': queue.num_counters or 1,
                        'daily_limit': queue.daily_limit or 100,
                        'sector_encoded': sector_encoded,
                        'category_encoded': category_encoded,
                        'service_time': ticket.service_time
                    })

                offset += batch_size

            # Transfer learning para filas com poucos dados
            if len(data) < self.MIN_SAMPLES:
                similar_queues = Queue.query.filter(
                    Queue.category_id == queue.category_id,
                    Queue.id != queue_id
                ).limit(10).all()
                for similar_queue in similar_queues:
                    tickets = Ticket.query.filter(
                        Ticket.queue_id == similar_queue.id,
                        Ticket.status == 'Atendido',
                        Ticket.issued_at >= start_date,
                        Ticket.service_time.isnot(None),
                        Ticket.service_time > 0
                    ).limit(batch_size).all()
                    for ticket in tickets:
                        position = max(0, ticket.ticket_number - similar_queue.current_ticket)
                        hour_of_day = ticket.issued_at.hour
                        sector_encoded = self.get_sector_id(similar_queue.department.sector if similar_queue.department else None)
                        category_encoded = self.get_category_id(similar_queue.category_id)
                        data.append({
                            'position': position,
                            'active_tickets': similar_queue.active_tickets,
                            'priority': ticket.priority or 0,
                            'hour_of_day': hour_of_day,
                            'num_counters': similar_queue.num_counters or 1,
                            'daily_limit': similar_queue.daily_limit or 100,
                            'sector_encoded': sector_encoded,
                            'category_encoded': category_encoded,
                            'service_time': ticket.service_time
                        })

            if len(data) < self.MIN_SAMPLES:
                logger.warning(f"Dados insuficientes para queue_id={queue_id}: {len(data)} amostras")
                return None, None

            df = pd.DataFrame(data)
            X = df[['position', 'active_tickets', 'priority', 'hour_of_day', 'num_counters', 'daily_limit', 'sector_encoded', 'category_encoded']]
            y = df['service_time']
            logger.debug(f"Dados preparados para queue_id={queue_id}: {len(data)} amostras")
            return X, y
        except Exception as e:
            logger.error(f"Erro ao preparar dados para queue_id={queue_id}: {e}")
            return None, None

    def train(self, queue_id):
        try:
            X, y = self.prepare_data(queue_id)
            if X is None or y is None:
                self.is_trained[queue_id] = False
                return

            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            model = RandomForestRegressor(n_estimators=100, random_state=42)
            model.fit(X_scaled, y)

            self.models[queue_id] = model
            self.scalers[queue_id] = scaler
            self.is_trained[queue_id] = True
            joblib.dump((model, scaler), self.MODEL_PATH.format(queue_id=queue_id))
            logger.info(f"Modelo treinado para queue_id={queue_id}")
        except Exception as e:
            logger.error(f"Erro ao treinar modelo para queue_id={queue_id}: {e}")
            self.is_trained[queue_id] = False

    def load_model(self, queue_id):
        try:
            path = self.MODEL_PATH.format(queue_id=queue_id)
            if os.path.exists(path):
                model, scaler = joblib.load(path)
                self.models[queue_id] = model
                self.scalers[queue_id] = scaler
                self.is_trained[queue_id] = True
                logger.info(f"Modelo carregado para queue_id={queue_id}")
        except Exception as e:
            logger.error(f"Erro ao carregar modelo para queue_id={queue_id}: {e}")
            self.is_trained[queue_id] = False

    def predict(self, queue_id, position, active_tickets, priority, hour_of_day, user_lat=None, user_lon=None):
        try:
            if queue_id not in self.is_trained or not self.is_trained[queue_id]:
                self.load_model(queue_id)
                if not self.is_trained.get(queue_id, False):
                    logger.warning(f"Modelo não treinado para queue_id={queue_id}, usando fallback")
                    return self.FALLBACK_TIME

            queue = Queue.query.get(queue_id)
            if not queue:
                logger.error(f"Fila não encontrada: queue_id={queue_id}")
                return self.FALLBACK_TIME

            branch = Branch.query.join(Department).filter(Department.id == queue.department_id).first()
            distance = self.calculate_distance(user_lat, user_lon, branch) if user_lat and user_lon and branch else 0

            features = np.array([[
                position,
                active_tickets,
                priority,
                hour_of_day,
                queue.num_counters or 1,
                queue.daily_limit or 100,
                self.get_sector_id(queue.department.sector if queue.department else None),
                self.get_category_id(queue.category_id),
                distance
            ]])
            features_scaled = self.scalers[queue_id].transform(features)
            wait_time = self.models[queue_id].predict(features_scaled)[0]
            return max(0, round(wait_time, 1))
        except Exception as e:
            logger.error(f"Erro ao prever wait_time para queue_id={queue_id}: {e}")
            return self.FALLBACK_TIME

class ServiceRecommendationPredictor:
    """Modelo para prever pontuação de qualidade de filas."""
    MIN_SAMPLES = 10
    MODEL_PATH = "service_recommendation_model.joblib"
    DEFAULT_SCORE = 0.5

    def __init__(self):
        self.model = RandomForestRegressor(n_estimators=100, random_state=42)
        self.scaler = StandardScaler()
        self.is_trained = False
        self.sector_mapping = {}
        self.category_mapping = {}
        self.next_sector_id = 1
        self.next_category_id = 1

    def get_sector_id(self, sector):
        if not sector:
            return 0
        if sector not in self.sector_mapping:
            self.sector_mapping[sector] = self.next_sector_id
            self.next_sector_id += 1
        return self.sector_mapping[sector]

    def get_category_id(self, category_id):
        if not category_id:
            return 0
        if category_id not in self.category_mapping:
            self.category_mapping[category_id] = self.next_category_id
            self.next_category_id += 1
        return self.category_mapping[category_id]

    def calculate_tag_similarity(self, queue_tags, user_id):
        try:
            if not user_id or not queue_tags:
                return 0
            user_prefs = UserPreference.query.filter_by(user_id=user_id).all()
            preferred_tags = {pref.service_category_id for pref in user_prefs if pref.service_category_id}
            queue_tag_ids = {tag.tag for tag in queue_tags}
            intersection = len(queue_tag_ids.intersection(preferred_tags))
            return intersection / max(1, len(queue_tag_ids))
        except Exception as e:
            logger.error(f"Erro ao calcular tag_similarity: {e}")
            return 0

    def prepare_data(self, user_id=None, batch_size=1000):
        try:
            data = []
            queues = Queue.query.all()
            user_prefs = UserPreference.query.filter_by(user_id=user_id).all() if user_id else []
            preferred_institutions = {pref.institution_id for pref in user_prefs if pref.institution_id}
            preferred_categories = {pref.service_category_id for pref in user_prefs if pref.service_category_id}
            preferred_neighborhoods = {pref.neighborhood for pref in user_prefs if pref.neighborhood}

            for queue in queues:
                branch = Branch.query.join(Department).filter(Department.id == queue.department_id).first()
                tickets = Ticket.query.filter(
                    Ticket.queue_id == queue.id,
                    Ticket.status == 'Atendido',
                    Ticket.service_time.isnot(None),
                    Ticket.service_time > 0
                ).limit(batch_size).all()
                service_times = [t.service_time for t in tickets]
                avg_service_time = np.mean(service_times) if service_times else 30
                availability = max(0, queue.daily_limit - queue.active_tickets)
                is_open = (
                    1 if any(
                        s.weekday == Weekday(datetime.utcnow().weekday()).name
                        and s.open_time <= datetime.utcnow().time() <= s.end_time
                        and not s.is_closed
                        for s in queue.schedules
                    ) else 0
                )
                tag_similarity = self.calculate_tag_similarity(queue.tags, user_id)
                predicted_demand = DemandForecastingModel().predict(queue.id, hours_ahead=1)

                quality_score = (
                    0.3 * (availability / max(1, queue.daily_limit))
                    + 0.25 * (1 / (1 + avg_service_time / 30))
                    + 0.15 * (1 / (1 + predicted_demand / 10))
                    + 0.1 * tag_similarity
                )
                quality_score = max(0, min(1, quality_score))

                data.append({
                    'avg_service_time': avg_service_time,
                    'availability': availability,
                    'sector_encoded': self.get_sector_id(queue.department.sector if queue.department else None),
                    'category_encoded': self.get_category_id(queue.category_id),
                    'is_open': is_open,
                    'tag_similarity': tag_similarity,
                    'predicted_demand': predicted_demand,
                    'is_preferred_institution': 1 if branch and branch.institution_id in preferred_institutions else 0,
                    'is_preferred_neighborhood': 1 if branch and branch.neighborhood in preferred_neighborhoods else 0,
                    'quality_score': quality_score
                })

            if len(data) < self.MIN_SAMPLES:
                logger.warning(f"Dados insuficientes: {len(data)} amostras")
                return None, None

            df = pd.DataFrame(data)
            X = df[[
                'avg_service_time', 'availability', 'sector_encoded', 'category_encoded',
                'is_open', 'tag_similarity', 'predicted_demand',
                'is_preferred_institution', 'is_preferred_neighborhood'
            ]]
            y = df['quality_score']
            return X, y
        except Exception as e:
            logger.error(f"Erro ao preparar dados: {e}")
            return None, None

    def train(self, user_id=None):
        try:
            X, y = self.prepare_data(user_id)
            if X is None or y is None:
                self.is_trained = False
                return

            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled, y)
            self.is_trained = True
            joblib.dump((self.model, self.scaler), self.MODEL_PATH)
            logger.info("Modelo de recomendação treinado")
        except Exception as e:
            logger.error(f"Erro ao treinar modelo de recomendação: {e}")
            self.is_trained = False

    def load_model(self):
        try:
            if os.path.exists(self.MODEL_PATH):
                self.model, self.scaler = joblib.load(self.MODEL_PATH)
                self.is_trained = True
                logger.info("Modelo de recomendação carregado")
        except Exception as e:
            logger.error(f"Erro ao carregar modelo de recomendação: {e}")
            self.is_trained = False

    def predict(self, queue, user_id=None, user_lat=None, user_lon=None):
        try:
            if not self.is_trained:
                self.load_model()
                if not self.is_trained:
                    logger.warning("Modelo de recomendação não treinado, usando default")
                    return self.DEFAULT_SCORE

            branch = Branch.query.join(Department).filter(Department.id == queue.department_id).first()
            tickets = Ticket.query.filter(
                Ticket.queue_id == queue.id,
                Ticket.status == 'Atendido',
                Ticket.service_time.isnot(None)
            ).all()
            avg_service_time = np.mean([t.service_time for t in tickets]) if tickets else 30
            availability = max(0, queue.daily_limit - queue.active_tickets)
            is_open = (
                1 if any(
                    s.weekday == Weekday(datetime.utcnow().weekday()).name
                    and s.open_time <= datetime.utcnow().time() <= s.end_time
                    and not s.is_closed
                    for s in queue.schedules
                ) else 0
            )
            tag_similarity = self.calculate_tag_similarity(queue.tags, user_id)
            predicted_demand = DemandForecastingModel().predict(queue.id, hours_ahead=1)
            user_prefs = UserPreference.query.filter_by(user_id=user_id).all() if user_id else []
            preferred_institutions = {pref.institution_id for pref in user_prefs if pref.institution_id}
            preferred_neighborhoods = {pref.neighborhood for pref in user_prefs if pref.neighborhood}

            features = np.array([[
                avg_service_time,
                availability,
                self.get_sector_id(queue.department.sector if queue.department else None),
                self.get_category_id(queue.category_id),
                is_open,
                tag_similarity,
                predicted_demand,
                1 if branch and branch.institution_id in preferred_institutions else 0,
                1 if branch and branch.neighborhood in preferred_neighborhoods else 0
            ]])
            features_scaled = self.scaler.transform(features)
            score = self.model.predict(features_scaled)[0]
            return max(0, min(1, round(score, 2)))
        except Exception as e:
            logger.error(f"Erro ao prever quality_score para queue_id={queue.id}: {e}")
            return self.DEFAULT_SCORE

class CollaborativeFilteringModel:
    """Modelo de filtragem colaborativa para recomendações baseadas em padrões de usuários."""
    MODEL_PATH = "collaborative_model.joblib"
    MIN_INTERACTIONS = 10

    def __init__(self):
        self.svd = TruncatedSVD(n_components=50, random_state=42)
        self.user_mapping = {}
        self.queue_mapping = {}
        self.is_trained = False

    def load_model(self):
        try:
            if os.path.exists(self.MODEL_PATH):
                self.svd, self.user_mapping, self.queue_mapping = joblib.load(self.MODEL_PATH)
                self.is_trained = True
                logger.info("Modelo colaborativo carregado")
        except Exception as e:
            logger.error(f"Erro ao carregar modelo colaborativo: {e}")

    def save_model(self):
        try:
            joblib.dump((self.svd, self.user_mapping, self.queue_mapping), self.MODEL_PATH)
            logger.info("Modelo colaborativo salvo")
        except Exception as e:
            logger.error(f"Erro ao salvar modelo colaborativo: {e}")

    def prepare_data(self):
        try:
            tickets = Ticket.query.filter(Ticket.user_id.isnot(None)).all()
            user_queue_counts = {}
            for ticket in tickets:
                key = (ticket.user_id, ticket.queue_id)
                user_queue_counts[key] = user_queue_counts.get(key, 0) + 1

            if len(user_queue_counts) < self.MIN_INTERACTIONS:
                logger.warning(f"Interações insuficientes: {len(user_queue_counts)}")
                return None

            users = sorted(set(k[0] for k in user_queue_counts.keys()))
            queues = sorted(set(k[1] for k in user_queue_counts.keys()))
            self.user_mapping = {u: i for i, u in enumerate(users)}
            self.queue_mapping = {q: i for i, q in enumerate(queues)}

            data = []
            rows = []
            cols = []
            for (user_id, queue_id), count in user_queue_counts.items():
                data.append(count)
                rows.append(self.user_mapping[user_id])
                cols.append(self.queue_mapping[queue_id])

            interaction_matrix = csr_matrix((data, (rows, cols)), shape=(len(users), len(queues)))
            return interaction_matrix
        except Exception as e:
            logger.error(f"Erro ao preparar dados colaborativos: {e}")
            return None

    def train(self):
        try:
            interaction_matrix = self.prepare_data()
            if interaction_matrix is None:
                self.is_trained = False
                return

            self.svd.fit(interaction_matrix)
            self.is_trained = True
            self.save_model()
            logger.info("Modelo colaborativo treinado")
        except Exception as e:
            logger.error(f"Erro ao treinar modelo colaborativo: {e}")
            self.is_trained = False

    def predict(self, user_id, queue_ids):
        try:
            if not self.is_trained or user_id not in self.user_mapping:
                return {q: 0.5 for q in queue_ids}

            user_idx = self.user_mapping[user_id]
            user_vector = self.svd.transform(np.zeros((1, len(self.queue_mapping))))
            scores = {}
            for queue_id in queue_ids:
                if queue_id in self.queue_mapping:
                    queue_idx = self.queue_mapping[queue_id]
                    score = np.dot(user_vector[0], self.svd.components_[:, queue_idx])
                    scores[queue_id] = max(0, min(1, score))
                else:
                    scores[queue_id] = 0.5
            return scores
        except Exception as e:
            logger.error(f"Erro ao prever colaborativamente para user_id={user_id}: {e}")
            return {q: 0.5 for q in queue_ids}

class DemandForecastingModel:
    """Modelo para prever demanda futura de filas."""
    MODEL_PATH = "demand_model_{queue_id}.joblib"
    MIN_DAYS = 7

    def __init__(self):
        self.models = {}
        self.is_trained = {}
        self.use_prophet = Prophet is not None

    def get_model_path(self, queue_id):
        return self.MODEL_PATH.format(queue_id=queue_id)

    def prepare_data(self, queue_id):
        try:
            start_date = datetime.utcnow() - timedelta(days=self.MIN_DAYS)
            tickets = Ticket.query.filter(
                Ticket.queue_id == queue_id,
                Ticket.issued_at >= start_date
            ).all()

            if not tickets:
                return None

            df = pd.DataFrame([
                {'ds': t.issued_at, 'y': 1}
                for t in tickets
            ])
            df = df.groupby(pd.Grouper(key='ds', freq='H')).sum().reset_index()
            return df
        except Exception as e:
            logger.error(f"Erro ao preparar dados de demanda para queue_id={queue_id}: {e}")
            return None

    def train(self, queue_id):
        if not self.use_prophet:
            logger.warning(f"Prophet não disponível, pulando treinamento para queue_id={queue_id}")
            self.is_trained[queue_id] = False
            return
        try:
            df = self.prepare_data(queue_id)
            if df is None or len(df) < 24:
                self.is_trained[queue_id] = False
                return

            model = Prophet(daily_seasonality=True, weekly_seasonality=True)
            model.fit(df)
            self.models[queue_id] = model
            self.is_trained[queue_id] = True
            joblib.dump(model, self.get_model_path(queue_id))
            logger.info(f"Modelo de demanda treinado para queue_id={queue_id}")
        except Exception as e:
            logger.error(f"Erro ao treinar modelo de demanda para queue_id={queue_id}: {e}")
            self.is_trained[queue_id] = False

    def load_model(self, queue_id):
        if not self.use_prophet:
            logger.warning(f"Prophet não disponível, pulando carregamento para queue_id={queue_id}")
            self.is_trained[queue_id] = False
            return
        try:
            path = self.get_model_path(queue_id)
            if os.path.exists(path):
                self.models[queue_id] = joblib.load(path)
                self.is_trained[queue_id] = True
                logger.info(f"Modelo de demanda carregado para queue_id={queue_id}")
        except Exception as e:
            logger.error(f"Erro ao carregar modelo de demanda para queue_id={queue_id}: {e}")
            self.is_trained[queue_id] = False

    def predict(self, queue_id, hours_ahead=1):
        if not self.use_prophet or queue_id not in self.is_trained or not self.is_trained[queue_id]:
            logger.warning(f"Modelo de demanda não disponível para queue_id={queue_id}, retornando 0")
            return 0
        try:
            model = self.models[queue_id]
            future = model.make_future_dataframe(periods=hours_ahead, freq='H')
            forecast = model.predict(future)
            predicted_demand = forecast.tail(1)['yhat'].iloc[0]
            return max(0, round(predicted_demand, 1))
        except Exception as e:
            logger.error(f"Erro ao prever demanda para queue_id={queue_id}: {e}")
            return 0

class ServiceClusteringModel:
    """Modelo para agrupar filas semelhantes e sugerir alternativas."""
    MODEL_PATH = "clustering_model.joblib"
    MIN_QUEUES = 10

    def __init__(self):
        self.kmeans = KMeans(n_clusters=10, random_state=42)
        self.queue_mapping = {}
        self.is_trained = False
        self.tag_set = set()

    def get_category_id(self, category_id):
        return category_id if category_id else 0

    def get_sector_id(self, sector):
        return hash(sector) % 1000 if sector else 0

    def prepare_data(self):
        try:
            queues = Queue.query.all()
            if len(queues) < self.MIN_QUEUES:
                logger.warning(f"Filas insuficientes: {len(queues)}")
                return None

            self.tag_set = set(t.tag for q in queues for t in q.tags)
            data = []
            for queue in queues:
                tags = [t.tag for t in queue.tags]
                tag_vector = [1 if tag in tags else 0 for tag in self.tag_set]
                data.append({
                    'queue_id': queue.id,
                    'category_encoded': self.get_category_id(queue.category_id),
                    'sector_encoded': self.get_sector_id(queue.department.sector if queue.department else None),
                    'tag_vector': tag_vector
                })

            X = np.array([
                [d['category_encoded'], d['sector_encoded']] + d['tag_vector']
                for d in data
            ])
            self.queue_mapping = {d['queue_id']: i for i, d in enumerate(data)}
            return X
        except Exception as e:
            logger.error(f"Erro ao preparar dados de clustering: {e}")
            return None

    def train(self):
        try:
            X = self.prepare_data()
            if X is None:
                self.is_trained = False
                return

            self.kmeans.fit(X)
            self.is_trained = True
            joblib.dump((self.kmeans, self.queue_mapping, self.tag_set), self.MODEL_PATH)
            logger.info("Modelo de clustering treinado")
        except Exception as e:
            logger.error(f"Erro ao treinar modelo de clustering: {e}")
            self.is_trained = False

    def load_model(self):
        try:
            if os.path.exists(self.MODEL_PATH):
                self.kmeans, self.queue_mapping, self.tag_set = joblib.load(self.MODEL_PATH)
                self.is_trained = True
                logger.info("Modelo de clustering carregado")
        except Exception as e:
            logger.error(f"Erro ao carregar modelo de clustering: {e}")
            self.is_trained = False

    def get_alternatives(self, queue_id, n=3):
        try:
            if not self.is_trained or queue_id not in self.queue_mapping:
                self.load_model()
                if not self.is_trained:
                    return []

            queue_idx = self.queue_mapping[queue_id]
            cluster = self.kmeans.labels_[queue_idx]
            similar_queues = [
                qid for qid, idx in self.queue_mapping.items()
                if self.kmeans.labels_[idx] == cluster and qid != queue_id
            ]
            return similar_queues[:n]
        except Exception as e:
            logger.error(f"Erro ao obter alternativas para queue_id={queue_id}: {e}")
            return []

# Instâncias globais dos modelos
wait_time_predictor = WaitTimePredictor()
service_recommendation_predictor = ServiceRecommendationPredictor()
collaborative_model = CollaborativeFilteringModel()
demand_model = DemandForecastingModel()
clustering_model = ServiceClusteringModel()
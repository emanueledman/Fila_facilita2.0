import logging
import uuid
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import TruncatedSVD
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import cosine_similarity
try:
    from prophet import Prophet
except ImportError as e:
    logging.error(f"Prophet not available: {e}")
    Prophet = None
try:
    from sentence_transformers import SentenceTransformer
except ImportError as e:
    logging.error(f"sentence-transformers not available: {e}")
    SentenceTransformer = None
from sqlalchemy import and_, func
from datetime import datetime, timedelta
from app import db
from app.models import Queue, Ticket, Department, ServiceTag, UserPreference, QueueSchedule, Branch, Weekday, Institution, InstitutionService, ServiceCategory, UserBehavior, UserLocationFallback
from geopy.distance import geodesic
import joblib
import os
from holidays import country_holidays

logger = logging.getLogger(__name__)

class WaitTimePredictor:
    """Predictor for queue wait times with enhanced personalization."""
    MIN_SAMPLES = 5
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

    def is_holiday(self, date):
        holidays = country_holidays('AO')  # Angola holidays
        return 1 if date in holidays else 0

    def calculate_distance(self, user_lat, user_lon, branch):
        try:
            if not all(isinstance(x, (int, float)) for x in [user_lat, user_lon, branch.latitude, branch.longitude]):
                return 0
            return geodesic((user_lat, user_lon), (branch.latitude, branch.longitude)).kilometers
        except Exception as e:
            logger.error(f"Error calculating distance: {e}")
            return 0

    def get_user_preferred_hour(self, user_id):
        try:
            behaviors = UserBehavior.query.filter_by(user_id=user_id).all()
            if not behaviors:
                return None
            hours = [b.timestamp.hour for b in behaviors if b.timestamp]
            return np.mean(hours) if hours else None
        except Exception as e:
            logger.error(f"Error getting preferred hour for user_id={user_id}: {e}")
            return None

    def prepare_data(self, queue_id, days=MAX_DAYS, batch_size=1000):
        try:
            queue = Queue.query.get(queue_id)
            if not queue:
                logger.error(f"Queue not found: queue_id={queue_id}")
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
                    is_holiday = self.is_holiday(ticket.issued_at.date())
                    sector_encoded = self.get_sector_id(queue.department.sector if queue.department else None)
                    category_encoded = self.get_category_id(queue.service.category_id if queue.service else None)
                    user_preferred_hour = self.get_user_preferred_hour(ticket.user_id) if ticket.user_id else hour_of_day
                    data.append({
                        'position': position,
                        'active_tickets': queue.active_tickets,
                        'priority': ticket.priority or 0,
                        'hour_of_day': hour_of_day,
                        'num_counters': queue.num_counters or 1,
                        'daily_limit': queue.daily_limit or 100,
                        'sector_encoded': sector_encoded,
                        'category_encoded': category_encoded,
                        'is_holiday': is_holiday,
                        'user_preferred_hour': user_preferred_hour or hour_of_day,
                        'service_time': ticket.service_time
                    })

                offset += batch_size

            if len(data) < self.MIN_SAMPLES:
                similar_queues = Queue.query.filter(
                    Queue.service_id == queue.service_id,
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
                        is_holiday = self.is_holiday(ticket.issued_at.date())
                        sector_encoded = self.get_sector_id(similar_queue.department.sector if similar_queue.department else None)
                        category_encoded = self.get_category_id(similar_queue.service.category_id if similar_queue.service else None)
                        user_preferred_hour = self.get_user_preferred_hour(ticket.user_id) if ticket.user_id else hour_of_day
                        data.append({
                            'position': position,
                            'active_tickets': similar_queue.active_tickets,
                            'priority': ticket.priority or 0,
                            'hour_of_day': hour_of_day,
                            'num_counters': similar_queue.num_counters or 1,
                            'daily_limit': similar_queue.daily_limit or 100,
                            'sector_encoded': sector_encoded,
                            'category_encoded': category_encoded,
                            'is_holiday': is_holiday,
                            'user_preferred_hour': user_preferred_hour or hour_of_day,
                            'service_time': ticket.service_time
                        })

            if len(data) < self.MIN_SAMPLES:
                logger.warning(f"Insufficient data for queue_id={queue_id}: {len(data)} samples")
                return None, None

            df = pd.DataFrame(data)
            X = df[['position', 'active_tickets', 'priority', 'hour_of_day', 'num_counters', 'daily_limit', 'sector_encoded', 'category_encoded', 'is_holiday', 'user_preferred_hour']]
            y = df['service_time']
            logger.debug(f"Data prepared for queue_id={queue_id}: {len(data)} samples")
            return X, y
        except Exception as e:
            logger.error(f"Error preparing data for queue_id={queue_id}: {e}")
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
            logger.info(f"Model trained for queue_id={queue_id}")
        except Exception as e:
            logger.error(f"Error training model for queue_id={queue_id}: {e}")
            self.is_trained[queue_id] = False

    def load_model(self, queue_id):
        try:
            path = self.MODEL_PATH.format(queue_id=queue_id)
            if os.path.exists(path):
                model, scaler = joblib.load(path)
                self.models[queue_id] = model
                self.scalers[queue_id] = scaler
                self.is_trained[queue_id] = True
                logger.info(f"Model loaded for queue_id={queue_id}")
        except Exception as e:
            logger.error(f"Error loading model for queue_id={queue_id}: {e}")
            self.is_trained[queue_id] = False

    def predict(self, queue_id, position, active_tickets, priority, hour_of_day, user_id=None, user_lat=None, user_lon=None):
        try:
            if queue_id not in self.is_trained or not self.is_trained[queue_id]:
                self.load_model(queue_id)
                if not self.is_trained.get(queue_id, False):
                    logger.warning(f"Model not trained for queue_id={queue_id}, using fallback")
                    return self.FALLBACK_TIME

            queue = Queue.query.get(queue_id)
            if not queue:
                logger.error(f"Queue not found: queue_id={queue_id}")
                return self.FALLBACK_TIME

            user_preferred_hour = self.get_user_preferred_hour(user_id) if user_id else hour_of_day
            is_holiday = self.is_holiday(datetime.utcnow().date())
            features = np.array([[
                position,
                active_tickets,
                priority,
                hour_of_day,
                queue.num_counters or 1,
                queue.daily_limit or 100,
                self.get_sector_id(queue.department.sector if queue.department else None),
                self.get_category_id(queue.service.category_id if queue.service else None),
                is_holiday,
                user_preferred_hour or hour_of_day
            ]])
            logger.debug(f"Features for queue_id={queue_id}: {features.tolist()}")
            features_scaled = self.scalers[queue_id].transform(features)
            wait_time = self.models[queue_id].predict(features_scaled)[0]
            return max(0, round(wait_time, 1))
        except Exception as e:
            logger.error(f"Error predicting wait_time for queue_id={queue_id}: {e}")
            return self.FALLBACK_TIME

class ServiceRecommendationPredictor:
    """Predictor for queue quality scores with service similarity focus."""
    MIN_SAMPLES = 5
    MODEL_PATH = "service_recommendation_model.joblib"
    DEFAULT_SCORE = 0.5
    EMBEDDING_MODEL = 'paraphrase-MiniLM-L6-v2'

    def __init__(self):
        self.model = RandomForestRegressor(n_estimators=100, random_state=42)
        self.scaler = StandardScaler()
        self.is_trained = False
        self.sector_mapping = {}
        self.category_mapping = {}
        self.institution_type_mapping = {}
        self.next_sector_id = 1
        self.next_category_id = 1
        self.next_institution_type_id = 1
        self.embedding_model = SentenceTransformer(self.EMBEDDING_MODEL) if SentenceTransformer else None
        self.service_embeddings = {}

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

    def get_institution_type_id(self, institution_type_id):
        if not institution_type_id:
            return 0
        if institution_type_id not in self.institution_type_mapping:
            self.institution_type_mapping[institution_type_id] = self.next_institution_type_id
            self.next_institution_type_id += 1
        return self.institution_type_mapping[institution_type_id]

    def calculate_service_similarity(self, target_service_id, queue_service_id):
        try:
            if not target_service_id or not queue_service_id or target_service_id == queue_service_id:
                return 1.0
            target_service = InstitutionService.query.get(target_service_id)
            queue_service = InstitutionService.query.get(queue_service_id)
            if not target_service or not queue_service:
                return 0.0

            if self.embedding_model:
                if target_service_id not in self.service_embeddings:
                    text = f"{target_service.name} {target_service.description or ''} {' '.join(t.tag for t in ServiceTag.query.filter_by(queue_id=target_service_id))}"
                    self.service_embeddings[target_service_id] = self.embedding_model.encode(text)
                if queue_service_id not in self.service_embeddings:
                    text = f"{queue_service.name} {queue_service.description or ''} {' '.join(t.tag for t in ServiceTag.query.filter_by(queue_id=queue_service_id))}"
                    self.service_embeddings[queue_service_id] = self.embedding_model.encode(text)
                return cosine_similarity([self.service_embeddings[target_service_id]], [self.service_embeddings[queue_service_id]])[0][0]
            else:
                tags1 = set(t.tag for t in ServiceTag.query.filter_by(queue_id=target_service_id))
                tags2 = set(t.tag for t in ServiceTag.query.filter_by(queue_id=queue_service_id))
                intersection = len(tags1.intersection(tags2))
                return intersection / max(1, len(tags1.union(tags2)))
        except Exception as e:
            logger.error(f"Error calculating service similarity: {e}")
            return 0.0

    def get_user_service_preference_score(self, user_id, service_id):
        try:
            behaviors = UserBehavior.query.filter_by(user_id=user_id, service_id=service_id).all()
            return len(behaviors) / max(1, len(UserBehavior.query.filter_by(user_id=user_id).all())) if behaviors else 0.0
        except Exception as e:
            logger.error(f"Error calculating user service preference score for user_id={user_id}: {e}")
            return 0.0

    def prepare_data(self, user_id=None, target_service_id=None, batch_size=1000):
        try:
            data = []
            queues = Queue.query.join(InstitutionService).filter(InstitutionService.category_id == InstitutionService.query.get(target_service_id).category_id if target_service_id else True).all()
            user_prefs = UserPreference.query.filter_by(user_id=user_id).all() if user_id else []
            preferred_institutions = {pref.institution_id for pref in user_prefs if pref.institution_id}
            preferred_neighborhoods = {pref.neighborhood for pref in user_prefs if pref.neighborhood}
            preferred_institution_types = {pref.institution_type_id for pref in user_prefs if pref.institution_type_id}
            fallback = UserLocationFallback.query.filter_by(user_id=user_id).first() if user_id else None

            for queue in queues:
                branch = Branch.query.join(Department).filter(Department.id == queue.department_id).first()
                institution = Institution.query.get(branch.institution_id) if branch else None
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
                        s.weekday == datetime.utcnow().strftime('%A').lower()
                        and s.open_time <= datetime.utcnow().time() <= s.end_time
                        and not s.is_closed
                        for s in queue.schedules
                    ) else 0
                )
                service_similarity = self.calculate_service_similarity(target_service_id, queue.service_id) if target_service_id else 1.0
                predicted_demand = DemandForecastingModel().predict(queue.id, hours_ahead=1)
                user_service_preference = self.get_user_service_preference_score(user_id, queue.service_id) if user_id else 0.0
                is_preferred_neighborhood = 1 if (branch and branch.neighborhood in preferred_neighborhoods) or (fallback and branch and branch.neighborhood == fallback.neighborhood) else 0

                quality_score = (
                    0.3 * (availability / max(1, queue.daily_limit))
                    + 0.25 * (1 / (1 + avg_service_time / 30))
                    + 0.15 * (1 / (1 + predicted_demand / 10))
                    + 0.2 * service_similarity
                    + 0.1 * user_service_preference
                )
                quality_score = max(0, min(1, quality_score))

                data.append({
                    'avg_service_time': avg_service_time,
                    'availability': availability,
                    'sector_encoded': self.get_sector_id(queue.department.sector if queue.department else None),
                    'category_encoded': self.get_category_id(queue.service.category_id if queue.service else None),
                    'institution_type_encoded': self.get_institution_type_id(institution.institution_type_id if institution else None),
                    'is_open': is_open,
                    'service_similarity': service_similarity,
                    'predicted_demand': predicted_demand,
                    'user_service_preference': user_service_preference,
                    'is_preferred_institution': 1 if branch and branch.institution_id in preferred_institutions else 0,
                    'is_preferred_neighborhood': is_preferred_neighborhood,
                    'is_preferred_institution_type': 1 if institution and institution.institution_type_id in preferred_institution_types else 0,
                    'quality_score': quality_score
                })

            if len(data) < self.MIN_SAMPLES:
                logger.warning(f"Insufficient data: {len(data)} samples")
                return None, None

            df = pd.DataFrame(data)
            X = df[[
                'avg_service_time', 'availability', 'sector_encoded', 'category_encoded', 'institution_type_encoded',
                'is_open', 'service_similarity', 'predicted_demand', 'user_service_preference',
                'is_preferred_institution', 'is_preferred_neighborhood', 'is_preferred_institution_type'
            ]]
            y = df['quality_score']
            return X, y
        except Exception as e:
            logger.error(f"Error preparing data: {e}")
            return None, None

    def train(self, user_id=None, target_service_id=None):
        try:
            X, y = self.prepare_data(user_id, target_service_id)
            if X is None or y is None:
                self.is_trained = False
                return

            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled, y)
            self.is_trained = True
            joblib.dump((self.model, self.scaler), self.MODEL_PATH)
            logger.info("Recommendation model trained")
        except Exception as e:
            logger.error(f"Error training recommendation model: {e}")
            self.is_trained = False

    def load_model(self):
        try:
            if os.path.exists(self.MODEL_PATH):
                self.model, self.scaler = joblib.load(self.MODEL_PATH)
                self.is_trained = True
                logger.info("Recommendation model loaded")
        except Exception as e:
            logger.error(f"Error loading recommendation model: {e}")
            self.is_trained = False

    def predict(self, queue, user_id=None, user_lat=None, user_lon=None, target_service_id=None):
        try:
            if not self.is_trained:
                self.load_model()
                if not self.is_trained:
                    logger.warning("Recommendation model not trained, using default")
                    return self.DEFAULT_SCORE

            branch = Branch.query.join(Department).filter(Department.id == queue.department_id).first()
            institution = Institution.query.get(branch.institution_id) if branch else None
            tickets = Ticket.query.filter(
                Ticket.queue_id == queue.id,
                Ticket.status == 'Atendido',
                Ticket.service_time.isnot(None)
            ).all()
            avg_service_time = np.mean([t.service_time for t in tickets]) if tickets else 30
            availability = max(0, queue.daily_limit - queue.active_tickets)
            is_open = (
                1 if any(
                    s.weekday == datetime.utcnow().strftime('%A').lower()
                    and s.open_time <= datetime.utcnow().time() <= s.end_time
                    and not s.is_closed
                    for s in queue.schedules
                ) else 0
            )
            service_similarity = self.calculate_service_similarity(target_service_id, queue.service_id) if target_service_id else 1.0
            predicted_demand = DemandForecastingModel().predict(queue.id, hours_ahead=1)
            user_service_preference = self.get_user_service_preference_score(user_id, queue.service_id) if user_id else 0.0
            user_prefs = UserPreference.query.filter_by(user_id=user_id).all() if user_id else []
            preferred_institutions = {pref.institution_id for pref in user_prefs if pref.institution_id}
            preferred_neighborhoods = {pref.neighborhood for pref in user_prefs if pref.neighborhood}
            preferred_institution_types = {pref.institution_type_id for pref in user_prefs if pref.institution_type_id}
            fallback = UserLocationFallback.query.filter_by(user_id=user_id).first() if user_id else None
            is_preferred_neighborhood = 1 if (branch and branch.neighborhood in preferred_neighborhoods) or (fallback and branch and branch.neighborhood == fallback.neighborhood) else 0

            features = np.array([[
                avg_service_time,
                availability,
                self.get_sector_id(queue.department.sector if queue.department else None),
                self.get_category_id(queue.service.category_id if queue.service else None),
                self.get_institution_type_id(institution.institution_type_id if institution else None),
                is_open,
                service_similarity,
                predicted_demand,
                user_service_preference,
                1 if branch and branch.institution_id in preferred_institutions else 0,
                is_preferred_neighborhood,
                1 if institution and institution.institution_type_id in preferred_institution_types else 0
            ]])
            features_scaled = self.scaler.transform(features)
            score = self.model.predict(features_scaled)[0]
            return max(0, min(1, round(score, 2)))
        except Exception as e:
            logger.error(f"Error predicting quality_score for queue_id={queue.id}: {e}")
            return self.DEFAULT_SCORE

class CollaborativeFilteringModel:
    """Collaborative filtering model for service-based recommendations."""
    MODEL_PATH = "collaborative_model.joblib"
    MIN_INTERACTIONS = 3

    def __init__(self):
        self.svd = None
        self.user_mapping = {}
        self.queue_mapping = {}
        self.is_trained = False

    def load_model(self):
        try:
            if os.path.exists(self.MODEL_PATH):
                self.svd, self.user_mapping, self.queue_mapping = joblib.load(self.MODEL_PATH)
                self.is_trained = True
                logger.info("Collaborative model loaded")
        except Exception as e:
            logger.error(f"Error loading collaborative model: {e}")

    def save_model(self):
        try:
            joblib.dump((self.svd, self.user_mapping, self.queue_mapping), self.MODEL_PATH)
            logger.info("Collaborative model saved")
        except Exception as e:
            logger.error(f"Error saving collaborative model: {e}")

    def prepare_data(self, target_service_id=None):
        try:
            target_service = InstitutionService.query.get(target_service_id) if target_service_id else None
            target_category = target_service.category_id if target_service else None
            tickets = Ticket.query.join(Queue).filter(
                Ticket.user_id.isnot(None),
                Queue.service_id.in_(
                    db.session.query(InstitutionService.id).filter(InstitutionService.category_id == target_category)
                ) if target_category else True
            ).all()
            user_queue_counts = {}
            for ticket in tickets:
                key = (ticket.user_id, ticket.queue_id)
                user_queue_counts[key] = user_queue_counts.get(key, 0) + 1

            if len(user_queue_counts) < self.MIN_INTERACTIONS:
                logger.warning(f"Insufficient interactions: {len(user_queue_counts)}")
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

            n_features = len(queues)
            n_components = min(50, n_features - 1) if n_features > 1 else 1
            self.svd = TruncatedSVD(n_components=n_components, random_state=42)
            interaction_matrix = csr_matrix((data, (rows, cols)), shape=(len(users), n_features))
            return interaction_matrix
        except Exception as e:
            logger.error(f"Error preparing collaborative data: {e}")
            return None

    def train(self, target_service_id=None):
        try:
            interaction_matrix = self.prepare_data(target_service_id)
            if interaction_matrix is None:
                self.is_trained = False
                return

            self.svd.fit(interaction_matrix)
            self.is_trained = True
            self.save_model()
            logger.info("Collaborative model trained")
        except Exception as e:
            logger.error(f"Error training collaborative model: {e}")
            self.is_trained = False

    def predict(self, user_id, queue_ids, target_service_id=None):
        try:
            if not self.is_trained or user_id not in self.user_mapping:
                prefs = UserPreference.query.filter_by(user_id=user_id).all() if user_id else []
                default_score = max([pref.preference_score / 100 for pref in prefs if pref.preference_score] or [0.5])
                return {q: default_score for q in queue_ids}

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
            logger.error(f"Error predicting collaboratively for user_id={user_id}: {e}")
            return {q: 0.5 for q in queue_ids}

class DemandForecastingModel:
    """Model for predicting future queue demand with lightweight fallback."""
    MODEL_PATH = "demand_model_{queue_id}.joblib"
    MIN_DAYS = 3
    FALLBACK_DEMAND = 10

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
            df = df.groupby(pd.Grouper(key='ds', freq='h')).sum().reset_index()
            return df
        except Exception as e:
            logger.error(f"Error preparing demand data for queue_id={queue_id}: {e}")
            return None

    def train(self, queue_id):
        if self.use_prophet:
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
                logger.info(f"Demand model trained for queue_id={queue_id}")
            except Exception as e:
                logger.error(f"Error training demand model for queue_id={queue_id}: {e}")
                self.is_trained[queue_id] = False
        else:
            self.is_trained[queue_id] = False

    def load_model(self, queue_id):
        if not self.use_prophet:
            self.is_trained[queue_id] = False
            return
        try:
            path = self.get_model_path(queue_id)
            if os.path.exists(path):
                self.models[queue_id] = joblib.load(path)
                self.is_trained[queue_id] = True
                logger.info(f"Demand model loaded for queue_id={queue_id}")
        except Exception as e:
            logger.error(f"Error loading demand model for queue_id={queue_id}: {e}")
            self.is_trained[queue_id] = False

    def predict(self, queue_id, hours_ahead=1):
        if self.use_prophet and queue_id in self.is_trained and self.is_trained[queue_id]:
            try:
                model = self.models[queue_id]
                future = model.make_future_dataframe(periods=hours_ahead, freq='h')
                forecast = model.predict(future)
                predicted_demand = forecast.tail(1)['yhat'].iloc[0]
                logger.debug(f"Demand predicted for queue_id={queue_id}: {predicted_demand}")
                return max(0, round(predicted_demand, 1))
            except Exception as e:
                logger.error(f"Error predicting demand for queue_id={queue_id}: {e}")
        return self._fallback_demand(queue_id)

    def _fallback_demand(self, queue_id):
        try:
            queue = Queue.query.get(queue_id)
            if not queue or not queue.service:
                return self.FALLBACK_DEMAND

            start_date = datetime.utcnow() - timedelta(days=self.MIN_DAYS)
            similar_queues = Queue.query.filter(
                Queue.service_id == queue.service_id,
                Queue.id != queue_id
            ).all()
            ticket_counts = []
            for sim_queue in similar_queues:
                tickets = Ticket.query.filter(
                    Ticket.queue_id == sim_queue.id,
                    Ticket.issued_at >= start_date
                ).count()
                ticket_counts.append(tickets / self.MIN_DAYS)
            return round(np.mean(ticket_counts) if ticket_counts else self.FALLBACK_DEMAND, 1)
        except Exception as e:
            logger.error(f"Error in demand fallback for queue_id={queue_id}: {e}")
            return self.FALLBACK_DEMAND

class ServiceClusteringModel:
    """Model for clustering similar services and suggesting alternatives."""
    MODEL_PATH = "clustering_model.joblib"
    MIN_QUEUES = 5
    EMBEDDING_MODEL = 'paraphrase-MiniLM-L6-v2'

    def __init__(self):
        self.kmeans = KMeans(n_clusters=10, random_state=42)
        self.queue_mapping = {}
        self.is_trained = False
        self.tag_set = set()
        self.institution_type_mapping = {}
        self.next_institution_type_id = 1
        self.embedding_model = SentenceTransformer(self.EMBEDDING_MODEL) if SentenceTransformer else None
        self.service_embeddings = {}

    def get_category_id(self, category_id):
        return category_id if category_id else 0

    def get_sector_id(self, sector):
        return hash(sector) % 1000 if sector else 0

    def get_institution_type_id(self, institution_type_id):
        if not institution_type_id:
            return 0
        if institution_type_id not in self.institution_type_mapping:
            self.institution_type_mapping[institution_type_id] = self.next_institution_type_id
            self.next_institution_type_id += 1
        return self.institution_type_mapping[institution_type_id]

    def get_service_embedding(self, service_id):
        try:
            if service_id not in self.service_embeddings:
                service = InstitutionService.query.get(service_id)
                if not service:
                    return np.zeros(384)  # Default for paraphrase-MiniLM-L6-v2
                text = f"{service.name} {service.description or ''} {' '.join(t.tag for t in ServiceTag.query.filter_by(queue_id=service_id))}"
                self.service_embeddings[service_id] = self.embedding_model.encode(text) if self.embedding_model else np.zeros(384)
            return self.service_embeddings[service_id]
        except Exception as e:
            logger.error(f"Error getting service embedding for service_id={service_id}: {e}")
            return np.zeros(384)

    def prepare_data(self, target_service_id=None):
        try:
            target_service = InstitutionService.query.get(target_service_id) if target_service_id else None
            target_category = target_service.category_id if target_service else None
            queues = Queue.query.join(InstitutionService).filter(
                InstitutionService.category_id == target_category if target_category else True
            ).all()
            if len(queues) < self.MIN_QUEUES:
                logger.warning(f"Insufficient queues: {len(queues)}")
                return None

            self.tag_set = set(t.tag for q in queues for t in q.tags)
            data = []
            for queue in queues:
                branch = Branch.query.join(Department).filter(Department.id == queue.department_id).first()
                institution = Institution.query.get(branch.institution_id) if branch else None
                service_embedding = self.get_service_embedding(queue.service_id)
                data.append({
                    'queue_id': queue.id,
                    'category_encoded': float(self.get_category_id(queue.service.category_id if queue.service else None)),
                    'sector_encoded': float(self.get_sector_id(queue.department.sector if queue.department else None)),
                    'institution_type_encoded': float(self.get_institution_type_id(institution.institution_type_id if institution else None)),
                    'service_embedding': service_embedding
                })

            X = np.array([
                [d['category_encoded'], d['sector_encoded'], d['institution_type_encoded']] + d['service_embedding'].tolist()
                for d in data
            ], dtype=float)
            self.queue_mapping = {d['queue_id']: i for i, d in enumerate(data)}
            return X
        except Exception as e:
            logger.error(f"Error preparing clustering data: {e}")
            return None

    def train(self, target_service_id=None):
        try:
            X = self.prepare_data(target_service_id)
            if X is None:
                self.is_trained = False
                return

            n_clusters = min(10, len(X))
            self.kmeans = KMeans(n_clusters=n_clusters, random_state=42)
            self.kmeans.fit(X)
            self.is_trained = True
            joblib.dump((self.kmeans, self.queue_mapping, self.tag_set), self.MODEL_PATH)
            logger.info("Clustering model trained")
        except Exception as e:
            logger.error(f"Error training clustering model: {e}")
            self.is_trained = False

    def load_model(self):
        try:
            if os.path.exists(self.MODEL_PATH):
                self.kmeans, self.queue_mapping, self.tag_set = joblib.load(self.MODEL_PATH)
                self.is_trained = True
                logger.info("Clustering model loaded")
        except Exception as e:
            logger.error(f"Error loading clustering model: {e}")
            self.is_trained = False

    def get_alternatives(self, queue_id, user_id=None, n=3):
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
            if user_id:
                fallback = UserLocationFallback.query.filter_by(user_id=user_id).first()
                if fallback:
                    similar_queues = sorted(
                        similar_queues,
                        key=lambda qid: 1 if Branch.query.join(Department).join(Queue).filter(Queue.id == qid, Branch.neighborhood == fallback.neighborhood).first() else 0,
                        reverse=True
                    )
            return similar_queues[:n]
        except Exception as e:
            logger.error(f"Error getting alternatives for queue_id={queue_id}: {e}")
            return []

# Global model instances
wait_time_predictor = WaitTimePredictor()
service_recommendation_predictor = ServiceRecommendationPredictor()
collaborative_model = CollaborativeFilteringModel()
demand_model = DemandForecastingModel()
clustering_model = ServiceClusteringModel()
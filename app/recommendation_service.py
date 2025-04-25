import logging
import json
import re
import uuid
import numpy as np
from sqlalchemy import and_, func, or_
from datetime import datetime
from .models import Queue, QueueSchedule, Ticket, Department, Institution, User, Weekday, Branch, ServiceCategory, ServiceTag, UserPreference, InstitutionType
from .ml_models import wait_time_predictor, service_recommendation_predictor, collaborative_model, demand_model, clustering_model
from . import db, redis_client
from geopy.distance import geodesic

logger = logging.getLogger(__name__)

class RecommendationService:
    """Serviço para recomendações personalizadas de filas e serviços."""

    @staticmethod
    def calculate_distance(user_lat, user_lon, branch):
        """Calcula a distância entre o usuário e a filial em quilômetros."""
        try:
            if not all(isinstance(x, (int, float)) for x in [user_lat, user_lon, branch.latitude, branch.longitude]):
                logger.warning(f"Coordenadas inválidas")
                return None
            user_location = (float(user_lat), float(user_lon))
            branch_location = (float(branch.latitude), float(branch.longitude))
            distance = geodesic(user_location, branch_location).kilometers
            return round(distance, 2)
        except Exception as e:
            logger.error(f"Erro ao calcular distância: {e}")
            return None

    @staticmethod
    def is_location_valid(user_id, user_lat, user_lon):
        """Verifica se a localização do usuário é válida e recente."""
        if not user_id or not user_lat or not user_lon:
            return False
        user = User.query.get(user_id)
        if not user or not user.last_location_update:
            return False
        time_diff = (datetime.utcnow() - user.last_location_update).total_seconds()
        return time_diff < 600  # 10 minutos

    @staticmethod
    def invalidate_cache(queue_id):
        """Invalida o cache de buscas relacionadas a uma fila."""
        try:
            keys = redis_client.keys(f'services:*:{queue_id}:*')
            if keys:
                redis_client.delete(*keys)
                logger.debug(f"Cache invalidado para queue_id={queue_id}")
        except Exception as e:
            logger.error(f"Erro ao invalidar cache: {e}")

    @staticmethod
    def get_filter_options(institution_id=None):
        """Retorna opções para filtros dinâmicos."""
        try:
            query = db.session.query
            if institution_id:
                query = query.filter(Institution.id == institution_id)
            categories = ServiceCategory.query.all()
            tags = ServiceTag.query.distinct(ServiceTag.tag).all()
            neighborhoods = Branch.query.distinct(Branch.neighborhood).all()
            return {
                'categories': [{'id': c.id, 'name': c.name} for c in categories],
                'tags': [t.tag for t in tags],
                'neighborhoods': [n.neighborhood for n in neighborhoods if n.neighborhood]
            }
        except Exception as e:
            logger.error(f"Erro ao obter opções de filtro: {e}")
            raise

    @staticmethod
    def search_services_structured(
        institution,
        neighborhood,
        service,
        max_wait_time,
        user_id=None,
        user_lat=None,
        user_lon=None,
        max_distance_km=10.0,
        page=1,
        per_page=10,
        sort_by='score'
    ):
        """Busca serviços com base em instituição, bairro, serviço e tempo de espera."""
        try:
            now = datetime.utcnow()
            results = []

            # Validação de entradas obrigatórias
            if not institution or not isinstance(institution, str) or not institution.strip():
                raise ValueError("Instituição é obrigatória")
            if not service or not isinstance(service, str) or not service.strip():
                raise ValueError("Serviço é obrigatório")
            if not isinstance(max_wait_time, (int, float)) or max_wait_time <= 0:
                raise ValueError("Tempo de espera máximo deve ser positivo")
            if not isinstance(neighborhood, str) or not neighborhood.strip():
                neighborhood = None
            if user_id and not isinstance(user_id, str):
                user_id = None
            if user_lat and user_lon and not RecommendationService.is_location_valid(user_id, user_lat, user_lon):
                logger.warning(f"Localização antiga ou inválida para user_id={user_id}")
                user_lat, user_lon = None, None

            # Construir consulta base
            query_base = Queue.query.join(Department).join(Branch).join(Institution).join(InstitutionType)

            # Filtro por instituição (nome ou ID)
            query_base = query_base.filter(
                or_(
                    Institution.id == institution,
                    Institution.name.ilike(f'%{institution}%')
                )
            )

            # Filtro por bairro
            if neighborhood:
                query_base = query_base.filter(Branch.neighborhood.ilike(f'%{neighborhood}%'))

            # Filtro por serviço (busca textual)
            if service:
                search_terms = re.sub(r'[^\w\sÀ-ÿ]', '', service.lower()).split()
                if search_terms:
                    search_query = ' & '.join(search_terms)
                    query_base = query_base.filter(
                        or_(
                            func.to_tsvector('portuguese', func.concat(
                                Queue.service, ' ', Department.sector
                            )).op('@@')(func.to_tsquery('portuguese', search_query)),
                            Queue.id.in_(
                                db.session.query(ServiceTag.queue_id).filter(
                                    ServiceTag.tag.ilike(f'%{service.lower()}%')
                                )
                            )
                        )
                    )

            # Filtrar por filas abertas
            query_base = query_base.join(QueueSchedule).filter(
                and_(
                    QueueSchedule.weekday == getattr(Weekday, now.strftime('%A').upper(), None),
                    QueueSchedule.is_closed == False,
                    QueueSchedule.open_time <= now.time(),
                    QueueSchedule.end_time >= now.time(),
                    Queue.active_tickets < Queue.daily_limit
                )
            )

            # Obter preferências do usuário
            user_prefs = UserPreference.query.filter_by(user_id=user_id).all() if user_id else []
            preferred_institutions = {pref.institution_id for pref in user_prefs if pref.institution_id}
            preferred_categories = {pref.service_category_id for pref in user_prefs if pref.service_category_id}
            preferred_neighborhoods = {pref.neighborhood for pref in user_prefs if pref.neighborhood}

            # Contar total de resultados
            total = query_base.count()

            # Aplicar ordenação inicial
            if service and search_terms:
                query_base = query_base.order_by(
                    func.ts_rank(
                        func.to_tsvector('portuguese', func.concat(
                            Queue.service, ' ', Department.sector
                        )),
                        func.to_tsquery('portuguese', search_query)
                    ).desc()
                )
            else:
                query_base = query_base.order_by(Queue.active_tickets.asc())

            # Paginação
            queues = query_base.offset((page - 1) * per_page).limit(per_page).all()

            # Obter scores colaborativos
            collaborative_scores = collaborative_model.predict(user_id, [q.id for q in queues]) if user_id else {q.id: 0.5 for q in queues}

            for queue in queues:
                branch = queue.department.branch
                institution = branch.institution
                institution_type = institution.type

                if not all([branch, institution, queue.department, institution_type]):
                    logger.warning(f"Dados incompletos para queue_id={queue.id}")
                    continue

                # Calcular distância
                distance = None
                if user_lat and user_lon and branch.latitude and branch.longitude:
                    distance = RecommendationService.calculate_distance(user_lat, user_lon, branch)
                    if distance and distance > max_distance_km:
                        continue

                # Calcular tempo de espera
                wait_time = wait_time_predictor.predict(
                    queue_id=queue.id,
                    position=queue.active_tickets + 1,
                    active_tickets=queue.active_tickets,
                    priority=0,
                    hour_of_day=now.hour,
                    user_lat=user_lat,
                    user_lon=user_lon
                )
                if isinstance(wait_time, (int, float)) and wait_time > max_wait_time:
                    continue

                # Previsão de demanda
                predicted_demand = demand_model.predict(queue.id, hours_ahead=1)

                # Pontuação de qualidade
                quality_score = service_recommendation_predictor.predict(queue, user_id, user_lat, user_lon)

                # Velocidade da fila
                speed_label = "Desconhecida"
                tickets = Ticket.query.filter_by(queue_id=queue.id, status='Atendido').all()
                service_times = [t.service_time for t in tickets if t.service_time is not None and t.service_time > 0]
                avg_service_time = np.mean(service_times) if service_times else 30
                if avg_service_time <= 5:
                    speed_label = "Rápida"
                elif avg_service_time <= 15:
                    speed_label = "Moderada"
                else:
                    speed_label = "Lenta"

                # Explicação da recomendação
                explanation = []
                if institution.id in preferred_institutions:
                    explanation.append(f"Você prefere {institution.name}")
                if distance is not None:
                    explanation.append(f"Filial a {distance:.2f} km")
                if isinstance(wait_time, (int, float)):
                    explanation.append(f"Espera de {int(wait_time)} min")
                if quality_score > 0.8:
                    explanation.append("Alta qualidade")
                if speed_label == "Rápida":
                    explanation.append("Atendimento rápido")

                # Sugestões de alternativas (restritas à mesma instituição)
                alternatives = clustering_model.get_alternatives(queue.id, n=3)
                alternative_queues = Queue.query.filter(
                    Queue.id.in_(alternatives),
                    Branch.institution_id == institution.id
                ).join(Department).join(Branch).all()
                alternatives_data = []
                for alt_queue in alternative_queues:
                    alt_wait_time = wait_time_predictor.predict(
                        queue_id=alt_queue.id,
                        position=alt_queue.active_tickets + 1,
                        active_tickets=alt_queue.active_tickets,
                        priority=0,
                        hour_of_day=now.hour,
                        user_lat=user_lat,
                        user_lon=user_lon
                    )
                    alt_distance = RecommendationService.calculate_distance(user_lat, user_lon, alt_queue.department.branch) if user_lat and user_lon else None
                    alternatives_data.append({
                        'queue_id': alt_queue.id,
                        'service': alt_queue.service or "Desconhecido",
                        'branch': alt_queue.department.branch.name or "Desconhecida",
                        'wait_time': f"{int(alt_wait_time)} minutos" if isinstance(alt_wait_time, (int, float)) else 'Aguardando início',
                        'distance': float(alt_distance) if alt_distance is not None else 'Desconhecida',
                        'quality_score': service_recommendation_predictor.predict(alt_queue, user_id, user_lat, user_lon)
                    })

                # Horário de funcionamento
                schedule = QueueSchedule.query.filter_by(queue_id=queue.id, weekday=getattr(Weekday, now.strftime('%A').upper(), None)).first()
                open_time = schedule.open_time.strftime('%H:%M') if schedule and schedule.open_time else None
                end_time = schedule.end_time.strftime('%H:%M') if schedule and schedule.end_time else None

                # Pontuação composta
                composite_score = 0.0
                if service and search_terms:
                    rank = db.session.query(
                        func.ts_rank(
                            func.to_tsvector('portuguese', func.concat(
                                Queue.service, ' ', Department.sector
                            )),
                            func.to_tsquery('portuguese', search_query)
                        )
                    ).filter(Queue.id == queue.id).scalar() or 0.0
                    composite_score += rank * 0.3
                if distance is not None:
                    composite_score += (1 / (1 + distance)) * 0.25
                composite_score += quality_score * 0.2
                composite_score += collaborative_scores.get(queue.id, 0.5) * 0.15
                composite_score += (1 / (1 + predicted_demand / 10)) * 0.1
                if isinstance(wait_time, (int, float)):
                    composite_score += (1 / (1 + wait_time / 10)) * 0.1
                if user_prefs:
                    if institution.id in preferred_institutions:
                        composite_score += 0.2
                    if queue.category_id in preferred_categories:
                        composite_score += 0.1
                    if branch.neighborhood in preferred_neighborhoods:
                        composite_score += 0.05

                # Nível de recomendação para ícones no mapa
                recommendation_level = 'low'
                if composite_score > 0.8:
                    recommendation_level = 'high'
                elif composite_score > 0.5:
                    recommendation_level = 'medium'

                results.append({
                    'institution': {
                        'id': institution.id,
                        'name': institution.name or "Desconhecida",
                        'type': {
                            'id': institution_type.id,
                            'name': institution_type.name or "Desconhecido"
                        }
                    },
                    'branch': {
                        'id': branch.id,
                        'name': branch.name or "Desconhecida",
                        'location': branch.location or "Desconhecida",
                        'neighborhood': branch.neighborhood or "Desconhecido",
                        'latitude': float(branch.latitude) if branch.latitude else None,
                        'longitude': float(branch.longitude) if branch.longitude else None
                    },
                    'queue': {
                        'id': queue.id,
                        'service': queue.service or "Desconhecido",
                        'category_id': queue.category_id,
                        'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else 'Aguardando início',
                        'distance': float(distance) if distance is not None else 'Desconhecida',
                        'active_tickets': queue.active_tickets or 0,
                        'daily_limit': queue.daily_limit or 100,
                        'open_time': open_time,
                        'end_time': end_time,
                        'quality_score': float(quality_score),
                        'speed_label': speed_label,
                        'alternatives': alternatives_data,
                        'explanation': ", ".join(explanation) or f"Filial de {institution.name} recomendada",
                        'recommendation_level': recommendation_level
                    },
                    'score': float(composite_score)
                })

            # Ordenar resultados
            if sort_by == 'wait_time':
                results.sort(key=lambda x: float(x['queue']['wait_time'].split()[0]) if x['queue']['wait_time'] != 'Aguardando início' else float('inf'))
            elif sort_by == 'distance':
                results.sort(key=lambda x: x['queue']['distance'] if x['queue']['distance'] != 'Desconhecida' else float('inf'))
            else:
                results.sort(key=lambda x: x['score'], reverse=True)

            # Sugestões baseadas na instituição
            suggestions = []
            if results:
                target_institution_id = results[0]['institution']['id']
                related_queues = Queue.query.filter(
                    Queue.id != results[0]['queue']['id'],
                    Branch.institution_id == target_institution_id
                ).join(Department).join(Branch).limit(3).all()
                for q in related_queues:
                    if q.department and q.department.branch and q.department.branch.institution:
                        wait_time = wait_time_predictor.predict(
                            queue_id=q.id,
                            position=q.active_tickets + 1,
                            active_tickets=q.active_tickets,
                            priority=0,
                            hour_of_day=now.hour
                        )
                        distance = RecommendationService.calculate_distance(user_lat, user_lon, q.department.branch) if user_lat and user_lon else None
                        suggestions.append({
                            'queue_id': q.id,
                            'institution': q.department.branch.institution.name or "Desconhecida",
                            'branch': q.department.branch.name or "Desconhecida",
                            'service': q.service or "Desconhecido",
                            'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else 'Aguardando início',
                            'distance': float(distance) if distance is not None else 'Desconhecida'
                        })

            # Opções de filtro para dropdowns
            filter_options = RecommendationService.get_filter_options()

            result = {
                'services': results,
                'total': total,
                'page': int(page),
                'per_page': int(per_page),
                'total_pages': (total + per_page - 1) // per_page,
                'suggestions': suggestions,
                'filter_options': filter_options,
                'message': (f"Nenhuma fila encontrada para {institution}" if not results else "Recomendações personalizadas!")
            }

            # Cachear resultados
            cache_key = f'services_structured:{institution}:{neighborhood}:{service}:{max_wait_time}:{user_id}:{sort_by}'
            redis_client.setex(cache_key, 60, json.dumps(result, default=str))

            logger.info(f"Busca estruturada: {total} resultados, {len(results)} retornados")
            return result
        except Exception as e:
            logger.error(f"Erro ao buscar serviços estruturados: {str(e)}")
            raise

    # Mantendo o método original para compatibilidade
    @staticmethod
    def search_services(
        query,
        user_id=None,
        user_lat=None,
        user_lon=None,
        institution_name=None,
        neighborhood=None,
        branch_id=None,
        institution_id=None,
        institution_type_id=None,
        category_id=None,
        tags=None,
        max_wait_time=None,
        min_quality_score=None,
        sort_by='score',
        max_results=5,
        max_distance_km=10.0,
        page=1,
        per_page=10
    ):
        try:
            now = datetime.utcnow()
            results = []

            if not query or not isinstance(query, str) or not query.strip():
                query = ""
            if not isinstance(user_id, str):
                user_id = None
            if not all(isinstance(x, (int, float)) for x in [user_lat, user_lon] if x is not None):
                user_lat, user_lon = None, None
            if not isinstance(institution_id, str):
                institution_id = None
            if not isinstance(institution_type_id, str):
                institution_type_id = None
            if not isinstance(category_id, str):
                category_id = None
            if tags and (not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)):
                tags = []
            if user_lat and user_lon and user_id and not RecommendationService.is_location_valid(user_id, user_lat, user_lon):
                logger.warning(f"Localização antiga para user_id={user_id}")
                user_lat, user_lon = None, None

            if not institution_id and user_id:
                recent_ticket = Ticket.query.filter_by(user_id=user_id).join(Queue).join(Department).join(Branch).order_by(Ticket.issued_at.desc()).first()
                if recent_ticket:
                    institution_id = recent_ticket.queue.department.branch.institution_id
                    logger.debug(f"Inferiu institution_id={institution_id} do histórico do usuário {user_id}")

            query_base = Queue.query.join(Department).join(Branch).join(Institution).join(InstitutionType)

            if institution_id:
                query_base = query_base.filter(Institution.id == institution_id)
            if institution_name:
                query_base = query_base.filter(Institution.name.ilike(f'%{institution_name}%'))
            if institution_type_id:
                query_base = query_base.filter(Institution.institution_type_id == institution_type_id)
            if neighborhood:
                query_base = query_base.filter(Branch.neighborhood.ilike(f'%{neighborhood}%'))
            if branch_id:
                query_base = query_base.filter(Branch.id == branch_id)
            if category_id:
                query_base = query_base.filter(Queue.category_id == category_id)
            if tags:
                query_base = query_base.join(ServiceTag).filter(ServiceTag.tag.in_([tag.strip() for tag in tags]))

            if query:
                search_terms = re.sub(r'[^\w\sÀ-ÿ]', '', query.lower()).split()
                if search_terms:
                    search_query = ' & '.join(search_terms)
                    query_base = query_base.filter(
                        or_(
                            func.to_tsvector('portuguese', func.concat(
                                Queue.service, ' ', Department.sector, ' ', Institution.name, ' ', InstitutionType.name
                            )).op('@@')(func.to_tsquery('portuguese', search_query)),
                            Queue.id.in_(
                                db.session.query(ServiceTag.queue_id).filter(
                                    ServiceTag.tag.ilike(f'%{query.lower()}%')
                                )
                            )
                        )
                    )

            query_base = query_base.join(QueueSchedule).filter(
                and_(
                    QueueSchedule.weekday == getattr(Weekday, now.strftime('%A').upper(), None),
                    QueueSchedule.is_closed == False,
                    QueueSchedule.open_time <= now.time(),
                    QueueSchedule.end_time >= now.time(),
                    Queue.active_tickets < Queue.daily_limit
                )
            )

            user_prefs = UserPreference.query.filter_by(user_id=user_id).all() if user_id else []
            preferred_institutions = {pref.institution_id for pref in user_prefs if pref.institution_id}
            preferred_categories = {pref.service_category_id for pref in user_prefs if pref.service_category_id}
            preferred_neighborhoods = {pref.neighborhood for pref in user_prefs if pref.neighborhood}
            preferred_institution_types = {pref.institution_type_id for pref in user_prefs if pref.institution_type_id}

            total = query_base.count()

            if query and search_terms:
                search_query = ' & '.join(search_terms)
                query_base = query_base.order_by(
                    func.ts_rank(
                        func.to_tsvector('portuguese', func.concat(
                            Queue.service, ' ', Department.sector, ' ', Institution.name, ' ', InstitutionType.name
                        )),
                        func.to_tsquery('portuguese', search_query)
                    ).desc()
                )
            else:
                query_base = query_base.order_by(Queue.active_tickets.asc())

            queues = query_base.offset((page - 1) * per_page).limit(per_page).all()

            collaborative_scores = collaborative_model.predict(user_id, [q.id for q in queues]) if user_id else {q.id: 0.5 for q in queues}

            for queue in queues:
                branch = queue.department.branch
                institution = branch.institution
                institution_type = institution.type

                if not all([branch, institution, queue.department, institution_type]):
                    logger.warning(f"Dados incompletos para queue_id={queue.id}")
                    continue

                distance = None
                if user_lat and user_lon and branch.latitude and branch.longitude:
                    distance = RecommendationService.calculate_distance(user_lat, user_lon, branch)
                    if distance and distance > max_distance_km:
                        continue

                wait_time = wait_time_predictor.predict(
                    queue_id=queue.id,
                    position=queue.active_tickets + 1,
                    active_tickets=queue.active_tickets,
                    priority=0,
                    hour_of_day=now.hour,
                    user_lat=user_lat,
                    user_lon=user_lon
                )
                if max_wait_time and isinstance(wait_time, (int, float)) and wait_time > max_wait_time:
                    continue

                predicted_demand = demand_model.predict(queue.id, hours_ahead=1)

                quality_score = service_recommendation_predictor.predict(queue, user_id, user_lat, user_lon)
                if min_quality_score and quality_score < min_quality_score:
                    continue

                speed_label = "Desconhecida"
                tickets = Ticket.query.filter_by(queue_id=queue.id, status='Atendido').all()
                service_times = [t.service_time for t in tickets if t.service_time is not None and t.service_time > 0]
                avg_service_time = np.mean(service_times) if service_times else 30
                if avg_service_time <= 5:
                    speed_label = "Rápida"
                elif avg_service_time <= 15:
                    speed_label = "Moderada"
                else:
                    speed_label = "Lenta"

                explanation = []
                if institution.id in preferred_institutions:
                    explanation.append(f"Você prefere {institution.name}")
                if distance is not None:
                    explanation.append(f"Filial a {distance:.2f} km")
                if isinstance(wait_time, (int, float)):
                    explanation.append(f"Espera de {int(wait_time)} min")
                if quality_score > 0.8:
                    explanation.append("Alta qualidade")
                if speed_label == "Rápida":
                    explanation.append("Atendimento rápido")

                alternatives = clustering_model.get_alternatives(queue.id, n=3)
                alternative_queues = Queue.query.filter(
                    Queue.id.in_(alternatives),
                    Branch.institution_id == institution.id
                ).join(Department).join(Branch).all()
                alternatives_data = []
                for alt_queue in alternative_queues:
                    alt_wait_time = wait_time_predictor.predict(
                        queue_id=alt_queue.id,
                        position=alt_queue.active_tickets + 1,
                        active_tickets=alt_queue.active_tickets,
                        priority=0,
                        hour_of_day=now.hour,
                        user_lat=user_lat,
                        user_lon=user_lon
                    )
                    alt_distance = RecommendationService.calculate_distance(user_lat, user_lon, alt_queue.department.branch) if user_lat and user_lon else None
                    alternatives_data.append({
                        'queue_id': alt_queue.id,
                        'service': alt_queue.service or "Desconhecido",
                        'branch': alt_queue.department.branch.name or "Desconhecida",
                        'wait_time': f"{int(alt_wait_time)} minutos" if isinstance(alt_wait_time, (int, float)) else 'Aguardando início',
                        'distance': float(alt_distance) if alt_distance is not None else 'Desconhecida',
                        'quality_score': service_recommendation_predictor.predict(alt_queue, user_id, user_lat, user_lon)
                    })

                schedule = QueueSchedule.query.filter_by(queue_id=queue.id, weekday=getattr(Weekday, now.strftime('%A').upper(), None)).first()
                open_time = schedule.open_time.strftime('%H:%M') if schedule and schedule.open_time else None
                end_time = schedule.end_time.strftime('%H:%M') if schedule and schedule.end_time else None

                composite_score = 0.0
                if query and search_terms:
                    rank = db.session.query(
                        func.ts_rank(
                            func.to_tsvector('portuguese', func.concat(
                                Queue.service, ' ', Department.sector, ' ', Institution.name, ' ', InstitutionType.name
                            )),
                            func.to_tsquery('portuguese', search_query)
                        )
                    ).filter(Queue.id == queue.id).scalar() or 0.0
                    composite_score += rank * 0.2
                if distance is not None:
                    composite_score += (1 / (1 + distance)) * 0.25
                composite_score += quality_score * 0.2
                composite_score += collaborative_scores.get(queue.id, 0.5) * 0.15
                composite_score += (1 / (1 + predicted_demand / 10)) * 0.1
                if isinstance(wait_time, (int, float)):
                    composite_score += (1 / (1 + wait_time / 10)) * 0.05
                if user_prefs:
                    if institution.id in preferred_institutions:
                        composite_score += 0.2
                    if queue.category_id in preferred_categories:
                        composite_score += 0.1
                    if branch.neighborhood in preferred_neighborhoods:
                        composite_score += 0.05
                    if institution.institution_type_id in preferred_institution_types:
                        composite_score += 0.05

                recommendation_level = 'low'
                if composite_score > 0.8:
                    recommendation_level = 'high'
                elif composite_score > 0.5:
                    recommendation_level = 'medium'

                results.append({
                    'institution': {
                        'id': institution.id,
                        'name': institution.name or "Desconhecida",
                        'type': {
                            'id': institution_type.id,
                            'name': institution_type.name or "Desconhecido"
                        }
                    },
                    'branch': {
                        'id': branch.id,
                        'name': branch.name or "Desconhecida",
                        'location': branch.location or "Desconhecida",
                        'neighborhood': branch.neighborhood or "Desconhecido",
                        'latitude': float(branch.latitude) if branch.latitude else None,
                        'longitude': float(branch.longitude) if branch.longitude else None
                    },
                    'queue': {
                        'id': queue.id,
                        'service': queue.service or "Desconhecido",
                        'category_id': queue.category_id,
                        'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else 'Aguardando início',
                        'distance': float(distance) if distance is not None else 'Desconhecida',
                        'active_tickets': queue.active_tickets or 0,
                        'daily_limit': queue.daily_limit or 100,
                        'open_time': open_time,
                        'end_time': end_time,
                        'quality_score': float(quality_score),
                        'collaborative_score': float(collaborative_scores.get(queue.id, 0.5)),
                        'predicted_demand': float(predicted_demand),
                        'speed_label': speed_label,
                        'alternatives': alternatives_data,
                        'explanation': ", ".join(explanation) or f"Filial de {institution.name} recomendada",
                        'recommendation_level': recommendation_level
                    },
                    'score': float(composite_score)
                })

            if sort_by == 'wait_time':
                results.sort(key=lambda x: float(x['queue']['wait_time'].split()[0]) if x['queue']['wait_time'] != 'Aguardando início' else float('inf'))
            elif sort_by == 'distance':
                results.sort(key=lambda x: x['queue']['distance'] if x['queue']['distance'] != 'Desconhecida' else float('inf'))
            elif sort_by == 'quality_score':
                results.sort(key=lambda x: x['queue']['quality_score'], reverse=True)
            else:
                results.sort(key=lambda x: x['score'], reverse=True)

            results = results[:max_results]

            suggestions = []
            if results and (institution_id or results[0]['institution']['type']['id']):
                target_institution_id = institution_id or results[0]['institution']['id']
                related_queues = Queue.query.filter(
                    Queue.id != results[0]['queue']['id'],
                    Branch.institution_id == target_institution_id
                ).join(Department).join(Branch).limit(3).all()
                if not related_queues and results[0]['institution']['type']['id']:
                    related_queues = Queue.query.filter(
                        Institution.institution_type_id == results[0]['institution']['type']['id'],
                        Queue.id != results[0]['queue']['id']
                    ).join(Department).join(Branch).join(Institution).limit(3).all()
                for q in related_queues:
                    if q.department and q.department.branch and q.department.branch.institution:
                        wait_time = wait_time_predictor.predict(
                            queue_id=q.id,
                            position=q.active_tickets + 1,
                            active_tickets=q.active_tickets,
                            priority=0,
                            hour_of_day=now.hour
                        )
                        distance = RecommendationService.calculate_distance(user_lat, user_lon, q.department.branch) if user_lat and user_lon else None
                        suggestions.append({
                            'queue_id': q.id,
                            'institution': q.department.branch.institution.name or "Desconhecida",
                            'branch': q.department.branch.name or "Desconhecida",
                            'service': q.service or "Desconhecido",
                            'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else 'Aguardando início',
                            'distance': float(distance) if distance is not None else 'Desconhecida'
                        })

            filter_options = RecommendationService.get_filter_options(institution_id)

            result = {
                'services': results,
                'total': total,
                'page': int(page),
                'per_page': int(per_page),
                'total_pages': (total + per_page - 1) // per_page,
                'suggestions': suggestions,
                'filter_options': filter_options,
                'message': (f"Nenhuma fila encontrada em {institution_name or 'sua instituição preferida'}" if not results and institution_id
                        else "Recomendações personalizadas para você!")
            }

            cache_key = f'services:{query}:{institution_name}:{neighborhood}:{branch_id}:{institution_id}:{institution_type_id}:{category_id}:{tags}:{max_wait_time}:{min_quality_score}:{sort_by}'
            redis_client.setex(cache_key, 60, json.dumps(result, default=str))

            logger.info(f"Busca de serviços: {total} resultados, {len(results)} retornados")
            return result
        except Exception as e:
            logger.error(f"Erro ao buscar serviços: {str(e)}")
            raise
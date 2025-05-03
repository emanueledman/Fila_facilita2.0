import logging
import json
import re
import uuid
import numpy as np
from sqlalchemy import and_, func, or_
from datetime import datetime
from .models import Queue, Ticket, Department, Institution, User, Weekday, Branch, ServiceCategory, ServiceTag, UserPreference, InstitutionType,BranchSchedule, InstitutionService, UserBehavior, UserLocationFallback, NotificationLog
from .ml_models import wait_time_predictor, service_recommendation_predictor, collaborative_model, demand_model, clustering_model
from . import db, redis_client
from geopy.distance import geodesic

logger = logging.getLogger(__name__)
 

class RecommendationService:
    """Serviço para recomendações personalizadas de filas e serviços, com foco em serviços semelhantes."""

    @staticmethod
    def calculate_distance(user_lat, user_lon, branch):
        """Calcula a distância entre o usuário e a filial em quilômetros."""
        try:
            if not all(isinstance(x, (int, float)) for x in [user_lat, user_lon, branch.latitude, branch.longitude]):
                logger.warning(f"Coordenadas inválidas para branch_id={branch.id}")
                return None
            user_location = (float(user_lat), float(user_lon))
            branch_location = (float(branch.latitude), float(branch.longitude))
            distance = geodesic(user_location, branch_location).kilometers
            logger.debug(f"Distância calculada para branch_id={branch.id}: {distance:.2f} km")
            return round(distance, 2)
        except Exception as e:
            logger.error(f"Erro ao calcular distância para branch_id={branch.id}: {e}")
            return None

    @staticmethod
    def is_location_valid(user_id, user_lat, user_lon):
        """Verifica se a localização do usuário é válida e recente (últimos 10 minutos)."""
        try:
            if not user_id or not user_lat or not user_lon:
                logger.warning(f"Parâmetros de localização ausentes para user_id={user_id}")
                return False
            user = User.query.get(user_id)
            if not user or not user.last_location_update:
                logger.warning(f"Usuário ou última atualização de localização não encontrados para user_id={user_id}")
                return False
            time_diff = (datetime.utcnow() - user.last_location_update).total_seconds()
            is_valid = time_diff < 600  # 10 minutos
            logger.debug(f"Localização válida para user_id={user_id}: {is_valid} (diferença de {time_diff:.0f}s)")
            return is_valid
        except Exception as e:
            logger.error(f"Erro ao validar localização para user_id={user_id}: {e}")
            return False

    @staticmethod
    def invalidate_cache(queue_id):
        """Invalida o cache de buscas relacionadas a uma fila."""
        try:
            keys = redis_client.keys(f'services:*:{queue_id}:*')
            if keys:
                redis_client.delete(*keys)
                logger.info(f"Cache invalidado para queue_id={queue_id}: {len(keys)} chaves removidas")
            else:
                logger.debug(f"Nenhum cache encontrado para queue_id={queue_id}")
        except Exception as e:
            logger.error(f"Erro ao invalidar cache para queue_id={queue_id}: {e}")

    @staticmethod
    def get_filter_options(institution_id=None):
        """Retorna opções para filtros dinâmicos (categorias, tags, bairros)."""
        try:
            query = db.session.query(Institution)
            if institution_id:
                query = query.filter(Institution.id == institution_id)
            categories = ServiceCategory.query.all()
            tags = ServiceTag.query.distinct(ServiceTag.tag).all()
            neighborhoods = Branch.query.distinct(Branch.neighborhood).all()
            filter_options = {
                'categories': [{'id': c.id, 'name': c.name} for c in categories],
                'tags': [t.tag for t in tags],
                'neighborhoods': [n.neighborhood for n in neighborhoods if n.neighborhood]
            }
            logger.debug(f"Opções de filtro obtidas: {len(categories)} categorias, {len(tags)} tags, {len(neighborhoods)} bairros")
            return filter_options
        except Exception as e:
            logger.error(f"Erro ao obter opções de filtro: {e}")
            raise

    @staticmethod
    def get_service_id_from_query(service_query):
        """Busca o ID do serviço com base no texto da consulta."""
        try:
            if not service_query:
                logger.warning("Consulta de serviço vazia")
                return None
            search_terms = re.sub(r'[^\w\sÀ-ÿ]', '', service_query.lower()).strip()
            service = InstitutionService.query.filter(
                or_(
                    InstitutionService.name.ilike(f'%{search_terms}%'),
                    InstitutionService.description.ilike(f'%{search_terms}%'),
                    InstitutionService.id.in_(
                        db.session.query(ServiceTag.queue_id).filter(
                            ServiceTag.tag.ilike(f'%{search_terms}%')
                        )
                    )
                )
            ).first()
            if service:
                logger.debug(f"Serviço encontrado: service_id={service.id}, nome={service.name}")
                return service.id
            logger.warning(f"Nenhum serviço encontrado para consulta: {search_terms}")
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar service_id para consulta '{service_query}': {e}")
            return None

    @staticmethod
    def get_user_service_preference(user_id, service_id):
        """Calcula a preferência do usuário por um serviço com base em UserBehavior."""
        try:
            behaviors = UserBehavior.query.filter_by(user_id=user_id, service_id=service_id).all()
            total_behaviors = UserBehavior.query.filter_by(user_id=user_id).count()
            preference_score = len(behaviors) / max(1, total_behaviors) if behaviors else 0.0
            logger.debug(f"Preferência do usuário user_id={user_id} para service_id={service_id}: {preference_score:.2f}")
            return preference_score
        except Exception as e:
            logger.error(f"Erro ao calcular preferência para user_id={user_id}, service_id={service_id}: {e}")
            return 0.0

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
        """Busca serviços com filtros estruturados, priorizando serviços semelhantes e verificando horários via BranchSchedule."""
        try:
            now = datetime.utcnow()
            results = []

            # Validação de entradas
            if not institution or not isinstance(institution, str) or not institution.strip():
                logger.error("Instituição é obrigatória")
                raise ValueError("Instituição é obrigatória")
            if not service or not isinstance(service, str) or not service.strip():
                logger.error("Serviço é obrigatório")
                raise ValueError("Serviço é obrigatório")
            if not isinstance(max_wait_time, (int, float)) or max_wait_time <= 0:
                logger.error("Tempo de espera máximo deve ser positivo")
                raise ValueError("Tempo de espera máximo deve ser positivo")
            if not isinstance(neighborhood, str) or not neighborhood.strip():
                neighborhood = None
            if user_id and not isinstance(user_id, str):
                logger.warning(f"User_id inválido: {user_id}")
                user_id = None
            if user_lat and user_lon and user_id and not RecommendationService.is_location_valid(user_id, user_lat, user_lon):
                logger.warning(f"Localização antiga ou inválida para user_id={user_id}")
                user_lat, user_lon = None, None
            if not isinstance(max_distance_km, (int, float)) or max_distance_km <= 0:
                max_distance_km = 10.0

            # Obter service_id para similaridade
            target_service_id = RecommendationService.get_service_id_from_query(service)
            if not target_service_id:
                logger.warning(f"Serviço '{service}' não encontrado, prosseguindo sem similaridade específica")
            target_service = InstitutionService.query.get(target_service_id) if target_service_id else None
            target_category_id = target_service.category_id if target_service else None

            # Usar UserLocationFallback se localização ausente
            if not (user_lat and user_lon) and user_id:
                fallback = UserLocationFallback.query.filter_by(user_id=user_id).first()
                if fallback and fallback.latitude and fallback.longitude:
                    user_lat, user_lon = fallback.latitude, fallback.longitude
                    logger.debug(f"Usando localização fallback para user_id={user_id}: lat={user_lat}, lon={user_lon}")

            # Construir consulta base
            query_base = Queue.query.join(Department).join(Branch).join(Institution).join(InstitutionService)

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

            # Filtro por serviço (categoria e similaridade)
            if target_category_id:
                query_base = query_base.filter(InstitutionService.category_id == target_category_id)
            elif service:
                search_terms = re.sub(r'[^\w\sÀ-ÿ]', '', service.lower()).split()
                if search_terms:
                    search_query = ' & '.join(search_terms)
                    query_base = query_base.filter(
                        or_(
                            func.to_tsvector('portuguese', func.concat(
                                InstitutionService.name, ' ', InstitutionService.description
                            )).op('@@')(func.to_tsquery('portuguese', search_query)),
                            Queue.id.in_(
                                db.session.query(ServiceTag.queue_id).filter(
                                    ServiceTag.tag.ilike(f'%{service.lower()}%')
                                )
                            )
                        )
                    )

            # Filtrar por filas abertas com base em BranchSchedule
            weekday_str = now.strftime('%A').upper()
            try:
                weekday_enum = Weekday[weekday_str]
            except KeyError:
                logger.error(f"Dia da semana inválido: {weekday_str}")
                raise ValueError("Dia da semana inválido")
            query_base = query_base.join(BranchSchedule, BranchSchedule.branch_id == Branch.id).filter(
                and_(
                    BranchSchedule.weekday == weekday_enum,
                    BranchSchedule.is_closed == False,
                    BranchSchedule.open_time <= now.time(),
                    BranchSchedule.end_time >= now.time(),
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
            logger.debug(f"Total de filas encontradas antes da filtragem: {total}")

            # Aplicar ordenação inicial
            if service and search_terms:
                search_query = ' & '.join(search_terms)
                query_base = query_base.order_by(
                    func.ts_rank(
                        func.to_tsvector('portuguese', func.concat(
                            InstitutionService.name, ' ', InstitutionService.description
                        )),
                        func.to_tsquery('portuguese', search_query)
                    ).desc()
                )
            else:
                query_base = query_base.order_by(Queue.active_tickets.asc())

            # Paginação
            queues = query_base.offset((page - 1) * per_page).limit(per_page).all()
            logger.debug(f"Filas retornadas após paginação: {len(queues)}")

            # Obter scores colaborativos
            collaborative_scores = collaborative_model.predict(user_id, [q.id for q in queues], target_service_id=target_service_id) if user_id else {q.id: 0.5 for q in queues}
            logger.debug(f"Scores colaborativos calculados para {len(collaborative_scores)} filas")

            for queue in queues:
                branch = queue.department.branch
                institution = branch.institution
                service_obj = queue.service

                if not all([branch, institution, queue.department, service_obj]):
                    logger.warning(f"Dados incompletos para queue_id={queue.id}")
                    continue

                # Calcular distância
                distance = None
                if user_lat and user_lon and branch.latitude and branch.longitude:
                    distance = RecommendationService.calculate_distance(user_lat, user_lon, branch)
                    if distance and distance > max_distance_km:
                        logger.debug(f"Fila queue_id={queue.id} descartada: distância {distance:.2f} km > {max_distance_km} km")
                        continue

                # Calcular tempo de espera
                wait_time = wait_time_predictor.predict(
                    queue_id=queue.id,
                    position=queue.active_tickets + 1,
                    active_tickets=queue.active_tickets,
                    priority=0,
                    hour_of_day=now.hour,
                    user_id=user_id,
                    user_lat=user_lat,
                    user_lon=user_lon
                )
                logger.debug(f"Previsão de wait_time para queue_id={queue.id}: {wait_time} minutos")
                if isinstance(wait_time, (int, float)) and wait_time > max_wait_time:
                    logger.debug(f"Fila queue_id={queue.id} descartada: tempo de espera {wait_time} min > {max_wait_time} min")
                    continue

                # Previsão de demanda
                predicted_demand = demand_model.predict(queue.id, hours_ahead=1)
                logger.debug(f"Previsão de demanda para queue_id={queue.id}: {predicted_demand} tickets/hora")

                # Pontuação de qualidade com similaridade de serviço
                quality_score = service_recommendation_predictor.predict(
                    queue,
                    user_id=user_id,
                    user_lat=user_lat,
                    user_lon=user_lon,
                    target_service_id=target_service_id
                )
                logger.debug(f"Pontuação de qualidade para queue_id={queue.id}: {quality_score:.2f}")

                # Preferência do usuário pelo serviço
                user_service_preference = RecommendationService.get_user_service_preference(user_id, queue.service_id) if user_id else 0.0

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
                logger.debug(f"Velocidade da fila queue_id={queue.id}: {speed_label} (média {avg_service_time:.1f} min)")

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
                if user_service_preference > 0.5:
                    explanation.append(f"Você usa este serviço frequentemente")
                if target_service_id:
                    similarity = service_recommendation_predictor.calculate_service_similarity(target_service_id, queue.service_id)
                    if similarity > 0.8:
                        explanation.append(f"Serviço semelhante a {service}")

                # Sugestões de alternativas (mesma instituição e categoria)
                alternatives = clustering_model.get_alternatives(queue.id, user_id=user_id, n=3)
                alternative_queues = Queue.query.filter(
                    Queue.id.in_(alternatives),
                    Branch.institution_id == institution.id,
                    InstitutionService.category_id == target_category_id if target_category_id else True
                ).join(Department).join(Branch).join(InstitutionService).all()
                alternatives_data = []
                for alt_queue in alternative_queues:
                    alt_wait_time = wait_time_predictor.predict(
                        queue_id=alt_queue.id,
                        position=alt_queue.active_tickets + 1,
                        active_tickets=alt_queue.active_tickets,
                        priority=0,
                        hour_of_day=now.hour,
                        user_id=user_id,
                        user_lat=user_lat,
                        user_lon=user_lon
                    )
                    alt_distance = RecommendationService.calculate_distance(user_lat, user_lon, alt_queue.department.branch) if user_lat and user_lon else None
                    alternatives_data.append({
                        'queue_id': alt_queue.id,
                        'service': alt_queue.service.name or "Desconhecido",
                        'branch': alt_queue.department.branch.name or "Desconhecida",
                        'wait_time': f"{int(alt_wait_time)} minutos" if isinstance(alt_wait_time, (int, float)) else 'Aguardando início',
                        'distance': float(alt_distance) if alt_distance is not None else 'Desconhecida',
                        'quality_score': service_recommendation_predictor.predict(
                            alt_queue,
                            user_id=user_id,
                            user_lat=user_lat,
                            user_lon=user_lon,
                            target_service_id=target_service_id
                        )
                    })
                logger.debug(f"Alternativas para queue_id={queue.id}: {len(alternatives_data)} filas")

                # Horário de funcionamento via BranchSchedule
                schedule = BranchSchedule.query.filter_by(
                    branch_id=branch.id,
                    weekday=weekday_enum
                ).first()
                open_time = schedule.open_time.strftime('%H:%M') if schedule and schedule.open_time else None
                end_time = schedule.end_time.strftime('%H:%M') if schedule and schedule.end_time else None
                if not schedule:
                    logger.warning(f"Filial {branch.id} sem horário definido para {weekday_str}")

                # Pontuação composta
                composite_score = 0.0
                if service and search_terms:
                    rank = db.session.query(
                        func.ts_rank(
                            func.to_tsvector('portuguese', func.concat(
                                InstitutionService.name, ' ', InstitutionService.description
                            )),
                            func.to_tsquery('portuguese', search_query)
                        )
                    ).filter(Queue.id == queue.id).join(InstitutionService).scalar() or 0.0
                    composite_score += float(rank) * 0.2
                if distance is not None:
                    composite_score += (1 / (1 + float(distance))) * 0.2
                composite_score += float(quality_score) * 0.25
                composite_score += float(collaborative_scores.get(queue.id, 0.5)) * 0.15
                composite_score += (1 / (1 + float(predicted_demand) / 10)) * 0.1
                if isinstance(wait_time, (int, float)):
                    composite_score += (1 / (1 + float(wait_time) / 10)) * 0.1
                composite_score += user_service_preference * 0.15
                if user_prefs:
                    if institution.id in preferred_institutions:
                        composite_score += 0.15
                    if queue.service.category_id in preferred_categories:
                        composite_score += 0.1
                    if branch.neighborhood in preferred_neighborhoods:
                        composite_score += 0.05
                if target_service_id:
                    similarity = service_recommendation_predictor.calculate_service_similarity(target_service_id, queue.service_id)
                    composite_score += similarity * 0.2
                logger.debug(f"Pontuação composta para queue_id={queue.id}: {composite_score:.2f}")

                # Nível de recomendação para ícones no mapa
                recommendation_level = 'low'
                if composite_score > 0.8:
                    recommendation_level = 'high'
                elif composite_score > 0.5:
                    recommendation_level = 'medium'

                # Registrar notificação (se aplicável)
                if user_id and isinstance(wait_time, (int, float)) and wait_time <= max_wait_time:
                    notification = NotificationLog(
                        user_id=user_id,
                        message=f"{institution.name} {branch.name}: {int(wait_time)} min para {service_obj.name}",
                        type='recommendation',
                        timestamp=now
                    )
                    db.session.add(notification)
                    logger.debug(f"Notificação registrada para user_id={user_id}: queue_id={queue.id}")

                results.append({
                    'institution': {
                        'id': institution.id,
                        'name': institution.name or "Desconhecida",
                        'type': {
                            'id': institution.institution_type_id,
                            'name': institution.type.name or "Desconhecido"
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
                        'service': service_obj.name or "Desconhecido",
                        'category_id': service_obj.category_id,
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
                    Branch.institution_id == target_institution_id,
                    InstitutionService.category_id == target_category_id if target_category_id else True
                ).join(Department).join(Branch).join(InstitutionService).limit(3).all()
                for q in related_queues:
                    if q.department and q.department.branch and q.department.branch.institution:
                        wait_time = wait_time_predictor.predict(
                            queue_id=q.id,
                            position=q.active_tickets + 1,
                            active_tickets=q.active_tickets,
                            priority=0,
                            hour_of_day=now.hour,
                            user_id=user_id,
                            user_lat=user_lat,
                            user_lon=user_lon
                        )
                        distance = RecommendationService.calculate_distance(user_lat, user_lon, q.department.branch) if user_lat and user_lon else None
                        suggestions.append({
                            'queue_id': q.id,
                            'institution': q.department.branch.institution.name or "Desconhecida",
                            'branch': q.department.branch.name or "Desconhecida",
                            'service': q.service.name or "Desconhecido",
                            'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else 'Aguardando início',
                            'distance': float(distance) if distance is not None else 'Desconhecida'
                        })
                logger.debug(f"Sugestões geradas: {len(suggestions)} filas")

            # Opções de filtro para dropdowns
            filter_options = RecommendationService.get_filter_options()

            # Montar resultado
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

            # Cachear resultados apenas se houver resultados
            if results:
                cache_key = f'services_structured:{institution}:{neighborhood}:{service}:{max_wait_time}:{user_id}:{sort_by}:{page}:{per_page}'
                redis_client.setex(cache_key, 60, json.dumps(result, default=str))
                logger.info(f"Busca estruturada concluída: {total} resultados, {len(results)} retornados, cache_key={cache_key}")
            else:
                logger.info(f"Busca estruturada concluída: {total} resultados, sem cache devido a resultados vazios")

            # Commit de notificações
            db.session.commit()

            return result
        except Exception as e:
            logger.error(f"Erro ao buscar serviços estruturados: {str(e)}")
            db.session.rollback()
            raise
    
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
        per_page=10,
        offset=None
    ):
        """Busca serviços com filtros flexíveis, priorizando serviços semelhantes e verificando horários via BranchSchedule."""
        try:
            now = datetime.utcnow()
            results = []

            # Validação de entradas
            if not query or not isinstance(query, str) or not query.strip():
                query = ""
            if not isinstance(user_id, str):
                logger.warning(f"User_id inválido: {user_id}")
                user_id = None
            if not all(isinstance(x, (int, float)) for x in [user_lat, user_lon] if x is not None):
                logger.warning(f"Coordenadas inválidas: lat={user_lat}, lon={user_lon}")
                user_lat, user_lon = None, None
            if not isinstance(institution_id, str):
                institution_id = None
            if not isinstance(institution_type_id, str):
                institution_type_id = None
            if not isinstance(category_id, str):
                category_id = None
            if tags and (not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)):
                logger.warning(f"Tags inválidas: {tags}")
                tags = []
            if not isinstance(max_wait_time, (int, float)) or max_wait_time <= 0:
                max_wait_time = None
            if not isinstance(min_quality_score, (int, float)) or min_quality_score <= 0:
                min_quality_score = None
            if not isinstance(max_distance_km, (int, float)) or max_distance_km <= 0:
                max_distance_km = 10.0

            # Obter service_id para similaridade
            target_service_id = RecommendationService.get_service_id_from_query(query) if query else None
            target_service = InstitutionService.query.get(target_service_id) if target_service_id else None
            target_category_id = target_service.category_id if target_service else category_id

            # Inferir institution_id do histórico
            if not institution_id and user_id:
                recent_ticket = Ticket.query.filter_by(user_id=user_id).join(Queue).join(Department).join(Branch).order_by(Ticket.issued_at.desc()).first()
                if recent_ticket:
                    institution_id = recent_ticket.queue.department.branch.institution_id
                    logger.debug(f"Inferiu institution_id={institution_id} do histórico do usuário {user_id}")

            # Usar UserLocationFallback se localização ausente
            if not (user_lat and user_lon) and user_id:
                fallback = UserLocationFallback.query.filter_by(user_id=user_id).first()
                if fallback and fallback.latitude and fallback.longitude:
                    user_lat, user_lon = fallback.latitude, fallback.longitude
                    logger.debug(f"Usando localização fallback para user_id={user_id}: lat={user_lat}, lon={user_lon}")

            # Construir consulta base
            query_base = Queue.query.join(Department).join(Branch).join(Institution).join(InstitutionService)

            # Aplicar filtros
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
            if target_category_id:
                query_base = query_base.filter(InstitutionService.category_id == target_category_id)
            if tags:
                query_base = query_base.join(ServiceTag).filter(ServiceTag.tag.in_([tag.strip() for tag in tags]))

            # Filtro por busca textual
            if query:
                search_terms = re.sub(r'[^\w\sÀ-ÿ]', '', query.lower()).split()
                if search_terms:
                    search_query = ' & '.join(search_terms)
                    query_base = query_base.filter(
                        or_(
                            func.to_tsvector('portuguese', func.concat(
                                InstitutionService.name, ' ', InstitutionService.description, ' ', Institution.name
                            )).op('@@')(func.to_tsquery('portuguese', search_query)),
                            Queue.id.in_(
                                db.session.query(ServiceTag.queue_id).filter(
                                    ServiceTag.tag.ilike(f'%{query.lower()}%')
                                )
                            )
                        )
                    )

            # Filtrar por filas abertas com base em BranchSchedule
            weekday_str = now.strftime('%A').upper()
            try:
                weekday_enum = Weekday[weekday_str]
            except KeyError:
                logger.error(f"Dia da semana inválido: {weekday_str}")
                raise ValueError("Dia da semana inválido")
            query_base = query_base.join(BranchSchedule, BranchSchedule.branch_id == Branch.id).filter(
                and_(
                    BranchSchedule.weekday == weekday_enum,
                    BranchSchedule.is_closed == False,
                    BranchSchedule.open_time <= now.time(),
                    BranchSchedule.end_time >= now.time(),
                    Queue.active_tickets < Queue.daily_limit
                )
            )

            # Obter preferências do usuário
            user_prefs = UserPreference.query.filter_by(user_id=user_id).all() if user_id else []
            preferred_institutions = {pref.institution_id for pref in user_prefs if pref.institution_id}
            preferred_categories = {pref.service_category_id for pref in user_prefs if pref.service_category_id}
            preferred_neighborhoods = {pref.neighborhood for pref in user_prefs if pref.neighborhood}
            preferred_institution_types = {pref.institution_type_id for pref in user_prefs if pref.institution_type_id}

            # Contar total de resultados
            total = query_base.count()
            logger.debug(f"Total de filas encontradas antes da filtragem: {total}")

            # Aplicar ordenação inicial
            if query and search_terms:
                search_query = ' & '.join(search_terms)
                query_base = query_base.order_by(
                    func.ts_rank(
                        func.to_tsvector('portuguese', func.concat(
                            InstitutionService.name, ' ', InstitutionService.description, ' ', Institution.name
                        )),
                        func.to_tsquery('portuguese', search_query)
                    ).desc()
                )
            else:
                query_base = query_base.order_by(Queue.active_tickets.asc())

            # Paginação
            if offset is not None:
                queues = query_base.offset(offset).limit(per_page).all()
            else:
                queues = query_base.offset((page - 1) * per_page).limit(per_page).all()
            logger.debug(f"Filas retornadas após paginação: {len(queues)}")

            # Obter scores colaborativos
            collaborative_scores = collaborative_model.predict(user_id, [q.id for q in queues], target_service_id=target_service_id) if user_id else {q.id: 0.5 for q in queues}
            logger.debug(f"Scores colaborativos calculados para {len(collaborative_scores)} filas")

            for queue in queues:
                branch = queue.department.branch
                institution = branch.institution
                service_obj = queue.service

                if not all([branch, institution, queue.department, service_obj]):
                    logger.warning(f"Dados incompletos para queue_id={queue.id}")
                    continue

                # Calcular distância
                distance = None
                if user_lat and user_lon and branch.latitude and branch.longitude:
                    distance = RecommendationService.calculate_distance(user_lat, user_lon, branch)
                    if distance and distance > max_distance_km:
                        logger.debug(f"Fila queue_id={queue.id} descartada: distância {distance:.2f} km > {max_distance_km} km")
                        continue

                # Calcular tempo de espera
                wait_time = wait_time_predictor.predict(
                    queue_id=queue.id,
                    position=queue.active_tickets + 1,
                    active_tickets=queue.active_tickets,
                    priority=0,
                    hour_of_day=now.hour,
                    user_id=user_id,
                    user_lat=user_lat,
                    user_lon=user_lon
                )
                logger.debug(f"Previsão de wait_time para queue_id={queue.id}: {wait_time} minutos")
                if max_wait_time and isinstance(wait_time, (int, float)) and wait_time > max_wait_time:
                    logger.debug(f"Fila queue_id={queue.id} descartada: tempo de espera {wait_time} min > {max_wait_time} min")
                    continue

                # Previsão de demanda
                predicted_demand = demand_model.predict(queue.id, hours_ahead=1)
                logger.debug(f"Previsão de demanda para queue_id={queue.id}: {predicted_demand} tickets/hora")

                # Pontuação de qualidade com similaridade de serviço
                quality_score = service_recommendation_predictor.predict(
                    queue,
                    user_id=user_id,
                    user_lat=user_lat,
                    user_lon=user_lon,
                    target_service_id=target_service_id
                )
                if min_quality_score and quality_score < min_quality_score:
                    logger.debug(f"Fila queue_id={queue.id} descartada: qualidade {quality_score:.2f} < {min_quality_score}")
                    continue
                logger.debug(f"Pontuação de qualidade para queue_id={queue.id}: {quality_score:.2f}")

                # Preferência do usuário pelo serviço
                user_service_preference = RecommendationService.get_user_service_preference(user_id, queue.service_id) if user_id else 0.0

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
                logger.debug(f"Velocidade da fila queue_id={queue.id}: {speed_label} (média {avg_service_time:.1f} min)")

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
                if user_service_preference > 0.5:
                    explanation.append(f"Você usa este serviço frequentemente")
                if target_service_id:
                    similarity = service_recommendation_predictor.calculate_service_similarity(target_service_id, queue.service_id)
                    if similarity > 0.8:
                        explanation.append(f"Serviço semelhante a {query}")

                # Sugestões de alternativas
                alternatives = clustering_model.get_alternatives(queue.id, user_id=user_id, n=3)
                alternative_queues = Queue.query.filter(
                    Queue.id.in_(alternatives),
                    Branch.institution_id == institution.id,
                    InstitutionService.category_id == target_category_id if target_category_id else True
                ).join(Department).join(Branch).join(InstitutionService).all()
                alternatives_data = []
                for alt_queue in alternative_queues:
                    alt_wait_time = wait_time_predictor.predict(
                        queue_id=alt_queue.id,
                        position=alt_queue.active_tickets + 1,
                        active_tickets=alt_queue.active_tickets,
                        priority=0,
                        hour_of_day=now.hour,
                        user_id=user_id,
                        user_lat=user_lat,
                        user_lon=user_lon
                    )
                    alt_distance = RecommendationService.calculate_distance(user_lat, user_lon, alt_queue.department.branch) if user_lat and user_lon else None
                    alternatives_data.append({
                        'queue_id': alt_queue.id,
                        'service': alt_queue.service.name or "Desconhecido",
                        'branch': alt_queue.department.branch.name or "Desconhecida",
                        'wait_time': f"{int(alt_wait_time)} minutos" if isinstance(alt_wait_time, (int, float)) else 'Aguardando início',
                        'distance': float(alt_distance) if alt_distance is not None else 'Desconhecida',
                        'quality_score': service_recommendation_predictor.predict(
                            alt_queue,
                            user_id=user_id,
                            user_lat=user_lat,
                            user_lon=user_lon,
                            target_service_id=target_service_id
                        )
                    })
                logger.debug(f"Alternativas para queue_id={queue.id}: {len(alternatives_data)} filas")

                # Horário de funcionamento via BranchSchedule
                schedule = BranchSchedule.query.filter_by(
                    branch_id=branch.id,
                    weekday=weekday_enum
                ).first()
                open_time = schedule.open_time.strftime('%H:%M') if schedule and schedule.open_time else None
                end_time = schedule.end_time.strftime('%H:%M') if schedule and schedule.end_time else None
                if not schedule:
                    logger.warning(f"Filial {branch.id} sem horário definido para {weekday_str}")

                # Pontuação composta
                composite_score = 0.0
                if query and search_terms:
                    rank = db.session.query(
                        func.ts_rank(
                            func.to_tsvector('portuguese', func.concat(
                                InstitutionService.name, ' ', InstitutionService.description, ' ', Institution.name
                            )),
                            func.to_tsquery('portuguese', search_query)
                        )
                    ).filter(Queue.id == queue.id).join(InstitutionService).scalar() or 0.0
                    composite_score += float(rank) * 0.2
                if distance is not None:
                    composite_score += (1 / (1 + float(distance))) * 0.2
                composite_score += float(quality_score) * 0.25
                composite_score += float(collaborative_scores.get(queue.id, 0.5)) * 0.15
                composite_score += (1 / (1 + float(predicted_demand) / 10)) * 0.1
                if isinstance(wait_time, (int, float)):
                    composite_score += (1 / (1 + float(wait_time) / 10)) * 0.05
                composite_score += user_service_preference * 0.15
                if user_prefs:
                    if institution.id in preferred_institutions:
                        composite_score += 0.15
                    if queue.service.category_id in preferred_categories:
                        composite_score += 0.1
                    if branch.neighborhood in preferred_neighborhoods:
                        composite_score += 0.05
                    if institution.institution_type_id in preferred_institution_types:
                        composite_score += 0.05
                if target_service_id:
                    similarity = service_recommendation_predictor.calculate_service_similarity(target_service_id, queue.service_id)
                    composite_score += similarity * 0.2
                logger.debug(f"Pontuação composta para queue_id={queue.id}: {composite_score:.2f}")

                # Nível de recomendação
                recommendation_level = 'low'
                if composite_score > 0.8:
                    recommendation_level = 'high'
                elif composite_score > 0.5:
                    recommendation_level = 'medium'

                # Registrar notificação
                if user_id and isinstance(wait_time, (int, float)) and (max_wait_time is None or wait_time <= max_wait_time):
                    notification = NotificationLog(
                        user_id=user_id,
                        message=f"{institution.name} {branch.name}: {int(wait_time)} min para {service_obj.name}",
                        type='recommendation',
                        timestamp=now
                    )
                    db.session.add(notification)
                    logger.debug(f"Notificação registrada para user_id={user_id}: queue_id={queue.id}")

                results.append({
                    'institution': {
                        'id': institution.id,
                        'name': institution.name or "Desconhecida",
                        'type': {
                            'id': institution.institution_type_id,
                            'name': institution.type.name or "Desconhecido"
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
                        'service': service_obj.name or "Desconhecido",
                        'category_id': service_obj.category_id,
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

            # Ordenar resultados
            if sort_by == 'wait_time':
                results.sort(key=lambda x: float(x['queue']['wait_time'].split()[0]) if x['queue']['wait_time'] != 'Aguardando início' else float('inf'))
            elif sort_by == 'distance':
                results.sort(key=lambda x: x['queue']['distance'] if x['queue']['distance'] != 'Desconhecida' else float('inf'))
            elif sort_by == 'quality_score':
                results.sort(key=lambda x: x['queue']['quality_score'], reverse=True)
            else:
                results.sort(key=lambda x: x['score'], reverse=True)

            # Limitar resultados
            results = results[:max_results]
            logger.debug(f"Resultados finais após ordenação e limite: {len(results)}")

            # Sugestões
            suggestions = []
            if results and (institution_id or results[0]['institution']['type']['id']):
                target_institution_id = institution_id or results[0]['institution']['id']
                related_queues = Queue.query.filter(
                    Queue.id != results[0]['queue']['id'],
                    Branch.institution_id == target_institution_id,
                    InstitutionService.category_id == target_category_id if target_category_id else True
                ).join(Department).join(Branch).join(InstitutionService).limit(3).all()
                if not related_queues and results[0]['institution']['type']['id']:
                    related_queues = Queue.query.filter(
                        Institution.institution_type_id == results[0]['institution']['type']['id'],
                        Queue.id != results[0]['queue']['id'],
                        InstitutionService.category_id == target_category_id if target_category_id else True
                    ).join(Department).join(Branch).join(Institution).join(InstitutionService).limit(3).all()
                for q in related_queues:
                    if q.department and q.department.branch and q.department.branch.institution:
                        wait_time = wait_time_predictor.predict(
                            queue_id=q.id,
                            position=q.active_tickets + 1,
                            active_tickets=q.active_tickets,
                            priority=0,
                            hour_of_day=now.hour,
                            user_id=user_id,
                            user_lat=user_lat,
                            user_lon=user_lon
                        )
                        distance = RecommendationService.calculate_distance(user_lat, user_lon, q.department.branch) if user_lat and user_lon else None
                        suggestions.append({
                            'queue_id': q.id,
                            'institution': q.department.branch.institution.name or "Desconhecida",
                            'branch': q.department.branch.name or "Desconhecida",
                            'service': q.service.name or "Desconhecido",
                            'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else 'Aguardando início',
                            'distance': float(distance) if distance is not None else 'Desconhecida'
                        })
                logger.debug(f"Sugestões geradas: {len(suggestions)} filas")

            # Opções de filtro
            filter_options = RecommendationService.get_filter_options(institution_id)

            # Montar resultado
            result = {
                'services': results,
                'total': total,
                'page': int(page) if offset is None else None,
                'offset': int(offset) if offset is not None else (page - 1) * per_page,
                'per_page': int(per_page),
                'total_pages': (total + per_page - 1) // per_page,
                'suggestions': suggestions,
                'filter_options': filter_options,
                'message': (f"Nenhuma fila encontrada para {institution_name or 'sua instituição preferida'}" if not results and institution_id
                        else "Recomendações personalizadas para você!")
            }

            # Cachear resultados apenas se houver resultados
            if results:
                cache_key = f'services:{query}:{institution_name}:{neighborhood}:{branch_id}:{institution_id}:{institution_type_id}:{category_id}:{tags}:{max_wait_time}:{min_quality_score}:{sort_by}:{offset or (page-1)*per_page}:{per_page}'
                redis_client.setex(cache_key, 60, json.dumps(result, default=str))
                logger.info(f"Busca de serviços concluída: {total} resultados, {len(results)} retornados, cache_key={cache_key}")
            else:
                logger.info(f"Busca de serviços concluída: {total} resultados, sem cache devido a resultados vazios")

            # Commit de notificações
            db.session.commit()

            return result
        except Exception as e:
            logger.error(f"Erro ao buscar serviços: {str(e)}")
            db.session.rollback()
            raise
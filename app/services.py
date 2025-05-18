import logging
from typing import Any, Dict
import uuid
import numpy as np
import json
from sqlalchemy.orm import selectinload

import re
from sqlalchemy import and_, func, or_
from datetime import datetime, time, timedelta
from .models import Queue, Ticket, AuditLog, Department, Institution, User, UserPreference, Weekday, Branch, InstitutionService, ServiceCategory, ServiceTag, UserBehavior, UserLocationFallback, NotificationLog, BranchSchedule
from .ml_models import wait_time_predictor, service_recommendation_predictor, clustering_model, demand_model
from . import db, redis_client, socketio
from .utils.pdf_generator import generate_ticket_pdf, generate_physical_ticket_pdf
from firebase_admin import messaging
from sqlalchemy.exc import SQLAlchemyError
from flask_socketio import emit
from geopy.distance import geodesic
import pytz

logger = logging.getLogger(__name__)

class QueueService:
    """Serviço para gerenciamento de filas, tickets, notificações e dashboard, com foco em serviços semelhantes."""
    DEFAULT_EXPIRATION_MINUTES = 30
    CALL_TIMEOUT_MINUTES = 5
    PROXIMITY_THRESHOLD_KM = 1.0
    PRESENCE_PROXIMITY_THRESHOLD_KM = 0.5

    @staticmethod
    def is_branch_open(branch, now=None):
        """Verifica se a filial está aberta com base em BranchSchedule."""
        try:
            if not now:
                local_tz = pytz.timezone('Africa/Luanda')
                now = datetime.now(local_tz)
            weekday_str = now.strftime('%A').upper()
            try:
                weekday_enum = Weekday[weekday_str]
            except KeyError:
                logger.error(f"Dia da semana inválido para filial {branch.id}: {weekday_str}")
                return False
            schedule = BranchSchedule.query.filter_by(
                branch_id=branch.id,
                weekday=weekday_enum
            ).first()
            if not schedule:
                logger.warning(f"Filial {branch.id} sem horário definido para {weekday_str}")
                return False
            if schedule.is_closed:
                logger.debug(f"Filial {branch.id} marcada como fechada para {weekday_str}")
                return False
            if not schedule.open_time or not schedule.end_time:
                logger.warning(f"Filial {branch.id} com horário incompleto para {weekday_str}")
                return False
            current_time = now.time()
            is_open = schedule.open_time <= current_time <= schedule.end_time
            logger.debug(f"Filial {branch.id} {'aberta' if is_open else 'fechada'}: {schedule.open_time} - {schedule.end_time}")
            return is_open
        except Exception as e:
            logger.error(f"Erro ao verificar horário da filial {branch.id}: {e}")
            return False
        
    @staticmethod
    def is_queue_open(queue, now=None):
        """Verifica se a fila JACK está aberta com base no horário da filial definido em BranchSchedule."""
        try:
            if not now:
                local_tz = pytz.timezone('Africa/Luanda')
                now = datetime.now(local_tz)
            if not queue.department or not queue.department.branch:
                logger.error(f"Fila {queue.id} sem departamento ou filial associada")
                return False
            branch = queue.department.branch
            if not QueueService.is_branch_open(branch, now):
                logger.debug(f"Fila {queue.id} fechada: filial {branch.id} fora do horário")
                return False
            logger.debug(f"Fila {queue.id} aberta: filial {branch.id} dentro do horário")
            return True
        except Exception as e:
            logger.error(f"Erro ao verificar fila {queue.id}: {e}")
            return False
    
    @staticmethod
    def generate_qr_code():
        """Gera um QR code único para tickets."""
        qr_code = f"QR-{uuid.uuid4().hex[:8]}"
        logger.debug(f"QR Code gerado: {qr_code}")
        return qr_code

    @staticmethod
    def generate_receipt(ticket):
        """Gera um comprovante em texto para o ticket."""
        try:
            queue = ticket.queue
            if not queue or not queue.department or not queue.department.branch or not queue.department.branch.institution or not queue.service:
                logger.error(f"Dados incompletos para o ticket {ticket.id}")
                raise ValueError("Fila, departamento, instituição ou serviço associado ao ticket não encontrado")
            institution_type_name = queue.department.branch.institution.type.name if queue.department.branch.institution.type else "Desconhecido"
            receipt = (
                "=== Comprovante Facilita 2.0 ===\n"
                f"Tipo de Instituição: {institution_type_name}\n"
                f"Instituição: {queue.department.branch.institution.name or 'Desconhecida'}\n"
                f"Filial: {queue.department.branch.name or 'Desconhecida'}\n"
                f"Bairro: {queue.department.branch.neighborhood or 'Não especificado'}\n"
                f"Serviço: {queue.service.name or 'Desconhecido'}\n"
                f"Senha: {queue.prefix}{ticket.ticket_number}\n"
                f"Tipo: {'Física' if ticket.is_physical else 'Virtual'}\n"
                f"QR Code: {ticket.qr_code}\n"
                f"Prioridade: {ticket.priority or 0}\n"
                f"Data de Emissão: {ticket.issued_at.strftime('%d/%m/%Y %H:%M')}\n"
                f"Expira em: {ticket.expires_at.strftime('%d/%m/%Y %H:%M') if ticket.expires_at else 'N/A'}\n"
                "=== Guarde este comprovante ==="
            )
            logger.debug(f"Comprovante gerado para ticket {ticket.id}")
            return receipt
        except Exception as e:
            logger.error(f"Erro ao gerar comprovante para ticket {ticket.id}: {e}")
            raise

    @staticmethod
    def generate_pdf_ticket(ticket, position=None, wait_time=None):
        """Gera um PDF para o ticket com informações detalhadas."""
        try:
            if not ticket.queue or not ticket.queue.department or not ticket.queue.department.branch or not ticket.queue.department.branch.institution or not ticket.queue.service:
                logger.error(f"Dados incompletos para o ticket {ticket.id}")
                raise ValueError("Fila, departamento, instituição ou serviço associado ao ticket não encontrado")
            institution_type_name = ticket.queue.department.branch.institution.type.name if ticket.queue.department.branch.institution.type else "Desconhecido"
            if position is None:
                position = max(0, ticket.ticket_number - ticket.queue.current_ticket)
            if wait_time is None:
                wait_time = QueueService.calculate_wait_time(
                    ticket.queue.id, ticket.ticket_number, ticket.priority
                )
            pdf_buffer = generate_ticket_pdf(
                ticket=ticket,
                institution_name=f"{institution_type_name} - {ticket.queue.department.branch.institution.name or 'Desconhecida'} - {ticket.queue.department.branch.name or 'Desconhecida'}",
                service=ticket.queue.service.name or "Desconhecido",
                position=position,
                wait_time=wait_time
            )
            logger.debug(f"PDF gerado para ticket {ticket.id}")
            return pdf_buffer
        except Exception as e:
            logger.error(f"Erro ao gerar PDF para ticket {ticket.id}: {e}")
            raise

    @staticmethod
    def get_service_id_from_query(service_query):
        """Busca o ID do serviço com base no texto da consulta."""
        try:
            if not service_query or not isinstance(service_query, str) or not service_query.strip():
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
            if not user_id or not service_id:
                logger.warning(f"Parâmetros inválidos: user_id={user_id}, service_id={service_id}")
                return 0.0
            behaviors = UserBehavior.query.filter_by(user_id=user_id, service_id=service_id).all()
            total_behaviors = UserBehavior.query.filter_by(user_id=user_id).count()
            preference_score = len(behaviors) / max(1, total_behaviors) if behaviors else 0.0
            logger.debug(f"Preferência do usuário user_id={user_id} para service_id={service_id}: {preference_score:.2f}")
            return preference_score
        except Exception as e:
            logger.error(f"Erro ao calcular preferência para user_id={user_id}, service_id={service_id}: {e}")
            return 0.0

    @staticmethod
    def suggest_alternative_queues(queue_id, user_id=None, user_lat=None, user_lon=None, max_distance_km=10.0, n=3):
        """Sugere filas alternativas com base em similaridade de serviço e proximidade."""
        try:
            queue = Queue.query.get(queue_id)
            if not queue or not queue.service:
                logger.error(f"Fila ou serviço não encontrado para queue_id={queue_id}")
                return []
            target_service_id = queue.service_id
            target_category_id = queue.service.category_id if queue.service else None
            institution_id = queue.department.branch.institution_id if queue.department and queue.department.branch else None
            alternatives = clustering_model.get_alternatives(queue_id, user_id=user_id, n=n * 2)
            alt_queues = Queue.query.filter(
                Queue.id.in_(alternatives),
                Queue.id != queue_id,
                InstitutionService.category_id == target_category_id if target_category_id else True
            ).join(Department).join(Branch).join(InstitutionService).all()
            results = []
            for alt_queue in alt_queues:
                if not alt_queue.department or not alt_queue.department.branch:
                    continue
                if not QueueService.is_queue_open(alt_queue):
                    logger.debug(f"Fila {alt_queue.id} fechada")
                    continue
                distance = QueueService.calculate_distance(user_lat, user_lon, alt_queue.department.branch) if user_lat and user_lon else None
                if distance and distance > max_distance_km:
                    continue
                wait_time = QueueService.calculate_wait_time(
                    alt_queue.id,
                    alt_queue.active_tickets + 1,
                    priority=0,
                    user_id=user_id,
                    user_lat=user_lat,
                    user_lon=user_lon
                )
                quality_score = service_recommendation_predictor.predict(
                    alt_queue,
                    user_id=user_id,
                    user_lat=user_lat,
                    user_lon=user_lon,
                    target_service_id=target_service_id
                )
                similarity = service_recommendation_predictor.calculate_service_similarity(target_service_id, alt_queue.service_id) if target_service_id else 0.5
                results.append({
                    'queue_id': alt_queue.id,
                    'service': alt_queue.service.name or "Desconhecido",
                    'branch': alt_queue.department.branch.name or "Desconhecida",
                    'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "Aguardando início",
                    'distance': float(distance) if distance is not None else "Desconhecida",
                    'quality_score': float(quality_score),
                    'service_similarity': float(similarity)
                })
            results.sort(key=lambda x: (x['service_similarity'] * 0.5 + x['quality_score'] * 0.3 + (1 / (1 + float(x['wait_time'].split()[0])) if x['wait_time'] != "Aguardando início" else 0) * 0.2), reverse=True)
            logger.debug(f"Alternativas sugeridas para queue_id={queue_id}: {len(results)} filas")
            return results[:n]
        except Exception as e:
            logger.error(f"Erro ao sugerir alternativas para queue_id={queue_id}: {e}")
            return []

    @staticmethod
    def complete_ticket(ticket_id, user_id=None):
        """Marca um ticket como atendido, atualizando métricas e enviando notificações."""
        try:
            if not isinstance(ticket_id, str):
                logger.error(f"ticket_id inválido: {ticket_id}")
                raise ValueError("ticket_id inválido")
            
            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                logger.error(f"Ticket não encontrado: ticket_id={ticket_id}")
                raise ValueError("Ticket não encontrado")
            
            if ticket.status not in ['Pendente', 'Chamado']:
                logger.warning(f"Ticket {ticket_id} no estado {ticket.status} não pode ser completado")
                raise ValueError(f"Ticket já está {ticket.status}")
            
            queue = ticket.queue
            if not queue:
                logger.error(f"Fila não encontrada para ticket_id={ticket_id}")
                raise ValueError("Fila não encontrada")
            
            if not QueueService.is_queue_open(queue):
                logger.warning(f"Fila {queue.id} está fechada")
                raise ValueError("Fila está fechada (fora do horário da filial)")
            
            # Marcar como atendido
            ticket.status = 'Atendido'
            ticket.attended_at = datetime.utcnow()
            queue.active_tickets = max(0, queue.active_tickets - 1)
            
            # Calcular tempo de serviço
            last_ticket = Ticket.query.filter_by(queue_id=queue.id, status='Atendido')\
                .filter(Ticket.attended_at < ticket.attended_at).order_by(Ticket.attended_at.desc()).first()
            if last_ticket and last_ticket.attended_at:
                ticket.service_time = (ticket.attended_at - last_ticket.attended_at).total_seconds() / 60.0
                queue.last_service_time = ticket.service_time
            
            db.session.commit()
            
            # Enviar notificação
            if ticket.user_id != 'PRESENCIAL':
                message = f"Sua senha {queue.prefix}{ticket.ticket_number} foi atendida com sucesso em {queue.service.name}."
                QueueService.send_notification(
                    fcm_token=None,
                    message=message,
                    ticket_id=ticket.id,
                    via_websocket=True,
                    user_id=ticket.user_id
                )
            
            # Atualizar métricas da fila
            QueueService.update_queue_metrics(queue.id)
            
            # Emitir evento de atualização via WebSocket
            if socketio:
                socketio.emit('queue_update', {
                    'queue_id': queue.id,
                    'active_tickets': queue.active_tickets,
                    'current_ticket': queue.current_ticket,
                    'message': f"Senha {queue.prefix}{ticket.ticket_number} atendida"
                }, namespace='/', room=str(queue.id))
            
            logger.info(f"Ticket {ticket.id} marcado como atendido na fila {queue.service.name}")
            return ticket
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao completar ticket {ticket_id}: {str(e)}")
            raise

    @staticmethod
    def update_queue_metrics(queue_id):
        """Atualiza métricas da fila, como avg_wait_time e last_service_time."""
        try:
            queue = Queue.query.get(queue_id)
            if not queue:
                logger.error(f"Fila não encontrada para queue_id={queue_id}")
                return
            tickets = Ticket.query.filter_by(queue_id=queue_id, status='Atendido').all()
            service_times = [t.service_time for t in tickets if t.service_time is not None and t.service_time > 0]
            if service_times:
                queue.avg_wait_time = np.mean(service_times)
                queue.last_service_time = max(service_times)
            else:
                queue.avg_wait_time = 5.0
                queue.last_service_time = None
            queue.update_estimated_wait_time()
            db.session.commit()
            logger.debug(f"Métricas atualizadas para queue_id={queue_id}: avg_wait_time={queue.avg_wait_time:.1f} min")
        except Exception as e:
            logger.error(f"Erro ao atualizar métricas para queue_id={queue_id}: {e}")
            db.session.rollback()

    @staticmethod
    def calculate_wait_time(queue_id, ticket_number, priority=0, user_id=None, user_lat=None, user_lon=None):
        """Calcula o tempo de espera estimado para um ticket, considerando preferências do usuário."""
        try:
            if not isinstance(queue_id, str) or not queue_id:
                logger.error(f"queue_id inválido: {queue_id}")
                return "N/A"
            queue = Queue.query.get(queue_id)
            if not queue:
                logger.error(f"Fila não encontrada para queue_id={queue_id}")
                return "N/A"
            if not QueueService.is_queue_open(queue):
                logger.warning(f"Fila {queue_id} está fechada")
                return "N/A"
            ticket_number = int(ticket_number) if isinstance(ticket_number, (int, float)) else 0
            priority = int(priority) if isinstance(priority, (int, float)) else 0
            if queue.current_ticket == 0:
                queue.current_ticket = 1
                db.session.commit()
                logger.debug(f"Atendimento inicializado para queue_id={queue_id}, current_ticket=1")
            position = max(0, ticket_number - queue.current_ticket)
            if position == 0:
                logger.debug(f"Ticket {ticket_number} na posição 0")
                return 0
            local_tz = pytz.timezone('Africa/Luanda')
            now = datetime.now(local_tz)
            user_service_preference = QueueService.get_user_service_preference(user_id, queue.service_id) if user_id and queue.service_id else 0.0
            wait_time = wait_time_predictor.predict(
                queue_id=queue_id,
                position=position,
                active_tickets=queue.active_tickets,
                priority=priority,
                hour_of_day=now.hour,
                user_id=user_id,
                user_lat=user_lat,
                user_lon=user_lon,
                user_service_preference=user_service_preference
            )
            if not isinstance(wait_time, (int, float)):
                logger.warning(f"wait_time_predictor retornou valor inválido para queue_id={queue_id}: {wait_time}")
                return queue.avg_wait_time or 5
            wait_time = round(wait_time, 1)
            queue.update_estimated_wait_time()
            logger.debug(f"Wait time calculado para ticket {ticket_number} na fila {queue_id}: {wait_time} min (preferência: {user_service_preference:.2f})")
            return wait_time
        except Exception as e:
            logger.error(f"Erro ao calcular wait_time para queue_id={queue_id}: {e}")
            return "N/A"

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
    def send_notification(fcm_token, message, ticket_id=None, via_websocket=False, user_id=None):
        """Envia notificações via FCM e/ou WebSocket com auditoria, throttling e registro no NotificationLog."""
        try:
            if not user_id or not message or not isinstance(message, str) or not message.strip():
                logger.warning(f"Parâmetros inválidos para notificação: user_id={user_id}, message={message}, ticket_id={ticket_id}")
                return
            user = User.query.get(user_id)
            if not user:
                logger.warning(f"Usuário não encontrado para user_id={user_id}, ticket_id={ticket_id}")
                return
            if user.notification_preferences:
                max_wait_time = user.notification_preferences.get('max_wait_time')
                if max_wait_time and isinstance(max_wait_time, (int, float)):
                    wait_time_str = re.search(r'(\d+)\s*min', message)
                    if wait_time_str:
                        wait_time = int(wait_time_str.group(1))
                        if wait_time > max_wait_time:
                            logger.debug(f"Notificação suprimida para user_id={user_id}: wait_time={wait_time} excede max_wait_time={max_wait_time}")
                            return
            if not fcm_token and user.fcm_token:
                fcm_token = user.fcm_token
                logger.debug(f"FCM token recuperado para user_id={user_id}")
            cache_key = f"notification:throttle:{user_id}:{ticket_id or 'generic'}"
            if redis_client.get(cache_key):
                logger.debug(f"Notificação suprimida para user_id={user_id}, ticket_id={ticket_id} devido a throttling")
                return
            redis_client.setex(cache_key, 60, "1")
            logger.info(f"Enviando notificação para user_id={user_id}: {message}")
            notification = NotificationLog(
                user_id=user_id,
                message=message,
                type='ticket' if ticket_id else 'general',
                sent_at=datetime.utcnow()
            )
            db.session.add(notification)
            websocket_success = False
            if via_websocket and socketio:
                try:
                    socketio.emit('notification', {'user_id': user_id, 'message': message}, namespace='/', room=str(user_id))
                    logger.debug(f"Notificação WebSocket enviada para user_id={user_id}")
                    websocket_success = True
                    audit_log = AuditLog(
                        user_id=user_id,
                        action='enviar_notificacao',
                        resource_type='ticket' if ticket_id else 'geral',
                        resource_id=ticket_id or 'N/A',
                        details=f"Notificação WebSocket enviada: {message}",
                        timestamp=datetime.utcnow()
                    )
                    db.session.add(audit_log)
                except Exception as e:
                    logger.error(f"Erro ao enviar notificação WebSocket para user_id={user_id}: {str(e)}")
                    audit_log = AuditLog(
                        user_id=user_id,
                        action='enviar_notificacao',
                        resource_type='ticket' if ticket_id else 'geral',
                        resource_id=ticket_id or 'N/A',
                        details=f"Falha ao enviar notificação WebSocket: {message}",
                        timestamp=datetime.utcnow()
                    )
                    db.session.add(audit_log)
            if (not via_websocket or not websocket_success) and fcm_token:
                try:
                    fcm_message = messaging.Message(
                        notification=messaging.Notification(
                            title="Facilita 2.0",
                            body=message
                        ),
                        data={"ticket_id": str(ticket_id) if ticket_id else ""},
                        token=fcm_token
                    )
                    response = messaging.send(fcm_message)
                    logger.info(f"Notificação FCM enviada para user_id={user_id}: {response}")
                    audit_log = AuditLog(
                        user_id=user_id,
                        action='enviar_notificacao',
                        resource_type='ticket' if ticket_id else 'geral',
                        resource_id=ticket_id or 'N/A',
                        details=f"Notificação FCM enviada: {message}",
                        timestamp=datetime.utcnow()
                    )
                    db.session.add(audit_log)
                except Exception as e:
                    logger.error(f"Erro ao enviar notificação FCM para user_id={user_id}: {str(e)}")
                    audit_log = AuditLog(
                        user_id=user_id,
                        action='enviar_notificacao',
                        resource_type='ticket' if ticket_id else 'geral',
                        resource_id=ticket_id or 'N/A',
                        details=f"Falha ao enviar notificação FCM: {message}",
                        timestamp=datetime.utcnow()
                    )
                    db.session.add(audit_log)
            db.session.commit()
        except Exception as e:
            logger.error(f"Erro geral ao enviar notificação para user_id={user_id}: {str(e)}")
            db.session.rollback()

class QueueService:
    """Serviço para gerenciamento de filas, tickets, notificações e dashboard, com foco em serviços semelhantes."""
    
    @staticmethod
    def add_to_queue(queue_id=None, service=None, user_id=None, priority=0, is_physical=False, fcm_token=None, branch_id=None, user_lat=None, user_lon=None):
        """Adiciona um ticket à fila, usando queue_id diretamente se fornecido, ou buscando por serviço e filial."""
        try:
            if is_physical:
                logger.error("Senhas físicas só podem ser geradas via totem (use generate_physical_ticket_for_totem)")
                raise ValueError("Senhas físicas só podem ser geradas no totem da filial")
            if not user_id or not isinstance(user_id, str):
                logger.error("user_id inválido")
                raise ValueError("user_id inválido")
            if not isinstance(priority, (int, float)) or priority < 0:
                logger.error(f"Prioridade inválida: {priority}")
                raise ValueError("Prioridade deve ser um número não negativo")
            if branch_id and not isinstance(branch_id, str):
                logger.error(f"branch_id inválido: {branch_id}")
                raise ValueError("branch_id inválido")
            user = User.query.get(user_id)
            if not user:
                logger.error(f"Usuário não encontrado: user_id={user_id}")
                raise ValueError("Usuário não encontrado")

            # Buscar a fila
            queue = None
            if queue_id:
                queue = Queue.query.get(queue_id)
                if not queue:
                    logger.error(f"Fila não encontrada para queue_id: {queue_id}")
                    raise ValueError("Fila não encontrada")
            elif service and isinstance(service, str) and service.strip():
                service_id = QueueService.get_service_id_from_query(service)
                if not service_id:
                    logger.warning(f"Serviço '{service}' não encontrado, usando consulta textual")
                query = Queue.query.join(Department).join(Branch).join(InstitutionService)
                if service_id:
                    query = query.filter(Queue.service_id == service_id)
                else:
                    search_terms = re.sub(r'[^\w\sÀ-ÿ]', '', service.lower()).split()
                    if search_terms:
                        search_query = ' & '.join(search_terms)
                        query = query.filter(
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
                if branch_id:
                    query = query.filter(Branch.id == branch_id)
                queue = query.first()
                if not queue:
                    logger.error(f"Fila não encontrada para serviço: {service}, branch_id: {branch_id}")
                    raise ValueError("Fila não encontrada")
            else:
                logger.error("Nenhum queue_id ou serviço válido fornecido")
                raise ValueError("Forneça um queue_id ou um serviço válido")

            branch_name = queue.department.branch.name if queue.department and queue.department.branch else "Desconhecida"
            if not QueueService.is_queue_open(queue):
                logger.warning(f"Fila {queue.id} está fechada (filial: {branch_name})")
                raise ValueError(f"A fila {queue.service.name} na filial {branch_name} está fechada (fora do horário)")
            if queue.active_tickets >= queue.daily_limit:
                alternatives = QueueService.suggest_alternative_queues(queue.id, user_id, user_lat, user_lon)
                alt_message = "Alternativas: " + ", ".join([f"{alt['service']} ({alt['branch']}, {alt['wait_time']})" for alt in alternatives])
                logger.warning(f"Fila {queue.id} cheia: {queue.active_tickets}/{queue.daily_limit}")
                raise ValueError(f"Limite diário atingido. {alt_message}")
            if Ticket.query.filter_by(user_id=user_id, queue_id=queue.id, status='Pendente').first():
                logger.warning(f"Usuário {user_id} já possui senha ativa na fila {queue.id}")
                raise ValueError("Você já possui uma senha ativa")

            # Obter o maior ticket_number emitido hoje para a fila
            local_tz = pytz.timezone('Africa/Luanda')
            today_start = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            with db.session.begin():
                last_ticket = Ticket.query.filter(
                    Ticket.queue_id == queue.id,
                    Ticket.issued_at >= today_start,
                    Ticket.issued_at < today_end
                ).order_by(Ticket.ticket_number.desc()).first()
                ticket_number = last_ticket.ticket_number + 1 if last_ticket else 1

                # Criar ticket
                qr_code = QueueService.generate_qr_code()
                expires_at = None
                ticket = Ticket(
                    id=str(uuid.uuid4()),
                    queue_id=queue.id,
                    user_id=user_id,
                    ticket_number=ticket_number,
                    qr_code=qr_code,
                    priority=priority,
                    is_physical=False,
                    expires_at=expires_at,
                    issued_at=datetime.utcnow(),
                    status='Pendente'
                )
                queue.active_tickets += 1
                db.session.add(ticket)

                # Registrar comportamento do usuário, se aplicável
                service_id = queue.service_id
                if service_id:
                    behavior = UserBehavior(
                        user_id=user_id,
                        service_id=service_id,
                        action='ticket_emission',
                        timestamp=datetime.utcnow()
                    )
                    db.session.add(behavior)

            # Commit já é feito pelo with db.session.begin()

            db.session.refresh(ticket)
            if not ticket.queue:
                logger.error(f"Relação ticket.queue não carregada para ticket {ticket.id}")
                raise ValueError("Erro ao carregar a fila associada")

            # Logar o ticket criado
            logger.info(f"Ticket {ticket.id} criado com prefix={queue.prefix}, ticket_number={ticket_number} para user_id={user_id}")

            wait_time = QueueService.calculate_wait_time(queue.id, ticket_number, priority, user_id, user_lat, user_lon)
            position = max(0, ticket.ticket_number - queue.current_ticket)
            message = f"Senha {queue.prefix}{ticket_number} emitida (virtual, via telefone) para {queue.service.name}. QR: {qr_code}. Espera: {wait_time if wait_time != 'N/A' else 'Aguardando início'} min"
            QueueService.send_notification(fcm_token, message, ticket.id, via_websocket=True, user_id=user_id)
            if socketio:
                emit('queue_update', {
                    'queue_id': queue.id,
                    'active_tickets': queue.active_tickets,
                    'current_ticket': queue.current_ticket,
                    'message': f"Nova senha emitida: {queue.prefix}{ticket_number}"
                }, namespace='/', room=str(queue.id))
            QueueService.update_queue_metrics(queue.id)
            logger.info(f"Ticket {ticket.id} (virtual) adicionado à fila {queue.service.name}")
            return ticket, None
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao adicionar ticket à fila {queue_id or service}: {e}")
            raise

    @staticmethod
    def generate_physical_ticket_for_totem(queue_id: str, branch_id: str, client_ip: str) -> Dict[str, Any]:
        try:
            # Validações
            if not isinstance(queue_id, str) or not queue_id:
                raise ValueError("queue_id inválido")
            if not isinstance(branch_id, str) or not branch_id:
                raise ValueError("branch_id inválido")
            if not isinstance(client_ip, str) or not client_ip:
                raise ValueError("client_ip inválido")
            try:
                uuid.UUID(queue_id)
                uuid.UUID(branch_id)
            except ValueError:
                raise ValueError("queue_id ou branch_id não é um UUID válido")

            # Buscar fila com relacionamentos
            queue = Queue.query.options(
                selectinload(Queue.service),
                selectinload(Queue.department).selectinload(Department.branch).selectinload(Branch.institution)
            ).get(queue_id)
            if not queue:
                logger.error(f"Fila não encontrada para queue_id={queue_id}")
                raise ValueError("Fila não encontrada")
            if not queue.service or not queue.department or not queue.department.branch or not queue.department.branch.institution:
                logger.error(f"Dados incompletos para queue_id={queue_id}: falta serviço, departamento, filial ou instituição")
                raise ValueError("Fila, departamento, instituição ou serviço associado ao ticket não encontrado")

            # Logar o prefix para depuração
            logger.info(f"Fila {queue_id} carregada com prefix={queue.prefix}")

            branch = Branch.query.get(branch_id)
            if not branch:
                logger.error(f"Filial não encontrada para branch_id={branch_id}")
                raise ValueError("Filial não encontrada")
            if queue.department.branch_id != branch_id:
                logger.error(f"Fila {queue_id} não pertence à filial {branch_id}")
                raise ValueError("Fila não pertence à filial")

            # Verificar disponibilidade
            if not QueueService.is_queue_open(queue):
                raise ValueError("Fila está fechada")
            if queue.active_tickets >= queue.daily_limit:
                alternatives = QueueService.suggest_alternative_queues(queue.id)
                alt_message = "Alternativas: " + ", ".join([f"{alt['service']} ({alt['branch']}, {alt['wait_time']})" for alt in alternatives])
                raise ValueError(f"Limite diário atingido. {alt_message}")

            # Obter o maior ticket_number já emitido para a fila
            last_ticket = Ticket.query.filter_by(queue_id=queue.id).order_by(Ticket.ticket_number.desc()).first()
            ticket_number = last_ticket.ticket_number + 1 if last_ticket else 1

            # Criar ticket
            qr_code = QueueService.generate_qr_code()
            ticket = Ticket(
                id=str(uuid.uuid4()),
                queue_id=queue.id,
                user_id=None,
                ticket_number=ticket_number,
                qr_code=qr_code,
                priority=0,
                is_physical=True,
                status='Pendente',
                issued_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=4),
                receipt_data=None
            )

            # Atualizar fila
            queue.active_tickets += 1

            # Log de auditoria
            audit_log = AuditLog(
                id=str(uuid.uuid4()),
                user_id=None,
                action='GENERATE_PHYSICAL_TICKET',
                resource_type='Ticket',
                resource_id=ticket.id,
                details=f"Ticket {qr_code} gerado via totem para fila {queue.service.name} (IP: {client_ip}, Filial: {branch_id})",
                timestamp=datetime.utcnow()
            )

            # Persistir ticket e auditoria
            db.session.add(ticket)
            db.session.add(audit_log)
            db.session.commit()

            # Recarregar ticket para garantir que ticket.queue esteja disponível
            db.session.refresh(ticket)
            if not ticket.queue:
                logger.error(f"Relação ticket.queue não carregada para ticket {ticket.id}")
                raise ValueError("Erro ao carregar a fila associada")

            # Logar o prefix do ticket
            logger.info(f"Ticket {ticket.id} criado com prefix={ticket.queue.prefix}, ticket_number={ticket.ticket_number}")

            # Gerar PDF e comprovante após commit
            position = max(0, ticket.ticket_number - queue.current_ticket)
            pdf_buffer = generate_physical_ticket_pdf(ticket, position)
            pdf_base64 = pdf_buffer.getvalue().hex()
            ticket.receipt_data = QueueService.generate_receipt(ticket)

            # Persistir receipt_data
            db.session.add(ticket)
            db.session.commit()

            # Emitir evento
            if socketio:
                emit('queue_update', {
                    'queue_id': queue.id,
                    'active_tickets': queue.active_tickets,
                    'current_ticket': queue.current_ticket,
                    'message': f"Nova senha emitida: {ticket.queue.prefix}{ticket_number}"
                }, namespace='/', room=str(queue.id))

            QueueService.update_queue_metrics(queue.id)

            return {
                'ticket': {
                    'id': ticket.id,
                    'queue_id': ticket.queue_id,
                    'ticket_number': ticket.ticket_number,
                    'qr_code': ticket.qr_code,
                    'status': ticket.status,
                    'issued_at': ticket.issued_at.isoformat(),
                    'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None,
                    'prefix': ticket.queue.prefix
                },
                'pdf': pdf_base64
            }

        except ValueError as e:
            db.session.rollback()
            logger.error(f"Erro de validação ao emitir ticket para queue_id={queue_id}: {str(e)}")
            raise
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro no banco de dados ao emitir ticket para queue_id={queue_id}: {str(e)}")
            raise
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao emitir ticket para queue_id={queue_id}: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def call_next(queue_id, counter):
        """Chama o próximo ticket na fila especificada, atribuindo um guichê específico.

        Args:
            queue_id (str): ID da fila (UUID).
            counter (int): Número do guichê (deve estar entre 1 e queue.num_counters).

        Returns:
            Ticket: O ticket chamado.

        Raises:
            ValueError: Se queue_id, counter ou fila forem inválidos, ou se não houver tickets pendentes.
            Exception: Para erros inesperados, com rollback da transação.
        """
        try:
            # Validação do queue_id como UUID
            if not isinstance(queue_id, str):
                logger.error(f"queue_id inválido: {queue_id} (deve ser string)")
                raise ValueError("queue_id inválido")
            try:
                uuid.UUID(queue_id)
            except ValueError:
                logger.error(f"queue_id inválido: {queue_id} (não é UUID)")
                raise ValueError("queue_id inválido")

            # Buscar fila com relacionamentos
            queue = Queue.query.options(
                selectinload(Queue.service),
                selectinload(Queue.department).selectinload(Department.branch)
            ).get(queue_id)

            if not queue:
                logger.warning(f"Fila não encontrada: queue_id={queue_id}")
                raise ValueError("Fila não encontrada")

            # Verificar se a fila está aberta
            if not QueueService.is_queue_open(queue):
                logger.warning(f"Fila {queue_id} fechada (serviço: {queue.service.name})")
                raise ValueError("Fila está fechada (fora do horário da filial)")

            # Verificar se há tickets ativos
            if queue.active_tickets == 0:
                logger.warning(f"Fila {queue_id} vazia (serviço: {queue.service.name})")
                raise ValueError("Fila vazia")

            # Validar counter
            if not isinstance(counter, int):
                logger.error(f"Guichê inválido: {counter} (deve ser inteiro)")
                raise ValueError("Guichê inválido")
            if counter < 1 or counter > queue.num_counters:
                logger.error(f"Guichê inválido: {counter} (deve ser entre 1 e {queue.num_counters})")
                raise ValueError(f"Guichê inválido (deve ser entre 1 e {queue.num_counters})")

            # Buscar próximo ticket com prioridade
            next_ticket = Ticket.query.filter_by(queue_id=queue_id, status='Pendente')\
                .order_by(Ticket.priority.desc(), Ticket.ticket_number)\
                .options(selectinload(Ticket.queue)).first()

            if not next_ticket:
                logger.warning(f"Nenhum ticket pendente na fila {queue_id}")
                raise ValueError("Nenhum ticket pendente")

            # Atualizar estado do ticket e da fila
            now = datetime.utcnow()
            next_ticket.expires_at = now + timedelta(minutes=QueueService.CALL_TIMEOUT_MINUTES)
            queue.current_ticket = next_ticket.ticket_number
            queue.active_tickets = max(0, queue.active_tickets - 1)
            queue.last_counter = counter  # Atualizar last_counter para refletir o guichê usado
            next_ticket.status = 'Chamado'
            next_ticket.counter = counter
            next_ticket.attended_at = now

            db.session.commit()

            # Enviar notificação
            message = f"Dirija-se ao guichê {next_ticket.counter:02d}! Senha {queue.prefix}{next_ticket.ticket_number} chamada para {queue.service.name}."
            if next_ticket.user_id != 'PRESENCIAL':
                QueueService.send_notification(
                    fcm_token=None,
                    message=message,
                    ticket_id=next_ticket.id,
                    via_websocket=True,
                    user_id=next_ticket.user_id
                )
            else:
                logger.debug(f"Notificação suprimida para ticket físico {next_ticket.id} (usuário PRESENCIAL)")

            # Emitir evento de atualização
            if socketio:
                emit('queue_update', {
                    'queue_id': queue_id,
                    'active_tickets': queue.active_tickets,
                    'current_ticket': queue.current_ticket,
                    'counter': next_ticket.counter,
                    'message': f"Senha {queue.prefix}{next_ticket.ticket_number} chamada"
                }, namespace='/', room=str(queue_id))

            # Atualizar métricas
            QueueService.update_queue_metrics(queue_id)

            logger.info(f"Ticket {next_ticket.id} chamado na fila {queue.service.name} (guichê {counter})")
            return next_ticket

        except ValueError as e:
            logger.error(f"Erro de validação ao chamar ticket na fila {queue_id}: {str(e)}")
            raise
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro inesperado ao chamar ticket na fila {queue_id}: {str(e)}")
            raise

    @staticmethod
    def check_proximity_notifications(user_id, user_lat=None, user_lon=None, desired_service=None, institution_id=None, branch_id=None, institution_type_id=None):
        """Verifica e envia notificações de proximidade, usando UserLocationFallback se necessário."""
        try:
            if not isinstance(user_id, str) or not user_id:
                logger.error("user_id inválido")
                raise ValueError("user_id inválido")
            user = User.query.get(user_id)
            if not user:
                logger.error(f"Usuário não encontrado: user_id={user_id}")
                raise ValueError("Usuário não encontrado")
            if not (user_lat and user_lon):
                fallback = UserLocationFallback.query.filter_by(user_id=user_id).first()
                if fallback and fallback.latitude and fallback.longitude:
                    user_lat, user_lon = fallback.latitude, fallback.longitude
                    logger.debug(f"Usando localização fallback para user_id={user_id}: lat={user_lat}, lon={user_lon}")
                else:
                    logger.warning(f"Localização ausente para user_id={user_id}")
                    raise ValueError("Localização não disponível")
            if not all(isinstance(x, (int, float)) for x in [user_lat, user_lon]):
                logger.error("Localização inválida")
                raise ValueError("Localização inválida")
            user.last_known_lat = float(user_lat)
            user.last_known_lon = float(user_lon)
            user.last_location_update = datetime.utcnow()
            db.session.commit()
            logger.debug(f"Localização atualizada para user_id={user_id}")
            user_prefs = UserPreference.query.filter_by(user_id=user_id).all()
            preferred_institutions = {pref.institution_id for pref in user_prefs if pref.institution_id}
            preferred_categories = {pref.service_category_id for pref in user_prefs if pref.service_category_id}
            preferred_institution_types = {pref.institution_type_id for pref in user_prefs if pref.institution_type_id}
            service_id = QueueService.get_service_id_from_query(desired_service) if desired_service else None
            service = InstitutionService.query.get(service_id) if service_id else None
            target_category_id = service.category_id if service else None
            nearby_branches = Branch.query.filter(
                func.sqrt(
                    func.pow(Branch.latitude - user_lat, 2) +
                    func.pow(Branch.longitude - user_lon, 2)
                ) < QueueService.PROXIMITY_THRESHOLD_KM / 111.0
            ).all()
            branch_ids = [b.id for b in nearby_branches]
            query = Queue.query.join(Department).join(Branch).join(Institution).join(InstitutionService)
            if branch_ids:
                query = query.filter(Branch.id.in_(branch_ids))
            if institution_id:
                if not isinstance(institution_id, str):
                    logger.error(f"institution_id inválido: {institution_id}")
                    raise ValueError("institution_id inválido")
                query = query.filter(Institution.id == institution_id)
            if branch_id:
                if not isinstance(branch_id, str):
                    logger.error(f"branch_id inválido: {branch_id}")
                    raise ValueError("branch_id inválido")
                query = query.filter(Branch.id == branch_id)
            if institution_type_id:
                if not isinstance(institution_type_id, str):
                    logger.error(f"institution_type_id inválido: {institution_type_id}")
                    raise ValueError("institution_type_id inválido")
                query = query.filter(Institution.institution_type_id == institution_type_id)
            if service_id:
                query = query.filter(InstitutionService.category_id == target_category_id)
            elif desired_service:
                search_terms = re.sub(r'[^\w\sÀ-ÿ]', '', desired_service.lower()).split()
                if search_terms:
                    search_query = ' & '.join(search_terms)
                    query = query.filter(
                        or_(
                            func.to_tsvector('portuguese', func.concat(
                                InstitutionService.name, ' ', InstitutionService.description
                            )).op('@@')(func.to_tsquery('portuguese', search_query)),
                            Queue.id.in_(
                                db.session.query(ServiceTag.queue_id).filter(
                                    ServiceTag.tag.ilike(f'%{desired_service.lower()}%')
                                )
                            )
                        )
                    )
            queues = query.all()
            local_tz = pytz.timezone('Africa/Luanda')
            now = datetime.now(local_tz)
            notified_branches = set()
            for queue in queues:
                branch = queue.department.branch
                if not branch or not branch.institution:
                    logger.warning(f"Fila {queue.id} sem filial ou instituição")
                    continue
                if not QueueService.is_queue_open(queue):
                    logger.debug(f"Fila {queue.id} fechada")
                    continue
                if queue.active_tickets >= queue.daily_limit:
                    logger.debug(f"Fila {queue.id} atingiu limite diário")
                    continue
                if preferred_institutions and branch.institution_id not in preferred_institutions:
                    continue
                if preferred_categories and queue.service.category_id and queue.service.category_id not in preferred_categories:
                    continue
                if preferred_institution_types and branch.institution.institution_type_id not in preferred_institution_types:
                    continue
                distance = QueueService.calculate_distance(user_lat, user_lon, branch)
                if distance is None or distance > QueueService.PROXIMITY_THRESHOLD_KM:
                    continue
                predicted_demand = demand_model.predict(queue.id, hours_ahead=1)
                if predicted_demand > 10:
                    logger.debug(f"Fila {queue.id} com alta demanda: {predicted_demand} tickets/h")
                    continue
                cache_key = f'notification:proximity:{user_id}:{branch.id}:{queue.id}'
                if redis_client.get(cache_key):
                    continue
                wait_time = QueueService.calculate_wait_time(queue.id, queue.active_tickets + 1, priority=0, user_id=user_id, user_lat=user_lat, user_lon=user_lon)
                similarity = service_recommendation_predictor.calculate_service_similarity(service_id, queue.service_id) if service_id else 0.5
                message = (
                    f"Fila próxima! {queue.service.name} em {branch.institution.name} ({branch.name}) "
                    f"a {distance:.2f} km. Espera: {wait_time if wait_time != 'N/A' else 'Aguardando início'} min."
                )
                if similarity > 0.8 and desired_service:
                    message += f" (Semelhante a {desired_service})"
                QueueService.send_notification(
                    user.fcm_token,
                    message,
                    via_websocket=True,
                    user_id=user_id
                )
                redis_client.setex(cache_key, 3600, 'sent')
                notified_branches.add(branch.id)
                logger.info(f"Notificação de proximidade enviada para user_id={user_id}: queue_id={queue.id}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao verificar notificações de proximidade para user_id={user_id}: {e}")
            raise

    @staticmethod
    def check_proactive_notifications():
        """Verifica tickets pendentes e envia notificações proativas, usando localização do usuário e BranchSchedule."""
        try:
            now = datetime.utcnow()
            tickets = Ticket.query.filter_by(status='Pendente').all()
            for ticket in tickets:
                queue = ticket.queue
                branch_name = queue.department.branch.name if queue.department and queue.department.branch else "Desconhecida"
                if not QueueService.is_queue_open(queue):
                    ticket.status = 'Cancelado'
                    ticket.queue.active_tickets -= 1
                    ticket.cancelled_at = datetime.utcnow()
                    db.session.commit()
                    if ticket.user_id != 'PRESENCIAL':
                        QueueService.send_notification(
                            None,
                            f"Sua senha {ticket.queue.prefix}{ticket.ticket_number} foi cancelada (horário da filial {branch_name} encerrado).",
                            ticket.id,
                            via_websocket=True,
                            user_id=ticket.user_id
                        )
                    logger.info(f"Ticket {ticket.id} cancelado (filial {branch_name} fora do horário)")
                    continue
                wait_time = QueueService.calculate_wait_time(ticket.queue_id, ticket.ticket_number, ticket.priority, user_id=ticket.user_id)
                if wait_time == "N/A":
                    continue
                predicted_demand = demand_model.predict(ticket.queue_id, hours_ahead=1)
                if wait_time <= 5 and ticket.user_id != 'PRESENCIAL':
                    user = User.query.get(ticket.user_id)
                    distance = None
                    if user and user.last_known_lat and user.last_known_lon and user.last_location_update:
                        if (datetime.utcnow() - user.last_location_update).total_seconds() < 600:
                            distance = QueueService.calculate_distance(user.last_known_lat, user.last_known_lon, ticket.queue.department.branch)
                    elif user:
                        fallback = UserLocationFallback.query.filter_by(user_id=user.id).first()
                        if fallback and fallback.latitude and fallback.longitude:
                            distance = QueueService.calculate_distance(fallback.latitude, fallback.longitude, ticket.queue.department.branch)
                            logger.debug(f"Usando localização fallback para user_id={user.id}")
                    distance_msg = f" Você está a {distance:.2f} km." if distance else ""
                    message = (
                        f"Sua vez está próxima! {ticket.queue.service.name}, Senha {ticket.queue.prefix}{ticket.ticket_number}. "
                        f"Prepare-se em {wait_time} min. Demanda prevista: {predicted_demand:.1f} senhas/h.{distance_msg}"
                    )
                    QueueService.send_notification(None, message, ticket.id, via_websocket=True, user_id=ticket.user_id)
                if ticket.user_id != 'PRESENCIAL':
                    user = User.query.get(ticket.user_id)
                    if user and user.last_known_lat and user.last_known_lon and user.last_location_update:
                        if (datetime.utcnow() - user.last_location_update).total_seconds() < 600:
                            distance = QueueService.calculate_distance(user.last_known_lat, user.last_known_lon, ticket.queue.department.branch)
                            if distance and distance > 5:
                                travel_time = distance * 2
                                if wait_time <= travel_time:
                                    message = (
                                        f"Você está a {distance:.2f} km! Senha {ticket.queue.prefix}{ticket.ticket_number} "
                                        f"será chamada em {wait_time} min. Comece a se deslocar!"
                                    )
                                    QueueService.send_notification(None, message, ticket.id, via_websocket=True, user_id=ticket.user_id)
            called_tickets = Ticket.query.filter_by(status='Chamado').all()
            for ticket in called_tickets:
                if ticket.expires_at and ticket.expires_at < now:
                    ticket.status = 'Cancelado'
                    ticket.queue.active_tickets -= 1
                    ticket.cancelled_at = datetime.utcnow()
                    db.session.commit()
                    if ticket.user_id != 'PRESENCIAL':
                        branch_name = ticket.queue.department.branch.name if ticket.queue.department and ticket.queue.department.branch else "Desconhecida"
                        QueueService.send_notification(
                            None,
                            f"Sua senha {ticket.queue.prefix}{ticket.ticket_number} foi cancelada (tempo esgotado na filial {branch_name}).",
                            ticket.id,
                            via_websocket=True,
                            user_id=ticket.user_id
                        )
                    logger.info(f"Ticket {ticket.id} cancelado por falta de validação")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao verificar notificações proativas: {e}")

    @staticmethod
    def get_wait_time_features(queue_id, ticket_number, priority):
        try:
            queue = Queue.query.get(queue_id)
            if not queue:
                logger.error(f"Fila não encontrada para queue_id={queue_id}")
                raise ValueError("Fila não encontrada")
            
            position = max(0, ticket_number - queue.current_ticket)
            local_tz = pytz.timezone('Africa/Luanda')
            now = datetime.now(local_tz)
            hour_of_day = now.hour
            
            features = {
                'position': position,
                'active_tickets': queue.active_tickets,
                'priority': priority,
                'hour_of_day': hour_of_day,
                'num_counters': queue.num_counters or 1,
                'avg_service_time': queue.avg_wait_time or 5.0,
                'daily_limit': queue.daily_limit or 100,
            }
            
            logger.debug(f"Características geradas para queue_id={queue_id}: {features}")
            return features
        except Exception as e:
            logger.error(f"Erro ao gerar características para queue_id={queue_id}: {str(e)}")
            raise

    @staticmethod
    def trade_tickets(ticket_from_id, ticket_to_id, user_from_id):
        """Troca dois tickets entre usuários, com validação rigorosa."""
        try:
            ticket_from = Ticket.query.get(ticket_from_id)
            ticket_to = Ticket.query.get(ticket_to_id)
            if not ticket_from or not ticket_to:
                logger.error(f"Tickets não encontrados: from={ticket_from_id}, to={ticket_to_id}")
                raise ValueError("Ticket não encontrado")
            if ticket_from.user_id != user_from_id or not ticket_to.trade_available or \
               ticket_from.queue_id != ticket_to.queue_id or ticket_from.status != 'Pendente' or \
               ticket_to.status != 'Pendente' or ticket_from.user_id == 'PRESENCIAL' or ticket_to.user_id == 'PRESENCIAL':
                logger.warning(f"Tentativa inválida de troca entre {ticket_from_id} e {ticket_to_id}")
                raise ValueError("Troca inválida ou não permitida para senhas físicas")
            user_from, user_to = ticket_from.user_id, ticket_to.user_id
            num_from, num_to = ticket_from.ticket_number, ticket_to.ticket_number
            ticket_from.user_id, ticket_from.ticket_number = user_to, num_to
            ticket_to.user_id, ticket_to.ticket_number = user_from, num_from
            ticket_from.trade_available, ticket_to.trade_available = False, False
            db.session.commit()
            message_from = f"Sua senha foi trocada! Nova senha: {ticket_from.queue.prefix}{ticket_from.ticket_number} para {ticket_from.queue.service.name}"
            message_to = f"Sua senha foi trocada! Nova senha: {ticket_to.queue.prefix}{ticket_to.ticket_number} para {ticket_to.queue.service.name}"
            QueueService.send_notification(
                None,
                message_from,
                ticket_from.id,
                via_websocket=True,
                user_id=ticket_from.user_id
            )
            QueueService.send_notification(
                None,
                message_to,
                ticket_to.id,
                via_websocket=True,
                user_id=ticket_to.user_id
            )
            logger.info(f"Troca realizada entre {ticket_from_id} e {ticket_to_id}")
            return {"ticket_from": ticket_from, "ticket_to": ticket_to}
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao trocar tickets {ticket_from_id} e {ticket_to_id}: {e}")
            raise

    @staticmethod
    def validate_presence(ticket_id=None, qr_code=None, user_lat=None, user_lon=None):
        """Valida a presença de um usuário com base no ticket_id ou QR code, verificando proximidade."""
        try:
            if not ticket_id and (not isinstance(qr_code, str) or not qr_code):
                logger.error("Ticket ID ou QR code inválido")
                raise ValueError("Ticket ID ou QR code inválido")
            
            ticket = None
            if ticket_id:
                ticket = Ticket.query.get(ticket_id)
            elif qr_code:
                ticket = Ticket.query.filter_by(qr_code=qr_code).first()
            
            if not ticket or ticket.status != 'Chamado':
                logger.warning(f"Tentativa inválida de validar presença com ticket_id={ticket_id} ou QR={qr_code}")
                raise ValueError("Senha inválida ou não chamada")
            
            if not QueueService.is_queue_open(ticket.queue):
                logger.warning(f"Fila {ticket.queue.id} está fechada")
                raise ValueError("Fila está fechada (fora do horário da filial)")
            
            if user_lat and user_lon:
                branch = ticket.queue.department.branch
                distance = QueueService.calculate_distance(user_lat, user_lon, branch)
                if distance and distance > QueueService.PRESENCE_PROXIMITY_THRESHOLD_KM:
                    logger.warning(f"Usuário muito longe: {distance} km para ticket {ticket.id}")
                    raise ValueError(f"Você está muito longe ({distance:.2f} km). Aproxime-se.")
            
            ticket.status = 'Atendido'
            ticket.attended_at = datetime.utcnow()
            queue = ticket.queue
            last_ticket = Ticket.query.filter_by(queue_id=queue.id, status='Atendido')\
                .filter(Ticket.attended_at < ticket.attended_at).order_by(Ticket.attended_at.desc()).first()
            if last_ticket and last_ticket.attended_at:
                ticket.service_time = (ticket.attended_at - last_ticket.attended_at).total_seconds() / 60.0
                queue.last_service_time = ticket.service_time
            
            db.session.commit()
            QueueService.update_queue_metrics(queue.id)
            message = f"Presença validada para senha {queue.prefix}{ticket.ticket_number} em {queue.service.name}."
            if ticket.user_id != 'PRESENCIAL':
                QueueService.send_notification(None, message, ticket.id, via_websocket=True, user_id=ticket.user_id)
            
            logger.info(f"Presença validada para ticket {ticket.id}")
            return ticket
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao validar presença com ticket_id={ticket_id} ou QR={qr_code}: {e}")
            raise

    @staticmethod
    def offer_trade(ticket_id, user_id):
        """Oferece um ticket para troca, notificando usuários elegíveis."""
        try:
            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                logger.error(f"Ticket não encontrado: {ticket_id}")
                raise ValueError("Ticket não encontrado")
            if ticket.user_id != user_id:
                logger.warning(f"Tentativa inválida de oferecer ticket {ticket_id} por {user_id}")
                raise ValueError("Você só pode oferecer sua própria senha.")
            if ticket.status != 'Pendente':
                logger.warning(f"Ticket {ticket_id} no estado {ticket.status} não pode ser oferecido")
                raise ValueError(f"Esta senha está no estado '{ticket.status}'.")
            if ticket.trade_available:
                logger.warning(f"Ticket {ticket_id} já está oferecido")
                raise ValueError("Esta senha já está oferecida.")
            if ticket.user_id == 'PRESENCIAL':
                logger.warning(f"Ticket físico {ticket_id} não pode ser oferecido para troca")
                raise ValueError("Senhas físicas não podem ser oferecidas para troca")
            ticket.trade_available = True
            db.session.commit()
            message = f"Sua senha {ticket.queue.prefix}{ticket.ticket_number} foi oferecida para troca em {ticket.queue.service.name}!"
            QueueService.send_notification(
                None,
                message,
                ticket.id,
                via_websocket=True,
                user_id=user_id
            )
            eligible_tickets = Ticket.query.filter(
                Ticket.queue_id == ticket.queue_id,
                Ticket.user_id != user_id,
                Ticket.status == 'Pendente',
                Ticket.trade_available == False,
                Ticket.user_id != 'PRESENCIAL'
            ).order_by(Ticket.issued_at.asc()).limit(5).all()
            if socketio:
                for eligible_ticket in eligible_tickets:
                    emit('trade_available', {
                        'ticket_id': ticket.id,
                        'queue_id': ticket.queue_id,
                        'service': ticket.queue.service.name,
                        'number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                        'position': max(0, ticket.ticket_number - ticket.queue.current_ticket)
                    }, namespace='/', room=str(eligible_ticket.user_id))
                    logger.debug(f"Evento trade_available emitido para user_id {eligible_ticket.user_id}")
            logger.info(f"Ticket {ticket_id} oferecido para troca")
            return ticket
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao oferecer troca do ticket {ticket_id}: {e}")
            raise

    @staticmethod
    def cancel_ticket(ticket_id, user_id):
        """Cancela um ticket, atualizando métricas da fila."""
        try:
            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                logger.error(f"Ticket não encontrado: {ticket_id}")
                raise ValueError("Ticket não encontrado")
            if ticket.user_id != user_id:
                logger.warning(f"Tentativa inválida de cancelar ticket {ticket_id} por user_id={user_id}")
                raise ValueError("Você só pode cancelar sua própria senha")
            if ticket.status != 'Pendente':
                logger.warning(f"Ticket {ticket_id} no estado {ticket.status} não pode ser cancelado")
                raise ValueError("Esta senha não pode ser cancelada")
            if ticket.user_id == 'PRESENCIAL':
                logger.warning(f"Ticket físico {ticket_id} não pode ser cancelado remotamente")
                raise ValueError("Senhas físicas não podem ser canceladas remotamente")
            ticket.status = 'Cancelado'
            ticket.queue.active_tickets -= 1
            db.session.commit()
            message = f"Sua senha {ticket.queue.prefix}{ticket.ticket_number} foi cancelada para {ticket.queue.service.name}."
            QueueService.send_notification(
                None,
                message,
                ticket.id,
                via_websocket=True,
                user_id=user_id
            )
            if socketio:
                emit('queue_update', {
                    'queue_id': ticket.queue_id,
                    'active_tickets': ticket.queue.active_tickets,
                    'current_ticket': ticket.current_ticket,
                    'message': f"Senha {ticket.queue.prefix}{ticket.ticket_number} cancelada"
                }, namespace='/', room=str(ticket.queue_id))
            QueueService.update_queue_metrics(ticket.queue_id)
            logger.info(f"Ticket {ticket.id} cancelado por user_id={user_id}")
            return ticket
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao cancelar ticket {ticket_id}: {e}")
            raise

    @staticmethod
    def get_dashboard_data(institution_id):
        """Obtém dados para o dashboard de uma instituição, incluindo métricas de comportamento."""
        try:
            if not isinstance(institution_id, str):
                logger.error(f"institution_id inválido: {institution_id}")
                raise ValueError("institution_id inválido")
            institution = Institution.query.get(institution_id)
            if not institution:
                logger.error(f"Instituição não encontrada: {institution_id}")
                raise ValueError("Instituição não encontrada")
            branches = Branch.query.filter_by(institution_id=institution_id).all()
            result = {
                'institution': {
                    'id': institution.id,
                    'name': institution.name or "Desconhecida",
                    'type': {
                        'id': institution.institution_type_id if institution.institution_type else None,
                        'name': institution.institution_type.name if institution.institution_type else "Desconhecido"
                    }
                },
                'branches': [],
                'popular_services': [],
                'ticket_conversion_rate': 0.0
            }
            total_tickets = Ticket.query.join(Queue).join(Department).join(Branch).filter(
                Branch.institution_id == institution_id
            ).count()
            attended_tickets = Ticket.query.join(Queue).join(Department).join(Branch).filter(
                Branch.institution_id == institution_id,
                Ticket.status == 'Atendido'
            ).count()
            result['ticket_conversion_rate'] = (attended_tickets / max(1, total_tickets)) * 100 if total_tickets > 0 else 0.0
            behaviors = UserBehavior.query.join(InstitutionService).join(Queue).join(Department).join(Branch).filter(
                Branch.institution_id == institution_id
            ).all()
            service_counts = {}
            for behavior in behaviors:
                if behavior.service_id:
                    service_counts[behavior.service_id] = service_counts.get(behavior.service_id, 0) + 1
            top_services = sorted(service_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            for service_id, count in top_services:
                service = InstitutionService.query.get(service_id)
                if service:
                    result['popular_services'].append({
                        'service_id': service.id,
                        'name': service.name,
                        'interactions': count
                    })
            for branch in branches:
                if not QueueService.is_branch_open(branch):
                    logger.debug(f"Filial {branch.id} fechada, mas incluída no dashboard")
                departments = Department.query.filter_by(branch_id=branch.id).all()
                department_ids = [d.id for d in departments]
                queues = Queue.query.filter(Queue.department_id.in_(department_ids)).all()
                branch_data = {
                    'branch_id': branch.id,
                    'branch_name': branch.name or "Desconhecida",
                    'neighborhood': branch.neighborhood or "Desconhecido",
                    'latitude': float(branch.latitude) if branch.latitude else None,
                    'longitude': float(branch.longitude) if branch.longitude else None,
                    'queues': []
                }
                for queue in queues:
                    current_ticket = Ticket.query.filter_by(queue_id=queue.id, status='Chamado')\
                        .order_by(Ticket.attended_at.desc()).first()
                    current_call = None
                    if current_ticket:
                        current_call = {
                            'ticket_number': f"{queue.prefix}{current_ticket.ticket_number}",
                            'counter': current_ticket.counter or queue.last_counter or 1,
                            'timestamp': current_ticket.attended_at.isoformat() if current_ticket.attended_at else None
                        }
                    recent_tickets = Ticket.query.filter_by(queue_id=queue.id, status='Atendido')\
                        .order_by(Ticket.attended_at.desc()).limit(5).all()
                    recent_calls_data = [
                        {
                            'ticket_number': f"{queue.prefix}{ticket.ticket_number}",
                            'counter': ticket.counter or queue.last_counter or 1,
                            'timestamp': ticket.attended_at.isoformat() if ticket.attended_at else None,
                            'service_time': float(ticket.service_time) if ticket.service_time else None
                        } for ticket in recent_tickets
                    ]
                    wait_time = QueueService.calculate_wait_time(queue.id, queue.active_tickets + 1, priority=0)
                    quality_score = service_recommendation_predictor.predict(queue)
                    predicted_demand = demand_model.predict(queue.id, hours_ahead=1)
                    alternatives = QueueService.suggest_alternative_queues(queue.id, max_distance_km=10.0)
                    alternatives_data = [
                        {
                            'queue_id': alt['queue_id'],
                            'service': alt['service'],
                            'wait_time': alt['wait_time'],
                            'service_similarity': alt['service_similarity']
                        } for alt in alternatives
                    ]
                    speed_label = "Desconhecida"
                    service_times = [t.service_time for t in recent_tickets if t.service_time is not None and t.service_time > 0]
                    if service_times:
                        avg_service_time = np.mean(service_times)
                        if avg_service_time <= 5:
                            speed_label = "Rápida"
                        elif avg_service_time <= 15:
                            speed_label = "Moderada"
                        else:
                            speed_label = "Lenta"
                    branch_data['queues'].append({
                        'queue_id': queue.id,
                        'service': queue.service.name or "Atendimento Geral",
                        'category_id': queue.service.category_id if queue.service else None,
                        'current_call': current_call,
                        'recent_calls': recent_calls_data,
                        'active_tickets': queue.active_tickets or 0,
                        'daily_limit': queue.daily_limit or 100,
                        'wait_time': f"{int(wait_time)} minutos" if isinstance(wait_time, (int, float)) else "Aguardando início",
                        'quality_score': float(quality_score),
                        'predicted_demand': float(predicted_demand),
                        'speed_label': speed_label,
                        'alternatives': alternatives_data,
                        'is_open': QueueService.is_queue_open(queue)
                    })
                result['branches'].append(branch_data)
            if result['branches']:
                cache_key = f'dashboard:{institution_id}'
                redis_client.setex(cache_key, 10, json.dumps(result, default=str))
                logger.debug(f"Dados do dashboard cacheados: {cache_key}")
            logger.info(f"Dados do dashboard gerados para institution_id={institution_id}")
            return result
        except Exception as e:
            logger.error(f"Erro ao obter dados do dashboard para institution_id={institution_id}: {e}")
            raise

    @staticmethod
    def emit_dashboard_update(institution_id, queue_id, event_type, data):
        """Publica uma atualização no dashboard via Redis."""
        try:
            if not isinstance(institution_id, str) or not isinstance(queue_id, str):
                logger.error(f"Parâmetros inválidos: institution_id={institution_id}, queue_id={queue_id}")
                raise ValueError("institution_id ou queue_id inválido")
            channel = f'dashboard:{institution_id}'
            message = {
                'event': event_type,
                'queue_id': queue_id,
                'data': data,
                'timestamp': datetime.utcnow().isoformat()
            }
            redis_client.publish(channel, json.dumps(message, default=str))
            logger.info(f"Atualização de dashboard publicada para {channel}: {event_type}")
        except Exception as e:
            logger.warning(f"Erro ao publicar atualização para {channel}: {e}")

    @staticmethod
    def subscribe_to_dashboard(institution_id):
        """Inscreve-se em atualizações do dashboard via Redis Pub/Sub."""
        try:
            if not isinstance(institution_id, str):
                logger.error(f"institution_id inválido: {institution_id}")
                raise ValueError("institution_id inválido")
            pubsub = redis_client.pubsub()
            pubsub.subscribe(f'dashboard:{institution_id}')
            logger.info(f"Inscrito em atualizações do dashboard para institution_id={institution_id}")
            return pubsub
        except Exception as e:
            logger.error(f"Erro ao subscrever dashboard {institution_id}: {e}")
            raise
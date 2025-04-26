import logging
import uuid
import numpy as np
import json
import re
from sqlalchemy import and_, func
from datetime import datetime, time, timedelta
from app.models import Queue, QueueSchedule, Ticket, AuditLog, Department, Institution, User, UserPreference, Weekday, Branch
from app.ml_models import wait_time_predictor, service_recommendation_predictor, clustering_model, demand_model
from app import db, redis_client, socketio
from .utils.pdf_generator import generate_ticket_pdf
from firebase_admin import messaging
from sqlalchemy.exc import SQLAlchemyError
from flask_socketio import emit
from geopy.distance import geodesic

logger = logging.getLogger(__name__)

class QueueService:
    """Serviço para gerenciamento de filas, tickets, notificações e dashboard."""
    DEFAULT_EXPIRATION_MINUTES = 30
    CALL_TIMEOUT_MINUTES = 5
    PROXIMITY_THRESHOLD_KM = 1.0
    PRESENCE_PROXIMITY_THRESHOLD_KM = 0.5

    @staticmethod
    def generate_qr_code():
        """Gera um QR code único."""
        qr_code = f"QR-{uuid.uuid4().hex[:8]}"
        logger.debug(f"QR Code gerado: {qr_code}")
        return qr_code

    @staticmethod
    def generate_receipt(ticket):
        """Gera um comprovante em texto para o ticket."""
        try:
            queue = ticket.queue
            if not queue or not queue.department or not queue.department.branch or not queue.department.branch.institution:
                logger.error(f"Dados incompletos para o ticket {ticket.id}")
                raise ValueError("Fila, departamento ou instituição associada ao ticket não encontrada")
            
            institution_type_name = queue.department.branch.institution.type.name if queue.department.branch.institution.type else "Desconhecido"
            
            receipt = (
                "=== Comprovante Facilita 2.0 ===\n"
                f"Tipo de Instituição: {institution_type_name}\n"
                f"Instituição: {queue.department.branch.institution.name or 'Desconhecida'}\n"
                f"Filial: {queue.department.branch.name or 'Desconhecida'}\n"
                f"Bairro: {queue.department.branch.neighborhood or 'Não especificado'}\n"
                f"Serviço: {queue.service or 'Desconhecido'}\n"
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
        """Gera um PDF para o ticket."""
        try:
            if not ticket.queue or not ticket.queue.department or not ticket.queue.department.branch or not ticket.queue.department.branch.institution:
                logger.error(f"Dados incompletos para o ticket {ticket.id}")
                raise ValueError("Fila, departamento ou instituição associada ao ticket não encontrada")
            
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
                service=ticket.queue.service or "Desconhecido",
                position=position,
                wait_time=wait_time
            )
            return pdf_buffer
        except Exception as e:
            logger.error(f"Erro ao gerar PDF para ticket {ticket.id}: {e}")
            raise

    @staticmethod
    def calculate_wait_time(queue_id, ticket_number, priority=0, user_lat=None, user_lon=None):
        """Calcula o tempo de espera estimado para um ticket."""
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

            now = datetime.utcnow()
            wait_time = wait_time_predictor.predict(
                queue_id=queue_id,
                position=position,
                active_tickets=queue.active_tickets,
                priority=priority,
                hour_of_day=now.hour,
                user_lat=user_lat,
                user_lon=user_lon
            )

            wait_time = round(wait_time, 1)
            logger.debug(f"Wait time calculado para ticket {ticket_number} na fila {queue_id}: {wait_time} min")
            return wait_time if wait_time != "N/A" else queue.avg_wait_time or 5
        except Exception as e:
            logger.error(f"Erro ao calcular wait_time para queue_id={queue_id}: {e}")
            return "N/A"

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
    def send_notification(fcm_token, message, ticket_id=None, via_websocket=False, user_id=None):
        """Envia notificações via FCM e/ou WebSocket."""
        try:
            logger.info(f"Enviando notificação para user_id {user_id}: {message}")
            
            if not fcm_token and user_id:
                user = User.query.get(user_id)
                if user and user.fcm_token:
                    fcm_token = user.fcm_token
                    logger.debug(f"FCM token recuperado para user_id {user_id}")

            if fcm_token:
                fcm_message = messaging.Message(
                    notification=messaging.Notification(
                        title="Facilita 2.0",
                        body=message
                    ),
                    data={"ticket_id": str(ticket_id) if ticket_id else ""},
                    token=fcm_token
                )
                response = messaging.send(fcm_message)
                logger.info(f"Notificação FCM enviada: {response}")

            if via_websocket and socketio and user_id:
                emit('notification', {'user_id': user_id, 'message': message}, namespace='/', room=str(user_id))
                logger.debug(f"Notificação WebSocket enviada para user_id={user_id}")
        except Exception as e:
            logger.error(f"Erro ao enviar notificação: {e}")

    @staticmethod
    def add_to_queue(service, user_id, priority=0, is_physical=False, fcm_token=None, branch_id=None, user_lat=None, user_lon=None):
        """Adiciona um ticket à fila."""
        try:
            if not isinstance(service, str) or not service.strip():
                raise ValueError("Serviço inválido")

            # Verificar se o user_id existe na tabela User, se fornecido
            ticket_user_id = None
            if user_id:
                user = User.query.get(user_id)
                ticket_user_id = user.id if user else None  # Usa NULL se o usuário não existe

            query = Queue.query.filter_by(service=service)
            if branch_id:
                if not isinstance(branch_id, str):
                    raise ValueError("branch_id inválido")
                query = query.join(Department).join(Branch).filter(Branch.id == branch_id)
            
            queue = query.first()
            if not queue:
                logger.error(f"Fila não encontrada: {service}, branch_id: {branch_id}")
                raise ValueError("Fila não encontrada")
            
            if not QueueService.is_queue_open(queue):
                logger.warning(f"Fila {queue.id} está fechada")
                raise ValueError(f"A fila {queue.service} está fechada")
            
            if queue.active_tickets >= queue.daily_limit:
                alternatives = clustering_model.get_alternatives(queue.id, n=3)
                alt_queues = Queue.query.filter(Queue.id.in_(alternatives)).all()
                alt_message = "Alternativas: " + ", ".join([f"{q.service} (ID: {q.id})" for q in alt_queues])
                logger.warning(f"Fila {queue.id} cheia: {queue.active_tickets}/{queue.daily_limit}")
                raise ValueError(f"Limite diário atingido. {alt_message}")
            
            # Verificar se o usuário já tem um ticket pendente na mesma fila
            if ticket_user_id and Ticket.query.filter_by(user_id=ticket_user_id, queue_id=queue.id, status='Pendente').first():
                logger.warning(f"Usuário {ticket_user_id} já possui senha ativa na fila {queue.id}")
                raise ValueError("Você já possui uma senha ativa")
            
            ticket_number = queue.active_tickets + 1
            qr_code = QueueService.generate_qr_code()
            ticket = Ticket(
                id=str(uuid.uuid4()),
                queue_id=queue.id,
                user_id=ticket_user_id,  # Pode ser NULL
                ticket_number=ticket_number,
                qr_code=qr_code,
                priority=priority,
                is_physical=is_physical,
                expires_at=None,
                issued_at=datetime.utcnow()
            )
            
            queue.active_tickets += 1
            db.session.add(ticket)
            db.session.commit()
            db.session.refresh(ticket)
            
            if not ticket.queue:
                logger.error(f"Relação ticket.queue não carregada para ticket {ticket.id}")
                raise ValueError("Erro ao carregar a fila associada")
            
            ticket.receipt_data = QueueService.generate_receipt(ticket) if is_physical else None
            wait_time = QueueService.calculate_wait_time(queue.id, ticket_number, priority, user_lat, user_lon)
            position = max(0, ticket.ticket_number - queue.current_ticket)
            pdf_buffer = None
            
            if is_physical:
                pdf_buffer = QueueService.generate_pdf_ticket(ticket, position, wait_time)
            
            message = f"Senha {queue.prefix}{ticket_number} emitida. QR: {qr_code}. Espera: {wait_time if wait_time != 'N/A' else 'Aguardando início'} min"
            QueueService.send_notification(fcm_token, message, ticket.id, via_websocket=True, user_id=user_id)
            
            if socketio:
                emit('queue_update', {
                    'queue_id': queue.id,
                    'active_tickets': queue.active_tickets,
                    'current_ticket': queue.current_ticket,
                    'message': f"Nova senha emitida: {queue.prefix}{ticket_number}"
                }, namespace='/', room=str(queue.id))
            
            logger.info(f"Ticket {ticket.id} adicionado à fila {service}")
            return ticket, pdf_buffer
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao adicionar ticket à fila {service}: {e}")
            raise

    @staticmethod
    def generate_physical_ticket_for_totem(queue_id, client_ip):
        """Gera um ticket físico via totem."""
        try:
            if not isinstance(queue_id, str) or not queue_id:
                raise ValueError("queue_id inválido")
            
            queue = Queue.query.get(queue_id)
            if not queue:
                logger.error(f"Fila não encontrada para queue_id={queue_id}")
                raise ValueError("Fila não encontrada")

            if not QueueService.is_queue_open(queue):
                logger.warning(f"Fila {queue_id} está fechada")
                raise ValueError("Fila está fechada")

            if queue.active_tickets >= queue.daily_limit:
                alternatives = clustering_model.get_alternatives(queue.id, n=3)
                alt_queues = Queue.query.filter(Queue.id.in_(alternatives)).all()
                alt_message = "Alternativas: " + ", ".join([f"{q.service} (ID: {q.id})" for q in alt_queues])
                logger.warning(f"Fila {queue_id} cheia")
                raise ValueError(f"Limite diário atingido. {alt_message}")

            cache_key = f'ticket_limit:{client_ip}:{queue.department.branch.institution_id}'
            emission_count = redis_client.get(cache_key)
            emission_count = int(emission_count) if emission_count else 0
            if emission_count >= 5:
                logger.warning(f"Limite de emissões atingido para IP {client_ip}")
                raise ValueError("Limite de emissões por hora atingido")
            redis_client.setex(cache_key, 3600, emission_count + 1)

            ticket_number = queue.active_tickets + 1
            qr_code = QueueService.generate_qr_code()
            ticket = Ticket(
                id=str(uuid.uuid4()),
                queue_id=queue.id,
                user_id='PRESENCIAL',  # Mantido como está para tickets de totem
                ticket_number=ticket_number,
                qr_code=qr_code,
                priority=0,
                is_physical=True,
                status='Pendente',
                issued_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=4),
                receipt_data=None
            )
            queue.active_tickets += 1
            db.session.add(ticket)

            wait_time = QueueService.calculate_wait_time(queue.id, ticket_number, 0)
            position = max(0, ticket.ticket_number - queue.current_ticket)
            pdf_buffer = QueueService.generate_pdf_ticket(ticket, position, wait_time)
            pdf_base64 = pdf_buffer.getvalue().hex()

            ticket.receipt_data = QueueService.generate_receipt(ticket)
            audit_log = AuditLog(
                id=str(uuid.uuid4()),
                user_id=None,
                action='GENERATE_USER_PHYSICAL_TICKET',
                resource_type='Ticket',
                resource_id=ticket.id,
                details=f"Ticket {qr_code} gerado via totem para fila {queue.service} (IP: {client_ip})",
                timestamp=datetime.utcnow()
            )
            db.session.add(audit_log)
            db.session.commit()

            if socketio:
                emit('queue_update', {
                    'queue_id': queue.id,
                    'active_tickets': queue.active_tickets,
                    'current_ticket': queue.current_ticket,
                    'message': f"Nova senha emitida: {queue.prefix}{ticket_number}"
                }, namespace='/', room=str(queue.id))

            logger.info(f"Ticket físico {ticket.id} gerado para fila {queue_id}")
            return {
                'ticket': {
                    'id': ticket.id,
                    'queue_id': ticket.queue_id,
                    'ticket_number': ticket.ticket_number,
                    'qr_code': ticket.qr_code,
                    'status': ticket.status,
                    'issued_at': ticket.issued_at.isoformat(),
                    'expires_at': ticket.expires_at.isoformat() if ticket.expires_at else None
                },
                'pdf': pdf_base64
            }
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao gerar ticket físico para queue_id={queue_id}: {e}")
            raise

    @staticmethod
    def call_next(service, branch_id=None):
        """Chama o próximo ticket na fila."""
        try:
            query = Queue.query.filter_by(service=service)
            if branch_id:
                if not isinstance(branch_id, str):
                    raise ValueError("branch_id inválido")
                query = query.join(Department).join(Branch).filter(Branch.id == branch_id)
            
            queue = query.first()
            if not queue:
                logger.warning(f"Fila {service} não encontrada")
                raise ValueError("Fila não encontrada")
            
            if not QueueService.is_queue_open(queue):
                logger.warning(f"Fila {queue.id} está fechada")
                raise ValueError("Fila está fechada")

            if queue.active_tickets == 0:
                logger.warning(f"Fila {service} está vazia")
                raise ValueError("Fila vazia")
            
            next_ticket = Ticket.query.filter_by(queue_id=queue.id, status='Pendente')\
                .order_by(Ticket.priority.desc(), Ticket.ticket_number).first()
            if not next_ticket:
                logger.warning(f"Sem tickets pendentes na fila {queue.id}")
                raise ValueError("Nenhum ticket pendente")
            
            now = datetime.utcnow()
            next_ticket.expires_at = now + timedelta(minutes=QueueService.CALL_TIMEOUT_MINUTES)
            
            queue.current_ticket = next_ticket.ticket_number
            queue.active_tickets -= 1
            queue.last_counter = (queue.last_counter % queue.num_counters) + 1
            next_ticket.status = 'Chamado'
            next_ticket.counter = queue.last_counter
            next_ticket.attended_at = now
            db.session.commit()
            
            message = f"Dirija-se ao guichê {next_ticket.counter:02d}! Senha {queue.prefix}{next_ticket.ticket_number} chamada."
            QueueService.send_notification(None, message, next_ticket.id, via_websocket=True, user_id=next_ticket.user_id)
            
            if socketio:
                emit('queue_update', {
                    'queue_id': queue.id,
                    'active_tickets': queue.active_tickets,
                    'current_ticket': queue.current_ticket,
                    'message': f"Senha {queue.prefix}{next_ticket.ticket_number} chamada"
                }, namespace='/', room=str(queue.id))
            
            logger.info(f"Ticket {next_ticket.id} chamado na fila {service}")
            return next_ticket
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao chamar próximo ticket na fila {service}: {e}")
            raise

    @staticmethod
    def check_proximity_notifications(user_id, user_lat, user_lon, desired_service=None, institution_id=None, branch_id=None, institution_type_id=None):
        """Verifica e envia notificações de proximidade."""
        try:
            if not isinstance(user_id, str) or not user_id:
                raise ValueError("user_id inválido")
            if not all(isinstance(x, (int, float)) for x in [user_lat, user_lon]):
                raise ValueError("Localização inválida")

            user = User.query.get(user_id)
            if not user or not user.fcm_token:
                logger.warning(f"Usuário {user_id} não encontrado ou sem FCM token")
                raise ValueError("Usuário não encontrado ou sem token")

            user.last_known_lat = float(user_lat)
            user.last_known_lon = float(user_lon)
            user.last_location_update = datetime.utcnow()
            db.session.commit()
            logger.debug(f"Localização atualizada para user_id={user_id}")

            user_prefs = UserPreference.query.filter_by(user_id=user_id).all()
            preferred_institutions = {pref.institution_id for pref in user_prefs if pref.institution_id}
            preferred_categories = {pref.service_category_id for pref in user_prefs if pref.service_category_id}
            preferred_institution_types = {pref.institution_type_id for pref in user_prefs if pref.institution_type_id}

            query = Queue.query.join(Department).join(Branch).join(Institution)
            if institution_id:
                if not isinstance(institution_id, str):
                    raise ValueError("institution_id inválido")
                query = query.filter(Institution.id == institution_id)
            if branch_id:
                if not isinstance(branch_id, str):
                    raise ValueError("branch_id inválido")
                query = query.filter(Branch.id == branch_id)
            if institution_type_id:
                if not isinstance(institution_type_id, str):
                    raise ValueError("institution_type_id inválido")
                query = query.filter(Institution.institution_type_id == institution_type_id)
            if desired_service:
                if not isinstance(desired_service, str) or not desired_service.strip():
                    raise ValueError("Serviço inválido")
                
                search_terms = re.sub(r'[^\w\sÀ-ÿ]', '', desired_service.lower()).split()
                search_query = ' & '.join(search_terms)
                query = query.filter(
                    func.to_tsvector('portuguese', Queue.service + ' ' + Department.sector)
                    .op('@@')(func.to_tsquery('portuguese', search_query))
                )

            queues = query.all()
            now = datetime.utcnow()
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
                if preferred_categories and queue.category_id and queue.category_id not in preferred_categories:
                    continue
                if preferred_institution_types and branch.institution.institution_type_id not in preferred_institution_types:
                    continue

                distance = QueueService.calculate_distance(user_lat, user_lon, branch)
                if distance is None or distance > QueueService.PROXIMITY_THRESHOLD_KM:
                    continue

                predicted_demand = demand_model.predict(queue.id, hours_ahead=1)
                if predicted_demand > 10:
                    continue

                cache_key = f'notification:{user_id}:{branch.id}:{queue.id}:{int(user_lat*1000)}:{int(user_lon*1000)}'
                if redis_client.get(cache_key):
                    continue

                wait_time = QueueService.calculate_wait_time(queue.id, queue.active_tickets + 1, priority=0, user_lat=user_lat, user_lon=user_lon)
                message = (
                    f"Fila popular próxima! {queue.service} em {branch.institution.name} ({branch.name}) "
                    f"a {distance:.2f} km. Tempo de espera: {wait_time if wait_time != 'N/A' else 'Aguardando início'} min."
                )

                QueueService.send_notification(
                    user.fcm_token,
                    message,
                    via_websocket=True,
                    user_id=user_id
                )

                redis_client.setex(cache_key, 3600, 'sent')
                notified_branches.add(branch.id)
                logger.info(f"Notificação de proximidade enviada para user_id={user_id}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao verificar notificações de proximidade para user_id={user_id}: {e}")
            raise

    @staticmethod
    def check_proactive_notifications():
        """Verifica tickets pendentes e envia notificações proativas."""
        try:
            now = datetime.utcnow()
            tickets = Ticket.query.filter_by(status='Pendente').all()
            for ticket in tickets:
                queue = ticket.queue
                if not QueueService.is_queue_open(queue):
                    ticket.status = 'Cancelado'
                    ticket.queue.active_tickets -= 1
                    db.session.commit()
                    QueueService.send_notification(
                        None,
                        f"Sua senha {ticket.queue.prefix}{ticket.ticket_number} foi cancelada (horário encerrado).",
                        user_id=ticket.user_id
                    )
                    logger.info(f"Ticket {ticket.id} cancelado (horário encerrado)")
                    continue
                
                wait_time = QueueService.calculate_wait_time(ticket.queue_id, ticket.ticket_number, ticket.priority)
                if wait_time == "N/A":
                    continue

                predicted_demand = demand_model.predict(ticket.queue_id, hours_ahead=1)
                if wait_time <= 5 and ticket.user_id != 'PRESENCIAL':
                    distance = QueueService.calculate_distance(-8.8147, 13.2302, ticket.queue.department.branch)
                    distance_msg = f" Você está a {distance:.2f} km." if distance else ""
                    message = (
                        f"Sua vez está próxima! {ticket.queue.service}, Senha {ticket.queue.prefix}{ticket.ticket_number}. "
                        f"Prepare-se em {wait_time} min. Demanda prevista: {predicted_demand:.1f} tickets/h.{distance_msg}"
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
                    db.session.commit()
                    QueueService.send_notification(
                        None,
                        f"Sua senha {ticket.queue.prefix}{ticket.ticket_number} foi cancelada (tempo esgotado).",
                        user_id=ticket.user_id
                    )
                    logger.info(f"Ticket {ticket.id} cancelado por falta de validação")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao verificar notificações proativas: {e}")

    @staticmethod
    def trade_tickets(ticket_from_id, ticket_to_id, user_from_id):
        """Troca dois tickets entre usuários."""
        try:
            ticket_from = Ticket.query.get_or_404(ticket_from_id)
            ticket_to = Ticket.query.get_or_404(ticket_to_id)
            if ticket_from.user_id != user_from_id or not ticket_to.trade_available or \
               ticket_from.queue_id != ticket_to.queue_id or ticket_from.status != 'Pendente' or \
               ticket_to.status != 'Pendente':
                logger.warning(f"Tentativa inválida de troca entre {ticket_from_id} e {ticket_to_id}")
                raise ValueError("Troca inválida")
            
            user_from, user_to = ticket_from.user_id, ticket_to.user_id
            num_from, num_to = ticket_from.ticket_number, ticket_to.ticket_number
            ticket_from.user_id, ticket_from.ticket_number = user_to, num_to
            ticket_to.user_id, ticket_to.ticket_number = user_from, num_from
            ticket_from.trade_available, ticket_to.trade_available = False, False
            db.session.commit()
            logger.info(f"Troca realizada entre {ticket_from_id} e {ticket_to_id}")

            QueueService.send_notification(
                None,
                f"Sua senha foi trocada! Nova senha: {ticket_from.queue.prefix}{ticket_from.ticket_number}",
                ticket_from.id,
                via_websocket=True,
                user_id=ticket_from.user_id
            )
            QueueService.send_notification(
                None,
                f"Sua senha foi trocada! Nova senha: {ticket_to.queue.prefix}{ticket_to.ticket_number}",
                ticket_to.id,
                via_websocket=True,
                user_id=ticket_to.user_id
            )

            return {"ticket_from": ticket_from, "ticket_to": ticket_to}
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao subir tickets {ticket_from_id} e {ticket_to_id}: {e}")
            raise

    @staticmethod
    def validate_presence(qr_code, user_lat=None, user_lon=None):
        """Valida a presença de um usuário com base no QR code."""
        try:
            if not isinstance(qr_code, str) or not qr_code:
                raise ValueError("QR code inválido")
            
            ticket = Ticket.query.filter_by(qr_code=qr_code).first()
            if not ticket or ticket.status != 'Chamado':
                logger.warning(f"Tentativa inválida de validar presença com QR {qr_code}")
                raise ValueError("Senha inválida ou não chamada")
            if not QueueService.is_queue_open(ticket.queue):
                logger.warning(f"Fila {ticket.queue.id} está fechada")
                raise ValueError("Fila está fechada")
            
            if user_lat and user_lon:
                branch = ticket.queue.department.branch
                distance = QueueService.calculate_distance(user_lat, user_lon, branch)
                if distance and distance > QueueService.PRESENCE_PROXIMITY_THRESHOLD_KM:
                    logger.warning(f"Usuário muito longe: {distance} km")
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
            logger.info(f"Presença validada para ticket {ticket.id}")
            return ticket
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao validar presença com QR {qr_code}: {e}")
            raise

    @staticmethod
    def offer_trade(ticket_id, user_id):
        """Oferece um ticket para troca."""
        try:
            ticket = Ticket.query.get_or_404(ticket_id)
            if ticket.user_id != user_id:
                logger.warning(f"Tentativa inválida de oferecer ticket {ticket_id} por {user_id}")
                raise ValueError("Você só pode oferecer sua própria senha.")
            if ticket.status != 'Pendente':
                logger.warning(f"Ticket {ticket_id} no estado {ticket.status} não pode ser oferecido")
                raise ValueError(f"Esta senha está no estado '{ticket.status}'.")
            if ticket.trade_available:
                logger.warning(f"Ticket {ticket_id} já está oferecido")
                raise ValueError("Esta senha já está oferecida.")
            
            ticket.trade_available = True
            db.session.commit()
            logger.info(f"Ticket {ticket_id} oferecido para troca")

            QueueService.send_notification(
                None,
                f"Sua senha {ticket.queue.prefix}{ticket.ticket_number} foi oferecida para troca!",
                ticket.id,
                via_websocket=True,
                user_id=user_id
            )

            eligible_tickets = Ticket.query.filter(
                Ticket.queue_id == ticket.queue_id,
                Ticket.user_id != user_id,
                Ticket.status == 'Pendente',
                Ticket.trade_available == False
            ).order_by(Ticket.issued_at.asc()).limit(5).all()

            if socketio:
                for eligible_ticket in eligible_tickets:
                    emit('trade_available', {
                        'ticket_id': ticket.id,
                        'queue_id': ticket.queue_id,
                        'service': ticket.queue.service,
                        'number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                        'position': max(0, ticket.ticket_number - ticket.queue.current_ticket)
                    }, namespace='/', room=str(eligible_ticket.user_id))
                    logger.debug(f"Evento trade_available emitido para user_id {eligible_ticket.user_id}")
            
            return ticket
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao oferecer troca do ticket {ticket_id}: {e}")
            raise

    @staticmethod
    def cancel_ticket(ticket_id, user_id):
        """Cancela um ticket."""
        try:
            ticket = Ticket.query.get_or_404(ticket_id)
            if ticket.user_id != user_id:
                logger.warning(f"Tentativa inválida de cancelar ticket {ticket_id} por user_id={user_id}")
                raise ValueError("Você só pode cancelar sua própria senha")
            if ticket.status != 'Pendente':
                logger.warning(f"Ticket {ticket_id} no estado {ticket.status} não pode ser cancelado")
                raise ValueError("Esta senha não pode ser cancelada")
            
            ticket.status = 'Cancelado'
            ticket.queue.active_tickets -= 1
            db.session.commit()
            
            QueueService.send_notification(
                None,
                f"Sua senha {ticket.queue.prefix}{ticket.ticket_number} foi cancelada.",
                ticket.id,
                via_websocket=True,
                user_id=user_id
            )
            
            if socketio:
                emit('queue_update', {
                    'queue_id': ticket.queue_id,
                    'active_tickets': ticket.queue.active_tickets,
                    'current_ticket': ticket.queue.current_ticket,
                    'message': f"Senha {ticket.queue.prefix}{ticket.ticket_number} cancelada"
                }, namespace='/', room=str(ticket.queue_id))
            
            logger.info(f"Ticket {ticket.id} cancelado por user_id={user_id}")
            return ticket
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao cancelar ticket {ticket_id}: {e}")
            raise

    @staticmethod
    def is_queue_open(queue, now=None):
        """Verifica se a fila está aberta."""
        try:
            if not now:
                now = datetime.utcnow()
            
            weekday_str = now.strftime('%A')
            weekday_enum = Weekday[weekday_str.upper()]
            schedule = QueueSchedule.query.filter_by(
                queue_id=queue.id,
                weekday=weekday_enum
            ).first()
            
            if not schedule or schedule.is_closed:
                return False
            
            current_time = now.time()
            return schedule.open_time <= current_time <= schedule.end_time
        except (KeyError, AttributeError):
            logger.error(f"Erro ao verificar fila {queue.id}: dia {weekday_str} inválido")
            return False

    @staticmethod
    def get_dashboard_data(institution_id):
        """Obtém dados para o dashboard de uma instituição."""
        try:
            if not isinstance(institution_id, str):
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
                        'id': institution.type.id if institution.type else None,
                        'name': institution.type.name if institution.type else "Desconhecido"
                    }
                },
                'branches': []
            }

            for branch in branches:
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

                    alternatives = clustering_model.get_alternatives(queue.id, n=3)
                    alternative_queues = Queue.query.filter(Queue.id.in_(alternatives)).all()
                    alternatives_data = [
                        {
                            'queue_id': alt_queue.id,
                            'service': alt_queue.service or "Desconhecido",
                            'wait_time': QueueService.calculate_wait_time(alt_queue.id, alt_queue.active_tickets + 1, 0)
                        } for alt_queue in alternative_queues
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
                        'service': queue.service or "Atendimento Geral",
                        'category_id': queue.category_id,
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

            try:
                cache_key = f'dashboard:{institution_id}'
                redis_client.setex(cache_key, 10, json.dumps(result, default=str))
            except Exception as e:
                logger.warning(f"Erro ao salvar cache para {cache_key}: {e}")

            logger.info(f"Dados do dashboard gerados para institution_id={institution_id}")
            return result
        except Exception as e:
            logger.error(f"Erro ao obter dados do dashboard para institution_id={institution_id}: {e}")
            raise

    @staticmethod
    def emit_dashboard_update(institution_id, queue_id, event_type, data):
        """Publica uma atualização no dashboard."""
        try:
            channel = f'dashboard:{institution_id}'
            message = {
                'event': event_type,
                'queue_id': queue_id,
                'data': data,
                'timestamp': datetime.utcnow().isoformat()
            }
            redis_client.publish(channel, json.dumps(message, default=str))
            logger.info(f"Atualização de dashboard publicada para {channel}")
        except Exception as e:
            logger.warning(f"Erro ao publicar atualização para {channel}: {e}")

    @staticmethod
    def subscribe_to_dashboard(institution_id):
        """Inscreve-se em atualizações do dashboard."""
        try:
            pubsub = redis_client.pubsub()
            pubsub.subscribe(f'dashboard:{institution_id}')
            logger.info(f"Inscrito em atualizações do dashboard para institution_id={institution_id}")
            return pubsub
        except Exception as e:
            logger.error(f"Erro ao subscrever dashboard {institution_id}: {e}")
            raise
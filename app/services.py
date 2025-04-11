# app/services.py

import logging
import uuid
import numpy as np
import math
from datetime import datetime, timedelta
from flask_socketio import emit
from . import db, socketio
from .models import Queue, Ticket, User
from .utils.pdf_generator import generate_ticket_pdf
from firebase_admin import messaging
from sqlalchemy.exc import SQLAlchemyError
from .ml_models import wait_time_predictor, service_recommendation_predictor  # Importar os preditores

logger = logging.getLogger(__name__)

def setup_logging():
    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            'queue_service.log', maxBytes=1024*1024, backupCount=10
        )
        handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

setup_logging()

class QueueService:
    DEFAULT_EXPIRATION_MINUTES = 30
    CALL_TIMEOUT_MINUTES = 5

    @staticmethod
    def generate_qr_code():
        qr_code = f"QR-{uuid.uuid4().hex[:8]}"
        logger.debug(f"QR Code gerado: {qr_code}")
        return qr_code

    @staticmethod
    def generate_receipt(ticket):
        queue = ticket.queue
        if not queue:
            logger.error(f"Fila não encontrada para o ticket {ticket.id}")
            raise ValueError("Fila associada ao ticket não encontrada")
        
        receipt = (
            "=== Comprovante Facilita 2.0 ===\n"
            f"Serviço: {queue.service}\n"
            f"Instituição: {queue.institution_name}\n"
            f"Senha: {queue.prefix}{ticket.ticket_number}\n"
            f"Tipo: {'Física' if ticket.is_physical else 'Virtual'}\n"
            f"QR Code: {ticket.qr_code}\n"
            f"Prioridade: {ticket.priority}\n"
            f"Data de Emissão: {ticket.issued_at.strftime('%d/%m/%Y %H:%M')}\n"
            f"Expira em: {ticket.expires_at.strftime('%d/%m/%Y %H:%M') if ticket.expires_at else 'N/A'}\n"
            "=== Guarde este comprovante ==="
        )
        logger.debug(f"Comprovante gerado para ticket {ticket.id}")
        return receipt

    @staticmethod
    def generate_pdf_ticket(ticket, position=None, wait_time=None):
        if not ticket.queue:
            logger.error(f"Fila não encontrada para o ticket {ticket.id}")
            raise ValueError("Fila associada ao ticket não encontrada")
            
        if position is None:
            position = max(0, ticket.ticket_number - ticket.queue.current_ticket)
        if wait_time is None:
            wait_time = QueueService.calculate_wait_time(
                ticket.queue.id, ticket.ticket_number, ticket.priority
            )

        pdf_buffer = generate_ticket_pdf(
            ticket=ticket,
            institution_name=ticket.queue.institution_name,
            service=ticket.queue.service,
            position=position,
            wait_time=wait_time
        )
        return pdf_buffer

    @staticmethod
    def calculate_wait_time(queue_id, ticket_number, priority=0):
        queue = Queue.query.get(queue_id)
        if not queue:
            logger.error(f"Fila não encontrada para queue_id={queue_id}")
            return 0
        
        # Se o atendimento ainda não começou (current_ticket == 0), retornar "N/A"
        if queue.current_ticket == 0:
            logger.debug(f"Atendimento ainda não começou para queue_id={queue_id}, wait_time='N/A'")
            return "N/A"

        # Calcular a posição do ticket na fila
        position = max(0, ticket_number - queue.current_ticket)
        if position == 0:
            logger.debug(f"Ticket {ticket_number} está na posição 0, wait_time=0")
            return 0

        # Tentar usar o modelo de machine learning para previsão
        now = datetime.utcnow()
        hour_of_day = now.hour
        predicted_time = wait_time_predictor.predict(position, queue.active_tickets, priority, hour_of_day)
        
        if predicted_time is not None:
            wait_time = predicted_time
        else:
            # Fallback para o cálculo manual se o modelo não estiver treinado ou falhar
            completed_tickets = Ticket.query.filter_by(queue_id=queue_id, status='attended').all()
            service_times = [t.service_time for t in completed_tickets if t.service_time is not None and t.service_time > 0]
            
            if service_times:
                avg_time = np.mean(service_times)
                estimated_time = avg_time
                logger.debug(f"Tempo médio de atendimento calculado: {avg_time} min")
            else:
                estimated_time = queue.avg_wait_time or 5
                logger.debug(f"Nenhum ticket atendido, usando tempo padrão: {estimated_time} min")

            wait_time = position * estimated_time
            if priority > 0:
                wait_time *= (1 - priority * 0.1)  # Reduz o tempo para prioridades mais altas
            if queue.active_tickets > 10:
                wait_time += (queue.active_tickets - 10) * 0.5  # Ajuste para filas longas

            # Atualizar o tempo médio de espera da fila
            queue.avg_wait_time = estimated_time
            db.session.commit()

        wait_time = round(wait_time, 1)
        logger.debug(f"Wait time calculado para ticket {ticket_number} na fila {queue_id}: {wait_time} min (position={position}, priority={priority})")
        return wait_time

    @staticmethod
    def calculate_distance(user_lat, user_lon, institution):
        if not all([user_lat, user_lon, institution.latitude, institution.longitude]):
            logger.warning(f"Coordenadas incompletas para cálculo de distância: user_lat={user_lat}, user_lon={user_lon}, inst_lat={institution.latitude}, inst_lon={institution.longitude}")
            return None
        distance = math.sqrt((user_lat - institution.latitude)**2 + (user_lon - institution.longitude)**2) * 111
        return round(distance, 1)

    @staticmethod
    def send_notification(fcm_token, message, ticket_id=None, via_websocket=False, user_id=None):
        logger.info(f"Notificação para user_id {user_id}: {message}")
        
        if not fcm_token and user_id:
            user = User.query.get(user_id)
            if user and user.fcm_token:
                fcm_token = user.fcm_token
                logger.debug(f"FCM token recuperado do banco para user_id {user_id}: {fcm_token}")
            else:
                logger.warning(f"FCM token não encontrado para user_id {user_id}")

        if fcm_token:
            try:
                fcm_message = messaging.Message(
                    notification=messaging.Notification(
                        title="Facilita 2.0",
                        body=message
                    ),
                    data={"ticket_id": ticket_id or ""},
                    token=fcm_token
                )
                response = messaging.send(fcm_message)
                logger.info(f"Notificação FCM enviada para {fcm_token}: {response}")
            except Exception as e:
                logger.error(f"Erro ao enviar notificação FCM: {e}")
        else:
            logger.warning(f"Token FCM não fornecido e não encontrado para user_id {user_id}")

        if via_websocket and socketio:
            try:
                emit('notification', {'user_id': user_id, 'message': message}, namespace='/', broadcast=True)
                logger.debug(f"Notificação WebSocket enviada para {user_id}")
            except Exception as e:
                logger.error(f"Erro ao enviar notificação via WebSocket: {e}")

    @staticmethod
    def add_to_queue(service, user_id, priority=0, is_physical=False, fcm_token=None):
        queue = Queue.query.filter_by(service=service).first()
        if not queue:
            logger.error(f"Fila não encontrada para o serviço: {service}")
            raise ValueError("Fila não encontrada")
        
        # Verificar se a fila está aberta
        now = datetime.utcnow().time()
        if now < queue.open_time:
            logger.warning(f"Tentativa de emitir senha antes do horário de abertura para serviço {service}. Horário atual: {now}, abertura: {queue.open_time}")
            raise ValueError(f"A fila {queue.service} ainda não está aberta. Abertura às {queue.open_time.strftime('%H:%M')}.")

        if queue.active_tickets >= queue.daily_limit:
            logger.warning(f"Fila {service} está cheia: {queue.active_tickets}/{queue.daily_limit}")
            raise ValueError("Limite diário atingido")
        if Ticket.query.filter_by(user_id=user_id, queue_id=queue.id, status='Pendente').first():
            logger.warning(f"Usuário {user_id} já possui uma senha ativa na fila {queue.id}")
            raise ValueError("Você já possui uma senha ativa")

        ticket_number = queue.active_tickets + 1
        qr_code = QueueService.generate_qr_code()
        ticket = Ticket(
            id=str(uuid.uuid4()),
            queue_id=queue.id,
            user_id=user_id,
            ticket_number=ticket_number,
            qr_code=qr_code,
            priority=priority,
            is_physical=is_physical,
            expires_at=None
        )
        
        queue.active_tickets += 1
        db.session.add(ticket)
        db.session.commit()

        db.session.refresh(ticket)
        if not ticket.queue:
            logger.error(f"Relação ticket.queue não carregada para ticket {ticket.id}")
            raise ValueError("Erro ao carregar a fila associada ao ticket")

        ticket.receipt_data = QueueService.generate_receipt(ticket) if is_physical else None

        wait_time = QueueService.calculate_wait_time(queue.id, ticket_number, priority)
        position = max(0, ticket.ticket_number - queue.current_ticket)
        
        pdf_buffer = None
        if is_physical:
            pdf_buffer = QueueService.generate_pdf_ticket(ticket, position, wait_time)

        message = f"Senha {queue.prefix}{ticket_number} emitida. QR: {qr_code}. Espera: {wait_time if wait_time != 'N/A' else 'Aguardando início'}"
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

    @staticmethod
    def call_next(service):
        queue = Queue.query.filter_by(service=service).first()
        if not queue or queue.active_tickets == 0:
            logger.warning(f"Fila {service} está vazia ou não encontrada")
            raise ValueError("Fila vazia ou não encontrada")
        
        next_ticket = Ticket.query.filter_by(queue_id=queue.id, status='Pendente')\
            .order_by(Ticket.priority.desc(), Ticket.ticket_number).first()
        if not next_ticket:
            logger.warning(f"Não há tickets pendentes na fila {queue.id}")
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

    @staticmethod
    def check_proactive_notifications():
        now = datetime.utcnow()
        tickets = Ticket.query.filter_by(status='Pendente').all()
        for ticket in tickets:
            queue = ticket.queue
            if queue.end_time and now.time() > queue.end_time:
                ticket.status = 'Cancelado'
                ticket.queue.active_tickets -= 1
                db.session.commit()
                QueueService.send_notification(
                    None,
                    f"Sua senha {ticket.queue.prefix}{ticket.ticket_number} foi cancelada porque o horário de atendimento terminou.",
                    user_id=ticket.user_id
                )
                logger.info(f"Ticket {ticket.id} cancelado devido ao fim do horário de atendimento")
                continue
            
            wait_time = QueueService.calculate_wait_time(ticket.queue_id, ticket.ticket_number, ticket.priority)
            if wait_time == "N/A":
                continue

            if wait_time <= 5 and ticket.user_id != 'PRESENCIAL':
                distance = QueueService.calculate_distance(-8.8147, 13.2302, ticket.queue.institution)
                distance_msg = f" Você está a {distance} km." if distance else ""
                message = f"Sua vez está próxima! {ticket.queue.service}, Senha {ticket.queue.prefix}{ticket.ticket_number}. Prepare-se em {wait_time} min.{distance_msg}"
                QueueService.send_notification(None, message, ticket.id, via_websocket=True, user_id=ticket.user_id)

            if ticket.user_id != 'PRESENCIAL':
                user = User.query.get(ticket.user_id)
                if user and user.last_known_lat and user.last_known_lon:
                    distance = QueueService.calculate_distance(user.last_known_lat, user.last_known_lon, ticket.queue.institution)
                    if distance and distance > 5:
                        travel_time = distance * 2
                        if wait_time <= travel_time:
                            message = f"Você está a {distance} km! Senha {ticket.queue.prefix}{ticket.ticket_number} será chamada em {wait_time} min. Comece a se deslocar!"
                            QueueService.send_notification(None, message, ticket.id, via_websocket=True, user_id=ticket.user_id)

        called_tickets = Ticket.query.filter_by(status='Chamado').all()
        for ticket in called_tickets:
            if ticket.expires_at and ticket.expires_at < now:
                ticket.status = 'Cancelado'
                ticket.queue.active_tickets -= 1
                db.session.commit()
                QueueService.send_notification(
                    None,
                    f"Sua senha {ticket.queue.prefix}{ticket.ticket_number} foi cancelada porque você não validou a presença a tempo.",
                    user_id=ticket.user_id
                )
                logger.info(f"Ticket {ticket.id} cancelado por falta de validação de presença")

    @staticmethod
    def trade_tickets(ticket_from_id, ticket_to_id, user_from_id):
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

    @staticmethod
    def validate_presence(qr_code):
        ticket = Ticket.query.filter_by(qr_code=qr_code).first()
        if not ticket or ticket.status != 'Chamado':
            logger.warning(f"Tentativa inválida de validar presença com QR {qr_code}")
            raise ValueError("Senha inválida ou não chamada")
        ticket.status = 'attended'
        ticket.attended_at = datetime.utcnow()
        
        queue = ticket.queue
        last_ticket = Ticket.query.filter_by(queue_id=queue.id, status='attended')\
            .filter(Ticket.attended_at < ticket.attended_at).order_by(Ticket.attended_at.desc()).first()
        if last_ticket and last_ticket.attended_at:
            ticket.service_time = (ticket.attended_at - last_ticket.attended_at).total_seconds() / 60.0
            queue.last_service_time = ticket.service_time
        
        db.session.commit()
        logger.info(f"Presença validada para ticket {ticket.id}")
        return ticket

    @staticmethod
    def offer_trade(ticket_id, user_id):
        logger.info(f"Iniciando oferta de troca para ticket {ticket_id} por user_id {user_id}")
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != user_id:
            logger.warning(f"Tentativa inválida de oferecer ticket {ticket_id} por {user_id}")
            raise ValueError("Você só pode oferecer sua própria senha.")
        if ticket.status != 'Pendente':
            logger.warning(f"Ticket {ticket_id} no estado {ticket.status} não pode ser oferecido")
            raise ValueError(f"Esta senha está no estado '{ticket.status}' e não pode ser oferecida.")
        if ticket.trade_available:
            logger.warning(f"Ticket {ticket_id} já está oferecido para troca")
            raise ValueError("Esta senha já está oferecida para troca.")
        
        try:
            ticket.trade_available = True
            db.session.commit()
            logger.info(f"Ticket {ticket_id} oferecido para troca com sucesso")
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Erro ao persistir oferta de troca do ticket {ticket_id}: {e}")
            raise ValueError("Erro interno ao oferecer a senha para troca.")

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
        ).order_by(Ticket.created_at.asc()).limit(5).all()

        if socketio:
            for eligible_ticket in eligible_tickets:
                try:
                    emit('trade_available', {
                        'ticket_id': ticket.id,
                        'queue_id': ticket.queue_id,
                        'service': ticket.queue.service,
                        'number': f"{ticket.queue.prefix}{ticket.ticket_number}",
                        'position': max(0, ticket.ticket_number - ticket.queue.current_ticket)
                    }, namespace='/', room=str(eligible_ticket.user_id))
                    logger.debug(f"Evento trade_available emitido para user_id {eligible_ticket.user_id}")
                except Exception as e:
                    logger.error(f"Erro ao emitir trade_available para user_id {eligible_ticket.user_id}: {e}")

        return ticket

    @staticmethod
    def cancel_ticket(ticket_id, user_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != user_id:
            logger.warning(f"Tentativa inválida de cancelar ticket {ticket_id} por user_id={user_id}")
            raise ValueError("Você só pode cancelar sua própria senha")
        if ticket.status != 'Pendente':
            logger.warning(f"Ticket {ticket_id} no estado {ticket.status} não pode ser cancelado")
            raise ValueError("Esta senha não pode ser cancelada no momento")
        
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

def suggest_service_locations(service, user_lat=None, user_lon=None, max_results=3):
    """
    Sugere locais onde o usuário pode encontrar o serviço desejado, usando um modelo de machine learning para pontuar a qualidade de atendimento.
    
    Args:
        service (str): Nome do serviço procurado (ex.: "Consulta Médica").
        user_lat (float): Latitude do usuário (opcional).
        user_lon (float): Longitude do usuário (opcional).
        max_results (int): Número máximo de sugestões a retornar.
    
    Returns:
        list: Lista de sugestões ordenadas por pontuação.
    """
    queues = Queue.query.all()
    suggestions = []
    now = datetime.utcnow()
    current_time = now.time()
    hour_of_day = now.hour
    day_of_week = now.weekday()

    for queue in queues:
        # Verificar se a fila está aberta e tem vagas disponíveis
        if current_time < queue.open_time:
            continue
        if queue.active_tickets >= queue.daily_limit:
            continue

        # Verificar correspondência com o serviço ou setor
        service_match = service.lower() in queue.service.lower()
        sector_match = service.lower() in (queue.sector or "").lower()
        if not (service_match or sector_match):
            continue

        # Calcular o tempo de espera estimado
        next_ticket_number = queue.active_tickets + 1
        wait_time = QueueService.calculate_wait_time(queue.id, next_ticket_number, priority=0)
        if wait_time == "N/A":
            wait_time = float('inf')

        # Calcular a distância
        distance = None
        if user_lat is not None and user_lon is not None:
            distance = QueueService.calculate_distance(user_lat, user_lon, queue.institution)
            if distance is None:
                distance = float('inf')

        # Calcular a pontuação de qualidade de atendimento usando o modelo
        tickets = Ticket.query.filter_by(queue_id=queue.id, status='attended').all()
        service_times = [t.service_time for t in tickets if t.service_time is not None and t.service_time > 0]
        quality_score = None
        speed_label = "Desconhecida"
        if service_times:
            avg_service_time = np.mean(service_times)
            std_service_time = np.std(service_times) if len(service_times) > 1 else 0
            service_time_per_counter = avg_service_time / max(1, queue.num_counters)
            occupancy_rate = queue.active_tickets / max(1, queue.daily_limit)
            quality_score = service_recommendation_predictor.predict(
                avg_service_time, std_service_time, service_time_per_counter, occupancy_rate, hour_of_day, day_of_week
            )
            # Classificar a velocidade de atendimento com base no tempo médio
            if avg_service_time <= 5:
                speed_label = "Rápida"
            elif avg_service_time <= 15:
                speed_label = "Moderada"
            else:
                speed_label = "Lenta"
        
        if quality_score is None:
            # Fallback: usar uma pontuação baseada em heurísticas simples
            quality_score = 0.5  # Pontuação neutra
            if service_times:
                avg_service_time = np.mean(service_times)
                std_service_time = np.std(service_times) if len(service_times) > 1 else 0
                quality_score = (1 / (avg_service_time + 1)) - (std_service_time / (avg_service_time + 1))
                quality_score = max(0, min(1, quality_score))  # Normalizar entre 0 e 1

        # Calcular a pontuação final
        # Fórmula: score = (wait_time_score * 0.4) + (distance_score * 0.3) + (quality_score * 0.2) + (match_score * 0.1)
        wait_time_score = 1 / (wait_time + 1) if wait_time != float('inf') else 0
        distance_score = 1 / (distance + 1) if distance is not None and distance != float('inf') else 0
        match_score = 1 if service_match else 0.5
        score = (wait_time_score * 0.4) + (distance_score * 0.3) + (quality_score * 0.2) + (match_score * 0.1)

        suggestions.append({
            'institution': queue.institution_name,
            'location': queue.institution.location,
            'service': queue.service,
            'sector': queue.sector,
            'wait_time': wait_time if wait_time != float('inf') else "Aguardando início",
            'distance': distance if distance is not None else "Desconhecida",
            'quality_score': quality_score,
            'speed_label': speed_label,
            'score': score,
            'queue_id': queue.id,
            'open_time': queue.open_time.strftime('%H:%M'),
            'active_tickets': queue.active_tickets,
            'daily_limit': queue.daily_limit
        })

    suggestions.sort(key=lambda x: x['score'], reverse=True)
    return suggestions[:max_results]
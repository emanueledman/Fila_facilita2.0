# app/services.py
import logging
import uuid
import numpy as np
import math
from datetime import datetime, timedelta
from flask_socketio import emit
from . import db, socketio
from .models import Queue, Ticket
from .utils.pdf_generator import generate_ticket_pdf  # Novo import
import firebase_admin
from firebase_admin import credentials, messaging
import os

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

# Inicializar o Firebase Admin
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": os.getenv("FIREBASE_PROJECT_ID"),
            "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
            "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.getenv("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL"),
            "universe_domain": "googleapis.com"
        })
        firebase_admin.initialize_app(cred)
    logger.info("Firebase Admin inicializado com sucesso")
except Exception as e:
    logger.error(f"Erro ao inicializar o Firebase Admin: {e}")

class QueueService:
    DEFAULT_EXPIRATION_MINUTES = 30

    @staticmethod
    def generate_qr_code():
        qr_code = f"QR-{uuid.uuid4().hex[:8]}"
        logger.debug(f"QR Code gerado: {qr_code}")
        return qr_code

    @staticmethod
    def generate_receipt(ticket):
        queue = ticket.queue
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
    def generate_pdf_ticket(ticket, position, wait_time):
        """Gera um PDF para o ticket físico."""
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
        if not queue or queue.active_tickets == 0:
            return 0
        
        position = max(0, ticket_number - queue.current_ticket)
        if position == 0:
            return 0

        completed_tickets = Ticket.query.filter_by(queue_id=queue_id, status='attended').all()
        service_times = [t.service_time for t in completed_tickets if t.service_time is not None]
        
        if service_times:
            avg_time = np.mean(service_times)
            std_dev = np.std(service_times) if len(service_times) > 1 else 0
            estimated_time = avg_time + min(5, std_dev)
        else:
            estimated_time = queue.avg_wait_time or 5
        
        wait_time = position * estimated_time
        if priority > 0:
            wait_time = max(0, wait_time - (priority * 5))
        if queue.active_tickets > 10:
            wait_time += (queue.active_tickets - 10) * 0.2
        
        queue.avg_wait_time = estimated_time
        db.session.commit()
        logger.debug(f"Wait time calculado para ticket {ticket_number} na fila {queue_id}: {wait_time} min")
        return round(wait_time, 1)

    @staticmethod
    def calculate_distance(user_lat, user_lon, institution):
        if not all([user_lat, user_lon, institution.latitude, institution.longitude]):
            return None
        distance = math.sqrt((user_lat - institution.latitude)**2 + (user_lon - institution.longitude)**2) * 111
        return round(distance, 1)

    @staticmethod
    def send_notification(fcm_token, message, ticket_id=None, via_websocket=False, user_id=None):
        logger.info(f"Notificação para user_id {user_id}: {message}")
        
        # Enviar notificação via FCM usando firebase-admin
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
            logger.warning(f"Token FCM não fornecido para user_id {user_id}")

        # Enviar via WebSocket, se solicitado
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
            raise ValueError("Fila não encontrada")
        if queue.active_tickets >= queue.daily_limit:
            raise ValueError("Limite diário atingido")
        if Ticket.query.filter_by(user_id=user_id, queue_id=queue.id, status='pending').first():
            raise ValueError("Você já possui uma senha ativa")

        ticket_number = queue.active_tickets + 1
        qr_code = QueueService.generate_qr_code()
        expires_at = datetime.utcnow() + timedelta(minutes=QueueService.DEFAULT_EXPIRATION_MINUTES) if is_physical else None
        
        ticket = Ticket(
            id=str(uuid.uuid4()),
            queue_id=queue.id,
            user_id=user_id,
            ticket_number=ticket_number,
            qr_code=qr_code,
            priority=priority,
            is_physical=is_physical,
            expires_at=expires_at
        )
        ticket.receipt_data = QueueService.generate_receipt(ticket) if is_physical else None
        queue.active_tickets += 1
        db.session.add(ticket)
        db.session.commit()

        wait_time = QueueService.calculate_wait_time(queue.id, ticket_number, priority)
        position = max(0, ticket.ticket_number - queue.current_ticket)
        
        # Gera PDF se for ticket físico
        pdf_buffer = None
        if is_physical:
            pdf_buffer = QueueService.generate_pdf_ticket(ticket, position, wait_time)

        message = f"Senha {queue.prefix}{ticket_number} emitida. QR: {qr_code}. Espera: {wait_time} min"
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
            raise ValueError("Fila vazia ou não encontrada")
        
        next_ticket = Ticket.query.filter_by(queue_id=queue.id, status='pending')\
            .order_by(Ticket.priority.desc(), Ticket.ticket_number).first()
        if not next_ticket:
            raise ValueError("Nenhum ticket pendente")
        
        now = datetime.utcnow()
        if next_ticket.expires_at and next_ticket.expires_at < now:
            next_ticket.status = 'cancelled'
            queue.active_tickets -= 1
            db.session.commit()
            return QueueService.call_next(service)
        
        queue.current_ticket = next_ticket.ticket_number
        queue.active_tickets -= 1
        queue.last_counter = (queue.last_counter % queue.num_counters) + 1
        next_ticket.status = 'called'
        next_ticket.counter = queue.last_counter
        next_ticket.attended_at = now
        db.session.commit()
        
        message = f"É a sua vez! {queue.service}, Senha {queue.prefix}{next_ticket.ticket_number}. Guichê {next_ticket.counter:02d}."
        # Aqui você precisaria do fcm_token do usuário. Para simplificar, vamos pular a notificação FCM por enquanto
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
        tickets = Ticket.query.filter_by(status='pending').all()
        for ticket in tickets:
            if ticket.expires_at and ticket.expires_at < now:
                ticket.status = 'cancelled'
                ticket.queue.active_tickets -= 1
                db.session.commit()
                QueueService.send_notification(None, f"Sua senha {ticket.queue.prefix}{ticket.ticket_number} expirou!", user_id=ticket.user_id)
                logger.info(f"Ticket {ticket.id} expirou")
                continue
            
            wait_time = QueueService.calculate_wait_time(ticket.queue_id, ticket.ticket_number, ticket.priority)
            if wait_time <= 5 and ticket.user_id != 'PRESENCIAL':
                distance = QueueService.calculate_distance(-8.8147, 13.2302, ticket.queue.institution)
                distance_msg = f" Você está a {distance} km." if distance else ""
                message = f"Sua vez está próxima! {ticket.queue.service}, Senha {ticket.queue.prefix}{ticket.ticket_number}. " \
                          f"Prepare-se em {wait_time} min.{distance_msg}"
                QueueService.send_notification(None, message, ticket.id, via_websocket=True, user_id=ticket.user_id)

    @staticmethod
    def offer_trade(ticket_id, user_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != user_id or ticket.status != 'pending':
            logger.warning(f"Tentativa inválida de oferecer ticket {ticket_id} por {user_id}")
            raise ValueError("Você não pode oferecer esta senha")
        ticket.trade_available = True
        db.session.commit()
        logger.info(f"Ticket {ticket_id} oferecido para troca por {user_id}")
        return ticket

    @staticmethod
    def trade_tickets(ticket_from_id, ticket_to_id, user_from_id):
        ticket_from = Ticket.query.get_or_404(ticket_from_id)
        ticket_to = Ticket.query.get_or_404(ticket_to_id)
        if ticket_from.user_id != user_from_id or not ticket_to.trade_available or \
           ticket_from.queue_id != ticket_to.queue_id or ticket_from.status != 'pending' or \
           ticket_to.status != 'pending':
            logger.warning(f"Tentativa inválida de troca entre {ticket_from_id} e {ticket_to_id}")
            raise ValueError("Troca inválida")
        
        user_from, user_to = ticket_from.user_id, ticket_to.user_id
        num_from, num_to = ticket_from.ticket_number, ticket_to.ticket_number
        ticket_from.user_id, ticket_from.ticket_number = user_to, num_to
        ticket_to.user_id, ticket_to.ticket_number = user_from, num_from
        ticket_from.trade_available, ticket_to.trade_available = False, False
        db.session.commit()
        logger.info(f"Troca realizada entre {ticket_from_id} e {ticket_to_id}")
        return {"ticket_from": ticket_from, "ticket_to": ticket_to}

    @staticmethod
    def validate_presence(qr_code):
        ticket = Ticket.query.filter_by(qr_code=qr_code).first()
        if not ticket or ticket.status != 'called':
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
    def cancel_ticket(ticket_id, user_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != user_id:
            logger.warning(f"Tentativa inválida de cancelar ticket {ticket_id} por {user_id}")
            raise ValueError("Você só pode cancelar sua própria senha")
        if ticket.status not in ['pending', 'called']:
            raise ValueError("Esta senha não pode ser cancelada")
        
        ticket.status = 'cancelled'
        ticket.cancelled_at = datetime.utcnow()
        ticket.queue.active_tickets -= 1
        db.session.commit()
        logger.info(f"Ticket {ticket_id} cancelado por {user_id}")
        return ticket
# app/services.py
from . import db
from .models import Queue, Ticket
from datetime import datetime, timedelta
import uuid
import requests
import logging
import numpy as np  # Para cálculos estatísticos simples
import math

class QueueService:
    SMS_API_URL = "https://api.sms.com/send"  # Substitua por uma API real
    SMS_API_KEY = "sua_chave"
    EMAIL_API_URL = "https://api.email.com/send"
    EMAIL_API_KEY = "sua_chave"
    FCM_API_URL = "https://fcm.googleapis.com/fcm/send"
    FCM_API_KEY = "sua_chave_fcm"

    @staticmethod
    def generate_qr_code():
        return f"QR-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def calculate_wait_time(queue_id, ticket_number):
        queue = Queue.query.get(queue_id)
        if not queue or queue.active_tickets == 0:
            return 0
        
        position = max(0, ticket_number - queue.current_ticket)
        if position == 0:
            return 0

        # Coleta de tempos reais de atendimento
        completed_tickets = Ticket.query.filter_by(queue_id=queue_id, status='attended').all()
        service_times = [t.service_time for t in completed_tickets if t.service_time is not None]
        
        # Cálculo inteligente do tempo médio
        if service_times:
            avg_time = np.mean(service_times)  # Média dos tempos reais
            std_dev = np.std(service_times) if len(service_times) > 1 else 0  # Desvio padrão
            adjustment = min(5, std_dev)  # Ajuste baseado na variabilidade (máx 5 min)
            estimated_time = avg_time + adjustment
        else:
            estimated_time = queue.avg_wait_time  # Valor padrão se não houver histórico
        
        # Ajuste dinâmico baseado na quantidade de pessoas
        active_factor = max(0, (queue.active_tickets - 10) * 0.2)  # 0.2 min extra por pessoa acima de 10
        wait_time = position * estimated_time + active_factor
        
        # Atualiza o avg_wait_time da fila
        queue.avg_wait_time = estimated_time
        db.session.commit()
        
        return round(wait_time, 1)

    @staticmethod
    def calculate_distance(user_lat, user_lon, institution):
        if not user_lat or not user_lon or not institution.latitude or not institution.longitude:
            return None
        # Distância euclidiana simplificada (em km)
        distance = math.sqrt((user_lat - institution.latitude)**2 + (user_lon - institution.longitude)**2) * 111
        return round(distance, 1)

    @staticmethod
    def send_notification(user_id, message, ticket_id=None):
        logging.info(f"Notificação para user_id {user_id}: {message}")
        # Implementação real com FCM
        headers = {"Authorization": f"key={QueueService.FCM_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "to": user_id,
            "notification": {
                "title": "Facilita 2.0",
                "body": message
            },
            "data": {
                "ticket_id": ticket_id if ticket_id else ""
            }
        }
        try:
            response = requests.post(QueueService.FCM_API_URL, json=payload, headers=headers)
            if response.status_code != 200:
                logging.error(f"Erro ao enviar notificação FCM: {response.text}")
        except Exception as e:
            logging.error(f"Erro ao enviar notificação: {e}")

    @staticmethod
    def check_proactive_notifications():
        tickets = Ticket.query.filter_by(status='pending').all()
        for ticket in tickets:
            queue = ticket.queue
            institution = queue.institution
            wait_time = QueueService.calculate_wait_time(queue.id, ticket.ticket_number)
            if wait_time <= 5 and ticket.user_id != 'PRESENCIAL':
                # Simula a localização do usuário (em um sistema real, seria enviada pelo app)
                user_lat, user_lon = -8.8147, 13.2302  # Exemplo: Luanda Centro
                distance = QueueService.calculate_distance(user_lat, user_lon, institution)
                distance_msg = f" Você está a {distance} km do local." if distance else ""
                message = (f"Sua vez está próxima! {institution.name}, {queue.service}. "
                          f"Senha {queue.prefix}{ticket.ticket_number}. "
                          f"Prepare-se para o guichê em {institution.location}.{distance_msg}")
                QueueService.send_notification(ticket.user_id, message, ticket.id)

    @staticmethod
    def offer_trade(ticket_id, user_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != user_id or ticket.status != 'pending':
            raise ValueError("Você não pode oferecer esta senha para troca")
        ticket.trade_available = True
        db.session.commit()
        queue = ticket.queue
        QueueService.send_notification(user_id, f"Sua senha {queue.prefix}{ticket.ticket_number} está disponível para troca.")
        return ticket

    @staticmethod
    def trade_tickets(ticket_from_id, ticket_to_id, user_from_id):
        ticket_from = Ticket.query.get_or_404(ticket_from_id)
        ticket_to = Ticket.query.get_or_404(ticket_to_id)
        
        if ticket_from.user_id != user_from_id:
            raise ValueError("Você só pode trocar sua própria senha")
        if not ticket_to.trade_available or ticket_to.status != 'pending':
            raise ValueError("A senha destino não está disponível para troca")
        if ticket_from.queue_id != ticket_to.queue_id or ticket_from.status != 'pending':
            raise ValueError("Troca inválida: serviços ou status incompatíveis")
        
        user_from = ticket_from.user_id
        user_to = ticket_to.user_id
        num_from = ticket_from.ticket_number
        num_to = ticket_to.ticket_number
        
        ticket_from.user_id = user_to
        ticket_from.ticket_number = num_to
        ticket_from.trade_available = False
        ticket_to.user_id = user_from
        ticket_to.ticket_number = num_from
        ticket_to.trade_available = False
        
        db.session.commit()
        
        queue = ticket_from.queue
        QueueService.send_notification(user_from, f"Troca realizada! Sua nova senha é {queue.prefix}{ticket_to.ticket_number}.")
        QueueService.send_notification(user_to, f"Troca realizada! Sua nova senha é {queue.prefix}{ticket_from.ticket_number}.")
        return {"ticket_from": ticket_from, "ticket_to": ticket_to}

    @staticmethod
    def validate_presence(qr_code):
        ticket = Ticket.query.filter_by(qr_code=qr_code).first()
        if not ticket or ticket.status != 'called':
            raise ValueError("Senha inválida ou não chamada")
        ticket.status = 'attended'
        ticket.attended_at = datetime.utcnow()
        
        # Calcula o tempo real de atendimento
        queue = ticket.queue
        last_ticket = Ticket.query.filter_by(queue_id=queue.id, status='attended')\
            .filter(Ticket.attended_at < ticket.attended_at).order_by(Ticket.attended_at.desc()).first()
        if last_ticket and last_ticket.attended_at:
            service_time = (ticket.attended_at - last_ticket.attended_at).total_seconds() / 60.0
            ticket.service_time = service_time
            queue.last_service_time = service_time
        
        db.session.commit()
        return ticket

    @staticmethod
    def cancel_ticket(ticket_id, user_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != user_id:
            raise ValueError("Você só pode cancelar sua própria senha")
        if ticket.status not in ['pending', 'called']:
            raise ValueError("Esta senha não pode ser cancelada")
        
        ticket.status = 'cancelled'
        ticket.cancelled_at = datetime.utcnow()
        ticket.queue.active_tickets -= 1
        db.session.commit()
        
        queue = ticket.queue
        QueueService.send_notification(user_id, f"Sua senha {queue.prefix}{ticket.ticket_number} foi cancelada.")
        return ticket
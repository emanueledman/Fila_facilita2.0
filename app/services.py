# app/services.py
from . import db
from .models import Queue, Ticket
from datetime import datetime, timedelta
import uuid
import requests
import logging

class QueueService:
    SMS_API_URL = "https://api.sms.com/send"  # Substitua por uma API real
    SMS_API_KEY = "sua_chave"
    EMAIL_API_URL = "https://api.email.com/send"
    EMAIL_API_KEY = "sua_chave"
    FCM_API_URL = "https://fcm.googleapis.com/fcm/send"
    FCM_API_KEY = "sua_chave_fcm"

    @staticmethod
    def generate_qr_code():
        return f"QR-{uuid.uuid4().hex[:8]}"  # Código único simples

    @staticmethod
    def calculate_wait_time(queue_id, ticket_number):
        queue = Queue.query.get(queue_id)
        position = ticket_number - queue.current_ticket
        wait_time = max(0, position * queue.avg_wait_time)
        
        # Previsão dinâmica simples (ajuste baseado em histórico)
        active_tickets = queue.active_tickets
        if active_tickets > 10:  # Exemplo de ajuste dinâmico
            wait_time += int(active_tickets * 0.5)  # Aumenta 0.5 min por pessoa extra
        return wait_time

    @staticmethod
    def send_notification(user_id, message):
        # Simulação de envio (substitua por APIs reais)
        logging.info(f"Notificação para user_id {user_id}: {message}")
        # Exemplo de integração com FCM (Firebase Cloud Messaging)
        # requests.post(QueueService.FCM_API_URL, json={
        #     "to": user_id,  # Substituir por token real do dispositivo
        #     "notification": {"title": "Facilita 2.0", "body": message}
        # }, headers={"Authorization": f"key={QueueService.FCM_API_KEY}"})

    @staticmethod
    def offer_trade(ticket_id, user_id):
        ticket = Ticket.query.get_or_404(ticket_id)
        if ticket.user_id != user_id or ticket.status != 'pending':
            raise ValueError("Você não pode oferecer esta senha para troca")
        ticket.trade_available = True
        db.session.commit()
        QueueService.send_notification(user_id, f"Sua senha {ticket.ticket_number} está disponível para troca.")
        return ticket

    @staticmethod
    def trade_tickets(ticket_from_id, ticket_to_id, user_from_id):
        ticket_from = Ticket.query.get_or_404(ticket_from_id)
        ticket_to = Ticket.query.get_or_404(ticket_to_id)
        
        if ticket_from.user_id != user_from_id:
            raise ValueError("Você só pode trocar sua própria senha")
        if not ticket_to.trade_available:
            raise ValueError("A senha destino não está disponível para troca")
        if ticket_from.queue_id != ticket_to.queue_id or ticket_from.status != 'pending' or ticket_to.status != 'pending':
            raise ValueError("Troca inválida: serviços ou status incompatíveis")
        
        # Troca de usuários e números
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
        
        QueueService.send_notification(user_from, f"Troca realizada! Sua nova senha é #{ticket_to.ticket_number}.")
        QueueService.send_notification(user_to, f"Troca realizada! Sua nova senha é #{ticket_from.ticket_number}.")
        return {"ticket_from": ticket_from, "ticket_to": ticket_to}

    @staticmethod
    def validate_presence(qr_code):
        ticket = Ticket.query.filter_by(qr_code=qr_code).first()
        if not ticket or ticket.status != 'called':
            raise ValueError("Senha inválida ou não chamada")
        ticket.status = 'attended'
        db.session.commit()
        return ticket
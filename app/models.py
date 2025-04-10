# app/models.py
from . import db
from datetime import datetime, time

class Institution(db.Model):
    id = db.Column(db.String(36), primary_key=True)  # UUID para instituições
    name = db.Column(db.String(100), nullable=False, unique=True)  # Nome da instituição
    location = db.Column(db.String(200), nullable=False)  # Endereço
    latitude = db.Column(db.Float, nullable=True)  # Latitude para cálculos de distância
    longitude = db.Column(db.Float, nullable=True)  # Longitude para cálculos de distância
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Institution {self.name}>'

class Queue(db.Model):
    id = db.Column(db.String(36), primary_key=True)  # UUID para filas
    institution_id = db.Column(db.String(36), db.ForeignKey('institution.id'), nullable=False)
    service = db.Column(db.String(100), nullable=False)  # Nome do departamento/tipo de serviço
    prefix = db.Column(db.String(2), nullable=False)  # Prefixo da senha (ex.: "A")
    sector = db.Column(db.String(50), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    institution_name = db.Column(db.String(100), nullable=False)  # Mantido para compatibilidade
    open_time = db.Column(db.Time, nullable=False)
    daily_limit = db.Column(db.Integer, nullable=False)
    num_counters = db.Column(db.Integer, default=1)  # Número de guichês
    last_counter = db.Column(db.Integer, default=0)  # Último guichê usado (para round-robin)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    current_ticket = db.Column(db.Integer, default=0)  # Última senha chamada
    active_tickets = db.Column(db.Integer, default=0)  # Total de senhas ativas
    avg_wait_time = db.Column(db.Float, default=10.0)  # Tempo médio em minutos (ajustado por IA)
    last_service_time = db.Column(db.Float, default=0.0)  # Tempo do último atendimento (para IA)
    institution = db.relationship('Institution', backref=db.backref('queues', lazy=True))

    def __repr__(self):
        return f'<Queue {self.service} - {self.institution_name}>'

class Ticket(db.Model):
    id = db.Column(db.String(36), primary_key=True)  # UUID para senhas
    queue_id = db.Column(db.String(36), db.ForeignKey('queue.id'), nullable=False)
    user_id = db.Column(db.String(36), nullable=False)  # 'PRESENCIAL' para senhas físicas
    ticket_number = db.Column(db.Integer, nullable=False)
    qr_code = db.Column(db.String(50), unique=True)  # Código único para validação
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # pending, called, cancelled, attended
    trade_available = db.Column(db.Boolean, default=False)
    attended_at = db.Column(db.DateTime, nullable=True)  # Quando foi atendido
    cancelled_at = db.Column(db.DateTime, nullable=True)  # Quando foi cancelado
    service_time = db.Column(db.Float, nullable=True)  # Tempo real de atendimento (em minutos)
    counter = db.Column(db.Integer, nullable=True)  # Guichê atribuído
    priority = db.Column(db.Integer, nullable=False, default=0)  # Adicionado
    is_physical = db.Column(db.Boolean, nullable=False, default=False)  # Adicionado
    expires_at = db.Column(db.DateTime, nullable=True)  # Adicionado
    queue = db.relationship('Queue', backref=db.backref('tickets', lazy=True))

    def __repr__(self):
        return f'<Ticket {self.ticket_number} - {self.status}>'
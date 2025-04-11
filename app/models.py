from . import db
from datetime import datetime
import bcrypt
from sqlalchemy import Column, Integer, String, Float, Time, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

class Institution(db.Model):
    __tablename__ = 'institution'
    id = Column(String(36), primary_key=True, index=True)  # Índice para consultas rápidas
    name = Column(String(100), nullable=False)
    location = Column(String(200))
    latitude = Column(Float)
    longitude = Column(Float)

    def __repr__(self):
        return f'<Institution {self.name}>'

class Queue(db.Model):
    __tablename__ = 'queue'
    id = Column(String(36), primary_key=True, index=True)  # Índice para consultas rápidas
    institution_id = Column(String(36), ForeignKey('institution.id'), nullable=False, index=True)  # Índice para joins
    service = Column(String(50), nullable=False, index=True)  # Índice para filtros por serviço
    prefix = Column(String(10), nullable=False)
    sector = Column(String(50))
    end_time = Column(Time, nullable=True)
    department = Column(String(50), index=True)  # Índice para filtros por departamento
    institution_name = Column(String(100))
    open_time = Column(Time, nullable=False)
    daily_limit = Column(Integer, nullable=False)
    active_tickets = Column(Integer, default=0)
    current_ticket = Column(Integer, default=0)
    avg_wait_time = Column(Float)
    last_service_time = Column(Float)
    num_counters = Column(Integer, default=1)
    last_counter = Column(Integer, default=0)

    institution = relationship('Institution', backref=db.backref('queues', lazy='dynamic'))  # Lazy='dynamic' para eficiência

    def __repr__(self):
        return f'<Queue {self.service} at {self.institution_name}>'

class Ticket(db.Model):
    __tablename__ = 'ticket'
    id = Column(String(36), primary_key=True, index=True)  # Índice para consultas rápidas
    queue_id = Column(String(36), ForeignKey('queue.id'), nullable=False, index=True)  # Índice para joins
    user_id = Column(String(36), nullable=False, index=True)  # Índice para filtros por usuário
    ticket_number = Column(Integer, nullable=False)
    qr_code = Column(String(50), nullable=False, unique=True)  # Unique para evitar duplicatas
    priority = Column(Integer, default=0)
    is_physical = Column(Boolean, default=False)
    status = Column(String(20), default='Pendente')  # Pendente, Chamado, Atendido, Cancelado
    issued_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    attended_at = Column(DateTime)
    cancelled_at = Column(DateTime)
    counter = Column(Integer)
    service_time = Column(Float)
    receipt_data = Column(db.Text)
    trade_available = Column(Boolean, default=False)

    queue = relationship('Queue', backref=db.backref('tickets', lazy='dynamic'))  # Lazy='dynamic' para eficiência

    def __repr__(self):
        return f'<Ticket {self.ticket_number} for Queue {self.queue_id}>'

class User(db.Model):
    __tablename__ = 'user'
    id = Column(String(36), primary_key=True, index=True)  # Índice para consultas rápidas
    email = Column(String(120), unique=True, nullable=False, index=True)  # Índice para login
    password_hash = Column(String(128), nullable=True)  # Pode ser null para usuários Firebase
    fcm_token = Column(String(255), nullable=True)
    user_tipo = Column(String(20), default='user', index=True)  # Índice para filtros por tipo
    institution_id = Column(String(36), ForeignKey('institution.id'), nullable=True, index=True)  # Índice para joins
    department = Column(String(50), nullable=True, index=True)  # Índice para filtros por departamento
    last_known_lat = Column(Float, nullable=True)
    last_known_lon = Column(Float, nullable=True)
    last_location_update = Column(DateTime, nullable=True)

    institution = relationship('Institution', backref=db.backref('users', lazy='dynamic'))  # Lazy='dynamic' para eficiência

    def set_password(self, password):
        """Define a senha do usuário com hash seguro."""
        if password:
            self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        """Verifica se a senha fornecida corresponde ao hash armazenado."""
        if not self.password_hash or not password:
            return False
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    def __repr__(self):
        return f'<User {self.email}>'
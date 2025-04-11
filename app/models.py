from . import db
from datetime import datetime
import bcrypt
from sqlalchemy import Column, Integer, String, Float, Time

class Institution(db.Model):
    __tablename__ = 'institution'
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    def __repr__(self):
        return f'<Institution {self.name}>'

class Queue(db.Model):
    __tablename__ = 'queue'
    id = db.Column(db.String(36), primary_key=True)
    institution_id = db.Column(db.String(36), db.ForeignKey('institution.id'), nullable=False)
    service = db.Column(db.String(50), nullable=False)
    prefix = db.Column(db.String(10), nullable=False)
    sector = db.Column(db.String(50))
    end_time = db.Column(db.Time, nullable=True)
    department = db.Column(db.String(50))
    institution_name = db.Column(db.String(100))
    open_time = db.Column(db.Time, nullable=False)
    daily_limit = db.Column(db.Integer, nullable=False)
    active_tickets = db.Column(db.Integer, default=0)
    current_ticket = db.Column(db.Integer, default=0)
    avg_wait_time = db.Column(db.Float)
    last_service_time = db.Column(db.Float)
    num_counters = db.Column(db.Integer, default=1)
    last_counter = db.Column(db.Integer, default=0)

    institution = db.relationship('Institution', backref=db.backref('queues', lazy=True))

    def __repr__(self):
        return f'<Queue {self.service} at {self.institution_name}>'

class Ticket(db.Model):
    __tablename__ = 'ticket'
    id = db.Column(db.String(36), primary_key=True)
    queue_id = db.Column(db.String(36), db.ForeignKey('queue.id'), nullable=False)
    user_id = db.Column(db.String(36), nullable=False)
    ticket_number = db.Column(db.Integer, nullable=False)
    qr_code = db.Column(db.String(50), nullable=False)
    priority = db.Column(db.Integer, default=0)
    is_physical = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='Pendente')  # pending, called, attended, cancelled
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    attended_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    counter = db.Column(db.Integer)
    service_time = db.Column(db.Float)
    receipt_data = db.Column(db.Text)
    trade_available = db.Column(db.Boolean, default=False)

    queue = db.relationship('Queue', backref=db.backref('tickets', lazy=True))

    def __repr__(self):
        return f'<Ticket {self.ticket_number} for Queue {self.queue_id}>'

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.String(36), primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=True)
    fcm_token = db.Column(db.String(255))
    user_tipo = db.Column(db.String(20), default='user')
    institution_id = db.Column(db.String(36), db.ForeignKey('institution.id'), nullable=True)
    department = db.Column(db.String(50), nullable=True)
    last_known_lat = db.Column(db.Float, nullable=True)
    last_known_lon = db.Column(db.Float, nullable=True)
    last_location_update = db.Column(db.DateTime, nullable=True)

    institution = db.relationship('Institution', backref=db.backref('users', lazy=True))

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        if not self.password_hash:
            return False
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    def __repr__(self):
        return f'<User {self.email}>'
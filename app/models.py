from . import db
from datetime import datetime

class Institution(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

class Queue(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    institution_id = db.Column(db.String(36), db.ForeignKey('institution.id'), nullable=False)
    service = db.Column(db.String(50), nullable=False)
    prefix = db.Column(db.String(10), nullable=False)
    sector = db.Column(db.String(50))
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

class Ticket(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    queue_id = db.Column(db.String(36), db.ForeignKey('queue.id'), nullable=False)
    user_id = db.Column(db.String(36), nullable=False)
    ticket_number = db.Column(db.Integer, nullable=False)
    qr_code = db.Column(db.String(50), nullable=False)
    priority = db.Column(db.Integer, default=0)
    is_physical = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='pending')  # pending, called, attended, cancelled
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    attended_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    counter = db.Column(db.Integer)
    service_time = db.Column(db.Float)
    receipt_data = db.Column(db.Text)
    trade_available = db.Column(db.Boolean, default=False)

    queue = db.relationship('Queue', backref=db.backref('tickets', lazy=True))

class User(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    fcm_token = db.Column(db.String(255))
    user_tipo = db.Column(db.String(20), default='user')  # 'user' ou 'gestor'
    institution_id = db.Column(db.String(36), db.ForeignKey('institution.id'), nullable=True)
    department = db.Column(db.String(50), nullable=True)  # Departamento que o gestor atende

    institution = db.relationship('Institution', backref=db.backref('users', lazy=True))

    def __repr__(self):
        return f'<User {self.email}>'
from sqlalchemy import Column, Integer, String, Float, Time, Boolean, DateTime, ForeignKey, Enum, Index, Text, JSON
from sqlalchemy.orm import relationship
from app import db
from datetime import datetime
import bcrypt
import uuid
import enum

# Enums
class UserRole(enum.Enum):
    USER = "user"
    ATTENDANT = "attendant"
    BRANCH_ADMIN = "branch_admin"
    INSTITUTION_ADMIN = "inst_admin"
    SYSTEM_ADMIN = "sys_admin"

class Weekday(enum.Enum):
    MONDAY = "Monday"
    TUESDAY = "Tuesday"
    WEDNESDAY = "Wednesday"
    THURSDAY = "Thursday"
    FRIDAY = "Friday"
    SATURDAY = "Saturday"
    SUNDAY = "Sunday"

# Tabela para tipos de instituições
class InstitutionType(db.Model):
    __tablename__ = 'institution_type'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    logo_url = Column(String(255), nullable=True)
    institutions = relationship('Institution', backref='type', lazy='dynamic')
    
    def __repr__(self):
        return f'<InstitutionType {self.name}>'

# Tabela para serviços da instituição
class InstitutionService(db.Model):
    __tablename__ = 'institution_service'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    institution_id = Column(String(36), ForeignKey('institution.id'), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    category_id = Column(String(36), ForeignKey('service_category.id'), nullable=True, index=True)
    description = Column(Text, nullable=True)
    institution = relationship('Institution', backref=db.backref('services', lazy='dynamic'))
    category = relationship('ServiceCategory', backref=db.backref('services', lazy='dynamic'))
    
    def __repr__(self):
        return f'<InstitutionService {self.name} for Institution {self.institution_id}>'

# Tabela para categorias de serviços
class ServiceCategory(db.Model):
    __tablename__ = 'service_category'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    name = Column(String(100), nullable=False)
    parent_id = Column(String(36), ForeignKey('service_category.id'), nullable=True, index=True)
    description = Column(Text, nullable=True)
    parent = relationship('ServiceCategory', remote_side=[id], backref='subcategories')
    
    def __repr__(self):
        return f'<ServiceCategory {self.name}>'

# Tabela para tags de serviços
class ServiceTag(db.Model):
    __tablename__ = 'service_tag'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    tag = Column(String(50), nullable=False, index=True)
    queue_id = Column(String(36), ForeignKey('queue.id'), nullable=False, index=True)
    queue = relationship('Queue', backref=db.backref('tags', lazy='dynamic'))
    
    def __repr__(self):
        return f'<ServiceTag {self.tag} for Queue {self.queue_id}>'

# Tabela para instituições
class Institution(db.Model):
    __tablename__ = 'institution'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    name = Column(String(100), nullable=False)
    institution_type_id = Column(String(36), ForeignKey('institution_type.id'), nullable=False, index=True)
    description = Column(Text, nullable=True)
    logo_url = Column(String(255), nullable=True)
    
    def __repr__(self):
        return f'<Institution {self.name} ({self.type.name})>'

# Tabela para filiais
class Branch(db.Model):
    __tablename__ = 'branch'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    institution_id = Column(String(36), ForeignKey('institution.id'), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    location = Column(String(200))
    neighborhood = Column(String(100), nullable=True)
    latitude = Column(Float)
    longitude = Column(Float)
    institution = relationship('Institution', backref=db.backref('branches', lazy='dynamic'))
    schedules = relationship('BranchSchedule', back_populates='branch', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Branch {self.name} of {self.institution.name}>'

# Tabela para horários das filiais
class BranchSchedule(db.Model):
    __tablename__ = 'branch_schedules'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    branch_id = Column(String(36), ForeignKey('branch.id'), nullable=False, index=True)
    weekday = Column(Enum(Weekday), nullable=False)
    open_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    is_closed = Column(Boolean, default=False)
    branch = relationship('Branch', back_populates='schedules')
    
    def __repr__(self):
        return f'<BranchSchedule {self.weekday} for Branch {self.branch_id}>'

# Tabela para departamentos
class Department(db.Model):
    __tablename__ = 'department'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    branch_id = Column(String(36), ForeignKey('branch.id'), nullable=False, index=True)
    name = Column(String(50), nullable=False, index=True)
    sector = Column(String(50))
    branch = relationship('Branch', backref=db.backref('departments', lazy='dynamic'))
    
    def __repr__(self):
        return f'<Department {self.name} at {self.branch.name}>'

# Tabela para filas
class Queue(db.Model):
    __tablename__ = 'queue'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    department_id = Column(String(36), ForeignKey('department.id'), nullable=False, index=True)
    service_id = Column(String(36), ForeignKey('institution_service.id'), nullable=False, index=True)
    prefix = Column(String(10), nullable=False)
    daily_limit = Column(Integer, nullable=False)
    active_tickets = Column(Integer, default=0)
    current_ticket = Column(Integer, default=0)
    avg_wait_time = Column(Float)
    last_service_time = Column(Float)
    num_counters = Column(Integer, default=1)
    last_counter = Column(Integer, default=0)
    default_attendant_id = Column(String(36), ForeignKey('user.id'), nullable=True, index=True)
    estimated_wait_time = Column(Float, nullable=True)
    department = relationship('Department', backref=db.backref('queues', lazy='dynamic'))
    service = relationship('InstitutionService', backref=db.backref('queues', lazy='dynamic'))
    default_attendant = relationship('User', backref=db.backref('default_queues', lazy='dynamic'))
    
    def update_estimated_wait_time(self):
        from .ml_models import wait_time_predictor
        self.estimated_wait_time = wait_time_predictor.predict(
            queue_id=self.id,
            position=self.current_ticket + 1,
            active_tickets=self.active_tickets,
            priority=0,
            hour_of_day=datetime.now().hour
        )
    
    def __repr__(self):
        return f'<Queue {self.service.name} at {self.department.name}>'

# Tabela para tickets
class Ticket(db.Model):
    __tablename__ = 'ticket'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    queue_id = Column(String(36), ForeignKey('queue.id'), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey('user.id'), nullable=True, index=True)
    ticket_number = Column(Integer, nullable=False)  # Alterado de Integer para String(50)
    qr_code = Column(String(50), nullable=False, unique=True)
    priority = Column(Integer, default=0)
    is_physical = Column(Boolean, default=False)
    status = Column(String(20), default='Pendente')
    issued_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    attended_at = Column(DateTime)
    cancelled_at = Column(DateTime)
    counter = Column(Integer)
    service_time = Column(Float)
    receipt_data = Column(Text)
    trade_available = Column(Boolean, default=False)
    queue = relationship('Queue', backref=db.backref('tickets', lazy='dynamic'))
    user = relationship('User', backref=db.backref('tickets', lazy='dynamic'))
    
    def __repr__(self):
        return f'<Ticket {self.ticket_number} for Queue {self.queue_id}>'

# Tabela para usuários
class User(db.Model):
    __tablename__ = 'user'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    password_hash = Column(String(128), nullable=True)
    fcm_token = Column(String(255), nullable=True)
    user_role = Column(Enum(UserRole), default=UserRole.USER, index=True)
    branch_id = Column(String(36), ForeignKey('branch.id'), nullable=True, index=True)
    institution_id = Column(String(36), ForeignKey('institution.id'), nullable=True, index=True)
    last_known_lat = Column(Float, nullable=True)
    last_known_lon = Column(Float, nullable=True)
    last_location_update = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    active = Column(Boolean, default=True)
    notification_enabled = Column(Boolean, default=False)
    notification_preferences = Column(JSON, nullable=True)
    branch = relationship('Branch', backref=db.backref('users', lazy='dynamic'))
    institution = relationship('Institution', backref=db.backref('admins', lazy='dynamic'))
    
    def set_password(self, password):
        if password:
            self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
    def check_password(self, password):
        if not self.password_hash or not password:
            return False
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
    
    def __repr__(self):
        return f'<User {self.email} ({self.user_role.value})>'

# Tabela para logs de auditoria
class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=True)
    action = Column(String, nullable=False)
    resource_type = Column(String, nullable=False)
    resource_id = Column(String(36), nullable=False)
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime, nullable=False)
    
    @staticmethod
    def create(user_id, action, resource_type="user_preference", resource_id=None, details=None):
        audit_log = AuditLog(
            id=str(uuid.uuid4()),
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id or str(uuid.uuid4()),
            details=details,
            timestamp=datetime.utcnow()
        )
        db.session.add(audit_log)
        db.session.commit()
        return audit_log

# Tabela para preferências do usuário
class UserPreference(db.Model):
    __tablename__ = 'user_preference'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)
    institution_type_id = Column(String(36), ForeignKey('institution_type.id'), nullable=True, index=True)
    institution_id = Column(String(36), ForeignKey('institution.id'), nullable=True, index=True)
    service_category_id = Column(String(36), ForeignKey('service_category.id'), nullable=True, index=True)
    neighborhood = Column(String(100), nullable=True)
    preference_score = Column(Integer, default=0)
    is_client = Column(Boolean, default=False, nullable=False)
    is_favorite = Column(Boolean, default=False, nullable=False)
    visit_count = Column(Integer, default=0)
    last_visited = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship('User', backref=db.backref('preferences', lazy='dynamic'))
    institution_type = relationship('InstitutionType', backref=db.backref('preferred_by', lazy='dynamic'))
    institution = relationship('Institution', backref=db.backref('preferred_by', lazy='dynamic'))
    service_category = relationship('ServiceCategory', backref=db.backref('preferred_by', lazy='dynamic'))
    
    def __repr__(self):
        return f'<UserPreference for User {self.user_id} (Institution {self.institution_id}, is_client={self.is_client})>'

# Tabela para log de notificações
class NotificationLog(db.Model):
    __tablename__ = 'notification_log'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)
    branch_id = Column(String(36), ForeignKey('branch.id'), nullable=True, index=True)
    queue_id = Column(String(36), ForeignKey('queue.id'), nullable=True, index=True)
    message = Column(String(200), nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default='Sent')
    user = relationship('User', backref=db.backref('notifications', lazy='dynamic'))
    branch = relationship('Branch', backref=db.backref('notifications', lazy='dynamic'))
    queue = relationship('Queue', backref=db.backref('notifications', lazy='dynamic'))
    
    def __repr__(self):
        return f'<NotificationLog for User {self.user_id} at {self.sent_at}>'

# Tabela para comportamento do usuário
class UserBehavior(db.Model):
    __tablename__ = 'user_behavior'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)
    institution_id = Column(String(36), ForeignKey('institution.id'), nullable=True, index=True)
    service_id = Column(String(36), ForeignKey('institution_service.id'), nullable=True, index=True)
    branch_id = Column(String(36), ForeignKey('branch.id'), nullable=True, index=True)
    action = Column(String(50), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user = relationship('User', backref=db.backref('behaviors', lazy='dynamic'))
    institution = relationship('Institution', backref=db.backref('behaviors', lazy='dynamic'))
    service = relationship('InstitutionService', backref=db.backref('behaviors', lazy='dynamic'))
    branch = relationship('Branch', backref=db.backref('behaviors', lazy='dynamic'))
    
    def __repr__(self):
        return f'<UserBehavior User {self.user_id} Action {self.action} at {self.timestamp}>'

# Tabela para localização alternativa do usuário
class UserLocationFallback(db.Model):
    __tablename__ = 'user_location_fallback'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)
    neighborhood = Column(String(100), nullable=True)
    address = Column(String(200), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)
    user = relationship('User', backref=db.backref('location_fallbacks', lazy='dynamic'))
    
    def __repr__(self):
        return f'<UserLocationFallback User {self.user_id} Neighborhood {self.neighborhood}>'

# Índices otimizados
Index('idx_institution_type_id', Institution.institution_type_id)
Index('idx_queue_department_id_service_id', Queue.department_id, Queue.service_id)
Index('idx_audit_log_timestamp', AuditLog.timestamp)
Index('idx_service_tag_queue_id', ServiceTag.queue_id)
Index('idx_branch_institution_id', Branch.institution_id)
Index('idx_user_preference_user_id', UserPreference.user_id)
Index('idx_user_preference_institution_type_id', UserPreference.institution_type_id)
Index('idx_user_preference_institution_id', UserPreference.institution_id)
Index('idx_user_preference_is_client', UserPreference.is_client)
Index('idx_user_preference_is_favorite', UserPreference.is_favorite)
Index('idx_ticket_queue_id_issued_at', Ticket.queue_id, Ticket.issued_at)
Index('idx_user_branch_id', User.branch_id)
Index('idx_user_institution_id', User.institution_id)
Index('idx_notification_log_user_id', NotificationLog.user_id)
Index('idx_notification_log_sent_at', NotificationLog.sent_at)
Index('idx_user_behavior_user_id', UserBehavior.user_id)
Index('idx_user_behavior_timestamp', UserBehavior.timestamp)
Index('idx_user_location_fallback_user_id', UserLocationFallback.user_id)

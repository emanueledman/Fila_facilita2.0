import uuid
from datetime import time, datetime
from .models import Institution, Queue, User, Ticket, Department, UserRole
from . import db

def populate_initial_data(app):
    with app.app_context():
        institutions = [
            {
                'id': str(uuid.uuid4()),
                'name': 'Hospital Viana',
                'location': 'Viana, Luanda',
                'latitude': -8.9035,
                'longitude': 13.3741,
                'departments': [
                    {
                        'name': 'Consulta Geral',
                        'sector': 'Saúde',
                        'queues': [
                            {
                                'service': 'Consulta Geral',
                                'prefix': 'A',
                                'open_time': time(7, 0),
                                'end_time': time(17, 0),
                                'daily_limit': 20,
                                'num_counters': 3
                            }
                        ]
                    },
                    {
                        'name': 'Laboratório',
                        'sector': 'Saúde',
                        'queues': [
                            {
                                'service': 'Exames Laboratoriais',
                                'prefix': 'B',
                                'open_time': time(8, 0),
                                'end_time': time(16, 0),
                                'daily_limit': 15,
                                'num_counters': 2
                            }
                        ]
                    },
                    {
                        'name': 'Vacinação',
                        'sector': 'Saúde',
                        'queues': [
                            {
                                'service': 'Vacinação',
                                'prefix': 'C',
                                'open_time': time(8, 0),
                                'end_time': time(14, 0),
                                'daily_limit': 10,
                                'num_counters': 1
                            }
                        ]
                    }
                ]
            }
        ]

        try:
            queue_ids = {}
            for inst in institutions:
                institution = Institution(
                    id=inst['id'],
                    name=inst['name'],
                    location=inst['location'],
                    latitude=inst['latitude'],
                    longitude=inst['longitude']
                )
                db.session.add(institution)
                db.session.flush()

                for dept in inst['departments']:
                    department = Department(
                        id=str(uuid.uuid4()),
                        institution_id=inst['id'],
                        name=dept['name'],
                        sector=dept['sector']
                    )
                    db.session.add(department)
                    db.session.flush()

                    for q in dept['queues']:
                        queue = Queue(
                            id=str(uuid.uuid4()),
                            department_id=department.id,
                            service=q['service'],
                            prefix=q['prefix'],
                            open_time=q['open_time'],
                            end_time=q.get('end_time'),
                            daily_limit=q['daily_limit'],
                            num_counters=q['num_counters']
                        )
                        db.session.add(queue)
                        queue_ids[dept['name']] = queue.id
            
            db.session.commit()
            app.logger.info("Dados iniciais de instituições, departamentos e filas inseridos com sucesso!")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao inserir dados iniciais: {str(e)}")
            raise

        try:
            gestores = [
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.consulta@viana.com',
                    'name': 'Gestor Consulta',
                    'password': 'admin123',
                    'user_role': UserRole.DEPARTMENT_ADMIN,
                    'institution_id': institutions[0]['id'],
                    'department_id': None,  # Será preenchido após criar departamentos
                    'department_name': 'Consulta Geral'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.exames@viana.com',
                    'name': 'Gestor Exames',
                    'password': 'admin123',
                    'user_role': UserRole.DEPARTMENT_ADMIN,
                    'institution_id': institutions[0]['id'],
                    'department_id': None,
                    'department_name': 'Laboratório'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.vacinacao@viana.com',
                    'name': 'Gestor Vacinação',
                    'password': 'admin123',
                    'user_role': UserRole.DEPARTMENT_ADMIN,
                    'institution_id': institutions[0]['id'],
                    'department_id': None,
                    'department_name': 'Vacinação'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'default.user@viana.com',
                    'name': 'Usuário Padrão',
                    'password': 'user123',
                    'user_role': UserRole.USER,
                    'institution_id': institutions[0]['id'],
                    'department_id': None,
                    'department_name': None
                }
            ]

            for gestor in gestores:
                department = Department.query.filter_by(
                    institution_id=gestor['institution_id'],
                    name=gestor['department_name']
                ).first() if gestor['department_name'] else None
                user = User(
                    id=gestor['id'],
                    email=gestor['email'],
                    name=gestor['name'],
                    user_role=gestor['user_role'],
                    institution_id=gestor['institution_id'],
                    department_id=department.id if department else None,
                    active=True
                )
                user.set_password(gestor['password'])
                db.session.add(user)
            
            db.session.commit()
            app.logger.info("Gestores e usuários iniciais inseridos com sucesso!")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao inserir gestores iniciais: {str(e)}")
            raise

        try:
            default_user = User.query.filter_by(email='default.user@viana.com').first()
            if not default_user:
                raise ValueError("Usuário padrão não encontrado!")

            tickets = [
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Consulta Geral'],
                    'user_id': default_user.id,
                    'ticket_number': 1,
                    'qr_code': f"QR-{uuid.uuid4().hex[:10]}",
                    'status': 'Pendente',
                    'priority': 0,
                    'is_physical': False,
                    'counter': None,
                    'issued_at': datetime.utcnow(),
                    'trade_available': False
                },
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Consulta Geral'],
                    'user_id': default_user.id,
                    'ticket_number': 2,
                    'qr_code': f"QR-{uuid.uuid4().hex[:10]}",
                    'status': 'attended',
                    'priority': 0,
                    'is_physical': False,
                    'counter': 1,
                    'issued_at': datetime.utcnow(),
                    'trade_available': False
                },
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Laboratório'],
                    'user_id': default_user.id,
                    'ticket_number': 1,
                    'qr_code': f"QR-{uuid.uuid4().hex[:10]}",
                    'status': 'Pendente',
                    'priority': 0,
                    'is_physical': False,
                    'counter': None,
                    'issued_at': datetime.utcnow(),
                    'trade_available': False
                },
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Laboratório'],
                    'user_id': default_user.id,
                    'ticket_number': 2,
                    'qr_code': f"QR-{uuid.uuid4().hex[:10]}",
                    'status': 'attended',
                    'priority': 0,
                    'is_physical': False,
                    'counter': 2,
                    'issued_at': datetime.utcnow(),
                    'trade_available': False
                },
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Vacinação'],
                    'user_id': default_user.id,
                    'ticket_number': 1,
                    'qr_code': f"QR-{uuid.uuid4().hex[:10]}",
                    'status': 'Pendente',
                    'priority': 0,
                    'is_physical': False,
                    'counter': None,
                    'issued_at': datetime.utcnow(),
                    'trade_available': False
                },
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Vacinação'],
                    'user_id': default_user.id,
                    'ticket_number': 2,
                    'qr_code': f"QR-{uuid.uuid4().hex[:10]}",
                    'status': 'attended',
                    'priority': 0,
                    'is_physical': False,
                    'counter': 1,
                    'issued_at': datetime.utcnow(),
                    'trade_available': False
                }
            ]

            for t in tickets:
                ticket = Ticket(
                    id=t['id'],
                    queue_id=t['queue_id'],
                    user_id=t['user_id'],
                    ticket_number=t['ticket_number'],
                    qr_code=t['qr_code'],
                    status=t['status'],
                    priority=t['priority'],
                    is_physical=t['is_physical'],
                    counter=t['counter'],
                    issued_at=t['issued_at'],
                    trade_available=t['trade_available']
                )
                db.session.add(ticket)
            
            db.session.commit()
            app.logger.info("Tickets iniciais inseridos com sucesso!")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao inserir tickets iniciais: {str(e)}")
            raise
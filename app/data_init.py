import uuid
from datetime import time, datetime
from .models import Institution, Queue, User, Ticket, Department, UserRole
from . import db

def populate_initial_data(app):
    with app.app_context():
        try:
            # Verificar se já existe um super admin
            super_admin = User.query.filter_by(user_role=UserRole.SYSTEM_ADMIN).first()
            if super_admin:
                app.logger.info("Super admin já existe, pulando inicialização de dados administrativos.")
                return

            institutions = [
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Hospital Josina Machel',
                    'location': 'Luanda, Luanda',
                    'latitude': -8.8167,
                    'longitude': 13.2332,
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
                                    'daily_limit': 50,
                                    'num_counters': 5
                                }
                            ]
                        },
                        {
                            'name': 'Urgência',
                            'sector': 'Saúde',
                            'queues': [
                                {
                                    'service': 'Urgência',
                                    'prefix': 'B',
                                    'open_time': time(0, 0),
                                    'end_time': time(23, 59),
                                    'daily_limit': 100,
                                    'num_counters': 8
                                }
                            ]
                        },
                        {
                            'name': 'Farmácia',
                            'sector': 'Saúde',
                            'queues': [
                                {
                                    'service': 'Distribuição de Medicamentos',
                                    'prefix': 'C',
                                    'open_time': time(8, 0),
                                    'end_time': time(16, 0),
                                    'daily_limit': 60,
                                    'num_counters': 3
                                }
                            ]
                        }
                    ]
                },
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Escola Primária Ngola Kiluanje',
                    'location': 'Viana, Luanda',
                    'latitude': -8.9035,
                    'longitude': 13.3741,
                    'departments': [
                        {
                            'name': 'Secretaria Escolar',
                            'sector': 'Educação',
                            'queues': [
                                {
                                    'service': 'Matrículas',
                                    'prefix': 'M',
                                    'open_time': time(8, 0),
                                    'end_time': time(14, 0),
                                    'daily_limit': 30,
                                    'num_counters': 2
                                },
                                {
                                    'service': 'Declarações',
                                    'prefix': 'D',
                                    'open_time': time(8, 0),
                                    'end_time': time(14, 0),
                                    'daily_limit': 20,
                                    'num_counters': 1
                                }
                            ]
                        }
                    ]
                },
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Cartório Notarial de Luanda',
                    'location': 'Luanda, Luanda',
                    'latitude': -8.8147,
                    'longitude': 13.2302,
                    'departments': [
                        {
                            'name': 'Atendimento Notarial',
                            'sector': 'Serviços Públicos',
                            'queues': [
                                {
                                    'service': 'Autenticação de Documentos',
                                    'prefix': 'N',
                                    'open_time': time(8, 0),
                                    'end_time': time(15, 0),
                                    'daily_limit': 40,
                                    'num_counters': 3
                                },
                                {
                                    'service': 'Registo Civil',
                                    'prefix': 'R',
                                    'open_time': time(8, 0),
                                    'end_time': time(15, 0),
                                    'daily_limit': 30,
                                    'num_counters': 2
                                }
                            ]
                        }
                    ]
                },
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Hospital Maria Pia',
                    'location': 'Luanda, Luanda',
                    'latitude': -8.8200,
                    'longitude': 13.2400,
                    'departments': [
                        {
                            'name': 'Pediatria',
                            'sector': 'Saúde',
                            'queues': [
                                {
                                    'service': 'Consulta Pediátrica',
                                    'prefix': 'P',
                                    'open_time': time(7, 30),
                                    'end_time': time(16, 30),
                                    'daily_limit': 40,
                                    'num_counters': 4
                                }
                            ]
                        },
                        {
                            'name': 'Maternidade',
                            'sector': 'Saúde',
                            'queues': [
                                {
                                    'service': 'Consulta Pré-Natal',
                                    'prefix': 'M',
                                    'open_time': time(8, 0),
                                    'end_time': time(15, 0),
                                    'daily_limit': 30,
                                    'num_counters': 2
                                }
                            ]
                        }
                    ]
                },
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Instituto Médio de Saúde de Luanda',
                    'location': 'Luanda, Luanda',
                    'latitude': -8.8300,
                    'longitude': 13.2500,
                    'departments': [
                        {
                            'name': 'Administração Escolar',
                            'sector': 'Educação',
                            'queues': [
                                {
                                    'service': 'Inscrições',
                                    'prefix': 'I',
                                    'open_time': time(8, 0),
                                    'end_time': time(13, 0),
                                    'daily_limit': 25,
                                    'num_counters': 2
                                }
                            ]
                        }
                    ]
                }
            ]

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
                        queue_ids[f"{dept['name']}_{q['service']}"] = queue.id
            
            db.session.commit()
            app.logger.info("Dados iniciais de instituições, departamentos e filas inseridos com sucesso!")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao inserir dados iniciais de instituições: {str(e)}")
            raise

        try:
            users = [
                {
                    'id': str(uuid.uuid4()),
                    'email': 'superadmin@facilita.com',
                    'name': 'Super Admin',
                    'password': 'superadmin123',
                    'user_role': UserRole.SYSTEM_ADMIN,
                    'institution_id': None,
                    'department_id': None,
                    'department_name': None
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'admin.josina@facilita.com',
                    'name': 'Admin Josina Machel',
                    'password': 'admin123',
                    'user_role': UserRole.INSTITUTION_ADMIN,
                    'institution_id': institutions[0]['id'],
                    'department_id': None,
                    'department_name': None
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.consulta@josina.com',
                    'name': 'Gestor Consulta Josina',
                    'password': 'admin123',
                    'user_role': UserRole.DEPARTMENT_ADMIN,
                    'institution_id': institutions[0]['id'],
                    'department_id': None,
                    'department_name': 'Consulta Geral'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.urgencia@josina.com',
                    'name': 'Gestor Urgência Josina',
                    'password': 'admin123',
                    'user_role': UserRole.DEPARTMENT_ADMIN,
                    'institution_id': institutions[0]['id'],
                    'department_id': None,
                    'department_name': 'Urgência'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.farmacia@josina.com',
                    'name': 'Gestor Farmácia Josina',
                    'password': 'admin123',
                    'user_role': UserRole.DEPARTMENT_ADMIN,
                    'institution_id': institutions[0]['id'],
                    'department_id': None,
                    'department_name': 'Farmácia'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'admin.ngola@facilita.com',
                    'name': 'Admin Ngola Kiluanje',
                    'password': 'admin123',
                    'user_role': UserRole.INSTITUTION_ADMIN,
                    'institution_id': institutions[1]['id'],
                    'department_id': None,
                    'department_name': None
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.secretaria@ngola.com',
                    'name': 'Gestor Secretaria Ngola',
                    'password': 'admin123',
                    'user_role': UserRole.DEPARTMENT_ADMIN,
                    'institution_id': institutions[1]['id'],
                    'department_id': None,
                    'department_name': 'Secretaria Escolar'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'admin.cartorio@facilita.com',
                    'name': 'Admin Cartório Luanda',
                    'password': 'admin123',
                    'user_role': UserRole.INSTITUTION_ADMIN,
                    'institution_id': institutions[2]['id'],
                    'department_id': None,
                    'department_name': None
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.notarial@cartorio.com',
                    'name': 'Gestor Notarial Luanda',
                    'password': 'admin123',
                    'user_role': UserRole.DEPARTMENT_ADMIN,
                    'institution_id': institutions[2]['id'],
                    'department_id': None,
                    'department_name': 'Atendimento Notarial'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'admin.mariapia@facilita.com',
                    'name': 'Admin Maria Pia',
                    'password': 'admin123',
                    'user_role': UserRole.INSTITUTION_ADMIN,
                    'institution_id': institutions[3]['id'],
                    'department_id': None,
                    'department_name': None
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.pediatria@mariapia.com',
                    'name': 'Gestor Pediatria Maria Pia',
                    'password': 'admin123',
                    'user_role': UserRole.DEPARTMENT_ADMIN,
                    'institution_id': institutions[3]['id'],
                    'department_id': None,
                    'department_name': 'Pediatria'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.maternidade@mariapia.com',
                    'name': 'Gestor Maternidade Maria Pia',
                    'password': 'admin123',
                    'user_role': UserRole.DEPARTMENT_ADMIN,
                    'institution_id': institutions[3]['id'],
                    'department_id': None,
                    'department_name': 'Maternidade'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'admin.ims@facilita.com',
                    'name': 'Admin IMS Luanda',
                    'password': 'admin123',
                    'user_role': UserRole.INSTITUTION_ADMIN,
                    'institution_id': institutions[4]['id'],
                    'department_id': None,
                    'department_name': None
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.admin@ims.com',
                    'name': 'Gestor Administração IMS',
                    'password': 'admin123',
                    'user_role': UserRole.DEPARTMENT_ADMIN,
                    'institution_id': institutions[4]['id'],
                    'department_id': None,
                    'department_name': 'Administração Escolar'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'default.user@facilita.com',
                    'name': 'Usuário Padrão',
                    'password': 'user123',
                    'user_role': UserRole.USER,
                    'institution_id': institutions[0]['id'],
                    'department_id': None,
                    'department_name': 'Consulta Geral'
                }
            ]

            for user_data in users:
                department = Department.query.filter_by(
                    institution_id=user_data['institution_id'],
                    name=user_data['department_name']
                ).first() if user_data['department_name'] else None
                user = User(
                    id=user_data['id'],
                    email=user_data['email'],
                    name=user_data['name'],
                    user_role=user_data['user_role'],
                    institution_id=user_data['institution_id'],
                    department_id=department.id if department else None,
                    active=True
                )
                user.set_password(user_data['password'])
                db.session.add(user)
            
            db.session.commit()
            app.logger.info("Usuários iniciais (super admin, admins, gestores e usuário padrão) inseridos com sucesso!")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao inserir usuários iniciais: {str(e)}")
            raise

        try:
            default_user = User.query.filter_by(email='default.user@facilita.com').first()
            if not default_user:
                raise ValueError("Usuário padrão não encontrado!")

            tickets = [
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Consulta Geral_Consulta Geral'],
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
                    'queue_id': queue_ids['Consulta Geral_Consulta Geral'],
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
                    'queue_id': queue_ids['Urgência_Urgência'],
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
                    'queue_id': queue_ids['Farmácia_Distribuição de Medicamentos'],
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
                    'queue_id': queue_ids['Secretaria Escolar_Matrículas'],
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
                    'queue_id': queue_ids['Atendimento Notarial_Autenticação de Documentos'],
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
                    'queue_id': queue_ids['Pediatria_Consulta Pediátrica'],
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
                    'queue_id': queue_ids['Administração Escolar_Inscrições'],
                    'user_id': default_user.id,
                    'ticket_number': 1,
                    'qr_code': f"QR-{uuid.uuid4().hex[:10]}",
                    'status': 'Pendente',
                    'priority': 0,
                    'is_physical': False,
                    'counter': None,
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
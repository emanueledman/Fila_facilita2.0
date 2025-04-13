import uuid
from datetime import time, datetime
from .models import Institution, Queue, User, Ticket
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
                'queues': [
                    {
                        'service': 'Consulta Geral',
                        'prefix': 'A',
                        'sector': 'Saúde',
                        'department': 'Consulta Geral',
                        'open_time': time(7, 0),
                        'end_time': time(17, 0),
                        'daily_limit': 20,
                        'num_counters': 3
                    },
                    {
                        'service': 'Exames Laboratoriais',
                        'prefix': 'B',
                        'sector': 'Saúde',
                        'department': 'Laboratório',
                        'open_time': time(8, 0),
                        'end_time': time(16, 0),
                        'daily_limit': 15,
                        'num_counters': 2
                    },
                    {
                        'service': 'Vacinação',
                        'prefix': 'C',
                        'sector': 'Saúde',
                        'department': 'Vacinação',
                        'open_time': time(8, 0),
                        'end_time': time(14, 0),
                        'daily_limit': 10,
                        'num_counters': 1
                    },
                ]
            },
        ]

        try:
            queue_ids = {}  # Armazenar IDs das filas para tickets
            for inst in institutions:
                institution = Institution(
                    id=inst['id'],
                    name=inst['name'],
                    location=inst['location'],
                    latitude=inst['latitude'],
                    longitude=inst['longitude']
                )
                db.session.add(institution)
                
                for q in inst['queues']:
                    queue = Queue(
                        id=str(uuid.uuid4()),
                        institution_id=inst['id'],
                        service=q['service'],
                        prefix=q['prefix'],
                        sector=q['sector'],
                        department=q['department'],
                        institution_name=inst['name'],
                        open_time=q['open_time'],
                        end_time=q.get('end_time'),
                        daily_limit=q['daily_limit'],
                        num_counters=q['num_counters']
                    )
                    db.session.add(queue)
                    queue_ids[q['department']] = queue.id  # Mapear departamento ao queue_id
            
            db.session.commit()
            app.logger.info("Dados iniciais de instituições e filas inseridos com sucesso!")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao inserir dados iniciais de instituições: {str(e)}")
            raise

        try:
            gestores = [
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.consulta@viana.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[0]['id'],
                    'department': 'Consulta Geral'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.exames@viana.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[0]['id'],
                    'department': 'Laboratório'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.vacinacao@viana.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[0]['id'],
                    'department': 'Vacinação'
                },
                # Adicionar um usuário padrão para tickets
                {
                    'id': str(uuid.uuid4()),
                    'email': 'default.user@viana.com',
                    'password': 'user123',
                    'user_tipo': 'user',
                    'institution_id': institutions[0]['id'],
                    'department': None
                },
            ]

            for gestor in gestores:
                user = User(
                    id=gestor['id'],
                    email=gestor['email'],
                    user_tipo=gestor['user_tipo'],
                    institution_id=gestor['institution_id'],
                    department=gestor['department']
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
            # Encontrar o ID do usuário padrão
            default_user = User.query.filter_by(email='default.user@viana.com').first()
            if not default_user:
                raise ValueError("Usuário padrão não encontrado!")

            tickets = [
                # Consulta Geral
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
                # Exames Laboratoriais
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
                # Vacinação
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
                },
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
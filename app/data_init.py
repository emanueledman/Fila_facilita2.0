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
            app.logger.info("Gestores iniciais inseridos com sucesso!")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao inserir gestores iniciais: {str(e)}")
            raise

        try:
            tickets = [
                # Consulta Geral
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Consulta Geral'],
                    'ticket_number': '001',
                    'status': 'Pendente',
                    'priority': False,
                    'counter': None,
                    'issued_at': datetime.utcnow()
                },
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Consulta Geral'],
                    'ticket_number': '002',
                    'status': 'attended',
                    'priority': False,
                    'counter': 1,
                    'issued_at': datetime.utcnow()
                },
                # Exames Laboratoriais
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Laboratório'],
                    'ticket_number': '001',
                    'status': 'Pendente',
                    'priority': False,
                    'counter': None,
                    'issued_at': datetime.utcnow()
                },
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Laboratório'],
                    'ticket_number': '002',
                    'status': 'attended',
                    'priority': False,
                    'counter': 2,
                    'issued_at': datetime.utcnow()
                },
                # Vacinação
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Vacinação'],
                    'ticket_number': '001',
                    'status': 'Pendente',
                    'priority': False,
                    'counter': None,
                    'issued_at': datetime.utcnow()
                },
                {
                    'id': str(uuid.uuid4()),
                    'queue_id': queue_ids['Vacinação'],
                    'ticket_number': '002',
                    'status': 'attended',
                    'priority': False,
                    'counter': 1,
                    'issued_at': datetime.utcnow()
                },
            ]

            for t in tickets:
                ticket = Ticket(
                    id=t['id'],
                    queue_id=t['queue_id'],
                    ticket_number=t['ticket_number'],
                    status=t['status'],
                    priority=t['priority'],
                    counter=t['counter'],
                    issued_at=t['issued_at']
                )
                db.session.add(ticket)
            
            db.session.commit()
            app.logger.info("Tickets iniciais inseridos com sucesso!")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao inserir tickets iniciais: {str(e)}")
            raise
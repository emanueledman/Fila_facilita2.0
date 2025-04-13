import uuid
from datetime import time
from . import db
from .models import Institution, Queue, User

def populate_initial_data(app):
    with app.app_context():
        institutions = [
            # Instituições de Saúde
            {
                'id': str(uuid.uuid4()),
                'name': 'Centro de Saúde Camama',
                'location': 'Camama, Luanda',
                'latitude': -8.8383,
                'longitude': 13.2312,
                'queues': [
                    {'service': 'Consulta Geral', 'prefix': 'A', 'sector': 'Saúde', 'department': 'Consulta Geral', 'open_time': time(7, 0), 'end_time': time(17, 0), 'daily_limit': 20, 'num_counters': 3},
                    {'service': 'Vacinação Infantil', 'prefix': 'B', 'sector': 'Saúde', 'department': 'Vacinação', 'open_time': time(8, 0), 'end_time': time(16, 0), 'daily_limit': 18, 'num_counters': 2},
                ]
            },
            {
                'id': str(uuid.uuid4()),
                'name': 'Hospital Viana',
                'location': 'Viana, Luanda',
                'latitude': -8.9035,
                'longitude': 13.3741,
                'queues': [
                    {'service': 'Consulta Geral', 'prefix': 'A', 'sector': 'Saúde', 'department': 'Consulta Geral', 'open_time': time(7, 0), 'end_time': time(17, 0), 'daily_limit': 20, 'num_counters': 3},
                    {'service': 'Exames Laboratoriais', 'prefix': 'B', 'sector': 'Saúde', 'department': 'Laboratório', 'open_time': time(8, 0), 'end_time': time(16, 0), 'daily_limit': 15, 'num_counters': 2},
                ]
            },
            # ... (outras instituições permanecem inalteradas)
        ]

        try:
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
            
            db.session.commit()
            app.logger.info("Dados iniciais de instituições e filas inseridos com sucesso!")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao inserir dados iniciais de instituições: {str(e)}")
            raise

        try:
            gestores = [
                {'id': str(uuid.uuid4()), 'email': 'gestor.camama@saude.com', 'password': 'admin123', 'user_tipo': 'gestor', 'institution_id': institutions[0]['id'], 'department': 'Consulta Geral'},
                {'id': str(uuid.uuid4()), 'email': 'gestor.vacinacao@saude.com', 'password': 'admin123', 'user_tipo': 'gestor', 'institution_id': institutions[0]['id'], 'department': 'Vacinação'},
                {'id': str(uuid.uuid4()), 'email': 'gestor.hospital@viana.com', 'password': 'admin123', 'user_tipo': 'gestor', 'institution_id': institutions[1]['id'], 'department': 'Consulta Geral'},
                {'id': str(uuid.uuid4()), 'email': 'gestor.laboratorio@viana.com', 'password': 'admin123', 'user_tipo': 'gestor', 'institution_id': institutions[1]['id'], 'department': 'Laboratório'},
                # ... (outros gestores permanecem inalterados)
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
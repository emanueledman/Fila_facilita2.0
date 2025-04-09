# run.py
from app import create_app, db
from app.models import Institution, Queue
from datetime import time
import uuid
import logging

app = create_app()

def populate_initial_data():
    with app.app_context():
        db.drop_all()
        db.create_all()
        
        if Institution.query.count() > 0:
            app.logger.info("Dados iniciais já existem.")
            return
        
        # Instituições com localizações em Luanda
        institutions = [
            {
                'id': str(uuid.uuid4()),
                'name': 'Centro de Saúde Camama',
                'location': 'Camama, Luanda',
                'latitude': -8.8383,
                'longitude': 13.2312,
                'queues': [
                    {'service': 'Consulta Médica', 'prefix': 'A', 'sector': 'Saúde', 'department': 'Consulta Médica', 'open_time': time(7, 0), 'daily_limit': 20, 'num_counters': 3},
                    {'service': 'Vacinação Infantil', 'prefix': 'B', 'sector': 'Saúde', 'department': 'Vacinação', 'open_time': time(8, 0), 'daily_limit': 18, 'num_counters': 2},
                ]
            },
            {
                'id': str(uuid.uuid4()),
                'name': 'Posto de Identificação Luanda',
                'location': 'Luanda Centro, Luanda',
                'latitude': -8.8147,
                'longitude': 13.2302,
                'queues': [
                    {'service': 'Emissão de BI', 'prefix': 'A', 'sector': 'Documentação', 'department': 'Identificação', 'open_time': time(8, 0), 'daily_limit': 30, 'num_counters': 4},
                    {'service': 'Registo de Nascimento', 'prefix': 'B', 'sector': 'Documentação', 'department': 'Registo Civil', 'open_time': time(8, 30), 'daily_limit': 25, 'num_counters': 3},
                ]
            },
            {
                'id': str(uuid.uuid4()),
                'name': 'Banco BFA Kilamba',
                'location': 'Kilamba, Luanda',
                'latitude': -8.8472,
                'longitude': 13.1893,
                'queues': [
                    {'service': 'Abertura de Conta', 'prefix': 'A', 'sector': 'Bancário', 'department': 'Contas', 'open_time': time(9, 0), 'daily_limit': 20, 'num_counters': 3},
                    {'service': 'Manutenção de Conta', 'prefix': 'B', 'sector': 'Bancário', 'department': 'Contas', 'open_time': time(9, 0), 'daily_limit': 15, 'num_counters': 2},
                ]
            },
            {
                'id': str(uuid.uuid4()),
                'name': 'Escola Primária Cazenga',
                'location': 'Cazenga, Luanda',
                'latitude': -8.8236,
                'longitude': 13.2854,
                'queues': [
                    {'service': 'Matrícula Escolar', 'prefix': 'A', 'sector': 'Educação', 'department': 'Matrículas', 'open_time': time(7, 30), 'daily_limit': 40, 'num_counters': 2},
                ]
            },
            {
                'id': str(uuid.uuid4()),
                'name': 'Hospital Viana',
                'location': 'Viana, Luanda',
                'latitude': -8.9035,
                'longitude': 13.3741,
                'queues': [
                    {'service': 'Consulta Geral', 'prefix': 'A', 'sector': 'Saúde', 'department': 'Consulta Geral', 'open_time': time(7, 0), 'daily_limit': 20, 'num_counters': 3},
                    {'service': 'Exames Laboratoriais', 'prefix': 'B', 'sector': 'Saúde', 'department': 'Laboratório', 'open_time': time(8, 0), 'daily_limit': 15, 'num_counters': 2},
                ]
            },
            {
                'id': str(uuid.uuid4()),
                'name': 'Direção de Trânsito Talatona',
                'location': 'Talatona, Luanda',
                'latitude': -8.9147,
                'longitude': 13.1809,
                'queues': [
                    {'service': 'Licenciamento de Veículos', 'prefix': 'A', 'sector': 'Transportes', 'department': 'Licenciamento', 'open_time': time(8, 0), 'daily_limit': 35, 'num_counters': 4},
                ]
            },
        ]

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
                    institution_name=inst['name'],  # Mantido para compatibilidade
                    open_time=q['open_time'],
                    daily_limit=q['daily_limit'],
                    num_counters=q['num_counters']
                )
                db.session.add(queue)
        
        db.session.commit()
        app.logger.info("Dados iniciais inseridos com sucesso!")

with app.app_context():
    populate_initial_data()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
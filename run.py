# run.py
from app import create_app, db
from app.models import Queue
from datetime import time
import uuid
import logging

app = create_app()

def populate_initial_data():
    with app.app_context():
        db.drop_all()
        db.create_all()
        
        if Queue.query.count() > 0:
            app.logger.info("Dados iniciais já existem.")
            return
        
        services = [
            {'service': 'Vacinação Infantil', 'sector': 'Saúde', 'department': 'Centro de Saúde Camama', 'institution': 'Ministério da Saúde', 'open_time': time(3, 19), 'daily_limit': 18},
            {'service': 'Emissão de BI', 'sector': 'Documentação', 'department': 'Posto de Identificação Luanda', 'institution': 'Ministério da Justiça', 'open_time': time(8, 0), 'daily_limit': 30},
            {'service': 'Matrícula Escolar', 'sector': 'Educação', 'department': 'Escola Primária Cazenga', 'institution': 'Ministério da Educação', 'open_time': time(7, 30), 'daily_limit': 40},
            {'service': 'Pagamento de Energia', 'sector': 'Serviços Públicos', 'department': 'Agência ENDE Kilamba', 'institution': 'ENDE', 'open_time': time(9, 0), 'daily_limit': 60},
            {'service': 'Registo de Nascimento', 'sector': 'Documentação', 'department': 'Conservatória Rangel', 'institution': 'Ministério da Justiça', 'open_time': time(8, 30), 'daily_limit': 25},
            {'service': 'Consulta Médica', 'sector': 'Saúde', 'department': 'Hospital Viana', 'institution': 'Ministério da Saúde', 'open_time': time(7, 0), 'daily_limit': 20},
            {'service': 'Licenciamento de Veículos', 'sector': 'Transportes', 'department': 'Direção de Trânsito Luanda', 'institution': 'Ministério dos Transportes', 'open_time': time(8, 0), 'daily_limit': 35},
        ]

        for s in services:
            queue = Queue(id=str(uuid.uuid4()), **s)
            db.session.add(queue)
        
        db.session.commit()
        app.logger.info("Dados iniciais inseridos com sucesso!")

with app.app_context():
    populate_initial_data()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
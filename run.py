# app/main.py

import eventlet
eventlet.monkey_patch()

from app import create_app, db, socketio
from app.models import Institution, Queue, User
from app.services import QueueService
from app.ml_models import wait_time_predictor, service_recommendation_predictor  # Importar os preditores
from datetime import time, datetime
import uuid
import logging
import numpy as np

app = create_app()

def populate_initial_data():
    with app.app_context():
        db.drop_all()
        db.create_all()
        
        if Institution.query.count() > 0:
            app.logger.info("Dados iniciais de instituições já existem.")
        else:
            institutions = [
                # Instituições de Saúde
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
                    'name': 'Hospital Viana',
                    'location': 'Viana, Luanda',
                    'latitude': -8.9035,
                    'longitude': 13.3741,
                    'queues': [
                        {'service': 'Consulta Geral', 'prefix': 'A', 'sector': 'Saúde', 'department': 'Consulta Geral', 'open_time': time(7, 0), 'daily_limit': 20, 'num_counters': 3},
                        {'service': 'Exames Laboratoriais', 'prefix': 'B', 'sector': 'Saúde', 'department': 'Laboratório', 'open_time': time(8, 0), 'daily_limit': 15, 'num_counters': 2},
                    ]
                },
                # Instituições de Documentação
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
                # Instituições Bancárias
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
                # Instituições de Educação
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
                # Instituições de Transportes
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
                # Instituições de Correios
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Correios de Angola - Maianga',
                    'location': 'Maianga, Luanda',
                    'latitude': -8.8265,
                    'longitude': 13.2278,
                    'queues': [
                        {'service': 'Envio de Encomendas', 'prefix': 'A', 'sector': 'Correios', 'department': 'Encomendas', 'open_time': time(8, 0), 'daily_limit': 50, 'num_counters': 3},
                        {'service': 'Recebimento de Correspondência', 'prefix': 'B', 'sector': 'Correios', 'department': 'Correspondência', 'open_time': time(8, 0), 'daily_limit': 40, 'num_counters': 2},
                    ]
                },
                # Instituições de Energia e Águas
                {
                    'id': str(uuid.uuid4()),
                    'name': 'ENDE - Empresa Nacional de Distribuição de Eletricidade',
                    'location': 'Rangel, Luanda',
                    'latitude': -8.8290,
                    'longitude': 13.2601,
                    'queues': [
                        {'service': 'Pagamento de Faturas de Energia', 'prefix': 'A', 'sector': 'Energia e Águas', 'department': 'Faturação', 'open_time': time(8, 0), 'daily_limit': 60, 'num_counters': 4},
                        {'service': 'Reclamações de Energia', 'prefix': 'B', 'sector': 'Energia e Águas', 'department': 'Atendimento ao Cliente', 'open_time': time(8, 0), 'daily_limit': 30, 'num_counters': 2},
                    ]
                },
                {
                    'id': str(uuid.uuid4()),
                    'name': 'EPAL - Empresa Pública de Águas de Luanda',
                    'location': 'Samba, Luanda',
                    'latitude': -8.8402,
                    'longitude': 13.2156,
                    'queues': [
                        {'service': 'Pagamento de Faturas de Água', 'prefix': 'A', 'sector': 'Energia e Águas', 'department': 'Faturação', 'open_time': time(8, 0), 'daily_limit': 50, 'num_counters': 3},
                        {'service': 'Reclamações de Água', 'prefix': 'B', 'sector': 'Energia e Águas', 'department': 'Atendimento ao Cliente', 'open_time': time(8, 0), 'daily_limit': 25, 'num_counters': 2},
                    ]
                },
                # Instituições de Telecomunicações
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Unitel - Loja Cazenga',
                    'location': 'Cazenga, Luanda',
                    'latitude': -8.8201,
                    'longitude': 13.2903,
                    'queues': [
                        {'service': 'Ativação de Linha', 'prefix': 'A', 'sector': 'Telecomunicações', 'department': 'Atendimento ao Cliente', 'open_time': time(9, 0), 'daily_limit': 40, 'num_counters': 3},
                        {'service': 'Suporte Técnico', 'prefix': 'B', 'sector': 'Telecomunicações', 'department': 'Suporte', 'open_time': time(9, 0), 'daily_limit': 30, 'num_counters': 2},
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
                        institution_name=inst['name'],
                        open_time=q['open_time'],
                        daily_limit=q['daily_limit'],
                        num_counters=q['num_counters']
                    )
                    db.session.add(queue)
            
            db.session.commit()
            app.logger.info("Dados iniciais de instituições e filas inseridos com sucesso!")

        if User.query.filter_by(user_tipo='gestor').count() > 0:
            app.logger.info("Gestores iniciais já existem.")
        else:
            gestores = [
                # Gestores de Saúde
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.camama@saude.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[0]['id'],
                    'department': 'Consulta Médica'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.vacinacao@saude.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[0]['id'],
                    'department': 'Vacinação'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.hospital@viana.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[1]['id'],
                    'department': 'Consulta Geral'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.laboratorio@viana.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[1]['id'],
                    'department': 'Laboratório'
                },
                # Gestores de Documentação
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.identificacao@luanda.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[2]['id'],
                    'department': 'Identificação'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.registo@luanda.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[2]['id'],
                    'department': 'Registo Civil'
                },
                # Gestores Bancários
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.bfa@kilamba.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[3]['id'],
                    'department': 'Contas'
                },
                # Gestores de Educação
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.escola@cazenga.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[4]['id'],
                    'department': 'Matrículas'
                },
                # Gestores de Transportes
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.transito@talatona.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[5]['id'],
                    'department': 'Licenciamento'
                },
                # Gestores de Correios
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.correios@maianga.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[6]['id'],
                    'department': 'Encomendas'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.correspondencia@maianga.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[6]['id'],
                    'department': 'Correspondência'
                },
                # Gestores de Energia e Águas
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.ende@rangel.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[7]['id'],
                    'department': 'Faturação'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.atendimento@rangel.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[7]['id'],
                    'department': 'Atendimento ao Cliente'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.epal@samba.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[8]['id'],
                    'department': 'Faturação'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.atendimento@samba.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[8]['id'],
                    'department': 'Atendimento ao Cliente'
                },
                # Gestores de Telecomunicações
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.unitel@cazenga.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[9]['id'],
                    'department': 'Atendimento ao Cliente'
                },
                {
                    'id': str(uuid.uuid4()),
                    'email': 'gestor.suporte@cazenga.com',
                    'password': 'admin123',
                    'user_tipo': 'gestor',
                    'institution_id': institutions[9]['id'],
                    'department': 'Suporte'
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

def train_ml_model_periodically():
    """Tarefa periódica para treinar os modelos de machine learning."""
    while True:
        with app.app_context():
            app.logger.info("Iniciando treinamento periódico do modelo de previsão de tempo de espera.")
            wait_time_predictor.train()
            app.logger.info("Iniciando treinamento periódico do modelo de recomendação de serviços.")
            service_recommendation_predictor.train()
        eventlet.sleep(3600)  # Treinar a cada hora

def suggest_service_locations(service, user_lat=None, user_lon=None, max_results=3):
    """
    Sugere locais onde o usuário pode encontrar o serviço desejado, usando um modelo de machine learning para pontuar a qualidade de atendimento.
    
    Args:
        service (str): Nome do serviço procurado (ex.: "Consulta Médica").
        user_lat (float): Latitude do usuário (opcional).
        user_lon (float): Longitude do usuário (opcional).
        max_results (int): Número máximo de sugestões a retornar.
    
    Returns:
        list: Lista de sugestões ordenadas por pontuação.
    """
    with app.app_context():
        queues = Queue.query.all()
        suggestions = []
        now = datetime.utcnow()
        current_time = now.time()
        hour_of_day = now.hour
        day_of_week = now.weekday()

        for queue in queues:
            # Verificar se a fila está aberta e tem vagas disponíveis
            if current_time < queue.open_time:
                continue
            if queue.active_tickets >= queue.daily_limit:
                continue

            # Verificar correspondência com o serviço ou setor
            service_match = service.lower() in queue.service.lower()
            sector_match = service.lower() in (queue.sector or "").lower()
            if not (service_match or sector_match):
                continue

            # Calcular o tempo de espera estimado
            next_ticket_number = queue.active_tickets + 1
            wait_time = QueueService.calculate_wait_time(queue.id, next_ticket_number, priority=0)
            if wait_time == "N/A":
                wait_time = float('inf')

            # Calcular a distância
            distance = None
            if user_lat is not None and user_lon is not None:
                distance = QueueService.calculate_distance(user_lat, user_lon, queue.institution)
                if distance is None:
                    distance = float('inf')

            # Calcular a pontuação de qualidade de atendimento usando o modelo
            tickets = Ticket.query.filter_by(queue_id=queue.id, status='attended').all()
            service_times = [t.service_time for t in tickets if t.service_time is not None and t.service_time > 0]
            quality_score = None
            speed_label = "Desconhecida"
            if service_times:
                avg_service_time = np.mean(service_times)
                std_service_time = np.std(service_times) if len(service_times) > 1 else 0
                service_time_per_counter = avg_service_time / max(1, queue.num_counters)
                occupancy_rate = queue.active_tickets / max(1, queue.daily_limit)
                quality_score = service_recommendation_predictor.predict(
                    avg_service_time, std_service_time, service_time_per_counter, occupancy_rate, hour_of_day, day_of_week
                )
                # Classificar a velocidade de atendimento com base no tempo médio
                if avg_service_time <= 5:
                    speed_label = "Rápida"
                elif avg_service_time <= 15:
                    speed_label = "Moderada"
                else:
                    speed_label = "Lenta"
            
            if quality_score is None:
                # Fallback: usar uma pontuação baseada em heurísticas simples
                quality_score = 0.5  # Pontuação neutra
                if service_times:
                    avg_service_time = np.mean(service_times)
                    std_service_time = np.std(service_times) if len(service_times) > 1 else 0
                    quality_score = (1 / (avg_service_time + 1)) - (std_service_time / (avg_service_time + 1))
                    quality_score = max(0, min(1, quality_score))  # Normalizar entre 0 e 1

            # Calcular a pontuação final
            # Fórmula: score = (wait_time_score * 0.4) + (distance_score * 0.3) + (quality_score * 0.2) + (match_score * 0.1)
            wait_time_score = 1 / (wait_time + 1) if wait_time != float('inf') else 0
            distance_score = 1 / (distance + 1) if distance is not None and distance != float('inf') else 0
            match_score = 1 if service_match else 0.5
            score = (wait_time_score * 0.4) + (distance_score * 0.3) + (quality_score * 0.2) + (match_score * 0.1)

            suggestions.append({
                'institution': queue.institution_name,
                'location': queue.institution.location,
                'service': queue.service,
                'sector': queue.sector,
                'wait_time': wait_time if wait_time != float('inf') else "Aguardando início",
                'distance': distance if distance is not None else "Desconhecida",
                'quality_score': quality_score,
                'speed_label': speed_label,
                'score': score,
                'queue_id': queue.id,
                'open_time': queue.open_time.strftime('%H:%M'),
                'active_tickets': queue.active_tickets,
                'daily_limit': queue.daily_limit
            })

        suggestions.sort(key=lambda x: x['score'], reverse=True)
        return suggestions[:max_results]

if __name__ == '__main__':
    with app.app_context():
        populate_initial_data()
    
    eventlet.spawn(train_ml_model_periodically)
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
import eventlet
eventlet.monkey_patch()

from app import create_app, db, socketio
from app.models import Institution, Queue, User
from app.ml_models import wait_time_predictor, service_recommendation_predictor
from datetime import time
import uuid

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
                        {'service': 'Consulta Médica', 'prefix': 'A', 'sector': 'Saúde', 'department': 'Consulta Médica', 'open_time': time(7, 0), 'end_time': time(17, 0), 'daily_limit': 20, 'num_counters': 3},
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
                # Instituições de Documentação
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Posto de Identificação Luanda',
                    'location': 'Luanda Centro, Luanda',
                    'latitude': -8.8147,
                    'longitude': 13.2302,
                    'queues': [
                        {'service': 'Emissão de BI', 'prefix': 'A', 'sector': 'Documentação', 'department': 'Identificação', 'open_time': time(8, 0), 'end_time': time(16, 0), 'daily_limit': 30, 'num_counters': 4},
                        {'service': 'Registo de Nascimento', 'prefix': 'B', 'sector': 'Documentação', 'department': 'Registo Civil', 'open_time': time(8, 30), 'end_time': time(16, 30), 'daily_limit': 25, 'num_counters': 3},
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
                        {'service': 'Abertura de Conta', 'prefix': 'A', 'sector': 'Bancário', 'department': 'Contas', 'open_time': time(9, 0), 'end_time': time(15, 0), 'daily_limit': 20, 'num_counters': 3},
                        {'service': 'Manutenção de Conta', 'prefix': 'B', 'sector': 'Bancário', 'department': 'Contas', 'open_time': time(9, 0), 'end_time': time(15, 0), 'daily_limit': 15, 'num_counters': 2},
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
                        {'service': 'Matrícula Escolar', 'prefix': 'A', 'sector': 'Educação', 'department': 'Matrículas', 'open_time': time(7, 30), 'end_time': time(14, 0), 'daily_limit': 40, 'num_counters': 2},
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
                        {'service': 'Licenciamento de Veículos', 'prefix': 'A', 'sector': 'Transportes', 'department': 'Licenciamento', 'open_time': time(8, 0), 'end_time': time(16, 0), 'daily_limit': 35, 'num_counters': 4},
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
                        {'service': 'Envio de Encomendas', 'prefix': 'A', 'sector': 'Correios', 'department': 'Encomendas', 'open_time': time(8, 0), 'end_time': time(16, 0), 'daily_limit': 50, 'num_counters': 3},
                        {'service': 'Recebimento de Correspondência', 'prefix': 'B', 'sector': 'Correios', 'department': 'Correspondência', 'open_time': time(8, 0), 'end_time': time(16, 0), 'daily_limit': 40, 'num_counters': 2},
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
                        {'service': 'Pagamento de Faturas de Energia', 'prefix': 'A', 'sector': 'Energia e Águas', 'department': 'Faturação', 'open_time': time(8, 0), 'end_time': time(16, 0), 'daily_limit': 60, 'num_counters': 4},
                        {'service': 'Reclamações de Energia', 'prefix': 'B', 'sector': 'Energia e Águas', 'department': 'Atendimento ao Cliente', 'open_time': time(8, 0), 'end_time': time(16, 0), 'daily_limit': 30, 'num_counters': 2},
                    ]
                },
                {
                    'id': str(uuid.uuid4()),
                    'name': 'EPAL - Empresa Pública de Águas de Luanda',
                    'location': 'Samba, Luanda',
                    'latitude': -8.8402,
                    'longitude': 13.2156,
                    'queues': [
                        {'service': 'Pagamento de Faturas de Água', 'prefix': 'A', 'sector': 'Energia e Águas', 'department': 'Faturação', 'open_time': time(8, 0), 'end_time': time(16, 0), 'daily_limit': 50, 'num_counters': 3},
                        {'service': 'Reclamações de Água', 'prefix': 'B', 'sector': 'Energia e Águas', 'department': 'Atendimento ao Cliente', 'open_time': time(8, 0), 'end_time': time(16, 0), 'daily_limit': 25, 'num_counters': 2},
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
                        {'service': 'Ativação de Linha', 'prefix': 'A', 'sector': 'Telecomunicações', 'department': 'Atendimento ao Cliente', 'open_time': time(9, 0), 'end_time': time(17, 0), 'daily_limit': 40, 'num_counters': 3},
                        {'service': 'Suporte Técnico', 'prefix': 'B', 'sector': 'Telecomunicações', 'department': 'Suporte', 'open_time': time(9, 0), 'end_time': time(17, 0), 'daily_limit': 30, 'num_counters': 2},
                    ]
                },
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

        if User.query.filter_by(user_tipo='gestor').count() > 0:
            app.logger.info("Gestores iniciais já existem.")
        else:
            try:
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
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Erro ao inserir gestores iniciais: {str(e)}")
                raise

def train_ml_model_periodically():
    """Tarefa periódica para treinar os modelos de machine learning."""
    while True:
        with app.app_context():
            try:
                app.logger.info("Iniciando treinamento periódico do modelo de previsão de tempo de espera.")
                wait_time_predictor.train()
                app.logger.info("Iniciando treinamento periódico do modelo de recomendação de serviços.")
                service_recommendation_predictor.train()
            except Exception as e:
                app.logger.error(f"Erro ao treinar modelos de ML: {str(e)}")
        eventlet.sleep(3600)  # Treinar a cada hora

if __name__ == '__main__':
    with app.app_context():
        populate_initial_data()
    
    eventlet.spawn(train_ml_model_periodically)
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
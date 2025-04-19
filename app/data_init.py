import uuid
from datetime import time, datetime, timedelta
from .models import AuditLog, Institution, Queue, User, Ticket, Department, UserPreference, UserRole, QueueSchedule, Weekday, Branch, ServiceCategory, ServiceTag
from . import db
import os
from sqlalchemy.exc import SQLAlchemyError

def populate_initial_data(app):
    """
    Popula o banco de dados com dados iniciais para testes, incluindo apenas Bancos e Hospitais.
    Cada instituição tem 3 filiais em diferentes bairros de Luanda, com 15 senhas por fila.
    Mantém idempotência, logs em português, IDs fixos para filas principais, e compatibilidade com models.py.
    Usa bcrypt para senhas e respeita todos os relacionamentos.
    """
    with app.app_context():
        try:
            # Desativar autoflush para evitar problemas durante a inserção
            with db.session.no_autoflush:
                # Verificar idempotência
                if db.session.query(Institution).count() > 0:
                    app.logger.info("Instituições já existem, pulando inicialização de dados.")
                    return

                app.logger.info("Iniciando população de dados iniciais...")

                # --------------------------------------
                # Criar Categorias de Serviço
                # --------------------------------------
                def create_service_categories():
                    """
                    Cria categorias de serviço necessárias (Saúde, Consulta Médica, Bancário).
                    Retorna um mapa de nomes para IDs.
                    """
                    categories = [
                        {'name': 'Saúde', 'description': 'Serviços de saúde e atendimento médico', 'parent_id': None},
                        {'name': 'Consulta Médica', 'description': 'Consultas gerais e especializadas', 'parent_id': None},
                        {'name': 'Bancário', 'description': 'Serviços financeiros e bancários', 'parent_id': None},
                    ]
                    category_map = {}
                    for cat in categories:
                        existing_cat = ServiceCategory.query.filter_by(name=cat['name']).first()
                        if existing_cat:
                            category_map[cat['name']] = existing_cat.id
                            continue
                        category = ServiceCategory(
                            id=str(uuid.uuid4()),
                            name=cat['name'],
                            description=cat['description'],
                            parent_id=cat['parent_id']
                        )
                        db.session.add(category)
                        db.session.flush()
                        category_map[cat['name']] = category.id
                    # Definir parent_id para Consulta Médica
                    consulta_medica = ServiceCategory.query.filter_by(name='Consulta Médica').first()
                    if consulta_medica:
                        consulta_medica.parent_id = category_map['Saúde']
                        db.session.flush()
                    app.logger.info("Categorias de serviço criadas com sucesso.")
                    return category_map

                category_map = create_service_categories()

                # --------------------------------------
                # Bairros de Luanda
                # --------------------------------------
                neighborhoods = [
                    {'name': 'Ingombota', 'latitude': -8.8167, 'longitude': 13.2332},
                    {'name': 'Maianga', 'latitude': -8.8147, 'longitude': 13.2302},
                    {'name': 'Talatona', 'latitude': -8.9167, 'longitude': 13.1833},
                    {'name': 'Samba', 'latitude': -8.8200, 'longitude': 13.2400},
                    {'name': 'Rangel', 'latitude': -8.8300, 'longitude': 13.2500},
                    {'name': 'Kilamba', 'latitude': -8.9333, 'longitude': 13.2667},
                    {'name': 'Cazenga', 'latitude': -8.8500, 'longitude': 13.2833},
                    {'name': 'Viana', 'latitude': -8.9035, 'longitude': 13.3741},
                    {'name': 'Cacuaco', 'latitude': -8.7667, 'longitude': 13.3667},
                    {'name': 'Patriota', 'latitude': -8.9000, 'longitude': 13.2000}
                ]

                # --------------------------------------
                # Funções Auxiliares para Criação de Entidades
                # --------------------------------------
                def create_queue(department_id, queue_data):
                    """
                    Cria uma fila com agendamentos e tags, conforme models.py.
                    """
                    existing_queue = Queue.query.filter_by(department_id=department_id, service=queue_data['service']).first()
                    if existing_queue:
                        app.logger.info(f"Fila {queue_data['service']} já existe no departamento, pulando.")
                        return existing_queue

                    queue = Queue(
                        id=queue_data['id'],
                        department_id=department_id,
                        service=queue_data['service'],
                        category_id=queue_data['category_id'],
                        prefix=queue_data['prefix'],
                        open_time=queue_data['open_time'],
                        end_time=queue_data['end_time'],
                        daily_limit=queue_data['daily_limit'],
                        active_tickets=0,
                        current_ticket=0,
                        avg_wait_time=0.0,
                        last_service_time=0.0,
                        num_counters=queue_data['num_counters'],
                        last_counter=0
                    )
                    db.session.add(queue)
                    db.session.flush()

                    # Criar agendamentos
                    for schedule in queue_data['schedules']:
                        existing_schedule = QueueSchedule.query.filter_by(queue_id=queue.id, weekday=schedule['weekday']).first()
                        if existing_schedule:
                            continue
                        queue_schedule = QueueSchedule(
                            id=str(uuid.uuid4()),
                            queue_id=queue.id,
                            weekday=schedule['weekday'],
                            open_time=schedule.get('open_time'),
                            end_time=schedule.get('end_time'),
                            is_closed=schedule.get('is_closed', False)
                        )
                        db.session.add(queue_schedule)

                    # Criar tags
                    for tag_name in queue_data['tags']:
                        existing_tag = ServiceTag.query.filter_by(queue_id=queue.id, tag=tag_name).first()
                        if existing_tag:
                            continue
                        tag = ServiceTag(
                            id=str(uuid.uuid4()),
                            queue_id=queue.id,
                            tag=tag_name
                        )
                        db.session.add(tag)

                    return queue

                def create_department(branch_id, dept_data):
                    """
                    Cria um departamento com suas filas.
                    """
                    existing_dept = Department.query.filter_by(branch_id=branch_id, name=dept_data['name']).first()
                    if existing_dept:
                        app.logger.info(f"Departamento {dept_data['name']} já existe na filial, pulando.")
                        return existing_dept

                    department = Department(
                        id=str(uuid.uuid4()),
                        branch_id=branch_id,
                        name=dept_data['name'],
                        sector=dept_data['sector']
                    )
                    db.session.add(department)
                    db.session.flush()

                    for queue_data in dept_data['queues']:
                        create_queue(department.id, queue_data)

                    return department

                def create_branch(institution_id, branch_data):
                    """
                    Cria uma filial com seus departamentos.
                    """
                    existing_branch = Branch.query.filter_by(institution_id=institution_id, name=branch_data['name']).first()
                    if existing_branch:
                        app.logger.info(f"Filial {branch_data['name']} já existe na instituição, pulando.")
                        return existing_branch

                    branch = Branch(
                        id=str(uuid.uuid4()),
                        institution_id=institution_id,
                        name=branch_data['name'],
                        location=branch_data['location'],
                        neighborhood=branch_data['neighborhood'],
                        latitude=branch_data['latitude'],
                        longitude=branch_data['longitude']
                    )
                    db.session.add(branch)
                    db.session.flush()

                    for dept_data in branch_data['departments']:
                        create_department(branch.id, dept_data)

                    return branch

                def create_institution(inst_data):
                    """
                    Cria uma instituição com suas filiais.
                    """
                    existing_inst = Institution.query.filter_by(name=inst_data['name']).first()
                    if existing_inst:
                        app.logger.info(f"Instituição {inst_data['name']} já existe, pulando.")
                        return existing_inst

                    institution = Institution(
                        id=inst_data['id'],
                        name=inst_data['name'],
                        description=inst_data['description']
                    )
                    db.session.add(institution)
                    db.session.flush()

                    for branch_data in inst_data['branches']:
                        create_branch(institution.id, branch_data)

                    return institution

                # --------------------------------------
                # Dados das Instituições
                # --------------------------------------
                institutions_data = [
                    # Hospitais (2)
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Hospital Josina Machel',
                        'description': 'Hospital público de referência em Luanda',
                        'branches': [
                            {
                                'name': 'Unidade Ingombota',
                                'location': 'Ingombota, Luanda',
                                'neighborhood': 'Ingombota',
                                'latitude': -8.8167,
                                'longitude': 13.2332,
                                'departments': [
                                    {
                                        'name': 'Consulta Geral',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': '80746d76-f7f5-4c79-acd1-4173c1737a5a',
                                                'service': 'Consulta Geral',
                                                'category_id': category_map['Consulta Médica'],
                                                'prefix': 'A',
                                                'open_time': time(7, 0),
                                                'end_time': time(17, 0),
                                                'daily_limit': 50,
                                                'num_counters': 5,
                                                'tags': ['consulta', 'geral', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'open_time': time(7, 0), 'end_time': time(12, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Urgência',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': '72282889-e677-481a-9894-1c5bc68c2c44',
                                                'service': 'Urgência',
                                                'category_id': category_map['Saúde'],
                                                'prefix': 'B',
                                                'open_time': time(0, 0),
                                                'end_time': time(23, 59),
                                                'daily_limit': 100,
                                                'num_counters': 8,
                                                'tags': ['urgência', 'emergência', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.SUNDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Unidade Talatona',
                                'location': 'Talatona, Luanda',
                                'neighborhood': 'Talatona',
                                'latitude': -8.9167,
                                'longitude': 13.1833,
                                'departments': [
                                    {
                                        'name': 'Consulta Geral',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Consulta Geral',
                                                'category_id': category_map['Consulta Médica'],
                                                'prefix': 'A',
                                                'open_time': time(7, 0),
                                                'end_time': time(17, 0),
                                                'daily_limit': 50,
                                                'num_counters': 5,
                                                'tags': ['consulta', 'geral', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'open_time': time(7, 0), 'end_time': time(12, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Urgência',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Urgência',
                                                'category_id': category_map['Saúde'],
                                                'prefix': 'B',
                                                'open_time': time(0, 0),
                                                'end_time': time(23, 59),
                                                'daily_limit': 100,
                                                'num_counters': 8,
                                                'tags': ['urgência', 'emergência', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.SUNDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Unidade Kilamba',
                                'location': 'Kilamba, Luanda',
                                'neighborhood': 'Kilamba',
                                'latitude': -8.9333,
                                'longitude': 13.2667,
                                'departments': [
                                    {
                                        'name': 'Consulta Geral',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Consulta Geral',
                                                'category_id': category_map['Consulta Médica'],
                                                'prefix': 'A',
                                                'open_time': time(7, 0),
                                                'end_time': time(17, 0),
                                                'daily_limit': 50,
                                                'num_counters': 5,
                                                'tags': ['consulta', 'geral', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'open_time': time(7, 0), 'end_time': time(12, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Urgência',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Urgência',
                                                'category_id': category_map['Saúde'],
                                                'prefix': 'B',
                                                'open_time': time(0, 0),
                                                'end_time': time(23, 59),
                                                'daily_limit': 100,
                                                'num_counters': 8,
                                                'tags': ['urgência', 'emergência', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False},
                                                    {'weekday': Weekday.SUNDAY, 'open_time': time(0, 0), 'end_time': time(23, 59), 'is_closed': False}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Hospital Maria Pia',
                        'description': 'Hospital especializado em pediatria e maternidade',
                        'branches': [
                            {
                                'name': 'Unidade Samba',
                                'location': 'Samba, Luanda',
                                'neighborhood': 'Samba',
                                'latitude': -8.8200,
                                'longitude': 13.2400,
                                'departments': [
                                    {
                                        'name': 'Pediatria',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': '9c5fda76-2459-4622-b591-4180a4088d50',
                                                'service': 'Consulta Pediátrica',
                                                'category_id': category_map['Consulta Médica'],
                                                'prefix': 'P',
                                                'open_time': time(7, 30),
                                                'end_time': time(16, 30),
                                                'daily_limit': 40,
                                                'num_counters': 4,
                                                'tags': ['pediatria', 'consulta', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Maternidade',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': 'cccc41b7-60bb-47ff-955e-a5f71ae8827e',
                                                'service': 'Consulta Pré-Natal',
                                                'category_id': category_map['Consulta Médica'],
                                                'prefix': 'M',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['maternidade', 'pré-natal', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Unidade Rangel',
                                'location': 'Rangel, Luanda',
                                'neighborhood': 'Rangel',
                                'latitude': -8.8300,
                                'longitude': 13.2500,
                                'departments': [
                                    {
                                        'name': 'Pediatria',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Consulta Pediátrica',
                                                'category_id': category_map['Consulta Médica'],
                                                'prefix': 'P',
                                                'open_time': time(7, 30),
                                                'end_time': time(16, 30),
                                                'daily_limit': 40,
                                                'num_counters': 4,
                                                'tags': ['pediatria', 'consulta', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Maternidade',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Consulta Pré-Natal',
                                                'category_id': category_map['Consulta Médica'],
                                                'prefix': 'M',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['maternidade', 'pré-natal', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Unidade Cazenga',
                                'location': 'Cazenga, Luanda',
                                'neighborhood': 'Cazenga',
                                'latitude': -8.8500,
                                'longitude': 13.2833,
                                'departments': [
                                    {
                                        'name': 'Pediatria',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Consulta Pediátrica',
                                                'category_id': category_map['Consulta Médica'],
                                                'prefix': 'P',
                                                'open_time': time(7, 30),
                                                'end_time': time(16, 30),
                                                'daily_limit': 40,
                                                'num_counters': 4,
                                                'tags': ['pediatria', 'consulta', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(7, 30), 'end_time': time(16, 30), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Maternidade',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Consulta Pré-Natal',
                                                'category_id': category_map['Consulta Médica'],
                                                'prefix': 'M',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['maternidade', 'pré-natal', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # Bancos (5)
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Banco BCI',
                        'description': 'Banco comercial em Angola',
                        'branches': [
                            {
                                'name': 'Agência Ingombota',
                                'location': 'Ingombota, Luanda',
                                'neighborhood': 'Ingombota',
                                'latitude': -8.8167,
                                'longitude': 13.2332,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Agência Maianga',
                                'location': 'Maianga, Luanda',
                                'neighborhood': 'Maianga',
                                'latitude': -8.8147,
                                'longitude': 13.2302,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Agência Talatona',
                                'location': 'Talatona, Luanda',
                                'neighborhood': 'Talatona',
                                'latitude': -8.9167,
                                'longitude': 13.1833,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Banco Atlântico',
                        'description': 'Banco comercial em Angola',
                        'branches': [
                            {
                                'name': 'Agência Samba',
                                'location': 'Samba, Luanda',
                                'neighborhood': 'Samba',
                                'latitude': -8.8200,
                                'longitude': 13.2400,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Agência Rangel',
                                'location': 'Rangel, Luanda',
                                'neighborhood': 'Rangel',
                                'latitude': -8.8300,
                                'longitude': 13.2500,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Agência Kilamba',
                                'location': 'Kilamba, Luanda',
                                'neighborhood': 'Kilamba',
                                'latitude': -8.9333,
                                'longitude': 13.2667,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Banco BFA',
                        'description': 'Banco comercial em Angola',
                        'branches': [
                            {
                                'name': 'Agência Cazenga',
                                'location': 'Cazenga, Luanda',
                                'neighborhood': 'Cazenga',
                                'latitude': -8.8500,
                                'longitude': 13.2833,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Agência Viana',
                                'location': 'Viana, Luanda',
                                'neighborhood': 'Viana',
                                'latitude': -8.9035,
                                'longitude': 13.3741,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Agência Cacuaco',
                                'location': 'Cacuaco, Luanda',
                                'neighborhood': 'Cacuaco',
                                'latitude': -8.7667,
                                'longitude': 13.3667,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Banco Sol',
                        'description': 'Banco comercial em Angola',
                        'branches': [
                            {
                                'name': 'Agência Patriota',
                                'location': 'Patriota, Luanda',
                                'neighborhood': 'Patriota',
                                'latitude': -8.9000,
                                'longitude': 13.2000,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Agência Kilamba',
                                'location': 'Kilamba, Luanda',
                                'neighborhood': 'Kilamba',
                                'latitude': -8.9333,
                                'longitude': 13.2667,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Agência Ingombota',
                                'location': 'Ingombota, Luanda',
                                'neighborhood': 'Ingombota',
                                'latitude': -8.8167,
                                'longitude': 13.2332,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Banco Yetu',
                        'description': 'Banco comercial em Angola',
                        'branches': [
                            {
                                'name': 'Agência Viana',
                                'location': 'Viana, Luanda',
                                'neighborhood': 'Viana',
                                'latitude': -8.9035,
                                'longitude': 13.3741,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Agência Cacuaco',
                                'location': 'Cacuaco, Luanda',
                                'neighborhood': 'Cacuaco',
                                'latitude': -8.7667,
                                'longitude': 13.3667,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Agência Patriota',
                                'location': 'Patriota, Luanda',
                                'neighborhood': 'Patriota',
                                'latitude': -8.9000,
                                'longitude': 13.2000,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['banco', 'atendimento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Atendimento',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['banco', 'crédito'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]

                # Criar instituições
                app.logger.info("Criando instituições...")
                for inst_data in institutions_data:
                    create_institution(inst_data)
                app.logger.info("Instituições, filiais, departamentos e filas criados com sucesso.")

                # --------------------------------------
                # Criar Usuários
                # --------------------------------------
                def create_users():
                    """
                    Cria ~60 usuários: 1 SYSTEM_ADMIN, 1 INSTITUTION_ADMIN por instituição (7),
                    1 DEPARTMENT_ADMIN por departamento (42), 10 USER.
                    Usa User.set_password com bcrypt.
                    """
                    users = []
                    # SYSTEM_ADMIN
                    if not User.query.filter_by(email='sysadmin@queue.com').first():
                        super_admin = User(
                            id=str(uuid.uuid4()),
                            email='sysadmin@queue.com',
                            name='Sistema Admin',
                            user_role=UserRole.SYSTEM_ADMIN,
                            created_at=datetime.utcnow(),
                            active=True
                        )
                        super_admin.set_password('sysadmin123')
                        db.session.add(super_admin)
                        users.append(super_admin)

                    # INSTITUTION_ADMIN (7)
                    for inst in Institution.query.all():
                        email = f'admin_{inst.name.lower().replace(" ", "_")}@queue.com'
                        if not User.query.filter_by(email=email).first():
                            admin = User(
                                id=str(uuid.uuid4()),
                                email=email,
                                name=f'Admin {inst.name}',
                                user_role=UserRole.INSTITUTION_ADMIN,
                                institution_id=inst.id,
                                created_at=datetime.utcnow(),
                                active=True
                            )
                            admin.set_password('admin123')
                            db.session.add(admin)
                            users.append(admin)

                    # DEPARTMENT_ADMIN (42)
                    for dept in Department.query.all():
                        email = f'manager_{dept.name.lower().replace(" ", "_")}@queue.com'
                        if not User.query.filter_by(email=email).first():
                            manager = User(
                                id=str(uuid.uuid4()),
                                email=email,
                                name=f'Gerente {dept.name}',
                                user_role=UserRole.DEPARTMENT_ADMIN,
                                department_id=dept.id,
                                institution_id=dept.branch.institution_id,
                                created_at=datetime.utcnow(),
                                active=True
                            )
                            manager.set_password('manager123')
                            db.session.add(manager)
                            users.append(manager)

                    # USER (10)
                    for i in range(10):
                        email = f'user_{i}@queue.com'
                        if not User.query.filter_by(email=email).first():
                            user = User(
                                id=str(uuid.uuid4()),
                                email=email,
                                name=f'Usuário {i+1}',
                                user_role=UserRole.USER,
                                created_at=datetime.utcnow(),
                                active=True
                            )
                            user.set_password('user123')
                            db.session.add(user)
                            users.append(user)

                    db.session.flush()
                    app.logger.info("Usuários criados com sucesso.")
                    return users

                users = create_users()

                # --------------------------------------
                # Criar Preferências de Usuário
                # --------------------------------------
                def create_user_preferences():
                    """
                    Cria 20 preferências (2 por usuário USER).
                    """
                    user_list = User.query.filter_by(user_role=UserRole.USER).limit(10).all()
                    for user in user_list:
                        categories = ServiceCategory.query.filter(ServiceCategory.name.in_(['Saúde', 'Bancário'])).all()
                        for category in categories[:2]:
                            existing_pref = UserPreference.query.filter_by(user_id=user.id, service_category_id=category.id).first()
                            if not existing_pref:
                                preference = UserPreference(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    service_category_id=category.id,
                                    neighborhood=neighborhoods[i % len(neighborhoods)]['name']
                                )
                                db.session.add(preference)
                    db.session.flush()
                    app.logger.info("Preferências de usuário criadas com sucesso.")

                create_user_preferences()

                # --------------------------------------
                # Criar Tickets
                # --------------------------------------
                def create_tickets():
                    """
                    Cria 15 tickets por fila (total ~630), com ticket_number e qr_code.
                    """
                    now = datetime.utcnow()
                    for queue in Queue.query.all():
                        existing_tickets = Ticket.query.filter_by(queue_id=queue.id).count()
                        if existing_tickets >= 15:
                            app.logger.info(f"Fila {queue.service} já tem 15 tickets, pulando.")
                            continue
                        for i in range(15 - existing_tickets):
                            ticket_number = i + 1
                            qr_code = f"{queue.prefix}{ticket_number:03d}-{queue.id[:8]}"
                            status = 'Pendente' if i % 2 == 0 else 'Atendido'  # Alterna para simular
                            ticket = Ticket(
                                id=str(uuid.uuid4()),
                                queue_id=queue.id,
                                user_id=users[i % len(users)].id,
                                ticket_number=ticket_number,
                                qr_code=qr_code,
                                priority=0,
                                is_physical=False,
                                status=status,
                                issued_at=now - timedelta(days=i),
                                expires_at=now + timedelta(days=1),
                                counter=None,
                                service_time=0.0 if status == 'Pendente' else 300.0,  # Simula 5 minutos
                                trade_available=False
                            )
                            db.session.add(ticket)
                    db.session.flush()
                    app.logger.info("Tickets criados com sucesso.")

                create_tickets()

                # --------------------------------------
                # Criar Logs de Auditoria
                # --------------------------------------
                def create_audit_logs():
                    """
                    Cria logs de auditoria para criação de usuários.
                    """
                    now = datetime.utcnow()
                    for user in User.query.limit(10).all():
                        existing_log = AuditLog.query.filter_by(user_id=user.id, action='CREATE', resource_id=user.id).first()
                        if not existing_log:
                            audit_log = AuditLog(
                                id=str(uuid.uuid4()),
                                user_id=user.id,
                                action='CREATE',
                                resource_type='USER',
                                resource_id=user.id,
                                details=f'Usuário {user.email} criado.',
                                timestamp=now
                            )
                            db.session.add(audit_log)
                    db.session.flush()
                    app.logger.info("Logs de auditoria criados com sucesso.")

                create_audit_logs()

                # --------------------------------------
                # Commit e Finalização
                # --------------------------------------
                db.session.commit()
                app.logger.info("Dados iniciais populados com sucesso!")
                app.logger.info("FIM DA INICIALIZAÇÃO DE DADOS")

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao popular dados: {str(e)}")
            raise
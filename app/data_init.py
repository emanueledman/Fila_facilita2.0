import uuid
from datetime import time, datetime, timedelta
from .models import AuditLog, Institution, Queue, User, Ticket, Department, UserPreference, UserRole, QueueSchedule, Weekday, Branch, ServiceCategory, ServiceTag, InstitutionType
from . import db
import os
from sqlalchemy.exc import SQLAlchemyError

# Dados de teste para 3 instituições, cada uma com 3 filiais
institutions_data = [
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd099",
        "name": "SIAC",
        "description": "Serviço Integrado de Atendimento ao Cidadão em Luanda",
        "institution_type_id": None,  # Será preenchido com Administrativo
        "branches": [
            {
                "name": "Unidade Ingombota",
                "location": "Avenida 4 de Fevereiro, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Atendimento ao Cidadão",
                        "sector": "Administrativo",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd100",
                                "service": "Atendimento Geral",
                                "category_id": None,  # Será preenchido com Administrativo
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 15,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Administrativo"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Maianga",
                "location": "Rua Che Guevara, Maianga, Luanda",
                "neighborhood": "Maianga",
                "latitude": -8.8147,
                "longitude": 13.2302,
                "departments": [
                    {
                        "name": "Atendimento ao Cidadão",
                        "sector": "Administrativo",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 15,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Administrativo"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Talatona",
                "location": "Condomínio Belas Business Park, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Atendimento ao Cidadão",
                        "sector": "Administrativo",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 15,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Administrativo"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Banco BIC",
        "description": "Serviços bancários em Luanda",
        "institution_type_id": None,  # Será preenchido com Bancário
        "branches": [
            {
                "name": "Agência Ingombota",
                "location": "Avenida Lenine, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8160,
                "longitude": 13.2340,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Atendimento Bancário",
                                "category_id": None,  # Será preenchido com Bancário
                                "prefix": "AB",
                                "open_time": time(8, 30),
                                "end_time": time(15, 30),
                                "daily_limit": 20,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Bancário", "Atendimento"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Kilamba",
                "location": "Cidade do Kilamba, Luanda",
                "neighborhood": "Kilamba",
                "latitude": -8.9333,
                "longitude": 13.2667,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Atendimento Bancário",
                                "category_id": None,
                                "prefix": "AB",
                                "open_time": time(8, 30),
                                "end_time": time(15, 30),
                                "daily_limit": 20,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Bancário", "Atendimento"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Cazenga",
                "location": "Rua do Mercado, Cazenga, Luanda",
                "neighborhood": "Cazenga",
                "latitude": -8.8500,
                "longitude": 13.2833,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Atendimento Bancário",
                                "category_id": None,
                                "prefix": "AB",
                                "open_time": time(8, 30),
                                "end_time": time(15, 30),
                                "daily_limit": 20,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Bancário", "Atendimento"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Hospital Josina Machel",
        "description": "Serviços de saúde em Luanda",
        "institution_type_id": None,  # Será preenchido com Saúde
        "branches": [
            {
                "name": "Unidade Central",
                "location": "Avenida Ho Chi Minh, Luanda",
                "neighborhood": "Maianga",
                "latitude": -8.8145,
                "longitude": 13.2290,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Consulta Médica",
                                "category_id": None,  # Será preenchido com Consulta Médica
                                "prefix": "CM",
                                "open_time": time(7, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 30,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(7, 0), "end_time": time(12, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Saúde", "Consulta"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Viana",
                "location": "Estrada de Viana, Viana, Luanda",
                "neighborhood": "Viana",
                "latitude": -8.9035,
                "longitude": 13.3741,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Consulta Médica",
                                "category_id": None,
                                "prefix": "CM",
                                "open_time": time(7, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 30,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(7, 0), "end_time": time(12, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Saúde", "Consulta"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Rangel",
                "location": "Avenida Deolinda Rodrigues, Rangel, Luanda",
                "neighborhood": "Rangel",
                "latitude": -8.8300,
                "longitude": 13.2500,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Consulta Médica",
                                "category_id": None,
                                "prefix": "CM",
                                "open_time": time(7, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 30,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(7, 0), "end_time": time(12, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Saúde", "Consulta"]
                            }
                        ]
                    }
                ]
            }
        ]
    }
]

def populate_initial_data(app):
    """
    Popula o banco de dados com dados iniciais para testes, incluindo 3 instituições (SIAC, Banco BIC, Hospital Josina Machel),
    cada uma com 3 filiais em Luanda. Mantém idempotência, logs em português, e compatibilidade com models.py.
    Usa bcrypt para senhas e respeita todos os relacionamentos, incluindo InstitutionType.
    Suporta modelos de ML com dados suficientes para treinamento inicial.
    """
    with app.app_context():
        try:
            # Desativar autoflush para evitar problemas durante a inserção
            with db.session.no_autoflush:
                app.logger.info("Iniciando população de dados iniciais...")

                # --------------------------------------
                # Criar Tipos de Instituição
                # --------------------------------------
                def create_institution_types():
                    """
                    Cria tipos de instituição necessários (Administrativo, Bancário, Saúde).
                    Retorna um mapa de nomes para IDs.
                    """
                    types = [
                        {'name': 'Administrativo', 'description': 'Serviços administrativos e atendimento ao cidadão'},
                        {'name': 'Bancário', 'description': 'Serviços financeiros e bancários'},
                        {'name': 'Saúde', 'description': 'Serviços de saúde e atendimento médico'}
                    ]
                    type_map = {}
                    for inst_type in types:
                        existing_type = InstitutionType.query.filter_by(name=inst_type['name']).first()
                        if existing_type:
                            type_map[inst_type['name']] = existing_type.id
                            continue
                        institution_type = InstitutionType(
                            id=str(uuid.uuid4()),
                            name=inst_type['name'],
                            description=inst_type['description']
                        )
                        db.session.add(institution_type)
                        db.session.flush()
                        type_map[inst_type['name']] = institution_type.id
                    app.logger.info("Tipos de instituição criados com sucesso.")
                    return type_map

                institution_type_map = create_institution_types()

                # Atualizar institution_type_id nos dados de teste
                for inst in institutions_data:
                    if inst['name'] == 'SIAC':
                        inst['institution_type_id'] = institution_type_map['Administrativo']
                    elif inst['name'] == 'Banco BIC':
                        inst['institution_type_id'] = institution_type_map['Bancário']
                    elif inst['name'] == 'Hospital Josina Machel':
                        inst['institution_type_id'] = institution_type_map['Saúde']

                # --------------------------------------
                # Criar Categorias de Serviço
                # --------------------------------------
                def create_service_categories():
                    """
                    Cria categorias de serviço necessárias (Saúde, Consulta Médica, Administrativo, Bancário).
                    Retorna um mapa de nomes para IDs.
                    """
                    categories = [
                        {'name': 'Saúde', 'description': 'Serviços de saúde e atendimento médico', 'parent_id': None},
                        {'name': 'Consulta Médica', 'description': 'Consultas gerais e especializadas', 'parent_id': None},
                        {'name': 'Administrativo', 'description': 'Serviços administrativos municipais e atendimento ao cidadão', 'parent_id': None},
                        {'name': 'Bancário', 'description': 'Serviços financeiros e bancários', 'parent_id': None}
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
                    if consulta_medica and not consulta_medica.parent_id:
                        consulta_medica.parent_id = category_map['Saúde']
                        db.session.flush()
                    app.logger.info("Categorias de serviço criadas com sucesso.")
                    return category_map

                category_map = create_service_categories()

                # Atualizar category_id nas filas dos dados de teste
                for inst in institutions_data:
                    for branch in inst['branches']:
                        for dept in branch['departments']:
                            for queue in dept['queues']:
                                if 'Saúde' in queue['tags']:
                                    queue['category_id'] = category_map['Consulta Médica']
                                elif 'Administrativo' in queue['tags']:
                                    queue['category_id'] = category_map['Administrativo']
                                elif 'Bancário' in queue['tags']:
                                    queue['category_id'] = category_map['Bancário']

                # --------------------------------------
                # Bairros de Luanda
                # --------------------------------------
                neighborhoods = [
                    {'name': 'Ingombota', 'latitude': -8.8167, 'longitude': 13.2332},
                    {'name': 'Maianga', 'latitude': -8.8147, 'longitude': 13.2302},
                    {'name': 'Talatona', 'latitude': -8.9167, 'longitude': 13.1833},
                    {'name': 'Kilamba', 'latitude': -8.9333, 'longitude': 13.2667},
                    {'name': 'Cazenga', 'latitude': -8.8500, 'longitude': 13.2833},
                    {'name': 'Viana', 'latitude': -8.9035, 'longitude': 13.3741},
                    {'name': 'Rangel', 'latitude': -8.8300, 'longitude': 13.2500}
                ]

                # --------------------------------------
                # Funções Auxiliares para Criação de Entidades
                # --------------------------------------
                def create_queue(department_id, queue_data):
                    """
                    Cria uma fila com agendamentos e tags, conforme models.py.
                    """
                    existing_queue = Queue.query.filter_by(id=queue_data['id']).first()
                    if not existing_queue:
                        existing_queue = Queue.query.filter_by(
                            department_id=department_id, 
                            service=queue_data['service'],
                            prefix=queue_data['prefix']
                        ).first()
                    
                    if existing_queue:
                        app.logger.info(f"Fila {queue_data['service']} já existe com ID {existing_queue.id}, pulando.")
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
                        for dept_data in branch_data['departments']:
                            existing_dept = Department.query.filter_by(branch_id=existing_branch.id, name=dept_data['name']).first()
                            if not existing_dept:
                                create_department(existing_branch.id, dept_data)
                            else:
                                for queue_data in dept_data['queues']:
                                    create_queue(existing_dept.id, queue_data)
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
                        app.logger.info(f"Instituição {inst_data['name']} já existe, atualizando filiais se necessário.")
                        for branch_data in inst_data['branches']:
                            existing_branch = Branch.query.filter_by(institution_id=existing_inst.id, name=branch_data['name']).first()
                            if not existing_branch:
                                create_branch(existing_inst.id, branch_data)
                            else:
                                for dept_data in branch_data['departments']:
                                    existing_dept = Department.query.filter_by(branch_id=existing_branch.id, name=dept_data['name']).first()
                                    if not existing_dept:
                                        create_department(existing_branch.id, dept_data)
                                    else:
                                        for queue_data in dept_data['queues']:
                                            create_queue(existing_dept.id, queue_data)
                        return existing_inst

                    institution = Institution(
                        id=inst_data['id'],
                        name=inst_data['name'],
                        description=inst_data['description'],
                        institution_type_id=inst_data['institution_type_id']
                    )
                    db.session.add(institution)
                    db.session.flush()

                    for branch_data in inst_data['branches']:
                        create_branch(institution.id, branch_data)

                    return institution

                app.logger.info("Criando ou atualizando instituições...")
                for inst_data in institutions_data:
                    create_institution(inst_data)
                app.logger.info("Instituições, filiais, departamentos e filas criados ou atualizados com sucesso.")

                # --------------------------------------
                # Criar Usuários
                # --------------------------------------
                def create_users():
                    """
                    Cria ~16 usuários: 1 SYSTEM_ADMIN, 3 INSTITUTION_ADMIN, ~9 DEPARTMENT_ADMIN, 10 USER.
                    Usa User.set_password com bcrypt.
                    Garante emails únicos para DEPARTMENT_ADMIN.
                    """
                    users = []
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

                    for dept in Department.query.all():
                        inst_name = dept.branch.institution.name.lower().replace(" ", "_")
                        branch_name = dept.branch.name.lower().replace(" ", "_")
                        email = f'manager_{dept.name.lower().replace(" ", "_")}_{inst_name}_{branch_name}@queue.com'
                        if not User.query.filter_by(email=email).first():
                            manager = User(
                                id=str(uuid.uuid4()),
                                email=email,
                                name=f'Gerente {dept.name} {dept.branch.name}',
                                user_role=UserRole.DEPARTMENT_ADMIN,
                                department_id=dept.id,
                                institution_id=dept.branch.institution_id,
                                created_at=datetime.utcnow(),
                                active=True
                            )
                            manager.set_password('manager123')
                            db.session.add(manager)
                            users.append(manager)

                    user_count = User.query.filter_by(user_role=UserRole.USER).count()
                    if user_count < 10:
                        for i in range(10 - user_count):
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
                    for i, user in enumerate(user_list):
                        categories = ServiceCategory.query.filter(ServiceCategory.name.in_(['Saúde', 'Administrativo', 'Bancário'])).all()
                        for category in categories[:2]:
                            existing_pref = UserPreference.query.filter_by(user_id=user.id, service_category_id=category.id).first()
                            if not existing_pref:
                                preference = UserPreference(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    service_category_id=category.id,
                                    institution_type_id=InstitutionType.query.filter_by(name=category.name).first().id if category.name in ['Saúde', 'Administrativo', 'Bancário'] else None,
                                    institution_id=Institution.query.offset(i % 3).first().id,
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
                    Cria 25 tickets por fila, com ticket_number e qr_code únicos.
                    """
                    now = datetime.utcnow()
                    for queue in Queue.query.all():
                        existing_tickets = Ticket.query.filter_by(queue_id=queue.id).count()
                        if existing_tickets >= 25:
                            app.logger.info(f"Fila {queue.service} já tem {existing_tickets} tickets, pulando.")
                            continue

                        department = Department.query.filter_by(id=queue.department_id).first()
                        branch_id = department.branch_id
                        branch_code = branch_id[-4:]

                        for i in range(25 - existing_tickets):
                            max_ticket_number = db.session.query(db.func.max(Ticket.ticket_number)).filter_by(queue_id=queue.id).scalar() or 0
                            ticket_number = max_ticket_number + i + 1
                            qr_code = f"{queue.prefix}{ticket_number:03d}-{queue.id[:8]}-{branch_code}"
                            if Ticket.query.filter_by(qr_code=qr_code).first():
                                qr_code = f"{queue.prefix}{ticket_number:03d}-{queue.id[:8]}-{branch_code}-{int(now.timestamp())}"

                            status = 'Atendido' if i % 2 == 0 else 'Pendente'
                            ticket = Ticket(
                                id=str(uuid.uuid4()),
                                queue_id=queue.id,
                                user_id=User.query.filter_by(user_role=UserRole.USER).offset(i % 10).first().id,
                                ticket_number=ticket_number,
                                qr_code=qr_code,
                                priority=1 if i % 3 == 0 else 0,
                                is_physical=False,
                                status=status,
                                issued_at=now - timedelta(days=i % 7),
                                expires_at=now + timedelta(days=1),
                                counter=1 if status == 'Atendido' else None,
                                service_time=300.0 if status == 'Atendido' else 0.0,
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

        except SQLAlchemyError as e:
            db.session.rollback()
            app.logger.error(f"Erro SQL ao popular dados: {str(e)}")
            raise
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao popular dados: {str(e)}")
            raise

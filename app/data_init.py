import uuid
from datetime import time, datetime, timedelta
from .models import AuditLog, Institution, Queue, User, Ticket, Department, UserPreference, UserRole, QueueSchedule, Weekday, Branch, ServiceCategory, ServiceTag
from . import db
import os
from sqlalchemy.exc import SQLAlchemyError

# Dados de teste fornecidos
institutions_data = [
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd094",
        "name": "Hospital Josina Machel",
        "description": "Hospital público em Luanda",
        "branches": [
            {
                "name": "Unidade Ingombota",
                "location": "Rua dos Hospitais, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd095",
                                "service": "Consulta Geral",
                                "category_id": None,  # Será preenchido após criar categorias
                                "prefix": "CG",
                                "open_time": time(8, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 15,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Consulta", "Geral", "Saúde"]
                            }
                        ]
                    },
                    {
                        "name": "Emergência",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd096",
                                "service": "Emergência",
                                "category_id": None,
                                "prefix": "EM",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
                                "daily_limit": 15,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(0, 0), "end_time": time(23, 59)}
                                ],
                                "tags": ["Emergência", "Saúde"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Maianga",
                "location": "Avenida dos Combatentes, Maianga, Luanda",
                "neighborhood": "Maianga",
                "latitude": -8.8147,
                "longitude": 13.2302,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd097",
                                "service": "Consulta Geral",
                                "category_id": None,
                                "prefix": "CG",
                                "open_time": time(8, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 15,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Consulta", "Geral", "Saúde"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Talatona",
                "location": "Via Expressa, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd098",
                                "service": "Consulta Geral",
                                "category_id": None,
                                "prefix": "CG",
                                "open_time": time(8, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 15,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Consulta", "Geral", "Saúde"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd099",
        "name": "Banco de Fomento Angola",
        "description": "Banco comercial em Luanda",
        "branches": [
            {
                "name": "Agência Ingombota",
                "location": "Avenida 4 de Fevereiro, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd100",
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
                                "tags": ["Atendimento", "Bancário"]
                            }
                        ]
                    },
                    {
                        "name": "Caixa",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd101",
                                "service": "Caixa",
                                "category_id": None,
                                "prefix": "CX",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 15,
                                "num_counters": 6,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Caixa", "Bancário"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Maianga",
                "location": "Rua Che Guevara, Maianga, Luanda",
                "neighborhood": "Maianga",
                "latitude": -8.8147,
                "longitude": 13.2302,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd102",
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
                                "tags": ["Atendimento", "Bancário"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Talatona",
                "location": "Condomínio Belas Business Park, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd103",
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
                                "tags": ["Atendimento", "Bancário"]
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
    Popula o banco de dados com dados iniciais para testes, incluindo apenas Bancos e Hospitais.
    Cada instituição tem 3 filiais em diferentes bairros de Luanda, com 15 senhas por fila.
    Mantém idempotência, logs em português, IDs fixos para filas principais, e compatibilidade com models.py.
    Usa bcrypt para senhas e respeita todos os relacionamentos.
    Suporta modelos de ML com dados suficientes para treinamento inicial.
    """
    with app.app_context():
        try:
            # Desativar autoflush para evitar problemas durante a inserção
            with db.session.no_autoflush:
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
                                elif 'Bancário' in queue['tags']:
                                    queue['category_id'] = category_map['Bancário']

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
                    existing_queue = Queue.query.filter_by(id=queue_data['id']).first()
                    if existing_queue:
                        app.logger.info(f"Fila {queue_data['service']} já existe com ID {queue_data['id']}, pulando.")
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
                    existing_inst = Institution.query.filter_by(id=inst_data['id']).first()
                    if existing_inst:
                        app.logger.info(f"Instituição {inst_data['name']} já existe com ID {inst_data['id']}, pulando.")
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
                    Cria ~26 usuários: 1 SYSTEM_ADMIN, 2 INSTITUTION_ADMIN, ~13 DEPARTMENT_ADMIN, 10 USER.
                    Usa User.set_password com bcrypt.
                    Garante emails únicos para DEPARTMENT_ADMIN.
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

                    # INSTITUTION_ADMIN (2)
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

                    # DEPARTMENT_ADMIN (~13)
                    for dept in Department.query.all():
                        # Gerar email único incluindo o nome da instituição e filial
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
                    for i, user in enumerate(user_list):
                        categories = ServiceCategory.query.filter(ServiceCategory.name.in_(['Saúde', 'Bancário'])).all()
                        for category in categories[:2]:
                            existing_pref = UserPreference.query.filter_by(user_id=user.id, service_category_id=category.id).first()
                            if not existing_pref:
                                preference = UserPreference(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    service_category_id=category.id,
                                    institution_id=Institution.query.first().id if i % 2 == 0 else Institution.query.offset(1).first().id,
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
                    Cria 15 tickets por fila (total ~195), com ticket_number e qr_code únicos.
                    """
                    now = datetime.utcnow()
                    for queue in Queue.query.all():
                        existing_tickets = Ticket.query.filter_by(queue_id=queue.id).count()
                        if existing_tickets >= 15:
                            app.logger.info(f"Fila {queue.service} já tem 15 tickets, pulando.")
                            continue
                        
                        # Obter informações do departamento e filial para criar um código QR único
                        department = Department.query.filter_by(id=queue.department_id).first()
                        branch_id = department.branch_id
                        branch_code = branch_id[-4:] # Usar últimos 4 caracteres do ID da filial
                        
                        for i in range(15 - existing_tickets):
                            ticket_number = i + 1
                            # Criar um código QR único incluindo o ID da filial
                            qr_code = f"{queue.prefix}{ticket_number:03d}-{queue.id[:8]}-{branch_code}"
                            
                            status = 'Atendido' if i % 2 == 0 else 'Pendente'  # Alterna para suportar ML
                            ticket = Ticket(
                                id=str(uuid.uuid4()),
                                queue_id=queue.id,
                                user_id=users[i % len(users)].id,
                                ticket_number=ticket_number,
                                qr_code=qr_code,
                                priority=1 if i % 3 == 0 else 0,  # Adiciona prioridades para ML
                                is_physical=False,
                                status=status,
                                issued_at=now - timedelta(days=i % 7),  # Distribui tickets em 7 dias
                                expires_at=now + timedelta(days=1),
                                counter=1 if status == 'Atendido' else None,
                                service_time=300.0 if status == 'Atendido' else 0.0,  # 5 minutos para atendidos
                                trade_available=False
                            )
                            db.session.add(ticket)
                    db.session.flush()
                    app.logger.info("Tickets criados com sucesso.")
                
                create_tickets()

                # --------------------------------------
                # Criar Feedbacks de Usuário
                # --------------------------------------
                def create_user_feedbacks():
                    """
                    Cria feedbacks para tickets atendidos, para suportar ServiceRecommendationPredictor.
                    """
                    tickets = Ticket.query.filter_by(status='Atendido').all()
                    for i, ticket in enumerate(tickets):
                        existing_feedback = UserFeedback.query.filter_by(ticket_id=ticket.id).first()
                        if not existing_feedback:
                            feedback = UserFeedback(
                                id=str(uuid.uuid4()),
                                ticket_id=ticket.id,
                                user_id=ticket.user_id,
                                rating=3.0 + (i % 3),  # Ratings variam entre 3 e 5
                                comment=f"Feedback teste {i+1}",
                                created_at=datetime.utcnow()
                            )
                            db.session.add(feedback)
                    db.session.flush()
                    app.logger.info("Feedbacks de usuário criados com sucesso.")

                create_user_feedbacks()

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
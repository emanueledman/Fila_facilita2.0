import uuid
from datetime import time, datetime, timedelta
from .models import Institution, Queue, User, Ticket, Department, UserRole, QueueSchedule, Weekday, Branch, ServiceCategory, ServiceTag
from . import db
import os
from sqlalchemy.exc import SQLAlchemyError

def populate_initial_data(app):
    with app.app_context():
        try:
            # Desativar autoflush para evitar problemas durante a inserção
            with db.session.no_autoflush:
                # Mapear categorias de serviço existentes
                category_map = {}
                for cat in ServiceCategory.query.all():
                    category_map[cat.name] = cat.id

                # Verificar se as categorias necessárias existem
                required_categories = ['Bancário', 'Atendimento ao Cliente']
                for cat_name in required_categories:
                    if cat_name not in category_map:
                        app.logger.error(f"Categoria {cat_name} não encontrada no banco de dados!")
                        return

                # Lista de bancos
                institutions = [
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Banco BCI',
                        'description': 'Agência bancária do Banco BCI',
                        'branches': []
                    },
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Banco Atlântico',
                        'description': 'Agência bancária do Banco Atlântico',
                        'branches': []
                    },
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Banco BFA',
                        'description': 'Agência bancária do Banco BFA',
                        'branches': []
                    },
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Banco Sol',
                        'description': 'Agência bancária do Banco Sol',
                        'branches': []
                    },
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Banco Yetu',
                        'description': 'Agência bancária do Banco Yetu',
                        'branches': []
                    },
                ]

                # Adicionar filiais (2 por banco)
                neighborhoods = [
                    {'name': 'Ingombota', 'latitude': -8.8167, 'longitude': 13.2332},
                    {'name': 'Maianga', 'latitude': -8.8147, 'longitude': 13.2302},
                    {'name': 'Talatona', 'latitude': -8.9167, 'longitude': 13.1833},
                ]
                queue_ids = {}
                for inst in institutions:
                    # Verificar se a instituição já existe
                    existing_institution = Institution.query.filter_by(name=inst['name']).first()
                    if existing_institution:
                        app.logger.info(f"Instituição {inst['name']} já existe, pulando.")
                        inst['id'] = existing_institution.id
                        continue

                    for i in range(2):
                        neighborhood = neighborhoods[i % len(neighborhoods)]
                        branch = {
                            'name': f'Unidade {neighborhood["name"]}',
                            'location': f'{neighborhood["name"]}, Luanda',
                            'neighborhood': neighborhood['name'],
                            'latitude': neighborhood['latitude'],
                            'longitude': neighborhood['longitude'],
                            'departments': [
                                {
                                    'name': 'Atendimento ao Cliente',
                                    'sector': 'Bancário',
                                    'queues': [
                                        {
                                            'id': str(uuid.uuid4()),
                                            'service': 'Atendimento',
                                            'category_id': category_map['Atendimento ao Cliente'],
                                            'prefix': 'A',
                                            'open_time': time(8, 0),
                                            'end_time': time(16, 0),
                                            'daily_limit': 20,
                                            'num_counters': 1,
                                            'tags': ['banco', 'atendimento'],
                                            'schedules': [
                                                {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                {'weekday': Weekday.SATURDAY, 'open_time': time(8, 0), 'end_time': time(12, 0), 'is_closed': False},
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
                                            'category_id': category_map['Atendimento ao Cliente'],
                                            'prefix': 'A',
                                            'open_time': time(8, 0),
                                            'end_time': time(16, 0),
                                            'daily_limit': 20,
                                            'num_counters': 1,
                                            'tags': ['banco', 'atendimento'],
                                            'schedules': [
                                                {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                {'weekday': Weekday.SATURDAY, 'open_time': time(8, 0), 'end_time': time(12, 0), 'is_closed': False},
                                                {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                        inst['branches'].append(branch)

                    # Inserir instituição
                    institution = Institution(
                        id=inst['id'],
                        name=inst['name'],
                        description=inst['description']
                    )
                    db.session.add(institution)
                    db.session.flush()

                    for branch in inst['branches']:
                        # Verificar se a filial já existe
                        existing_branch = Branch.query.filter_by(
                            institution_id=inst['id'], name=branch['name']
                        ).first()
                        if existing_branch:
                            app.logger.info(f"Filial {branch['name']} já existe em {inst['name']}, pulando.")
                            continue

                        branch_obj = Branch(
                            id=str(uuid.uuid4()),
                            institution_id=inst['id'],
                            name=branch['name'],
                            location=branch['location'],
                            neighborhood=branch['neighborhood'],
                            latitude=branch['latitude'],
                            longitude=branch['longitude']
                        )
                        db.session.add(branch_obj)
                        db.session.flush()

                        for dept in branch['departments']:
                            # Verificar se o departamento já existe
                            existing_department = Department.query.filter_by(
                                branch_id=branch_obj.id, name=dept['name']
                            ).first()
                            if existing_department:
                                app.logger.info(f"Departamento {dept['name']} já existe em {branch['name']}, pulando.")
                                continue

                            department = Department(
                                id=str(uuid.uuid4()),
                                branch_id=branch_obj.id,
                                name=dept['name'],
                                sector=dept['sector']
                            )
                            db.session.add(department)
                            db.session.flush()

                            for q in dept['queues']:
                                # Verificar se a fila já existe
                                existing_queue = Queue.query.filter_by(
                                    department_id=department.id, service=q['service']
                                ).first()
                                if existing_queue:
                                    app.logger.info(f"Fila {q['service']} já existe em {dept['name']}, pulando.")
                                    queue_ids[f"{dept['name']}_{q['service']}"] = existing_queue.id
                                    continue

                                queue = Queue(
                                    id=q['id'],
                                    department_id=department.id,
                                    service=q['service'],
                                    category_id=q['category_id'],
                                    prefix=q['prefix'],
                                    open_time=q['open_time'],
                                    end_time=q['end_time'],
                                    daily_limit=q['daily_limit'],
                                    num_counters=q['num_counters'],
                                    active_tickets=0,
                                    current_ticket=0
                                )
                                db.session.add(queue)
                                db.session.flush()
                                queue_ids[f"{dept['name']}_{q['service']}"] = queue.id

                                # Criar agendamentos para a fila
                                for schedule in q['schedules']:
                                    # Verificar se o agendamento já existe
                                    existing_schedule = QueueSchedule.query.filter_by(
                                        queue_id=queue.id, weekday=schedule['weekday']
                                    ).first()
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

                                # Criar tags para a fila
                                for tag in q['tags']:
                                    # Verificar se a tag já existe
                                    existing_tag = ServiceTag.query.filter_by(queue_id=queue.id, tag=tag).first()
                                    if not existing_tag:
                                        service_tag = ServiceTag(
                                            id=str(uuid.uuid4()),
                                            queue_id=queue.id,
                                            tag=tag
                                        )
                                        db.session.add(service_tag)

                db.session.commit()
                app.logger.info("Dados iniciais de bancos, filiais, departamentos, filas, agendamentos e tags inseridos com sucesso!")

                # Inserir administradores dos bancos
                users = []
                for inst in institutions:
                    email = f'admin.{inst["name"].replace(" ", "").lower()}@facilita.com'
                    existing_user = User.query.filter_by(email=email).first()
                    if existing_user:
                        app.logger.info(f"Usuário {email} já existe, pulando.")
                        continue

                    users.append({
                        'id': str(uuid.uuid4()),
                        'email': email,
                        'name': f'Admin {inst["name"]}',
                        'password': os.getenv('ADMIN_PASSWORD', 'admin123'),
                        'user_role': UserRole.INSTITUTION_ADMIN,
                        'institution_id': inst['id'],
                        'department_id': None,
                        'department_name': None
                    })

                for user_data in users:
                    user = User(
                        id=user_data['id'],
                        email=user_data['email'],
                        name=user_data['name'],
                        user_role=user_data['user_role'],
                        institution_id=user_data['institution_id'],
                        department_id=user_data['department_id'],
                        active=True
                    )
                    user.set_password(user_data['password'])
                    db.session.add(user)

                db.session.commit()
                app.logger.info("Administradores de bancos inseridos com sucesso!")

        except SQLAlchemyError as e:
            db.session.rollback()
            app.logger.error(f"Erro ao inserir dados iniciais de bancos: {str(e)}")
            raise
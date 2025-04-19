from datetime import time, datetime, timedelta
import uuid
from .models import Institution, Queue, User, Ticket, Department, UserRole, QueueSchedule, Weekday, Branch, ServiceCategory, ServiceTag, UserPreference
from . import db
import os
from sqlalchemy.exc import SQLAlchemyError

def populate_initial_data(app):
    with app.app_context():
        try:
            with db.session.no_autoflush:
                # 1. Categorias de Serviço
                service_categories = [
                    {'name': 'Saúde', 'description': 'Serviços médicos'},
                    {'name': 'Bancário', 'description': 'Serviços financeiros'},
                    {'name': 'Notarial', 'description': 'Serviços cartorários'},
                    {'name': 'Consulta Médica', 'description': 'Consultas gerais', 'parent_name': 'Saúde'},
                    {'name': 'Atendimento ao Cliente', 'description': 'Atendimento bancário', 'parent_name': 'Bancário'},
                    {'name': 'Registro Civil', 'description': 'Registros', 'parent_name': 'Notarial'},
                ]
                
                category_map = {}
                for cat in service_categories:
                    # Verificar se a categoria já existe
                    existing_category = ServiceCategory.query.filter_by(name=cat['name']).first()
                    if existing_category:
                        category_map[cat['name']] = existing_category.id
                        continue
                    
                    parent_id = None
                    if 'parent_name' in cat:
                        parent_id = category_map[cat['parent_name']]
                    
                    category = ServiceCategory(
                        id=str(uuid.uuid4()),
                        name=cat['name'],
                        description=cat['description'],
                        parent_id=parent_id
                    )
                    db.session.add(category)
                    category_map[cat['name']] = category.id

                # 2. Bairros
                neighborhoods = [
                    {'name': 'Ingombota', 'lat': -8.8167, 'long': 13.2332},
                    {'name': 'Maianga', 'lat': -8.8147, 'long': 13.2302},
                    {'name': 'Talatona', 'lat': -8.9167, 'long': 13.1833},
                ]

                # 3. Instituições
                institutions = [
                    {
                        'name': 'Hospital Josina Machel',
                        'description': 'Hospital público em Ingombota',
                        'type': 'Saúde',
                        'branches': []
                    },
                    {
                        'name': 'Banco BIC Maianga',
                        'description': 'Agência bancária do Banco BIC',
                        'type': 'Bancário',
                        'branches': []
                    },
                    {
                        'name': 'Cartório Notarial Talatona',
                        'description': 'Serviços notariais',
                        'type': 'Notarial',
                        'branches': []
                    },
                    {
                        'name': 'Clínica Girassol',
                        'description': 'Clínica privada em Talatona',
                        'type': 'Saúde',
                        'branches': []
                    },
                    {
                        'name': 'Banco BAI Ingombota',
                        'description': 'Agência bancária do Banco BAI',
                        'type': 'Bancário',
                        'branches': []
                    },
                    {
                        'name': 'Centro de Atendimento Fiscal',
                        'description': 'Serviço público em Maianga',
                        'type': 'Utilidades',
                        'branches': []
                    },
                ]

                # Adicionar filiais (2 por instituição)
                for inst in institutions:
                    # Verificar se a instituição já existe
                    existing_inst = Institution.query.filter_by(name=inst['name']).first()
                    if existing_inst:
                        inst['id'] = existing_inst.id
                    else:
                        inst['id'] = str(uuid.uuid4())

                    # Adicionar 2 filiais, se não existirem
                    for i in range(2):
                        neighborhood = neighborhoods[i % len(neighborhoods)]
                        branch_name = f'Unidade {neighborhood["name"]}'
                        # Verificar se a filial já existe para essa instituição
                        existing_branch = Branch.query.filter_by(institution_id=inst['id'], name=branch_name).first()
                        if existing_branch:
                            continue

                        branch = {
                            'id': str(uuid.uuid4()),
                            'name': branch_name,
                            'location': f'{neighborhood["name"]}, Luanda',
                            'neighborhood': neighborhood['name'],
                            'latitude': neighborhood['lat'],
                            'longitude': neighborhood['long'],
                            'departments': []
                        }

                        # Adicionar departamentos (2 por filial)
                        for j in range(2):
                            if inst['type'] == 'Saúde':
                                dept_options = [
                                    ('Consulta Geral', 'Saúde', 'Consulta Médica'),
                                    ('Emergência', 'Saúde', 'Consulta Médica'),
                                ]
                            elif inst['type'] == 'Bancário':
                                dept_options = [
                                    ('Atendimento ao Cliente', 'Bancário', 'Atendimento ao Cliente'),
                                    ('Crédito', 'Bancário', 'Atendimento ao Cliente'),
                                ]
                            elif inst['type'] == 'Notarial':
                                dept_options = [
                                    ('Registro Civil', 'Notarial', 'Registro Civil'),
                                    ('Autenticações', 'Notarial', 'Registro Civil'),
                                ]
                            else:  # Utilidades
                                dept_options = [
                                    ('Atendimento Geral', 'Utilidades', None),
                                    ('Documentação', 'Utilidades', None),
                                ]

                            dept_name, sector, category = dept_options[j % len(dept_options)]
                            # Verificar se o departamento já existe
                            existing_dept = Department.query.filter_by(branch_id=branch['id'], name=dept_name).first()
                            if existing_dept:
                                continue

                            department = {
                                'id': str(uuid.uuid4()),
                                'name': dept_name,
                                'sector': sector,
                                'queues': []
                            }

                            # Adicionar filas (1 por departamento)
                            if sector == 'Saúde':
                                queue_options = [('Consulta', 'A', ['consulta', 'médico'])]
                            elif sector == 'Bancário':
                                queue_options = [('Atendimento', 'A', ['banco', 'atendimento'])]
                            elif sector == 'Notarial':
                                queue_options = [('Registro', 'R', ['registro', 'civil'])]
                            else:
                                queue_options = [('Atendimento', 'A', ['atendimento', 'serviço'])]

                            service, prefix, tags = queue_options[0]
                            open_time = time(8, 0)
                            end_time = time(16, 0) if sector != 'Saúde' else time(17, 0)

                            # Verificar se a fila já existe
                            existing_queue = Queue.query.filter_by(department_id=department['id'], service=service).first()
                            if existing_queue:
                                continue

                            queue = {
                                'id': str(uuid.uuid4()),
                                'service': service,
                                'category_id': category_map[category] if category else None,
                                'prefix': prefix,
                                'open_time': open_time,
                                'end_time': end_time,
                                'daily_limit': 20,
                                'num_counters': 1,
                                'tags': tags,
                                'schedules': []
                            }

                            # Agendamentos para dias da semana
                            for day in Weekday:
                                is_closed = (day == Weekday.SUNDAY)
                                if is_closed:
                                    schedule = {'weekday': day, 'is_closed': True}
                                else:
                                    q_open = time(8, 0) if day != Weekday.SATURDAY else time(8, 0)
                                    q_end = time(16, 0) if day != Weekday.SATURDAY else time(12, 0)
                                    schedule = {
                                        'weekday': day,
                                        'open_time': q_open,
                                        'end_time': q_end,
                                        'is_closed': False
                                    }
                                queue['schedules'].append(schedule)

                            department['queues'].append(queue)
                            branch['departments'].append(department)

                        inst['branches'].append(branch)

                # Inserir instituições, filiais, departamentos e filas
                for inst in institutions:
                    # Inserir instituição se não existir
                    existing_inst = Institution.query.filter_by(id=inst['id']).first()
                    if not existing_inst:
                        institution = Institution(id=inst['id'], name=inst['name'], description=inst['description'])
                        db.session.add(institution)

                    for branch in inst['branches']:
                        # Inserir filial se não existir
                        existing_branch = Branch.query.filter_by(id=branch['id']).first()
                        if not existing_branch:
                            branch_obj = Branch(
                                id=branch['id'], institution_id=inst['id'], name=branch['name'],
                                location=branch['location'], neighborhood=branch['neighborhood'],
                                latitude=branch['latitude'], longitude=branch['longitude']
                            )
                            db.session.add(branch_obj)

                        for dept in branch['departments']:
                            # Inserir departamento se não existir
                            existing_dept = Department.query.filter_by(id=dept['id']).first()
                            if not existing_dept:
                                department = Department(
                                    id=dept['id'], branch_id=branch['id'], name=dept['name'], sector=dept['sector']
                                )
                                db.session.add(department)

                            for q in dept['queues']:
                                # Inserir fila se não existir
                                existing_queue = Queue.query.filter_by(id=q['id']).first()
                                if not existing_queue:
                                    queue = Queue(
                                        id=q['id'], department_id=dept['id'], service=q['service'],
                                        category_id=q['category_id'], prefix=q['prefix'],
                                        open_time=q['open_time'], end_time=q['end_time'],
                                        daily_limit=q['daily_limit'], num_counters=q['num_counters'],
                                        active_tickets=0, current_ticket=0
                                    )
                                    db.session.add(queue)

                                    for schedule in q['schedules']:
                                        # Verificar se o agendamento já existe
                                        existing_schedule = QueueSchedule.query.filter_by(
                                            queue_id=q['id'], weekday=schedule['weekday']
                                        ).first()
                                        if not existing_schedule:
                                            queue_schedule = QueueSchedule(
                                                id=str(uuid.uuid4()), queue_id=q['id'], weekday=schedule['weekday'],
                                                open_time=schedule.get('open_time'), end_time=schedule.get('end_time'),
                                                is_closed=schedule.get('is_closed', False)
                                            )
                                            db.session.add(queue_schedule)

                                    for tag in q['tags']:
                                        # Verificar se a tag já existe
                                        existing_tag = ServiceTag.query.filter_by(queue_id=q['id'], tag=tag).first()
                                        if not existing_tag:
                                            service_tag = ServiceTag(id=str(uuid.uuid4()), queue_id=q['id'], tag=tag)
                                            db.session.add(service_tag)

                db.session.commit()
                app.logger.info("Dados iniciais de instituições inseridos com sucesso!")

                # 4. Usuários
                users = [
                    {
                        'email': 'superadmin@facilita.com',
                        'name': 'Super Admin',
                        'password': os.getenv('SUPERADMIN_PASSWORD', 'superadmin123'),
                        'role': UserRole.SYSTEM_ADMIN,
                        'institution_id': None,
                        'department_name': None
                    },
                ]

                # 1 Admin por instituição (6)
                for inst in institutions:
                    email = f'admin.{inst["name"].replace(" ", "").lower()}@facilita.com'
                    if not User.query.filter_by(email=email).first():
                        users.append({
                            'email': email,
                            'name': f'Admin {inst["name"]}',
                            'password': os.getenv('ADMIN_PASSWORD', 'admin123'),
                            'role': UserRole.INSTITUTION_ADMIN,
                            'institution_id': inst['id'],
                            'department_name': None
                        })

                # 1 Usuário padrão
                inst = institutions[0]
                if not User.query.filter_by(email='user.1@facilita.com').first():
                    users.append({
                        'email': 'user.1@facilita.com',
                        'name': 'Usuário 1',
                        'password': os.getenv('USER_PASSWORD', 'user123'),
                        'role': UserRole.USER,
                        'institution_id': inst['id'],
                        'department_name': None
                    })

                # 1 Gestor por departamento (selecionar alguns)
                for inst in institutions[:2]:  # Apenas 2 instituições
                    for branch in inst['branches']:
                        for dept in branch['departments'][:1]:  # Apenas 1 departamento
                            email = f'gestor.{dept["name"].replace(" ", "").lower()}@facilita.com'
                            if not User.query.filter_by(email=email).first():
                                users.append({
                                    'email': email,
                                    'name': f'Gestor {dept["name"]}',
                                    'password': os.getenv('ADMIN_PASSWORD', 'admin123'),
                                    'role': UserRole.DEPARTMENT_ADMIN,
                                    'institution_id': inst['id'],
                                    'department_name': dept['name']
                                })

                # Inserir usuários
                for user_data in users:
                    if User.query.filter_by(email=user_data['email']).first():
                        continue

                    department = None
                    if user_data['department_name'] and user_data['institution_id']:
                        institution = Institution.query.get(user_data['institution_id'])
                        if institution and institution.branches:
                            for branch in institution.branches:
                                department = Department.query.filter_by(
                                    branch_id=branch.id, name=user_data['department_name']
                                ).first()
                                if department:
                                    break

                    user = User(
                        id=str(uuid.uuid4()), email=user_data['email'], name=user_data['name'],
                        user_role=user_data['role'], institution_id=user_data['institution_id'],
                        department_id=department.id if department else None, active=True
                    )
                    user.set_password(user_data['password'])
                    db.session.add(user)

                db.session.commit()
                app.logger.info("Usuários iniciais inseridos com sucesso!")

                # 5. Preferências de usuário
                user_preferences = []
                regular_users = [u for u in users if u['role'] == UserRole.USER]
                for user in regular_users:
                    inst = institutions[0]
                    if not UserPreference.query.filter_by(
                        user_id=User.query.filter_by(email=user['email']).first().id,
                        institution_id=inst['id'],
                        service_category_id=category_map['Saúde']
                    ).first():
                        user_preferences.append({
                            'user_email': user['email'],
                            'institution_id': inst['id'],
                            'service_category_id': category_map['Saúde'],
                            'neighborhood': neighborhoods[0]['name']
                        })

                # Inserir preferências
                for pref in user_preferences:
                    user = User.query.filter_by(email=pref['user_email']).first()
                    if user and not UserPreference.query.filter_by(
                        user_id=user.id, institution_id=pref['institution_id'],
                        service_category_id=pref['service_category_id']
                    ).first():
                        preference = UserPreference(
                            id=str(uuid.uuid4()), user_id=user.id, institution_id=pref['institution_id'],
                            service_category_id=pref['service_category_id'], neighborhood=pref['neighborhood']
                        )
                        db.session.add(preference)

                db.session.commit()
                app.logger.info("Preferências de usuário inseridas com sucesso!")

                # 6. Tickets
                all_queues = Queue.query.all()
                regular_users = User.query.filter_by(user_role=UserRole.USER).all()
                for queue in all_queues[:2]:  # Apenas 2 filas
                    queue.active_tickets = 0
                    queue.current_ticket = 0
                    for i in range(1, 6):  # 5 tickets por fila
                        qr_code = f"QR-{uuid.uuid4().hex[:10]}"
                        if Ticket.query.filter_by(qr_code=qr_code).first():
                            continue

                        is_physical = (i % 2 == 0)
                        user = None if is_physical else regular_users[0]
                        status = 'Pendente' if i == 1 else 'Atendido'
                        issued_at = datetime.utcnow() - timedelta(days=i)
                        ticket = Ticket(
                            id=str(uuid.uuid4()), queue_id=queue.id, user_id=user.id if user else None,
                            ticket_number=i, qr_code=qr_code, status=status,
                            priority=0, is_physical=is_physical, counter=1 if status == 'Atendido' else None,
                            issued_at=issued_at, attended_at=issued_at + timedelta(minutes=30) if status == 'Atendido' else None,
                            service_time=15.0 if status == 'Atendido' else None,
                            expires_at=issued_at + timedelta(hours=4) if is_physical else None,
                            trade_available=False
                        )
                        db.session.add(ticket)
                        if status == 'Pendente':
                            queue.active_tickets += 1
                            queue.current_ticket = max(queue.current_ticket, i)

                db.session.commit()
                app.logger.info("Tickets iniciais inseridos com sucesso!")

        except SQLAlchemyError as e:
            db.session.rollback()
            app.logger.error(f"Erro ao inserir dados iniciais: {str(e)}")
            raise
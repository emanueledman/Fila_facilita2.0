import uuid
from datetime import time, datetime, timedelta
from .models import AuditLog, Institution, Queue, User, Ticket, Department, UserPreference, UserRole, QueueSchedule, Weekday, Branch, ServiceCategory, ServiceTag
from . import db
import os
from sqlalchemy.exc import SQLAlchemyError

from sqlalchemy import Column, Integer, String, Float, Time, Boolean, DateTime, ForeignKey, Enum, Index, Text
from sqlalchemy.orm import relationship
import enum
from app import db
from datetime import datetime, time, timedelta
import uuid
import bcrypt

def populate_initial_data(app):
    """
    Popula o banco de dados com dados iniciais para testes, seguindo rigorosamente o models.py.
    Gera ~50 instituições, ~100 filiais, ~300 departamentos, ~600 filas, ~400 usuários, ~3000 tickets, ~1800 tags e ~100 preferências.
    Distribuído por setores (hospitais, bancos, cartórios, serviços de alta demanda) e bairros de Luanda.
    Mantém idempotência, logs em português, IDs fixos e compatibilidade com init_queue_routes e __init__.py.
    Usa bcrypt para senhas e respeita todos os campos e relacionamentos do models.py.
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
                    Cria categorias de serviço com hierarquia.
                    Retorna um mapa de nomes para IDs.
                    """
                    categories = [
                        {'name': 'Saúde', 'description': 'Serviços de saúde e atendimento médico', 'parent_id': None},
                        {'name': 'Consulta Médica', 'description': 'Consultas gerais e especializadas', 'parent_id': None},
                        {'name': 'Bancário', 'description': 'Serviços financeiros e bancários', 'parent_id': None},
                        {'name': 'Notarial', 'description': 'Serviços notariais e de registro', 'parent_id': None},
                        {'name': 'Serviços Públicos', 'description': 'Serviços governamentais e administrativos', 'parent_id': None},
                        {'name': 'Utilidades', 'description': 'Serviços de água, energia e telecomunicações', 'parent_id': None},
                        {'name': 'Educação', 'description': 'Serviços educacionais e administrativos', 'parent_id': None},
                    ]
                    category_map = {}
                    for cat in categories:
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
                    {'name': 'Rangel', 'latitude': -8.8300, 'longitude': 13.2500},
                    {'name': 'Samba', 'latitude': -8.8200, 'longitude': 13.2400},
                    {'name': 'Viana', 'latitude': -8.9035, 'longitude': 13.3741},
                    {'name': 'Talatona', 'latitude': -8.9167, 'longitude': 13.1833},
                    {'name': 'Kilamba', 'latitude': -8.9333, 'longitude': 13.2667},
                    {'name': 'Cazenga', 'latitude': -8.8500, 'longitude': 13.2833},
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
                    # Hospitais (20)
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Hospital Josina Machel',
                        'description': 'Hospital público de referência em Luanda',
                        'branches': [
                            {
                                'name': 'Unidade Central',
                                'location': 'Luanda, Luanda',
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
                                            },
                                            {
                                                'id': '21591b32-cbc4-424a-882f-3db65d134040',
                                                'service': 'Triagem',
                                                'category_id': category_map['Saúde'],
                                                'prefix': 'T',
                                                'open_time': time(7, 0),
                                                'end_time': time(17, 0),
                                                'daily_limit': 50,
                                                'num_counters': 3,
                                                'tags': ['triagem', 'saúde'],
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
                                    },
                                    {
                                        'name': 'Farmácia',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': '321589c1-1688-4684-b50a-3febdd17ea23',
                                                'service': 'Distribuição de Medicamentos',
                                                'category_id': category_map['Saúde'],
                                                'prefix': 'C',
                                                'open_time': time(8, 0),
                                                'end_time': time(16, 0),
                                                'daily_limit': 60,
                                                'num_counters': 3,
                                                'tags': ['farmácia', 'medicamentos', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
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
                                        'name': 'Consulta Externa',
                                        'sector': 'Saúde',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Consulta Especializada',
                                                'category_id': category_map['Consulta Médica'],
                                                'prefix': 'E',
                                                'open_time': time(8, 0),
                                                'end_time': time(16, 0),
                                                'daily_limit': 40,
                                                'num_counters': 4,
                                                'tags': ['consulta', 'especializada', 'saúde'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
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
                        'name': 'Hospital Maria Pia',
                        'description': 'Hospital especializado em pediatria e maternidade',
                        'branches': [
                            {
                                'name': 'Unidade Principal',
                                'location': 'Luanda, Luanda',
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
                            }
                        ]
                    },
                    # Outros 18 hospitais
                    *[
                        {
                            'id': str(uuid.uuid4()),
                            'name': f'Hospital Municipal {i}',
                            'description': f'Hospital municipal em {neighborhoods[i % len(neighborhoods)]["name"]}',
                            'branches': [
                                {
                                    'name': f'Unidade {neighborhoods[i % len(neighborhoods)]["name"]}',
                                    'location': f'{neighborhoods[i % len(neighborhoods)]["name"]}, Luanda',
                                    'neighborhood': neighborhoods[i % len(neighborhoods)]['name'],
                                    'latitude': neighborhoods[i % len(neighborhoods)]['latitude'],
                                    'longitude': neighborhoods[i % len(neighborhoods)]['longitude'],
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
                                                    'num_counters': 4,
                                                    'tags': ['consulta', 'geral', 'saúde'],
                                                    'schedules': [
                                                        {'weekday': Weekday.MONDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                        {'weekday': Weekday.TUESDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                        {'weekday': Weekday.WEDNESDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                        {'weekday': Weekday.THURSDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                        {'weekday': Weekday.FRIDAY, 'open_time': time(7, 0), 'end_time': time(17, 0), 'is_closed': False},
                                                        {'weekday': Weekday.SATURDAY, 'is_closed': True},
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
                                                    'prefix': 'U',
                                                    'open_time': time(0, 0),
                                                    'end_time': time(23, 59),
                                                    'daily_limit': 80,
                                                    'num_counters': 6,
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
                        }
                        for i in range(18)
                    ],
                    # Bancos (15)
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Banco de Fomento Angola (BFA)',
                        'description': 'Banco comercial líder em Angola',
                        'branches': [
                            {
                                'name': 'Agência Ingombota',
                                'location': 'Luanda, Luanda',
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
                                                'service': 'Depósitos e Levantamentos',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'D',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['depósito', 'levantamento', 'banco'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            },
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Abertura de Conta',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'A',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['conta', 'banco'],
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
                                        'name': 'Crédito',
                                        'sector': 'Bancário',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Empréstimos',
                                                'category_id': category_map['Bancário'],
                                                'prefix': 'E',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 20,
                                                'num_counters': 2,
                                                'tags': ['empréstimo', 'crédito', 'banco'],
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
                    # Outros 14 bancos
                    *[
                        {
                            'id': str(uuid.uuid4()),
                            'name': f'Banco {["Standard Bank", "Banco BIC", "Banco Millennium Atlântico", "Banco Sol"][i % 4]} {i}',
                            'description': f'Banco comercial em {neighborhoods[i % len(neighborhoods)]["name"]}',
                            'branches': [
                                {
                                    'name': f'Agência {neighborhoods[i % len(neighborhoods)]["name"]}',
                                    'location': f'{neighborhoods[i % len(neighborhoods)]["name"]}, Luanda',
                                    'neighborhood': neighborhoods[i % len(neighborhoods)]['name'],
                                    'latitude': neighborhoods[i % len(neighborhoods)]['latitude'],
                                    'longitude': neighborhoods[i % len(neighborhoods)]['longitude'],
                                    'departments': [
                                        {
                                            'name': 'Atendimento ao Cliente',
                                            'sector': 'Bancário',
                                            'queues': [
                                                {
                                                    'id': str(uuid.uuid4()),
                                                    'service': 'Depósitos e Levantamentos',
                                                    'category_id': category_map['Bancário'],
                                                    'prefix': 'D',
                                                    'open_time': time(8, 0),
                                                    'end_time': time(15, 0),
                                                    'daily_limit': 60,
                                                    'num_counters': 5,
                                                    'tags': ['depósito', 'levantamento', 'banco'],
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
                        for i in range(14)
                    ],
                    # Cartórios (10)
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'Cartório Notarial de Luanda',
                        'description': 'Cartório para serviços notariais',
                        'branches': [
                            {
                                'name': 'Sede Maianga',
                                'location': 'Luanda, Luanda',
                                'neighborhood': 'Maianga',
                                'latitude': -8.8147,
                                'longitude': 13.2302,
                                'departments': [
                                    {
                                        'name': 'Atendimento Notarial',
                                        'sector': 'Notarial',
                                        'queues': [
                                            {
                                                'id': '1862b78e-b091-4969-882f-c1f91c8dbd97',
                                                'service': 'Autenticação de Documentos',
                                                'category_id': category_map['Notarial'],
                                                'prefix': 'N',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 40,
                                                'num_counters': 3,
                                                'tags': ['notarial', 'autenticação', 'documentos'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(15, 0), 'is_closed': False},
                                                    {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                                    {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                                ]
                                            },
                                            {
                                                'id': '4f3118f4-8bcb-4339-92c1-d8a81441d87f',
                                                'service': 'Registo Civil',
                                                'category_id': category_map['Notarial'],
                                                'prefix': 'R',
                                                'open_time': time(8, 0),
                                                'end_time': time(15, 0),
                                                'daily_limit': 30,
                                                'num_counters': 2,
                                                'tags': ['notarial', 'registro', 'civil'],
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
                    # Outros 9 cartórios
                    *[
                        {
                            'id': str(uuid.uuid4()),
                            'name': f'Cartório Notarial {neighborhoods[i % len(neighborhoods)]["name"]} {i}',
                            'description': f'Serviços notariais em {neighborhoods[i % len(neighborhoods)]["name"]}',
                            'branches': [
                                {
                                    'name': f'Sede {neighborhoods[i % len(neighborhoods)]["name"]}',
                                    'location': f'{neighborhoods[i % len(neighborhoods)]["name"]}, Luanda',
                                    'neighborhood': neighborhoods[i % len(neighborhoods)]['name'],
                                    'latitude': neighborhoods[i % len(neighborhoods)]['latitude'],
                                    'longitude': neighborhoods[i % len(neighborhoods)]['longitude'],
                                    'departments': [
                                        {
                                            'name': 'Atendimento Notarial',
                                            'sector': 'Notarial',
                                            'queues': [
                                                {
                                                    'id': str(uuid.uuid4()),
                                                    'service': 'Autenticação de Documentos',
                                                    'category_id': category_map['Notarial'],
                                                    'prefix': 'N',
                                                    'open_time': time(8, 0),
                                                    'end_time': time(15, 0),
                                                    'daily_limit': 40,
                                                    'num_counters': 3,
                                                    'tags': ['notarial', 'autenticação', 'documentos'],
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
                        for i in range(9)
                    ],
                    # Serviços de Alta Demanda (5)
                    {
                        'id': str(uuid.uuid4()),
                        'name': 'EPAL - Empresa Pública de Águas',
                        'description': 'Serviços de fornecimento de água',
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
                                        'sector': 'Utilidades',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Reclamações de Fatura',
                                                'category_id': category_map['Utilidades'],
                                                'prefix': 'F',
                                                'open_time': time(8, 0),
                                                'end_time': time(16, 0),
                                                'daily_limit': 50,
                                                'num_counters': 4,
                                                'tags': ['água', 'fatura', 'reclamação'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
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
                        'name': 'ENDE - Empresa Nacional de Distribuição de Electricidade',
                        'description': 'Serviços de fornecimento de energia',
                        'branches': [
                            {
                                'name': 'Agência Kilamba',
                                'location': 'Kilamba, Luanda',
                                'neighborhood': 'Kilamba',
                                'latitude': -8.9333,
                                'longitude': 13.2667,
                                'departments': [
                                    {
                                        'name': 'Atendimento ao Cliente',
                                        'sector': 'Utilidades',
                                        'queues': [
                                            {
                                                'id': str(uuid.uuid4()),
                                                'service': 'Pagamentos de Fatura',
                                                'category_id': category_map['Utilidades'],
                                                'prefix': 'P',
                                                'open_time': time(8, 0),
                                                'end_time': time(16, 0),
                                                'daily_limit': 60,
                                                'num_counters': 5,
                                                'tags': ['energia', 'fatura', 'pagamento'],
                                                'schedules': [
                                                    {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                    {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
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
                    # Outros 3 serviços de alta demanda
                    *[
                        {
                            'id': str(uuid.uuid4()),
                            'name': f'Serviço {["Unitel", "Multitel", "Angola Telecom"][i % 3]}',
                            'description': f'Serviço de telecomunicações em {neighborhoods[i % len(neighborhoods)]["name"]}',
                            'branches': [
                                {
                                    'name': f'Agência {neighborhoods[i % len(neighborhoods)]["name"]}',
                                    'location': f'{neighborhoods[i % len(neighborhoods)]["name"]}, Luanda',
                                    'neighborhood': neighborhoods[i % len(neighborhoods)]['name'],
                                    'latitude': neighborhoods[i % len(neighborhoods)]['latitude'],
                                    'longitude': neighborhoods[i % len(neighborhoods)]['longitude'],
                                    'departments': [
                                        {
                                            'name': 'Atendimento ao Cliente',
                                            'sector': 'Utilidades',
                                            'queues': [
                                                {
                                                    'id': str(uuid.uuid4()),
                                                    'service': 'Atendimento Geral',
                                                    'category_id': category_map['Utilidades'],
                                                    'prefix': 'G',
                                                    'open_time': time(8, 0),
                                                    'end_time': time(16, 0),
                                                    'daily_limit': 50,
                                                    'num_counters': 4,
                                                    'tags': ['telecomunicações', 'atendimento'],
                                                    'schedules': [
                                                        {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                        {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                        {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                        {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
                                                        {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(16, 0), 'is_closed': False},
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
                        for i in range(3)
                    ]
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
                    Cria ~400 usuários: 1 SYSTEM_ADMIN, 1 INSTITUTION_ADMIN por instituição,
                    1-2 DEPARTMENT_ADMIN por departamento, 50 USER.
                    Usa User.set_password com bcrypt.
                    """
                    users = []
                    # SYSTEM_ADMIN
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

                    # INSTITUTION_ADMIN (~50)
                    for inst in Institution.query.all():
                        admin = User(
                            id=str(uuid.uuid4()),
                            email=f'admin_{inst.name.lower().replace(" ", "_")}@queue.com',
                            name=f'Admin {inst.name}',
                            user_role=UserRole.INSTITUTION_ADMIN,
                            institution_id=inst.id,
                            created_at=datetime.utcnow(),
                            active=True
                        )
                        admin.set_password('admin123')
                        db.session.add(admin)
                        users.append(admin)

                    # DEPARTMENT_ADMIN (~300 departamentos x 2 = ~600)
                    for dept in Department.query.all():
                        for i in range(2):
                            manager = User(
                                id=str(uuid.uuid4()),
                                email=f'manager_{dept.name.lower().replace(" ", "_")}_{i}@queue.com',
                                name=f'Gerente {dept.name} {i+1}',
                                user_role=UserRole.DEPARTMENT_ADMIN,
                                department_id=dept.id,
                                institution_id=dept.branch.institution_id,
                                created_at=datetime.utcnow(),
                                active=True
                            )
                            manager.set_password('manager123')
                            db.session.add(manager)
                            users.append(manager)

                    # USER (50)
                    for i in range(50):
                        user = User(
                            id=str(uuid.uuid4()),
                            email=f'user_{i}@queue.com',
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
                    Cria ~100 preferências (~2 por usuário USER).
                    """
                    for user in User.query.filter_by(user_role=UserRole.USER).limit(50).all():
                        categories = ServiceCategory.query.limit(2).all()
                        for category in categories:
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
                    Cria ~3000 tickets (~5 por fila), com ticket_number e qr_code.
                    """
                    now = datetime.utcnow()
                    for queue in Queue.query.all():
                        for i in range(5):
                            ticket_number = i + 1
                            qr_code = f"{queue.prefix}{ticket_number:03d}-{queue.id[:8]}"
                            ticket = Ticket(
                                id=str(uuid.uuid4()),
                                queue_id=queue.id,
                                user_id=users[i % len(users)].id,
                                ticket_number=ticket_number,
                                qr_code=qr_code,
                                priority=0,
                                is_physical=False,
                                status='Pendente',
                                issued_at=now - timedelta(days=i),
                                expires_at=now + timedelta(days=1),
                                counter=None,
                                service_time=0.0,
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
                    Cria logs de auditoria para simular ações.
                    """
                    now = datetime.utcnow()
                    for user in User.query.limit(10).all():
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

# FIM DO ARQUIVO
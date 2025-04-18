import uuid
from datetime import time, datetime, timedelta
import random
from .models import Institution, Branch, Queue, ServiceCategory, ServiceTag, User, Ticket, Department, UserRole, QueueSchedule, Weekday, UserPreference
from . import db
import os
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

def populate_initial_data(app):
    with app.app_context():
        try:
            with db.session.no_autoflush:
                if Institution.query.count() > 0:
                    app.logger.info("Instituições já existem, pulando inicialização de dados.")
                    return

                # 1. Categorias de Serviço
                service_categories = [
                    {'name': 'Saúde Pública', 'description': 'Hospitais e clínicas públicas', 'parent_id': None},
                    {'name': 'Saúde Privada', 'description': 'Clínicas e hospitais privados', 'parent_id': None},
                    {'name': 'Bancário', 'description': 'Serviços bancários', 'parent_id': None},
                    {'name': 'Educação', 'description': 'Instituições de ensino', 'parent_id': None},
                    {'name': 'Serviços Públicos', 'description': 'Cartórios e serviços administrativos', 'parent_id': None},
                    {'name': 'Transporte', 'description': 'Serviços de transporte', 'parent_id': None},
                    {'name': 'Utilidades', 'description': 'Água, eletricidade, telecomunicações', 'parent_id': None},
                ]
                category_map = {}
                for cat in service_categories:
                    if ServiceCategory.query.filter_by(name=cat['name']).first():
                        app.logger.warning(f"Categoria {cat['name']} já existe, pulando.")
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

                # 2. Tags de Serviço
                service_tags = [
                    {'name': 'Urgente', 'category_id': category_map['Saúde Pública']},
                    {'name': 'Premium', 'category_id': category_map['Saúde Privada']},
                    {'name': 'Depósito', 'category_id': category_map['Bancário']},
                    {'name': 'Matrícula', 'category_id': category_map['Educação']},
                    {'name': 'Notarial', 'category_id': category_map['Serviços Públicos']},
                ]
                tag_map = {}
                for tag in service_tags:
                    if ServiceTag.query.filter_by(name=tag['name']).first():
                        app.logger.warning(f"Tag {tag['name']} já existe, pulando.")
                        continue
                    service_tag = ServiceTag(
                        id=str(uuid.uuid4()),
                        name=tag['name'],
                        category_id=tag['category_id']
                    )
                    db.session.add(service_tag)
                    db.session.flush()
                    tag_map[tag['name']] = service_tag.id

                # 3. Instituições e Filiais
                neighborhoods = [
                    'Ingombota', 'Maianga', 'Samba', 'Viana', 'Rangel', 'Cazenga', 'Kilamba', 'Talatona',
                    'Mutamba', 'Prenda', 'Alvalade', 'Patriota', 'Zango', 'Cacuaco', 'Benfica'
                ]
                institutions_data = [
                    {
                        'name': 'Hospital Josina Machel',
                        'description': 'Hospital público principal de Luanda',
                        'sector': 'Saúde Pública',
                        'category_id': category_map['Saúde Pública'],
                        'num_branches': 3,
                        'departments_per_branch': [
                            {
                                'name': 'Consulta Geral',
                                'queues': [
                                    {
                                        'id': '80746d76-f7f5-4c79-acd1-4173c1737a5a',
                                        'service': 'Consulta Geral',
                                        'prefix': 'A',
                                        'open_time': time(7, 0),
                                        'end_time': time(17, 0),
                                        'daily_limit': 50,
                                        'num_counters': 5,
                                        'avg_wait_time': 20.0,
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
                                        'prefix': 'T',
                                        'open_time': time(7, 0),
                                        'end_time': time(17, 0),
                                        'daily_limit': 50,
                                        'num_counters': 3,
                                        'avg_wait_time': 15.0,
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
                                'queues': [
                                    {
                                        'id': '72282889-e677-481a-9894-1c5bc68c2c44',
                                        'service': 'Urgência',
                                        'prefix': 'B',
                                        'open_time': time(0, 0),
                                        'end_time': time(23, 59),
                                        'daily_limit': 100,
                                        'num_counters': 8,
                                        'avg_wait_time': 30.0,
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
                                'queues': [
                                    {
                                        'id': '321589c1-1688-4684-b50a-3febdd17ea23',
                                        'service': 'Distribuição de Medicamentos',
                                        'prefix': 'C',
                                        'open_time': time(8, 0),
                                        'end_time': time(16, 0),
                                        'daily_limit': 60,
                                        'num_counters': 3,
                                        'avg_wait_time': 10.0,
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
                        'name': 'Clínica Sagrada Esperança',
                        'description': 'Hospital privado de referência',
                        'sector': 'Saúde Privada',
                        'category_id': category_map['Saúde Privada'],
                        'num_branches': 2,
                        'departments_per_branch': [
                            {
                                'name': 'Consulta Especializada',
                                'queues': [
                                    {
                                        'service': 'Consulta Especializada',
                                        'prefix': 'E',
                                        'open_time': time(8, 0),
                                        'end_time': time(18, 0),
                                        'daily_limit': 30,
                                        'num_counters': 4,
                                        'avg_wait_time': 15.0,
                                        'schedules': [
                                            {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(18, 0), 'is_closed': False},
                                            {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(18, 0), 'is_closed': False},
                                            {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(18, 0), 'is_closed': False},
                                            {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(18, 0), 'is_closed': False},
                                            {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(18, 0), 'is_closed': False},
                                            {'weekday': Weekday.SATURDAY, 'open_time': time(8, 0), 'end_time': time(12, 0), 'is_closed': False},
                                            {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                        ]
                                    }
                                ]
                            },
                            {
                                'name': 'Exames',
                                'queues': [
                                    {
                                        'service': 'Exames Diagnósticos',
                                        'prefix': 'X',
                                        'open_time': time(7, 0),
                                        'end_time': time(16, 0),
                                        'daily_limit': 40,
                                        'num_counters': 3,
                                        'avg_wait_time': 20.0,
                                        'schedules': [
                                            {'weekday': Weekday.MONDAY, 'open_time': time(7, 0), 'end_time': time(16, 0), 'is_closed': False},
                                            {'weekday': Weekday.TUESDAY, 'open_time': time(7, 0), 'end_time': time(16, 0), 'is_closed': False},
                                            {'weekday': Weekday.WEDNESDAY, 'open_time': time(7, 0), 'end_time': time(16, 0), 'is_closed': False},
                                            {'weekday': Weekday.THURSDAY, 'open_time': time(7, 0), 'end_time': time(16, 0), 'is_closed': False},
                                            {'weekday': Weekday.FRIDAY, 'open_time': time(7, 0), 'end_time': time(16, 0), 'is_closed': False},
                                            {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                            {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'name': 'Banco de Fomento Angola (BFA)',
                        'description': 'Banco comercial líder',
                        'sector': 'Bancário',
                        'category_id': category_map['Bancário'],
                        'num_branches': 5,
                        'departments_per_branch': [
                            {
                                'name': 'Atendimento ao Cliente',
                                'queues': [
                                    {
                                        'service': 'Depósito',
                                        'prefix': 'D',
                                        'open_time': time(8, 0),
                                        'end_time': time(15, 0),
                                        'daily_limit': 60,
                                        'num_counters': 4,
                                        'avg_wait_time': 10.0,
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
                                        'service': 'Levantamento',
                                        'prefix': 'L',
                                        'open_time': time(8, 0),
                                        'end_time': time(15, 0),
                                        'daily_limit': 50,
                                        'num_counters': 3,
                                        'avg_wait_time': 12.0,
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
                                'queues': [
                                    {
                                        'service': 'Empréstimo',
                                        'prefix': 'E',
                                        'open_time': time(9, 0),
                                        'end_time': time(14, 0),
                                        'daily_limit': 20,
                                        'num_counters': 2,
                                        'avg_wait_time': 25.0,
                                        'schedules': [
                                            {'weekday': Weekday.MONDAY, 'open_time': time(9, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.TUESDAY, 'open_time': time(9, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.WEDNESDAY, 'open_time': time(9, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.THURSDAY, 'open_time': time(9, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.FRIDAY, 'open_time': time(9, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                            {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'name': 'Escola Primária Ngola Kiluanje',
                        'description': 'Escola primária em Viana',
                        'sector': 'Educação',
                        'category_id': category_map['Educação'],
                        'num_branches': 2,
                        'departments_per_branch': [
                            {
                                'name': 'Secretaria Escolar',
                                'queues': [
                                    {
                                        'id': '066a3c0c-54e1-4c35-81d9-dcff210bd2d5',
                                        'service': 'Matrículas',
                                        'prefix': 'M',
                                        'open_time': time(8, 0),
                                        'end_time': time(14, 0),
                                        'daily_limit': 30,
                                        'num_counters': 2,
                                        'avg_wait_time': 15.0,
                                        'schedules': [
                                            {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                            {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                        ]
                                    },
                                    {
                                        'id': '06c9b02c-bd01-4bb5-9f98-2bc56cbadf3a',
                                        'service': 'Declarações',
                                        'prefix': 'D',
                                        'open_time': time(8, 0),
                                        'end_time': time(14, 0),
                                        'daily_limit': 20,
                                        'num_counters': 1,
                                        'avg_wait_time': 10.0,
                                        'schedules': [
                                            {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                            {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'name': 'Cartório Notarial de Luanda',
                        'description': 'Serviços notariais em Luanda',
                        'sector': 'Serviços Públicos',
                        'category_id': category_map['Serviços Públicos'],
                        'num_branches': 3,
                        'departments_per_branch': [
                            {
                                'name': 'Atendimento Notarial',
                                'queues': [
                                    {
                                        'id': '1862b78e-b091-4969-882f-c1f91c8dbd97',
                                        'service': 'Autenticação de Documentos',
                                        'prefix': 'N',
                                        'open_time': time(8, 0),
                                        'end_time': time(15, 0),
                                        'daily_limit': 40,
                                        'num_counters': 3,
                                        'avg_wait_time': 15.0,
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
                                        'prefix': 'R',
                                        'open_time': time(8, 0),
                                        'end_time': time(15, 0),
                                        'daily_limit': 30,
                                        'num_counters': 2,
                                        'avg_wait_time': 20.0,
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
                        'name': 'Hospital Maria Pia',
                        'description': 'Hospital público especializado',
                        'sector': 'Saúde Pública',
                        'category_id': category_map['Saúde Pública'],
                        'num_branches': 2,
                        'departments_per_branch': [
                            {
                                'name': 'Pediatria',
                                'queues': [
                                    {
                                        'id': '9c5fda76-2459-4622-b591-4180a4088d50',
                                        'service': 'Consulta Pediátrica',
                                        'prefix': 'P',
                                        'open_time': time(7, 30),
                                        'end_time': time(16, 30),
                                        'daily_limit': 40,
                                        'num_counters': 4,
                                        'avg_wait_time': 18.0,
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
                                'queues': [
                                    {
                                        'id': 'cccc41b7-60bb-47ff-955e-a5f71ae8827e',
                                        'service': 'Consulta Pré-Natal',
                                        'prefix': 'M',
                                        'open_time': time(8, 0),
                                        'end_time': time(15, 0),
                                        'daily_limit': 30,
                                        'num_counters': 2,
                                        'avg_wait_time': 20.0,
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
                        'name': 'Instituto Médio de Saúde de Luanda',
                        'description': 'Instituto de formação em saúde',
                        'sector': 'Educação',
                        'category_id': category_map['Educação'],
                        'num_branches': 2,
                        'departments_per_branch': [
                            {
                                'name': 'Administração Escolar',
                                'queues': [
                                    {
                                        'id': str(uuid.uuid4()),
                                        'service': 'Inscrições',
                                        'prefix': 'I',
                                        'open_time': time(8, 0),
                                        'end_time': time(13, 0),
                                        'daily_limit': 25,
                                        'num_counters': 2,
                                        'avg_wait_time': 15.0,
                                        'schedules': [
                                            {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(13, 0), 'is_closed': False},
                                            {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(13, 0), 'is_closed': False},
                                            {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(13, 0), 'is_closed': False},
                                            {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(13, 0), 'is_closed': False},
                                            {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(13, 0), 'is_closed': False},
                                            {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                            {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'name': 'EPAL',
                        'description': 'Empresa Pública de Águas de Luanda',
                        'sector': 'Utilidades',
                        'category_id': category_map['Utilidades'],
                        'num_branches': 4,
                        'departments_per_branch': [
                            {
                                'name': 'Atendimento ao Cliente',
                                'queues': [
                                    {
                                        'service': 'Faturação',
                                        'prefix': 'F',
                                        'open_time': time(8, 0),
                                        'end_time': time(16, 0),
                                        'daily_limit': 50,
                                        'num_counters': 3,
                                        'avg_wait_time': 20.0,
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
                        'name': 'TCUL',
                        'description': 'Transportes Colectivos Urbanos de Luanda',
                        'sector': 'Transporte',
                        'category_id': category_map['Transporte'],
                        'num_branches': 3,
                        'departments_per_branch': [
                            {
                                'name': 'Bilheteira',
                                'queues': [
                                    {
                                        'service': 'Compra de Bilhetes',
                                        'prefix': 'B',
                                        'open_time': time(6, 0),
                                        'end_time': time(20, 0),
                                        'daily_limit': 100,
                                        'num_counters': 5,
                                        'avg_wait_time': 10.0,
                                        'schedules': [
                                            {'weekday': Weekday.MONDAY, 'open_time': time(6, 0), 'end_time': time(20, 0), 'is_closed': False},
                                            {'weekday': Weekday.TUESDAY, 'open_time': time(6, 0), 'end_time': time(20, 0), 'is_closed': False},
                                            {'weekday': Weekday.WEDNESDAY, 'open_time': time(6, 0), 'end_time': time(20, 0), 'is_closed': False},
                                            {'weekday': Weekday.THURSDAY, 'open_time': time(6, 0), 'end_time': time(20, 0), 'is_closed': False},
                                            {'weekday': Weekday.FRIDAY, 'open_time': time(6, 0), 'end_time': time(20, 0), 'is_closed': False},
                                            {'weekday': Weekday.SATURDAY, 'open_time': time(6, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'name': 'Universidade Agostinho Neto',
                        'description': 'Principal universidade pública',
                        'sector': 'Educação',
                        'category_id': category_map['Educação'],
                        'num_branches': 2,
                        'departments_per_branch': [
                            {
                                'name': 'Secretaria Académica',
                                'queues': [
                                    {
                                        'service': 'Inscrições Académicas',
                                        'prefix': 'S',
                                        'open_time': time(8, 0),
                                        'end_time': time(14, 0),
                                        'daily_limit': 30,
                                        'num_counters': 2,
                                        'avg_wait_time': 20.0,
                                        'schedules': [
                                            {'weekday': Weekday.MONDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.TUESDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.WEDNESDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.THURSDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.FRIDAY, 'open_time': time(8, 0), 'end_time': time(14, 0), 'is_closed': False},
                                            {'weekday': Weekday.SATURDAY, 'is_closed': True},
                                            {'weekday': Weekday.SUNDAY, 'is_closed': True}
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                ]

                # Gerar mais 40 instituições dinamicamente
                additional_institutions = []
                sectors = [
                    ('Saúde Pública', category_map['Saúde Pública'], ['Consulta Geral', 'Urgência', 'Farmácia']),
                    ('Saúde Privada', category_map['Saúde Privada'], ['Consulta Especializada', 'Exames']),
                    ('Bancário', category_map['Bancário'], ['Atendimento ao Cliente', 'Crédito']),
                    ('Educação', category_map['Educação'], ['Secretaria Escolar', 'Administração']),
                    ('Serviços Públicos', category_map['Serviços Públicos'], ['Atendimento Notarial', 'Registo']),
                    ('Transporte', category_map['Transporte'], ['Bilheteira', 'Atendimento']),
                    ('Utilidades', category_map['Utilidades'], ['Faturação', 'Reclamações'])
                ]
                for i in range(40):
                    sector, cat_id, dept_names = random.choice(sectors)
                    inst_name = f"{sector} {chr(65+i)}"
                    additional_institutions.append({
                        'name': inst_name,
                        'description': f"Instituição de {sector} #{i+1}",
                        'sector': sector,
                        'category_id': cat_id,
                        'num_branches': random.randint(2, 4),
                        'departments_per_branch': [
                            {
                                'name': dept_name,
                                'queues': [
                                    {
                                        'service': f"Serviço {dept_name}",
                                        'prefix': dept_name[0].upper(),
                                        'open_time': time(8, 0),
                                        'end_time': time(16, 0),
                                        'daily_limit': random.randint(20, 100),
                                        'num_counters': random.randint(1, 5),
                                        'avg_wait_time': random.uniform(10.0, 30.0),
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
                            } for dept_name in random.sample(dept_names, random.randint(1, len(dept_names)))
                        ]
                    })
                institutions_data.extend(additional_institutions)

                queue_ids = {}
                for inst_data in institutions_data:
                    if Institution.query.filter_by(name=inst_data['name']).first():
                        app.logger.info(f"Instituição {inst_data['name']} já existe, pulando.")
                        continue

                    institution = Institution(
                        id=str(uuid.uuid4()),
                        name=inst_data['name'],
                        description=inst_data['description']
                    )
                    db.session.add(institution)
                    db.session.flush()

                    branches = []
                    for i in range(inst_data['num_branches']):
                        neighborhood = random.choice(neighborhoods)
                        lat = -8.8 + random.uniform(-0.1, 0.1)
                        lon = 13.2 + random.uniform(-0.1, 0.1)
                        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                            raise ValueError(f"Coordenadas inválidas para filial {inst_data['name']} {neighborhood}")
                        branch = {
                            'name': f"Unidade {neighborhood}",
                            'location': f"Luanda, {neighborhood}",
                            'neighborhood': neighborhood,
                            'latitude': lat,
                            'longitude': lon,
                            'departments': inst_data['departments_per_branch']
                        }
                        branches.append(branch)

                    for branch in branches:
                        branch_obj = Branch(
                            id=str(uuid.uuid4()),
                            institution_id=institution.id,
                            name=branch['name'],
                            location=branch['location'],
                            neighborhood=branch['neighborhood'],
                            latitude=branch['latitude'],
                            longitude=branch['longitude']
                        )
                        db.session.add(branch_obj)
                        db.session.flush()

                        for dept_data in branch['departments']:
                            if Department.query.filter_by(branch_id=branch_obj.id, name=dept_data['name']).first():
                                app.logger.info(f"Departamento {dept_data['name']} já existe em {branch['name']}, pulando.")
                                continue

                            department = Department(
                                id=str(uuid.uuid4()),
                                branch_id=branch_obj.id,
                                name=dept_data['name'],
                                sector=inst_data['sector']
                            )
                            db.session.add(department)
                            db.session.flush()

                            for q in dept_data['queues']:
                                queue_id = q.get('id', str(uuid.uuid4()))
                                if Queue.query.filter_by(department_id=department.id, service=q['service']).first():
                                    app.logger.info(f"Fila {q['service']} já existe em {dept_data['name']}, pulando.")
                                    queue_ids[f"{dept_data['name']}_{q['service']}"] = queue_id
                                    continue

                                queue = Queue(
                                    id=queue_id,
                                    department_id=department.id,
                                    service=q['service'],
                                    category_id=inst_data['category_id'],
                                    prefix=q['prefix'],
                                    open_time=q['open_time'],
                                    end_time=q.get('end_time'),
                                    daily_limit=q['daily_limit'],
                                    num_counters=q['num_counters'],
                                    active_tickets=0,
                                    current_ticket=0,
                                    avg_wait_time=q.get('avg_wait_time', 15.0)
                                )
                                db.session.add(queue)
                                db.session.flush()
                                queue_ids[f"{dept_data['name']}_{q['service']}"] = queue.id

                                for schedule in q.get('schedules', []):
                                    queue_schedule = QueueSchedule(
                                        id=str(uuid.uuid4()),
                                        queue_id=queue.id,
                                        weekday=schedule['weekday'],
                                        open_time=schedule.get('open_time'),
                                        end_time=schedule.get('end_time'),
                                        is_closed=schedule.get('is_closed', False)
                                    )
                                    db.session.add(queue_schedule)

                db.session.commit()
                app.logger.info("Instituições, filiais, departamentos, filas e agendamentos inseridos com sucesso!")

                # 4. Usuários
                users = [
                    {
                        'email': 'superadmin@facilita.com',
                        'name': 'Super Admin',
                        'password': os.getenv('SUPERADMIN_PASSWORD', 'superadmin123'),
                        'user_role': UserRole.SYSTEM_ADMIN,
                        'institution_id': None,
                        'branch_id': None,
                        'department_name': None
                    }
                ]
                for inst_data in institutions_data:
                    inst_id = Institution.query.filter_by(name=inst_data['name']).first().id
                    users.append({
                        'email': f"admin.{inst_data['name'].lower().replace(' ', '')}@facilita.com",
                        'name': f"Admin {inst_data['name']}",
                        'password': os.getenv('ADMIN_PASSWORD', 'admin123'),
                        'user_role': UserRole.INSTITUTION_ADMIN,
                        'institution_id': inst_id,
                        'branch_id': None,
                        'department_name': None
                    })
                    branches = Branch.query.filter_by(institution_id=inst_id).all()
                    for branch in branches:
                        departments = Department.query.filter_by(branch_id=branch.id).all()
                        for dept in departments:
                            users.append({
                                'email': f"gestor.{dept.name.lower().replace(' ', '')}.{branch.neighborhood.lower()}@facilita.com",
                                'name': f"Gestor {dept.name} {branch.neighborhood}",
                                'password': os.getenv('ADMIN_PASSWORD', 'admin123'),
                                'user_role': UserRole.DEPARTMENT_ADMIN,
                                'institution_id': inst_id,
                                'branch_id': branch.id,
                                'department_name': dept.name
                            })

                for i in range(50):
                    users.append({
                        'email': f"user{i+1}@facilita.com",
                        'name': f"Usuário {i+1}",
                        'password': os.getenv('USER_PASSWORD', 'user123'),
                        'user_role': UserRole.USER,
                        'institution_id': random.choice([inst['id'] for inst in institutions_data]),
                        'branch_id': None,
                        'department_name': None
                    })

                for user_data in users:
                    if User.query.filter_by(email=user_data['email']).first():
                        app.logger.info(f"Usuário {user_data['email']} já existe, pulando.")
                        continue

                    department = None
                    if user_data['department_name'] and user_data['branch_id']:
                        department = Department.query.filter_by(
                            branch_id=user_data['branch_id'],
                            name=user_data['department_name']
                        ).first()
                        if not department:
                            app.logger.warning(f"Departamento {user_data['department_name']} não encontrado para {user_data['email']}")
                            continue

                    user = User(
                        id=str(uuid.uuid4()),
                        email=user_data['email'],
                        name=user_data['name'],
                        user_role=user_data['user_role'],
                        institution_id=user_data['institution_id'],
                        department_id=department.id if department else None,
                        active=True
                    )
                    user.set_password(user_data['password'])
                    db.session.add(user)

                db.session.commit()
                app.logger.info("Usuários inseridos com sucesso!")

                # 5. Preferências de Usuário
                regular_users = User.query.filter_by(user_role=UserRole.USER).all()
                user_preferences = []
                for user in regular_users:
                    for _ in range(random.randint(1, 3)):
                        inst = random.choice(institutions_data)
                        user_preferences.append({
                            'user_id': user.id,
                            'institution_id': Institution.query.filter_by(name=inst['name']).first().id,
                            'service_category_id': inst['category_id'],
                            'neighborhood': random.choice(neighborhoods)
                        })

                for pref in user_preferences:
                    preference = UserPreference(
                        id=str(uuid.uuid4()),
                        user_id=pref['user_id'],
                        institution_id=pref['institution_id'],
                        service_category_id=pref['service_category_id'],
                        neighborhood=pref['neighborhood']
                    )
                    db.session.add(preference)

                db.session.commit()
                app.logger.info("Preferências de usuário inseridas com sucesso!")

                # 6. Tickets
                with db.session.no_autoflush:
                    default_user = User.query.filter_by(email='user1@facilita.com').first()
                    if not default_user:
                        raise ValueError("Usuário padrão não encontrado!")

                    tickets = []
                    for queue_id in queue_ids.values():
                        queue = Queue.query.get(queue_id)
                        if not queue:
                            app.logger.warning(f"Fila {queue_id} não encontrada.")
                            continue

                        queue.active_tickets = 0
                        queue.current_ticket = 0

                        for i in range(1, 1001):
                            is_physical = (i % 10 == 0)
                            status = 'Pendente' if i > 800 else 'Atendido'
                            issued_at = datetime.utcnow() - timedelta(days=random.randint(0, 60), hours=random.randint(0, 23))
                            service_time = random.uniform(5.0, 60.0) if status == 'Atendido' else None
                            attended_at = issued_at + timedelta(minutes=service_time) if status == 'Atendido' else None
                            priority = random.randint(0, 2)

                            qr_code = f"QR-{uuid.uuid4().hex[:10]}"
                            while Ticket.query.filter_by(qr_code=qr_code).first():
                                qr_code = f"QR-{uuid.uuid4().hex[:10]}"

                            ticket = Ticket(
                                id=str(uuid.uuid4()),
                                queue_id=queue_id,
                                user_id=default_user.id if not is_physical else None,
                                ticket_number=i,
                                qr_code=qr_code,
                                status=status,
                                priority=priority,
                                is_physical=is_physical,
                                counter=random.randint(1, queue.num_counters) if status == 'Atendido' else None,
                                issued_at=issued_at,
                                attended_at=attended_at,
                                service_time=service_time,
                                expires_at=issued_at + timedelta(hours=4) if is_physical else None,
                                trade_available=False
                            )
                            tickets.append(ticket)

                            if status == 'Pendente':
                                queue.active_tickets += 1
                                queue.current_ticket = max(queue.current_ticket, i)

                    db.session.bulk_save_objects(tickets)
                    db.session.commit()
                    app.logger.info("Tickets inseridos com sucesso!")

        except SQLAlchemyError as e:
            db.session.rollback()
            app.logger.error(f"Erro ao inserir dados iniciais: {str(e)}")
            raise
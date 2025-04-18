import logging
import uuid
from datetime import time, datetime
from sqlalchemy.exc import SQLAlchemyError
from app.models import Institution, Branch, Department, Queue, ServiceCategory, ServiceTag, QueueSchedule, Weekday, User, Ticket, UserPreference
from app import db, socketio
from flask_socketio import emit

logger = logging.getLogger(__name__)

class DataInitializer:
    """Classe para inicializar dados iniciais no banco de dados de forma robusta e escalável."""
    
    NEIGHBORHOODS = [
        'Ingombota', 'Maianga', 'Samba', 'Viana', 'Rangel', 'Cazenga', 'Kilamba', 'Talatona',
        'Mutamba', 'Prenda', 'Alvalade', 'Patriota', 'Zango', 'Cacuaco', 'Benfica'
    ]

    INSTITUTIONS_DATA = [
        {
            'name': 'Hospital Josina Machel',
            'description': 'Hospital público principal de Luanda',
            'sector': 'Saúde Pública',
            'category_name': 'Saúde Pública',
            'num_branches': 3,
            'departments_per_branch': [
                {
                    'name': 'Consulta Geral',
                    'sector': 'Atendimento Médico',
                    'queues': [
                        {
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
                            ],
                            'tags': ['Consulta']
                        },
                        {
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
                            ],
                            'tags': ['Triagem']
                        }
                    ]
                },
                {
                    'name': 'Urgência',
                    'sector': 'Atendimento de Emergência',
                    'queues': [
                        {
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
                            ],
                            'tags': ['Urgente']
                        }
                    ]
                },
                {
                    'name': 'Farmácia',
                    'sector': 'Distribuição de Medicamentos',
                    'queues': [
                        {
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
                            ],
                            'tags': ['Farmácia']
                        }
                    ]
                }
            ]
        },
        {
            'name': 'Clínica Sagrada Esperança',
            'description': 'Hospital privado de referência',
            'sector': 'Saúde Privada',
            'category_name': 'Saúde Privada',
            'num_branches': 2,
            'departments_per_branch': [
                {
                    'name': 'Consulta Especializada',
                    'sector': 'Atendimento Especializado',
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
                            ],
                            'tags': ['Premium']
                        }
                    ]
                },
                {
                    'name': 'Exames',
                    'sector': 'Diagnósticos',
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
                            ],
                            'tags': ['Diagnóstico']
                        }
                    ]
                }
            ]
        },
        {
            'name': 'Banco de Fomento Angola (BFA)',
            'description': 'Banco comercial líder',
            'sector': 'Bancário',
            'category_name': 'Bancário',
            'num_branches': 5,
            'departments_per_branch': [
                {
                    'name': 'Atendimento ao Cliente',
                    'sector': 'Serviços Bancários',
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
                            ],
                            'tags': ['Depósito']
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
                            ],
                            'tags': ['Levantamento']
                        }
                    ]
                },
                {
                    'name': 'Crédito',
                    'sector': 'Empréstimos',
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
                            ],
                            'tags': ['Crédito']
                        }
                    ]
                }
            ]
        },
        {
            'name': 'Escola Primária Ngola Kiluanje',
            'description': 'Escola primária em Viana',
            'sector': 'Educação',
            'category_name': 'Educação',
            'num_branches': 2,
            'departments_per_branch': [
                {
                    'name': 'Secretaria Escolar',
                    'sector': 'Administração Escolar',
                    'queues': [
                        {
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
                            ],
                            'tags': ['Matrícula']
                        },
                        {
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
                            ],
                            'tags': ['Declaração']
                        }
                    ]
                }
            ]
        },
        {
            'name': 'Cartório Notarial de Luanda',
            'description': 'Serviços notariais em Luanda',
            'sector': 'Serviços Públicos',
            'category_name': 'Serviços Públicos',
            'num_branches': 3,
            'departments_per_branch': [
                {
                    'name': 'Atendimento Notarial',
                    'sector': 'Serviços Notariais',
                    'queues': [
                        {
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
                            ],
                            'tags': ['Autenticação']
                        }
                    ]
                }
            ]
        }
    ]

    @staticmethod
    def initialize_data(app):
        """Inicializa os dados no banco de dados."""
        with app.app_context():
            logger.info("Iniciando população de dados iniciais")
            try:
                with db.session.no_autoflush:
                    # 1. Criar categorias de serviço
                    category_map = DataInitializer.create_service_categories()
                    logger.info(f"Criadas {len(category_map)} categorias de serviço")

                    # 2. Criar instituições, filiais, departamentos e filas
                    DataInitializer.create_institutions(category_map)
                    logger.info("Instituições, filiais, departamentos e filas criados com sucesso")

                    # 3. Commit final
                    db.session.commit()
                    logger.info("Dados iniciais populados com sucesso")

                    # 4. Enviar notificação via WebSocket (opcional)
                    if socketio:
                        emit('data_initialized', {'message': 'Dados iniciais populados com sucesso'}, namespace='/')
            except SQLAlchemyError as e:
                db.session.rollback()
                logger.error(f"Erro ao popular dados iniciais: {str(e)}")
                raise
            except Exception as e:
                db.session.rollback()
                logger.error(f"Erro inesperado ao popular dados iniciais: {str(e)}")
                raise

    @staticmethod
    def create_service_categories():
        """Cria categorias de serviço e retorna um mapa de nomes para IDs."""
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
            existing = ServiceCategory.query.filter_by(name=cat['name']).first()
            if existing:
                logger.debug(f"Categoria {cat['name']} já existe, usando ID existente: {existing.id}")
                category_map[cat['name']] = existing.id
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
            logger.debug(f"Criada categoria {cat['name']} com ID {category.id}")
        return category_map

    @staticmethod
    def create_institutions(category_map):
        """Cria instituições, filiais, departamentos e filas."""
        for inst_data in DataInitializer.INSTITUTIONS_DATA:
            # Criar instituição
            existing_inst = Institution.query.filter_by(name=inst_data['name']).first()
            if existing_inst:
                logger.debug(f"Instituição {inst_data['name']} já existe, pulando")
                continue
            institution = Institution(
                id=str(uuid.uuid4()),
                name=inst_data['name'],
                description=inst_data['description'],
                sector=inst_data['sector'],
                category_id=category_map[inst_data['category_name']]
            )
            db.session.add(institution)
            db.session.flush()
            logger.debug(f"Criada instituição {inst_data['name']} com ID {institution.id}")

            # Criar filiais
            for i in range(inst_data['num_branches']):
                neighborhood = DataInitializer.NEIGHBORHOODS[i % len(DataInitializer.NEIGHBORHOODS)]
                branch = Branch(
                    id=str(uuid.uuid4()),
                    institution_id=institution.id,
                    name=f"{inst_data['name']} - Filial {neighborhood}",
                    neighborhood=neighborhood,
                    location=f"Rua Principal, {neighborhood}, Luanda",
                    latitude=-8.8147 + (i * 0.01),  # Coordenadas fictícias para teste
                    longitude=13.2302 + (i * 0.01)
                )
                db.session.add(branch)
                db.session.flush()
                logger.debug(f"Criada filial {branch.name} com ID {branch.id}")

                # Criar departamentos
                for dept_data in inst_data['departments_per_branch']:
                    department = Department(
                        id=str(uuid.uuid4()),
                        branch_id=branch.id,
                        name=dept_data['name'],
                        sector=dept_data['sector']
                    )
                    db.session.add(department)
                    db.session.flush()
                    logger.debug(f"Criado departamento {dept_data['name']} com ID {department.id}")

                    # Criar filas
                    for queue_data in dept_data['queues']:
                        existing_queue = Queue.query.filter_by(
                            department_id=department.id, service=queue_data['service']
                        ).first()
                        if existing_queue:
                            logger.debug(f"Fila {queue_data['service']} já existe para departamento {department.id}, pulando")
                            continue
                        queue = Queue(
                            id=str(uuid.uuid4()),  # Novo UUID para cada fila
                            department_id=department.id,
                            service=queue_data['service'],
                            category_id=category_map[inst_data['category_name']],
                            prefix=queue_data['prefix'],
                            end_time=queue_data['end_time'],
                            open_time=queue_data['open_time'],
                            daily_limit=queue_data['daily_limit'],
                            active_tickets=0,
                            current_ticket=0,
                            avg_wait_time=queue_data['avg_wait_time'],
                            num_counters=queue_data['num_counters'],
                            last_counter=0
                        )
                        db.session.add(queue)
                        db.session.flush()
                        logger.debug(f"Criada fila {queue_data['service']} com ID {queue.id}")

                        # Criar tags
                        for tag_name in queue_data['tags']:
                            tag = ServiceTag(
                                id=str(uuid.uuid4()),
                                queue_id=queue.id,
                                tag=tag_name
                            )
                            db.session.add(tag)
                            logger.debug(f"Criada tag {tag_name} para fila {queue.id}")

                        # Criar horários
                        for schedule_data in queue_data['schedules']:
                            schedule = QueueSchedule(
                                id=str(uuid.uuid4()),
                                queue_id=queue.id,
                                weekday=schedule_data['weekday'],
                                open_time=schedule_data.get('open_time'),
                                end_time=schedule_data.get('end_time'),
                                is_closed=schedule_data.get('is_closed', False)
                            )
                            db.session.add(schedule)
                            logger.debug(f"Criado horário para fila {queue.id} no dia {schedule_data['weekday']}")

    @staticmethod
    def create_users_and_tickets():
        """Cria usuários e tickets para testes (opcional)."""
        # Implementar se necessário para criar ~900.000 tickets
        logger.info("Criação de usuários e tickets não implementada neste exemplo")
        pass
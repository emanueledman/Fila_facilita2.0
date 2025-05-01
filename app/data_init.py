import uuid
from datetime import datetime, time, timedelta
import bcrypt
from app import db
from app.models import (
    InstitutionType, Institution, Branch, BranchSchedule, Department, Queue, QueueSchedule,
    InstitutionService, ServiceCategory, ServiceTag, User, UserRole, Ticket, UserPreference,
    UserBehavior, UserLocationFallback, NotificationLog, AuditLog, Weekday
)

def populate_initial_data(app):
    """
    Popula o banco de dados com dados iniciais para testes, incluindo 5 instituições (Banco BAI, Banco BFA, Banco BIC,
    Hospital Josina Machel, SIAC), cada uma com 3 filiais em Luanda. Cada filial tem departamentos com 2 filas
    (1 24/7 e 1 com horário comercial). Cada fila tem 50 tickets. Inclui usuários, preferências, comportamentos,
    localizações alternativas, logs de auditoria e notificações. Mantém idempotência, logs em português, e compatibilidade
    com models.py atualizado (incluindo is_client e is_favorite). Suporta modelos de ML com dados suficientes para treinamento.
    """
    with app.app_context():
        try:
            # Desativar autoflush para evitar problemas durante a inserção
            with db.session.no_autoflush:
                app.logger.info("Iniciando população de dados iniciais...")

                # --------------------------------------
                # Função auxiliar para verificar existência
                # --------------------------------------
                def exists(model, **kwargs):
                    return model.query.filter_by(**kwargs).first() is not None

                # --------------------------------------
                # Função auxiliar para hashear senhas
                # --------------------------------------
                def hash_password(password):
                    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

                # --------------------------------------
                # Função auxiliar para normalizar strings
                # --------------------------------------
                from unidecode import unidecode
                def normalize_string(s):
                    return unidecode(s.lower().replace(' ', '_'))[:50]

                # --------------------------------------
                # Criar Tipos de Instituição
                # --------------------------------------
                def create_institution_types():
                    types = [
                        {"name": "Bancário", "description": "Serviços financeiros e bancários"},
                        {"name": "Saúde", "description": "Serviços de saúde e atendimento médico"},
                        {"name": "Administrativo", "description": "Serviços administrativos e atendimento ao cidadão"}
                    ]
                    type_map = {}
                    for inst_type in types:
                        if not exists(InstitutionType, name=inst_type["name"]):
                            it = InstitutionType(
                                id=str(uuid.uuid4()),
                                name=inst_type["name"],
                                description=inst_type["description"]
                            )
                            db.session.add(it)
                            db.session.flush()
                            app.logger.debug(f"Tipo de instituição criado: {inst_type['name']}")
                        type_map[inst_type["name"]] = InstitutionType.query.filter_by(name=inst_type["name"]).first().id
                    app.logger.info("Tipos de instituição criados ou recuperados com sucesso.")
                    return type_map

                institution_type_map = create_institution_types()

                # --------------------------------------
                # Criar Categorias de Serviço
                # --------------------------------------
                def create_service_categories():
                    categories = [
                        {"name": "Bancário", "description": "Serviços financeiros e bancários", "parent_id": None},
                        {"name": "Conta", "description": "Abertura e gestão de contas bancárias", "parent_id": None},
                        {"name": "Empréstimo", "description": "Solicitação e gestão de empréstimos", "parent_id": None},
                        {"name": "Investimento", "description": "Serviços de investimento financeiro", "parent_id": None},
                        {"name": "Saúde", "description": "Serviços de saúde e atendimento médico", "parent_id": None},
                        {"name": "Consulta Médica", "description": "Consultas gerais e especializadas", "parent_id": None},
                        {"name": "Exames", "description": "Exames laboratoriais e diagnósticos", "parent_id": None},
                        {"name": "Administrativo", "description": "Serviços administrativos e atendimento ao cidadão", "parent_id": None},
                        {"name": "Documentos", "description": "Emissão e renovação de documentos", "parent_id": None}
                    ]
                    category_map = {}
                    for cat in categories:
                        if not exists(ServiceCategory, name=cat["name"]):
                            sc = ServiceCategory(
                                id=str(uuid.uuid4()),
                                name=cat["name"],
                                description=cat["description"],
                                parent_id=cat["parent_id"]
                            )
                            db.session.add(sc)
                            db.session.flush()
                            app.logger.debug(f"Categoria de serviço criada: {cat['name']}")
                        category_map[cat["name"]] = ServiceCategory.query.filter_by(name=cat["name"]).first().id
                    # Definir hierarquia
                    for cat_name, parent_name in [
                        ("Conta", "Bancário"), ("Empréstimo", "Bancário"), ("Investimento", "Bancário"),
                        ("Consulta Médica", "Saúde"), ("Exames", "Saúde"),
                        ("Documentos", "Administrativo")
                    ]:
                        cat = ServiceCategory.query.filter_by(name=cat_name).first()
                        if cat and not cat.parent_id:
                            cat.parent_id = category_map[parent_name]
                            db.session.flush()
                    app.logger.info("Categorias de serviço criadas ou recuperadas com sucesso.")
                    return category_map

                category_map = create_service_categories()

                # --------------------------------------
                # Bairros de Luanda
                # --------------------------------------
                neighborhoods = [
                    {"name": "Ingombota", "latitude": -8.8167, "longitude": 13.2332},
                    {"name": "Maianga", "latitude": -8.8147, "longitude": 13.2302},
                    {"name": "Talatona", "latitude": -8.9167, "longitude": 13.1833},
                    {"name": "Kilamba", "latitude": -8.9333, "longitude": 13.2667},
                    {"name": "Cazenga", "latitude": -8.8500, "longitude": 13.2833},
                    {"name": "Viana", "latitude": -8.9035, "longitude": 13.3741},
                    {"name": "Rangel", "latitude": -8.8300, "longitude": 13.2500}
                ]

                # --------------------------------------
                # Dados de Instituições
                # --------------------------------------
                institutions_data = [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Banco BAI",
                        "description": "Serviços bancários em Luanda",
                        "institution_type_id": institution_type_map["Bancário"],
                        "services": [
                            {"name": "Atendimento Bancário", "category_id": category_map["Conta"], "description": "Depósitos e saques"},
                            {"name": "Empréstimos", "category_id": category_map["Empréstimo"], "description": "Empréstimos pessoais"}
                        ],
                        "branches": [
                            {
                                "name": "Agência Central",
                                "location": "Rua Rainha Ginga, Ingombota, Luanda",
                                "neighborhood": "Ingombota",
                                "latitude": -8.8170,
                                "longitude": 13.2350,
                                "departments": [
                                    {
                                        "name": "Atendimento ao Cliente",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento Bancário",
                                                "prefix": "AB",
                                                "daily_limit": 100,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Bancário", "Empréstimo"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Talatona",
                                "location": "Via Expressa, Talatona, Luanda",
                                "neighborhood": "Talatona",
                                "latitude": -8.9180,
                                "longitude": 13.1840,
                                "departments": [
                                    {
                                        "name": "Atendimento ao Cliente",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento Bancário",
                                                "prefix": "AB",
                                                "daily_limit": 100,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Bancário", "Empréstimo"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Viana",
                                "location": "Rua Principal, Viana, Luanda",
                                "neighborhood": "Viana",
                                "latitude": -8.9040,
                                "longitude": 13.3750,
                                "departments": [
                                    {
                                        "name": "Atendimento ao Cliente",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento Bancário",
                                                "prefix": "AB",
                                                "daily_limit": 100,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Bancário", "Empréstimo"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Banco BFA",
                        "description": "Serviços bancários em Luanda",
                        "institution_type_id": institution_type_map["Bancário"],
                        "services": [
                            {"name": "Atendimento Bancário", "category_id": category_map["Conta"], "description": "Gestão de contas"},
                            {"name": "Investimentos", "category_id": category_map["Investimento"], "description": "Investimentos financeiros"}
                        ],
                        "branches": [
                            {
                                "name": "Agência Maianga",
                                "location": "Rua Joaquim Kapango, Maianga, Luanda",
                                "neighborhood": "Maianga",
                                "latitude": -8.8150,
                                "longitude": 13.2310,
                                "departments": [
                                    {
                                        "name": "Atendimento ao Cliente",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento Bancário",
                                                "prefix": "AB",
                                                "daily_limit": 100,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Bancário", "Investimento"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Kilamba",
                                "location": "Avenida do Kilamba, Kilamba, Luanda",
                                "neighborhood": "Kilamba",
                                "latitude": -8.9340,
                                "longitude": 13.2670,
                                "departments": [
                                    {
                                        "name": "Atendimento ao Cliente",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento Bancário",
                                                "prefix": "AB",
                                                "daily_limit": 100,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Bancário", "Investimento"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Cazenga",
                                "location": "Avenida dos Combatentes, Cazenga, Luanda",
                                "neighborhood": "Cazenga",
                                "latitude": -8.8510,
                                "longitude": 13.2840,
                                "departments": [
                                    {
                                        "name": "Atendimento ao Cliente",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento Bancário",
                                                "prefix": "AB",
                                                "daily_limit": 100,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Bancário", "Investimento"]
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
                        "institution_type_id": institution_type_map["Bancário"],
                        "services": [
                            {"name": "Atendimento Bancário", "category_id": category_map["Conta"], "description": "Gestão de contas"},
                            {"name": "Empréstimos", "category_id": category_map["Empréstimo"], "description": "Empréstimos empresariais"}
                        ],
                        "branches": [
                            {
                                "name": "Agência Rangel",
                                "location": "Rua do Rangel, Rangel, Luanda",
                                "neighborhood": "Rangel",
                                "latitude": -8.8300,
                                "longitude": 13.2500,
                                "departments": [
                                    {
                                        "name": "Atendimento ao Cliente",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento Bancário",
                                                "prefix": "AB",
                                                "daily_limit": 100,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Bancário", "Empréstimo"]
                                            }
                                        ]
                                    }
                                ]
                            },
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
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento Bancário",
                                                "prefix": "AB",
                                                "daily_limit": 100,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Bancário", "Empréstimo"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Talatona",
                                "location": "Rua Principal, Talatona, Luanda",
                                "neighborhood": "Talatona",
                                "latitude": -8.9167,
                                "longitude": 13.1833,
                                "departments": [
                                    {
                                        "name": "Atendimento ao Cliente",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento Bancário",
                                                "prefix": "AB",
                                                "daily_limit": 100,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 30), "end_time": time(15, 30)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Bancário", "Empréstimo"]
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
                        "institution_type_id": institution_type_map["Saúde"],
                        "services": [
                            {"name": "Consulta Geral", "category_id": category_map["Consulta Médica"], "description": "Consultas médicas gerais"},
                            {"name": "Exames Laboratoriais", "category_id": category_map["Exames"], "description": "Exames de diagnóstico"}
                        ],
                        "branches": [
                            {
                                "name": "Unidade Central",
                                "location": "Avenida Ho Chi Minh, Maianga, Luanda",
                                "neighborhood": "Maianga",
                                "latitude": -8.8147,
                                "longitude": 13.2302,
                                "departments": [
                                    {
                                        "name": "Clínica Geral",
                                        "sector": "Saúde",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Consulta Geral",
                                                "prefix": "CG",
                                                "daily_limit": 80,
                                                "num_counters": 4,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.SATURDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.SUNDAY, "open_time": time(0, 0), "end_time": time(23, 59)}
                                                ],
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Laboratoriais",
                                                "prefix": "EL",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Saúde", "Exames"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Kilamba",
                                "location": "Rua Principal, Kilamba, Luanda",
                                "neighborhood": "Kilamba",
                                "latitude": -8.9333,
                                "longitude": 13.2667,
                                "departments": [
                                    {
                                        "name": "Clínica Geral",
                                        "sector": "Saúde",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Consulta Geral",
                                                "prefix": "CG",
                                                "daily_limit": 80,
                                                "num_counters": 4,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.SATURDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.SUNDAY, "open_time": time(0, 0), "end_time": time(23, 59)}
                                                ],
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Laboratoriais",
                                                "prefix": "EL",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Saúde", "Exames"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Cazenga",
                                "location": "Rua dos Combatentes, Cazenga, Luanda",
                                "neighborhood": "Cazenga",
                                "latitude": -8.8500,
                                "longitude": 13.2833,
                                "departments": [
                                    {
                                        "name": "Clínica Geral",
                                        "sector": "Saúde",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Consulta Geral",
                                                "prefix": "CG",
                                                "daily_limit": 80,
                                                "num_counters": 4,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.SATURDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.SUNDAY, "open_time": time(0, 0), "end_time": time(23, 59)}
                                                ],
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Laboratoriais",
                                                "prefix": "EL",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Saúde", "Exames"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "name": "SIAC",
                        "description": "Serviços administrativos em Luanda",
                        "institution_type_id": institution_type_map["Administrativo"],
                        "services": [
                            {"name": "Emissão de BI", "category_id": category_map["Documentos"], "description": "Emissão de bilhete de identidade"},
                            {"name": "Registo Civil", "category_id": category_map["Documentos"], "description": "Registos civis"}
                        ],
                        "branches": [
                            {
                                "name": "SIAC Talatona",
                                "location": "Rua Principal, Talatona, Luanda",
                                "neighborhood": "Talatona",
                                "latitude": -8.9167,
                                "longitude": 13.1833,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de BI",
                                                "prefix": "BI",
                                                "daily_limit": 120,
                                                "num_counters": 6,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.SATURDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.SUNDAY, "open_time": time(0, 0), "end_time": time(23, 59)}
                                                ],
                                                "tags": ["Administrativo", "Documentos", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "SIAC Viana",
                                "location": "Rua Principal, Viana, Luanda",
                                "neighborhood": "Viana",
                                "latitude": -8.9035,
                                "longitude": 13.3741,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de BI",
                                                "prefix": "BI",
                                                "daily_limit": 120,
                                                "num_counters": 6,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.SATURDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.SUNDAY, "open_time": time(0, 0), "end_time": time(23, 59)}
                                                ],
                                                "tags": ["Administrativo", "Documentos", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "SIAC Rangel",
                                "location": "Rua do Rangel, Rangel, Luanda",
                                "neighborhood": "Rangel",
                                "latitude": -8.8300,
                                "longitude": 13.2500,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de BI",
                                                "prefix": "BI",
                                                "daily_limit": 120,
                                                "num_counters": 6,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.SATURDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                                    {"weekday": Weekday.SUNDAY, "open_time": time(0, 0), "end_time": time(23, 59)}
                                                ],
                                                "tags": ["Administrativo", "Documentos", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "schedules": [
                                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                                ],
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]

                # --------------------------------------
                # Funções Auxiliares para Criação de Entidades
                # --------------------------------------
                def create_institution_services(institution_id, services):
                    for srv in services:
                        if not exists(InstitutionService, institution_id=institution_id, name=srv["name"]):
                            s = InstitutionService(
                                id=str(uuid.uuid4()),
                                institution_id=institution_id,
                                name=srv["name"],
                                category_id=srv["category_id"],
                                description=srv["description"]
                            )
                            db.session.add(s)
                            app.logger.debug(f"Serviço criado: {srv['name']} para instituição {institution_id}")
                    db.session.flush()

                def create_branch_schedules(branch_id):
                    weekdays = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY]
                    for day in weekdays:
                        if not exists(BranchSchedule, branch_id=branch_id, weekday=day):
                            bs = BranchSchedule(
                                id=str(uuid.uuid4()),
                                branch_id=branch_id,
                                weekday=day,
                                open_time=time(8, 0),
                                end_time=time(16, 0),
                                is_closed=False
                            )
                            db.session.add(bs)
                            app.logger.debug(f"Horário de filial criado: {day} para filial {branch_id}")
                    db.session.flush()

                def create_queue(department_id, queue_data, service_id):
                    if not exists(Queue, id=queue_data["id"]):
                        q = Queue(
                            id=queue_data["id"],
                            department_id=department_id,
                            service_id=service_id,
                            prefix=queue_data["prefix"],
                            daily_limit=queue_data["daily_limit"],
                            active_tickets=0,
                            current_ticket=0,
                            avg_wait_time=5.0,
                            last_service_time=2.0,
                            num_counters=queue_data["num_counters"],
                            last_counter=0
                        )
                        db.session.add(q)
                        db.session.flush()
                        for schedule in queue_data["schedules"]:
                            if not exists(QueueSchedule, queue_id=q.id, weekday=schedule["weekday"]):
                                qs = QueueSchedule(
                                    id=str(uuid.uuid4()),
                                    queue_id=q.id,
                                    weekday=schedule["weekday"],
                                    open_time=schedule.get("open_time"),
                                    end_time=schedule.get("end_time"),
                                    is_closed=schedule.get("is_closed", False)
                                )
                                db.session.add(qs)
                                app.logger.debug(f"Horário de fila criado: {schedule['weekday']} para fila {q.id}")
                        for tag in queue_data["tags"]:
                            if not exists(ServiceTag, queue_id=q.id, tag=tag):
                                st = ServiceTag(
                                    id=str(uuid.uuid4()),
                                    queue_id=q.id,
                                    tag=tag
                                )
                                db.session.add(st)
                                app.logger.debug(f"Tag criada: {tag} para fila {q.id}")
                        return q
                    return Queue.query.filter_by(id=queue_data["id"]).first()

                def create_department(branch_id, dept_data):
                    if not exists(Department, branch_id=branch_id, name=dept_data["name"]):
                        d = Department(
                            id=str(uuid.uuid4()),
                            branch_id=branch_id,
                            name=dept_data["name"],
                            sector=dept_data["sector"]
                        )
                        db.session.add(d)
                        db.session.flush()
                        app.logger.debug(f"Departamento criado: {dept_data['name']} para filial {branch_id}")
                        for queue_data in dept_data["queues"]:
                            service = InstitutionService.query.filter_by(institution_id=Branch.query.get(branch_id).institution_id, name=queue_data["service_name"]).first()
                            if service:
                                create_queue(d.id, queue_data, service.id)
                            else:
                                app.logger.warning(f"Serviço {queue_data['service_name']} não encontrado para filial {branch_id}")
                        return d
                    d = Department.query.filter_by(branch_id=branch_id, name=dept_data["name"]).first()
                    for queue_data in dept_data["queues"]:
                        service = InstitutionService.query.filter_by(institution_id=Branch.query.get(branch_id).institution_id, name=queue_data["service_name"]).first()
                        if service:
                            create_queue(d.id, queue_data, service.id)
                        else:
                            app.logger.warning(f"Serviço {queue_data['service_name']} não encontrado para filial {branch_id}")
                    return d

                def create_branch(institution_id, branch_data):
                    if not exists(Branch, institution_id=institution_id, name=branch_data["name"]):
                        b = Branch(
                            id=str(uuid.uuid4()),
                            institution_id=institution_id,
                            name=branch_data["name"],
                            location=branch_data["location"],
                            neighborhood=branch_data["neighborhood"],
                            latitude=branch_data["latitude"],
                            longitude=branch_data["longitude"]
                        )
                        db.session.add(b)
                        db.session.flush()
                        app.logger.debug(f"Filial criada: {branch_data['name']} para instituição {institution_id}")
                        create_branch_schedules(b.id)
                        for dept_data in branch_data["departments"]:
                            create_department(b.id, dept_data)
                        return b
                    b = Branch.query.filter_by(institution_id=institution_id, name=branch_data["name"]).first()
                    for dept_data in branch_data["departments"]:
                        create_department(b.id, dept_data)
                    return b

                def create_institution(inst_data):
                    if not exists(Institution, name=inst_data["name"]):
                        i = Institution(
                            id=inst_data["id"],
                            name=inst_data["name"],
                            description=inst_data["description"],
                            institution_type_id=inst_data["institution_type_id"]
                        )
                        db.session.add(i)
                        db.session.flush()
                        app.logger.debug(f"Instituição criada: {inst_data['name']}")
                        create_institution_services(i.id, inst_data["services"])
                        for branch_data in inst_data["branches"]:
                            create_branch(i.id, branch_data)
                        return i
                    i = Institution.query.filter_by(name=inst_data["name"]).first()
                    create_institution_services(i.id, inst_data["services"])
                    for branch_data in inst_data["branches"]:
                        create_branch(i.id, branch_data)
                    return i

                # Criar instituições
                for inst_data in institutions_data:
                    create_institution(inst_data)
                app.logger.info("Instituições, serviços, filiais, departamentos e filas criados ou atualizados com sucesso.")

                # --------------------------------------
                # Criar Usuários
                # --------------------------------------
                def create_users():
                    users = []
                    # System Admin
                    if not exists(User, email="sysadmin@queue.com"):
                        admin = User(
                            id=str(uuid.uuid4()),
                            email="sysadmin@queue.com",
                            name="Sistema Admin",
                            password_hash=hash_password("sysadmin123"),
                            user_role=UserRole.SYSTEM_ADMIN,
                            created_at=datetime.utcnow(),
                            active=True
                        )
                        db.session.add(admin)
                        users.append(admin)
                        app.logger.debug("Usuário criado: sysadmin@queue.com")

                    # Institution Admins
                    for inst in Institution.query.all():
                        email = f"admin_{normalize_string(inst.name)}@queue.com"
                        if not exists(User, email=email):
                            admin = User(
                                id=str(uuid.uuid4()),
                                email=email,
                                name=f"Admin {inst.name}",
                                password_hash=hash_password("admin123"),
                                user_role=UserRole.INSTITUTION_ADMIN,
                                institution_id=inst.id,
                                created_at=datetime.utcnow(),
                                active=True
                            )
                            db.session.add(admin)
                            users.append(admin)
                            app.logger.debug(f"Usuário criado: {email}")

                    # Branch Admins
                    for branch in Branch.query.all():
                        institution = Institution.query.get(branch.institution_id)
                        email = f"branch_admin_{normalize_string(institution.name)}_{normalize_string(branch.name)}@queue.com"
                        if not exists(User, email=email):
                            admin = User(
                                id=str(uuid.uuid4()),
                                email=email,
                                name=f"Gerente {branch.name}",
                                password_hash=hash_password("branch123"),
                                user_role=UserRole.BRANCH_ADMIN,
                                branch_id=branch.id,
                                institution_id=branch.institution_id,
                                created_at=datetime.utcnow(),
                                active=True
                            )
                            db.session.add(admin)
                            users.append(admin)
                            app.logger.debug(f"Usuário criado: {email}")

                    # Attendants
                    for dept in Department.query.all():
                        branch = Branch.query.get(dept.branch_id)
                        institution = Institution.query.get(branch.institution_id)
                        email = f"attendant_{normalize_string(dept.name)}_{normalize_string(branch.name)}_{normalize_string(institution.name)}@queue.com"
                        if not exists(User, email=email):
                            attendant = User(
                                id=str(uuid.uuid4()),
                                email=email,
                                name=f"Atendente {dept.name}",
                                password_hash=hash_password("attendant123"),
                                user_role=UserRole.ATTENDANT,
                                branch_id=dept.branch_id,
                                institution_id=dept.branch.institution_id,
                                created_at=datetime.utcnow(),
                                active=True
                            )
                            db.session.add(attendant)
                            users.append(attendant)
                            app.logger.debug(f"Usuário criado: {email}")

                    # Regular Users
                    user_count = User.query.filter_by(user_role=UserRole.USER).count()
                    for i in range(15 - user_count):
                        email = f"user_{i}@queue.com"
                        if not exists(User, email=email):
                            user = User(
                                id=str(uuid.uuid4()),
                                email=email,
                                name=f"Usuário {i+1}",
                                password_hash=hash_password("user123"),
                                user_role=UserRole.USER,
                                created_at=datetime.utcnow(),
                                active=True
                            )
                            db.session.add(user)
                            users.append(user)
                            app.logger.debug(f"Usuário criado: {email}")

                    db.session.flush()
                    app.logger.info("Usuários criados com sucesso.")
                    return users

                users = create_users()

                # --------------------------------------
                # Criar Preferências de Usuário
                # --------------------------------------
                def create_user_preferences():
                    now = datetime.utcnow()
                    user_list = User.query.filter_by(user_role=UserRole.USER).limit(15).all()
                    institutions = Institution.query.all()
                    for i, user in enumerate(user_list):
                        for j in range(3):
                            inst = institutions[(i + j) % len(institutions)]
                            neighborhood = neighborhoods[(i + j) % len(neighborhoods)]["name"]
                            is_client = (i + j) % 2 == 0
                            is_favorite = is_client and (i + j) % 3 == 0
                            if not exists(UserPreference, user_id=user.id, institution_id=inst.id):
                                pref = UserPreference(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    institution_id=inst.id,
                                    institution_type_id=inst.institution_type_id,
                                    neighborhood=neighborhood,
                                    preference_score=50 if is_client else 0,
                                    is_client=is_client,
                                    is_favorite=is_favorite,
                                    visit_count=5 if is_client else 0,
                                    last_visited=now if is_client else None,
                                    created_at=now,
                                    updated_at=now
                                )
                                db.session.add(pref)
                                app.logger.debug(f"Preferência criada para usuário {user.id} e instituição {inst.id}")
                    db.session.flush()
                    app.logger.info("Preferências de usuário criadas com sucesso.")

                create_user_preferences()

                # --------------------------------------
                # Criar Tickets
                # --------------------------------------
                def create_tickets():
                    now = datetime.utcnow()
                    for queue in Queue.query.all():
                        existing_tickets = Ticket.query.filter_by(queue_id=queue.id).count()
                        if existing_tickets >= 50:
                            continue
                        branch = Branch.query.join(Department).filter(Department.id == queue.department_id).first()
                        branch_code = branch.id[-4:]
                        for i in range(50 - existing_tickets):
                            ticket_number = (Ticket.query.filter_by(queue_id=queue.id).count() or 0) + i + 1
                            qr_code = f"{queue.prefix}{ticket_number:03d}-{queue.id[:8]}-{branch_code}"
                            if Ticket.query.filter_by(qr_code=qr_code).first():
                                qr_code = f"{queue.prefix}{ticket_number:03d}-{queue.id[:8]}-{branch_code}-{int(now.timestamp())}"
                            status = "Atendido" if i % 2 == 0 else "Pendente"
                            issued_at = now - timedelta(days=i % 14, hours=i % 24)
                            ticket = Ticket(
                                id=str(uuid.uuid4()),
                                queue_id=queue.id,
                                user_id=User.query.filter_by(user_role=UserRole.USER).offset(i % 15).first().id,
                                ticket_number=ticket_number,
                                qr_code=qr_code,
                                priority=1 if i % 5 == 0 else 0,
                                is_physical=False,
                                status=status,
                                issued_at=issued_at,
                                expires_at=issued_at + timedelta(days=1),
                                attended_at=issued_at + timedelta(minutes=10) if status == "Atendido" else None,
                                counter=(i % queue.num_counters) + 1 if status == "Atendido" else None,
                                service_time=300.0 + (i % 5) * 60 if status == "Atendido" else None,
                                trade_available=False
                            )
                            db.session.add(ticket)
                            app.logger.debug(f"Ticket criado: {qr_code} para fila {queue.id}")
                        queue.active_tickets = Ticket.query.filter_by(queue_id=queue.id, status="Pendente").count()
                    db.session.flush()
                    app.logger.info("Tickets criados com sucesso para todas as filas.")

                create_tickets()

                # --------------------------------------
                # Criar Comportamentos de Usuário
                # --------------------------------------
                def create_user_behaviors():
                    now = datetime.utcnow()
                    user_list = User.query.filter_by(user_role=UserRole.USER).limit(15).all()
                    for user in user_list:
                        for inst in Institution.query.limit(3).all():
                            service = InstitutionService.query.filter_by(institution_id=inst.id).first()
                            branch = Branch.query.filter_by(institution_id=inst.id).first()
                            if not exists(UserBehavior, user_id=user.id, institution_id=inst.id, action="issued_ticket", timestamp=now - timedelta(days=1)):
                                ub = UserBehavior(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    institution_id=inst.id,
                                    service_id=service.id if service else None,
                                    branch_id=branch.id,
                                    action="issued_ticket",
                                    timestamp=now - timedelta(days=1)
                                )
                                db.session.add(ub)
                                app.logger.debug(f"Comportamento criado para usuário {user.id} e instituição {inst.id}")
                    db.session.flush()
                    app.logger.info("Comportamentos de usuário criados com sucesso.")

                create_user_behaviors()

                # --------------------------------------
                # Criar Localizações Alternativas
                # --------------------------------------
                def create_user_location_fallbacks():
                    user_list = User.query.filter_by(user_role=UserRole.USER).limit(15).all()
                    for i, user in enumerate(user_list):
                        neighborhood = neighborhoods[i % len(neighborhoods)]["name"]
                        if not exists(UserLocationFallback, user_id=user.id):
                            ulf = UserLocationFallback(
                                id=str(uuid.uuid4()),
                                user_id=user.id,
                                neighborhood=neighborhood,
                                address=f"Rua Principal, {neighborhood}",
                                updated_at=datetime.utcnow()
                            )
                            db.session.add(ulf)
                            app.logger.debug(f"Localização alternativa criada para usuário {user.id}")
                    db.session.flush()
                    app.logger.info("Localizações alternativas criadas com sucesso.")

                create_user_location_fallbacks()

                # --------------------------------------
                # Criar Logs de Auditoria
                # --------------------------------------
                def create_audit_logs():
                    now = datetime.utcnow()
                    users = User.query.limit(20).all()
                    actions = ["USER_LOGIN", "TICKET_CREATED", "TICKET_UPDATED", "QUEUE_MODIFIED", "USER_PROFILE_UPDATED"]
                    for i in range(100):
                        user = users[i % len(users)]
                        action = actions[i % len(actions)]
                        timestamp = now - timedelta(days=i % 30, hours=i % 24)
                        if not exists(AuditLog, user_id=user.id, action=action, timestamp=timestamp):
                            al = AuditLog(
                                id=str(uuid.uuid4()),
                                user_id=user.id,
                                action=action,
                                resource_type=action.split("_")[0].lower(),
                                resource_id=str(uuid.uuid4()),
                                details=f"{action} por {user.email}",
                                                                timestamp=timestamp
                            )
                            db.session.add(al)
                            app.logger.debug(f"Log de auditoria criado: {action} para usuário {user.id}")
                    db.session.flush()
                    app.logger.info("Logs de auditoria criados com sucesso.")

                create_audit_logs()

                # --------------------------------------
                # Criar Logs de Notificação
                # --------------------------------------
                def create_notification_logs():
                    now = datetime.utcnow()
                    users = User.query.filter_by(user_role=UserRole.USER).limit(15).all()
                    for i, user in enumerate(users):
                        ticket = Ticket.query.filter_by(user_id=user.id).first()
                        if ticket:
                            message = f"Ticket {ticket.qr_code} emitido com sucesso."
                            if not exists(NotificationLog, user_id=user.id, message=message):
                                nl = NotificationLog(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    message=message,
                                    #channel="email",
                                    sent_at=now - timedelta(days=i % 7),
                                    status="sent"
                                )
                                db.session.add(nl)
                                app.logger.debug(f"Log de notificação criado para usuário {user.id}")
                    db.session.flush()
                    app.logger.info("Logs de notificação criados com sucesso.")

                create_notification_logs()

                # --------------------------------------
                # Commit Final
                # --------------------------------------
                db.session.commit()
                app.logger.info("População de dados iniciais concluída com sucesso.")

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro durante a população de dados: {str(e)}")
            raise

    return {"message": "População de dados concluída com sucesso."}
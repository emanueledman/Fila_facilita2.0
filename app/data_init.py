import uuid
from datetime import datetime, time, timedelta
import bcrypt
from app import db
from app.models import (
    InstitutionType, Institution, Branch, BranchSchedule, Department, Queue,
    InstitutionService, ServiceCategory, ServiceTag, User, UserRole, Ticket, UserPreference,
    UserBehavior, UserLocationFallback, NotificationLog, AuditLog, Weekday
)

def populate_initial_data(app):
    """
    Popula o banco de dados com dados iniciais para testes, com foco na Conservatória dos Registos e no ramo de Saúde.
    Inclui 8 instituições (4 bancos: BAI, BFA, BIC, Keve; 2 saúde: Hospital Josina Machel, Clínica Sagrada Esperança;
    2 administrativos: SIAC, Conservatória dos Registos). Conservatória tem 6 filiais em diferentes bairros de Luanda
    (Ingombota, Cazenga, Talatona, Kilamba, Viana, Rangel) com 8 serviços cada para testes de serviços semelhantes e
    sugestões. Saúde tem 10 serviços (5 por instituição). Bancos e SIAC têm 3 filiais cada. Cada filial tem departamentos
    com 3 filas (1 24/7, 1 horário comercial, 1 horário intermediário). Cada fila tem 50 tickets. Inclui usuários,
    preferências, comportamentos, localizações alternativas, logs de auditoria e notificações. Adiciona um usuário de teste
    com UID nMSnRc8jpYQbnrxujg5JZcHzFKP2 e email edmannews5@gmail.com com histórico robusto para testes.
    Mantém idempotência, logs em português, e compatibilidade com models.py (incluindo is_client e is_favorite).
    Suporta testes e modelos de ML.
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
                        {"name": "Triagem", "description": "Triagem e atendimento inicial", "parent_id": None},
                        {"name": "Internamento", "description": "Serviços de internamento hospitalar", "parent_id": None},
                        {"name": "Cirurgia", "description": "Procedimentos cirúrgicos", "parent_id": None},
                        {"name": "Fisioterapia", "description": "Serviços de reabilitação física", "parent_id": None},
                        {"name": "Vacinação", "description": "Serviços de imunização", "parent_id": None},
                        {"name": "Odontologia", "description": "Serviços odontológicos", "parent_id": None},
                        {"name": "Administrativo", "description": "Serviços administrativos e atendimento ao cidadão", "parent_id": None},
                        {"name": "Documentos", "description": "Emissão e renovação de documentos", "parent_id": None},
                        {"name": "Registros", "description": "Registros civis e comerciais", "parent_id": None},
                        {"name": "Licenças", "description": "Renovação e emissão de licenças", "parent_id": None},
                        {"name": "Autenticação", "description": "Autenticação de documentos", "parent_id": None}
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
                        ("Consulta Médica", "Saúde"), ("Exames", "Saúde"), ("Triagem", "Saúde"),
                        ("Internamento", "Saúde"), ("Cirurgia", "Saúde"), ("Fisioterapia", "Saúde"),
                        ("Vacinação", "Saúde"), ("Odontologia", "Saúde"),
                        ("Documentos", "Administrativo"), ("Registros", "Administrativo"),
                        ("Licenças", "Administrativo"), ("Autenticação", "Administrativo")
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
                            {"name": "Empréstimos", "category_id": category_map["Empréstimo"], "description": "Empréstimos pessoais"},
                            {"name": "Investimentos", "category_id": category_map["Investimento"], "description": "Gestão de investimentos"}
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Empréstimo"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Investimento"]
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Empréstimo"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Investimento"]
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Empréstimo"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 80,
                                                "num_counters": 2,
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
                        "name": "Banco BFA",
                        "description": "Serviços bancários em Luanda",
                        "institution_type_id": institution_type_map["Bancário"],
                        "services": [
                            {"name": "Atendimento Bancário", "category_id": category_map["Conta"], "description": "Gestão de contas"},
                            {"name": "Empréstimos", "category_id": category_map["Empréstimo"], "description": "Empréstimos empresariais"},
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Empréstimo"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 80,
                                                "num_counters": 2,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Empréstimo"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 80,
                                                "num_counters": 2,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Empréstimo"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 80,
                                                "num_counters": 2,
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
                            {"name": "Empréstimos", "category_id": category_map["Empréstimo"], "description": "Empréstimos empresariais"},
                            {"name": "Investimentos", "category_id": category_map["Investimento"], "description": "Consultoria de investimentos"}
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Empréstimo"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Investimento"]
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Empréstimo"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Investimento"]
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Empréstimo"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 80,
                                                "num_counters": 2,
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
                        "name": "Banco Keve",
                        "description": "Serviços bancários em Luanda",
                        "institution_type_id": institution_type_map["Bancário"],
                        "services": [
                            {"name": "Atendimento Bancário", "category_id": category_map["Conta"], "description": "Gestão de contas"},
                            {"name": "Empréstimos", "category_id": category_map["Empréstimo"], "description": "Empréstimos pessoais e empresariais"},
                            {"name": "Investimentos", "category_id": category_map["Investimento"], "description": "Consultoria de investimentos"}
                        ],
                        "branches": [
                            {
                                "name": "Agência Ingombota",
                                "location": "Avenida Che Guevara, Ingombota, Luanda",
                                "neighborhood": "Ingombota",
                                "latitude": -8.8165,
                                "longitude": 13.2340,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Empréstimo"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Investimento"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Viana",
                                "location": "Rua Principal, Viana, Luanda",
                                "neighborhood": "Viana",
                                "latitude": -8.9035,
                                "longitude": 13.3741,
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
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Empréstimo"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Investimento"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Kilamba",
                                "location": "Rua Principal, Kilamba, Luanda",
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
                                                "service_name": "Atendimento Bancário",
                                                "prefix": "AB",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Empréstimos",
                                                "prefix": "EM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Empréstimo"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Investimentos",
                                                "prefix": "IN",
                                                "daily_limit": 80,
                                                "num_counters": 2,
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
                        "name": "Hospital Josina Machel",
                        "description": "Serviços de saúde públicos em Luanda",
                        "institution_type_id": institution_type_map["Saúde"],
                        "services": [
                            {"name": "Consulta Geral", "category_id": category_map["Consulta Médica"], "description": "Consultas médicas gerais"},
                            {"name": "Exames Laboratoriais", "category_id": category_map["Exames"], "description": "Exames de diagnóstico"},
                            {"name": "Triagem", "category_id": category_map["Triagem"], "description": "Atendimento inicial e triagem"},
                            {"name": "Internamento", "category_id": category_map["Internamento"], "description": "Serviços de internamento hospitalar"},
                            {"name": "Cirurgia de Urgência", "category_id": category_map["Cirurgia"], "description": "Cirurgias de emergência"}
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
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Laboratoriais",
                                                "prefix": "EL",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Saúde", "Exames"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Internamento",
                                                "prefix": "IN",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Saúde", "Internamento"]
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
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Laboratoriais",
                                                "prefix": "EL",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Saúde", "Exames"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Internamento",
                                                "prefix": "IN",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Saúde", "Internamento"]
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
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Laboratoriais",
                                                "prefix": "EL",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Saúde", "Exames"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Internamento",
                                                "prefix": "IN",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Saúde", "Internamento"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Clínica Sagrada Esperança",
                        "description": "Serviços de saúde privados em Luanda",
                        "institution_type_id": institution_type_map["Saúde"],
                        "services": [
                            {"name": "Consulta Especializada", "category_id": category_map["Consulta Médica"], "description": "Consultas com especialistas"},
                            {"name": "Exames Diagnósticos", "category_id": category_map["Exames"], "description": "Exames avançados"},
                            {"name": "Fisioterapia", "category_id": category_map["Fisioterapia"], "description": "Serviços de reabilitação física"},
                            {"name": "Vacinação", "category_id": category_map["Vacinação"], "description": "Serviços de imunização"},
                            {"name": "Odontologia", "category_id": category_map["Odontologia"], "description": "Atendimento odontológico"}
                        ],
                        "branches": [
                            {
                                "name": "Unidade Talatona",
                                "location": "Rua Principal, Talatona, Luanda",
                                "neighborhood": "Talatona",
                                "latitude": -8.9167,
                                "longitude": 13.1833,
                                "departments": [
                                    {
                                        "name": "Clínica Especializada",
                                        "sector": "Saúde",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Consulta Especializada",
                                                "prefix": "CE",
                                                "daily_limit": 80,
                                                "num_counters": 4,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Diagnósticos",
                                                "prefix": "ED",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Saúde", "Exames"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Fisioterapia",
                                                "prefix": "FT",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Saúde", "Fisioterapia"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Ingombota",
                                "location": "Avenida 4 de Fevereiro, Ingombota, Luanda",
                                "neighborhood": "Ingombota",
                                "latitude": -8.8167,
                                "longitude": 13.2332,
                                "departments": [
                                    {
                                        "name": "Clínica Especializada",
                                        "sector": "Saúde",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Consulta Especializada",
                                                "prefix": "CE",
                                                "daily_limit": 80,
                                                "num_counters": 4,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Diagnósticos",
                                                "prefix": "ED",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Saúde", "Exames"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Fisioterapia",
                                                "prefix": "FT",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Saúde", "Fisioterapia"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Maianga",
                                "location": "Rua Joaquim Kapango, Maianga, Luanda",
                                "neighborhood": "Maianga",
                                "latitude": -8.8147,
                                "longitude": 13.2302,
                                "departments": [
                                    {
                                        "name": "Clínica Especializada",
                                        "sector": "Saúde",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Consulta Especializada",
                                                "prefix": "CE",
                                                "daily_limit": 80,
                                                "num_counters": 4,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Diagnósticos",
                                                "prefix": "ED",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Saúde", "Exames"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Fisioterapia",
                                                "prefix": "FT",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Saúde", "Fisioterapia"]
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
                            {"name": "Registo Civil", "category_id": category_map["Registros"], "description": "Registos civis"},
                            {"name": "Renovação de Licenças", "category_id": category_map["Licenças"], "description": "Renovação de licenças administrativas"}
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
                                                "tags": ["Administrativo", "Documentos", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Licenças",
                                                "prefix": "RL",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Licenças"]
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
                                                "tags": ["Administrativo", "Documentos", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Licenças",
                                                "prefix": "RL",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Licenças"]
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
                                                "tags": ["Administrativo", "Documentos", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Licenças",
                                                "prefix": "RL",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Licenças"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Conservatória dos Registos",
                        "description": "Serviços de registo civil e comercial em Luanda",
                        "institution_type_id": institution_type_map["Administrativo"],
                        "services": [
                            {"name": "Registo Comercial", "category_id": category_map["Registros"], "description": "Registo de empresas"},
                            {"name": "Registo Civil", "category_id": category_map["Registros"], "description": "Registos de nascimento e casamento"},
                            {"name": "Renovação de Licenças", "category_id": category_map["Licenças"], "description": "Renovação de licenças comerciais"},
                            {"name": "Autenticação de Documentos", "category_id": category_map["Autenticação"], "description": "Autenticação de documentos oficiais"},
                            {"name": "Registo Predial", "category_id": category_map["Registros"], "description": "Registo de propriedades"},
                            {"name": "Certidão de Nascimento", "category_id": category_map["Documentos"], "description": "Emissão de certidões de nascimento"},
                            {"name": "Certidão de Casamento", "category_id": category_map["Documentos"], "description": "Emissão de certidões de casamento"},
                            {"name": "Registo de Óbito", "category_id": category_map["Registros"], "description": "Registo de falecimentos"}
                        ],
                        "branches": [
                            {
                                "name": "Conservatória Ingombota",
                                "location": "Avenida Lenine, Ingombota, Luanda",
                                "neighborhood": "Ingombota",
                                "latitude": -8.8167,
                                "longitude": 13.2332,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Cazenga",
                                "location": "Rua dos Combatentes, Cazenga, Luanda",
                                "neighborhood": "Cazenga",
                                "latitude": -8.8500,
                                "longitude": 13.2833,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Talatona",
                                "location": "Rua Principal, Talatona, Luanda",
                                "neighborhood": "Talatona",
                                "latitude": -8.9167,
                                "longitude": 13.1833,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Kilamba",
                                "location": "Avenida do Kilamba, Kilamba, Luanda",
                                "neighborhood": "Kilamba",
                                "latitude": -8.9333,
                                "longitude": 13.2667,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Viana",
                                "location": "Rua Principal, Viana, Luanda",
                                "neighborhood": "Viana",
                                "latitude": -8.9035,
                                "longitude": 13.3741,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Rangel",
                                "location": "Rua do Rangel, Rangel, Luanda",
                                "neighborhood": "Rangel",
                                "latitude": -8.8300,
                                "longitude": 13.2500,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Autenticação"]
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

                def create_branch_schedules(branch_id, institution_type, is_24h=False):
                    weekdays = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY, Weekday.SUNDAY]
                    for day in weekdays:
                        if not exists(BranchSchedule, branch_id=branch_id, weekday=day):
                            if institution_type == "Saúde":
                                open_time = time(0, 0) if is_24h else time(7, 0)
                                end_time = time(23, 59) if is_24h else time(17, 0)
                            elif institution_type == "Administrativo":
                                open_time = time(0, 0) if is_24h else time(8, 0)
                                end_time = time(23, 59) if is_24h else time(16, 0)
                            else:  # Bancário
                                open_time = time(0, 0) if is_24h else time(8, 30)
                                end_time = time(23, 59) if is_24h else time(15, 30)
                            bs = BranchSchedule(
                                id=str(uuid.uuid4()),
                                branch_id=branch_id,
                                weekday=day,
                                open_time=open_time,
                                end_time=end_time,
                                is_closed=False if is_24h or day in [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY] else True
                            )
                            db.session.add(bs)
                            app.logger.debug(f"Horário de filial criado: {day} para filial {branch_id}")
                    db.session.flush()

                def create_queue(department_id, queue_data, service_id):
                    if not exists(Queue, id=queue_data["id"]):
                        is_24h = "24h" in queue_data["tags"]
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

                def create_branch(institution_id, branch_data, institution_type):
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
                        is_24h = any("24h" in queue_data["tags"] for dept in branch_data["departments"] for queue_data in dept["queues"])
                        create_branch_schedules(b.id, institution_type, is_24h)
                        for dept_data in branch_data["departments"]:
                            create_department(b.id, dept_data)
                        return b
                    b = Branch.query.filter_by(institution_id=institution_id, name=branch_data["name"]).first()
                    for dept_data in branch_data["departments"]:
                        create_department(b.id, dept_data)
                    return b

                def create_institution(inst_data):
                    institution_type = InstitutionType.query.get(inst_data["institution_type_id"]).name
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
                            create_branch(i.id, branch_data, institution_type)
                        return i
                    i = Institution.query.filter_by(name=inst_data["name"]).first()
                    create_institution_services(i.id, inst_data["services"])
                    for branch_data in inst_data["branches"]:
                        create_branch(i.id, branch_data, institution_type)
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
                    # Usuário de teste
                    test_user_id = "nMSnRc8jpYQbnrxujg5JZcHzFKP2"
                    test_user_email = "edmannews5@gmail.com"
                    if not exists(User, id=test_user_id) and not exists(User, email=test_user_email):
                        test_user = User(
                            id=test_user_id,
                            email=test_user_email,
                            name="Edman Teste",
                            password_hash=hash_password("test123"),
                            user_role=UserRole.USER,
                            created_at=datetime.utcnow(),
                            active=True
                        )
                        db.session.add(test_user)
                        users.append(test_user)
                        app.logger.debug(f"Usuário de teste criado: {test_user_email}")

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
                    for i in range(20 - user_count):
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
                    # Preferências para o usuário de teste
                    test_user = User.query.filter_by(id="nMSnRc8jpYQbnrxujg5JZcHzFKP2").first()
                    if test_user:
                        test_prefs = [
                            {
                                "institution_name": "Conservatória dos Registos",
                                "neighborhood": "Ingombota",
                                "is_client": True,
                                "is_favorite": True,
                                "visit_count": 15,
                                "preference_score": 80
                            },
                            {
                                "institution_name": "Hospital Josina Machel",
                                "neighborhood": "Maianga",
                                "is_client": True,
                                "is_favorite": False,
                                "visit_count": 10,
                                "preference_score": 60
                            },
                            {
                                "institution_name": "Banco BAI",
                                "neighborhood": "Talatona",
                                "is_client": True,
                                "is_favorite": False,
                                "visit_count": 5,
                                "preference_score": 50
                            }
                        ]
                        for pref in test_prefs:
                            inst = Institution.query.filter_by(name=pref["institution_name"]).first()
                            if inst and not exists(UserPreference, user_id=test_user.id, institution_id=inst.id):
                                up = UserPreference(
                                    id=str(uuid.uuid4()),
                                    user_id=test_user.id,
                                    institution_id=inst.id,
                                    institution_type_id=inst.institution_type_id,
                                    neighborhood=pref["neighborhood"],
                                    preference_score=pref["preference_score"],
                                    is_client=pref["is_client"],
                                    is_favorite=pref["is_favorite"],
                                    visit_count=pref["visit_count"],
                                    last_visited=now - timedelta(days=pref["visit_count"] % 5),
                                    created_at=now,
                                    updated_at=now
                                )
                                db.session.add(up)
                                app.logger.debug(f"Preferência criada para usuário de teste {test_user.id} e instituição {inst.id}")

                    # Preferências para outros usuários
                    user_list = User.query.filter_by(user_role=UserRole.USER).limit(20).all()
                    institutions = Institution.query.all()
                    for i, user in enumerate(user_list):
                        if user.id == "nMSnRc8jpYQbnrxujg5JZcHzFKP2":
                            continue
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
                    test_user = User.query.filter_by(id="nMSnRc8jpYQbnrxujg5JZcHzFKP2").first()
                    # Tickets para o usuário de teste
                    if test_user:
                        test_queues = [
                            {"institution": "Conservatória dos Registos", "service": "Registo Civil", "branch": "Conservatória Ingombota", "count": 4},
                            {"institution": "Hospital Josina Machel", "service": "Consulta Geral", "branch": "Unidade Central", "count": 3},
                            {"institution": "Banco BAI", "service": "Atendimento Bancário", "branch": "Agência Central", "count": 3}
                        ]
                        for tq in test_queues:
                            inst = Institution.query.filter_by(name=tq["institution"]).first()
                            branch = Branch.query.filter_by(institution_id=inst.id, name=tq["branch"]).first()
                            service = InstitutionService.query.filter_by(institution_id=inst.id, name=tq["service"]).first()
                            queue = Queue.query.join(Department).join(Branch).filter(
                                Branch.id == branch.id, Queue.service_id == service.id
                            ).first()
                            if queue:
                                existing_tickets = Ticket.query.filter_by(queue_id=queue.id, user_id=test_user.id).count()
                                for i in range(tq["count"] - existing_tickets):
                                    ticket_number = Ticket.query.filter_by(queue_id=queue.id).count() + i + 1
                                    branch_code = branch.id[-4:]
                                    qr_code = f"{queue.prefix}{ticket_number:03d}-{queue.id[:8]}-{branch_code}"
                                    if Ticket.query.filter_by(qr_code=qr_code).first():
                                        qr_code = f"{queue.prefix}{ticket_number:03d}-{queue.id[:8]}-{branch_code}-{int(now.timestamp())}"
                                    status = "Atendido" if i % 2 == 0 else "Pendente"
                                    issued_at = now - timedelta(days=i % 30, hours=i % 24)
                                    ticket = Ticket(
                                        id=str(uuid.uuid4()),
                                        queue_id=queue.id,
                                        user_id=test_user.id,
                                        ticket_number=ticket_number,
                                        qr_code=qr_code,
                                        priority=1 if i % 2 == 0 else 0,  # 50% alta prioridade
                                        is_physical=False,
                                        status=status,
                                        issued_at=issued_at,
                                        expires_at=issued_at + timedelta(days=1),
                                        attended_at=issued_at + timedelta(minutes=10) if status == "Atendido" else None,
                                        counter=(i % queue.num_counters) + 1 if status == "Atendido" else None,
                                        service_time=300.0 + (i % 26) * 60 if status == "Atendido" else None,
                                        trade_available=False
                                    )
                                    db.session.add(ticket)
                                    app.logger.debug(f"Ticket de teste criado: {qr_code} para usuário {test_user.id}")

                    # Tickets para outras filas
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
                                user_id=User.query.filter_by(user_role=UserRole.USER).offset(i % 20).first().id,
                                ticket_number=ticket_number,
                                qr_code=qr_code,
                                priority=1 if i % 5 == 0 else 0,  # 20% alta prioridade
                                is_physical=False,
                                status=status,
                                issued_at=issued_at,
                                expires_at=issued_at + timedelta(days=1),
                                attended_at=issued_at + timedelta(minutes=10) if status == "Atendido" else None,
                                counter=(i % queue.num_counters) + 1 if status == "Atendido" else None,
                                service_time=300.0 + (i % 26) * 60 if status == "Atendido" else None,
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
                # --------------------------------------
                # Criar Comportamentos de Usuário
                # --------------------------------------
                def create_user_behaviors():
                    now = datetime.utcnow()
                    test_user = User.query.filter_by(id="nMSnRc8jpYQbnrxujg5JZcHzFKP2").first()
                    # Comportamentos para o usuário de teste
                    if test_user:
                        test_behaviors = [
                            {"institution": "Conservatória dos Registos", "service": "Registo Civil", "branch": "Conservatória Ingombota", "action": "issued_ticket", "days_ago": 5},
                            {"institution": "Conservatória dos Registos", "service": "Registo Civil", "branch": "Conservatória Ingombota", "action": "viewed_queue", "days_ago": 4},
                            {"institution": "Hospital Josina Machel", "service": "Consulta Geral", "branch": "Unidade Central", "action": "issued_ticket", "days_ago": 10},
                            {"institution": "Hospital Josina Machel", "service": "Consulta Geral", "branch": "Unidade Central", "action": "viewed_queue", "days_ago": 9},
                            {"institution": "Banco BAI", "service": "Atendimento Bancário", "branch": "Agência Central", "action": "issued_ticket", "days_ago": 15}
                        ]
                        for beh in test_behaviors:
                            inst = Institution.query.filter_by(name=beh["institution"]).first()
                            branch = Branch.query.filter_by(institution_id=inst.id, name=beh["branch"]).first()
                            service = InstitutionService.query.filter_by(institution_id=inst.id, name=beh["service"]).first()
                            queue = Queue.query.join(Department).join(Branch).filter(
                                Branch.id == branch.id, Queue.service_id == service.id
                            ).first()
                            if queue and not exists(UserBehavior, user_id=test_user.id, queue_id=queue.id, action=beh["action"]):
                                ub = UserBehavior(
                                    id=str(uuid.uuid4()),
                                    user_id=test_user.id,
                                    institution_id=inst.id,
                                    branch_id=branch.id,
                                    queue_id=queue.id,
                                    action=beh["action"],
                                    timestamp=now - timedelta(days=beh["days_ago"]),
                                    created_at=now
                                )
                                db.session.add(ub)
                                app.logger.debug(f"Comportamento de teste criado: {beh['action']} para usuário {test_user.id} na fila {queue.id}")

                    # Comportamentos para outros usuários
                    user_list = User.query.filter_by(user_role=UserRole.USER).limit(20).all()
                    queues = Queue.query.all()
                    for i, user in enumerate(user_list):
                        if user.id == "nMSnRc8jpYQbnrxujg5JZcHzFKP2":
                            continue
                        for j in range(3):
                            queue = queues[(i + j) % len(queues)]
                            branch = Branch.query.join(Department).filter(Department.id == queue.department_id).first()
                            inst = Institution.query.get(branch.institution_id)
                            action = "issued_ticket" if j % 2 == 0 else "viewed_queue"
                            if not exists(UserBehavior, user_id=user.id, queue_id=queue.id, action=action):
                                ub = UserBehavior(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    institution_id=inst.id,
                                    branch_id=branch.id,
                                    queue_id=queue.id,
                                    action=action,
                                    timestamp=now - timedelta(days=(i + j) % 7),
                                    created_at=now
                                )
                                db.session.add(ub)
                                app.logger.debug(f"Comportamento criado: {action} para usuário {user.id} na fila {queue.id}")
                    db.session.flush()
                    app.logger.info("Comportamentos de usuário criados com sucesso.")

                create_user_behaviors()

                # --------------------------------------
                # Criar Logs de Auditoria
                # --------------------------------------
                def create_audit_logs():
                    now = datetime.utcnow()
                    test_user = User.query.filter_by(id="nMSnRc8jpYQbnrxujg5JZcHzFKP2").first()
                    # Logs de auditoria para o usuário de teste
                    if test_user:
                        test_audit_logs = [
                            {"action": "USER_LOGIN", "description": "Usuário autenticado via Firebase", "days_ago": 0},
                            {"action": "TICKET_CREATED", "description": "Ticket emitido para Registo Civil", "days_ago": 5},
                            {"action": "TICKET_CREATED", "description": "Ticket emitido para Consulta Geral", "days_ago": 10},
                            {"action": "TICKET_CREATED", "description": "Ticket emitido para Atendimento Bancário", "days_ago": 15},
                            {"action": "QUEUE_VIEWED", "description": "Fila Registo Civil visualizada", "days_ago": 4},
                            {"action": "QUEUE_VIEWED", "description": "Fila Consulta Geral visualizada", "days_ago": 9},
                            {"action": "USER_LOGIN", "description": "Usuário autenticado via Firebase", "days_ago": 7},
                            {"action": "TICKET_CREATED", "description": "Ticket emitido para Registo Civil", "days_ago": 3},
                            {"action": "USER_PROFILE_UPDATED", "description": "Perfil do usuário atualizado", "days_ago": 2},
                            {"action": "NOTIFICATION_SENT", "description": "Notificação de ticket enviada", "days_ago": 5}
                        ]
                        for log in test_audit_logs:
                            if not exists(AuditLog, user_id=test_user.id, action=log["action"], description=log["description"]):
                                al = AuditLog(
                                    id=str(uuid.uuid4()),
                                    user_id=test_user.id,
                                    action=log["action"],
                                    description=log["description"],
                                    timestamp=now - timedelta(days=log["days_ago"]),
                                    created_at=now
                                )
                                db.session.add(al)
                                app.logger.debug(f"Log de auditoria de teste criado: {log['action']} para usuário {test_user.id}")

                    # Logs de auditoria para outros usuários
                    user_list = User.query.filter_by(user_role=UserRole.USER).limit(20).all()
                    actions = ["USER_LOGIN", "TICKET_CREATED", "QUEUE_VIEWED", "USER_PROFILE_UPDATED", "NOTIFICATION_SENT"]
                    for i, user in enumerate(user_list):
                        if user.id == "nMSnRc8jpYQbnrxujg5JZcHzFKP2":
                            continue
                        for j in range(5):
                            action = actions[j % len(actions)]
                            description = f"{action.replace('_', ' ').title()} - Usuário {user.email}"
                            if not exists(AuditLog, user_id=user.id, action=action, description=description):
                                al = AuditLog(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    action=action,
                                    description=description,
                                    timestamp=now - timedelta(days=(i + j) % 7),
                                    created_at=now
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
                    test_user = User.query.filter_by(id="nMSnRc8jpYQbnrxujg5JZcHzFKP2").first()
                    # Logs de notificação para o usuário de teste
                    if test_user:
                        test_notifications = [
                            {"message": "Ticket emitido para Registo Civil", "days_ago": 5},
                            {"message": "Fila Registo Civil atualizada", "days_ago": 4},
                            {"message": "Ticket emitido para Consulta Geral", "days_ago": 10},
                            {"message": "Fila Consulta Geral atualizada", "days_ago": 9},
                            {"message": "Ticket emitido para Atendimento Bancário", "days_ago": 15}
                        ]
                        for notif in test_notifications:
                            if not exists(NotificationLog, user_id=test_user.id, message=notif["message"]):
                                nl = NotificationLog(
                                    id=str(uuid.uuid4()),
                                    user_id=test_user.id,
                                    message=notif["message"],
                                    notification_type="PUSH",
                                    status="SENT",
                                    sent_at=now - timedelta(days=notif["days_ago"]),
                                    created_at=now
                                )
                                db.session.add(nl)
                                app.logger.debug(f"Log de notificação de teste criado: {notif['message']} para usuário {test_user.id}")

                    # Logs de notificação para outros usuários
                    user_list = User.query.filter_by(user_role=UserRole.USER).limit(20).all()
                    messages = [
                        "Ticket emitido com sucesso",
                        "Fila atualizada",
                        "Sua vez está próxima"
                    ]
                    for i, user in enumerate(user_list):
                        if user.id == "nMSnRc8jpYQbnrxujg5JZcHzFKP2":
                            continue
                        for j in range(3):
                            message = messages[j % len(messages)]
                            if not exists(NotificationLog, user_id=user.id, message=message):
                                nl = NotificationLog(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    message=message,
                                    notification_type="PUSH",
                                    status="SENT",
                                    sent_at=now - timedelta(days=(i + j) % 7),
                                    created_at=now
                                )
                                db.session.add(nl)
                                app.logger.debug(f"Log de notificação criado: {message} para usuário {user.id}")
                    db.session.flush()
                    app.logger.info("Logs de notificação criados com sucesso.")

                create_notification_logs()

                # --------------------------------------
                # Criar Localizações Alternativas de Usuário
                # --------------------------------------
                def create_user_location_fallbacks():
                    now = datetime.utcnow()
                    test_user = User.query.filter_by(id="nMSnRc8jpYQbnrxujg5JZcHzFKP2").first()
                    # Localizações alternativas para o usuário de teste
                    if test_user:
                        test_locations = [
                            {"neighborhood": "Ingombota", "latitude": -8.8167, "longitude": 13.2332},
                            {"neighborhood": "Talatona", "latitude": -8.9167, "longitude": 13.1833}
                        ]
                        for loc in test_locations:
                            if not exists(UserLocationFallback, user_id=test_user.id, neighborhood=loc["neighborhood"]):
                                ulf = UserLocationFallback(
                                    id=str(uuid.uuid4()),
                                    user_id=test_user.id,
                                    neighborhood=loc["neighborhood"],
                                    latitude=loc["latitude"],
                                    longitude=loc["longitude"],
                                    created_at=now,
                                    updated_at=now
                                )
                                db.session.add(ulf)
                                app.logger.debug(f"Localização alternativa de teste criada: {loc['neighborhood']} para usuário {test_user.id}")

                    # Localizações alternativas para outros usuários
                    user_list = User.query.filter_by(user_role=UserRole.USER).limit(20).all()
                    for i, user in enumerate(user_list):
                        if user.id == "nMSnRc8jpYQbnrxujg5JZcHzFKP2":
                            continue
                        for j in range(2):
                            loc = neighborhoods[(i + j) % len(neighborhoods)]
                            if not exists(UserLocationFallback, user_id=user.id, neighborhood=loc["name"]):
                                ulf = UserLocationFallback(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    neighborhood=loc["name"],
                                    latitude=loc["latitude"],
                                    longitude=loc["longitude"],
                                    created_at=now,
                                    updated_at=now
                                )
                                db.session.add(ulf)
                                app.logger.debug(f"Localização alternativa criada: {loc['name']} para usuário {user.id}")
                    db.session.flush()
                    app.logger.info("Localizações alternativas de usuário criadas com sucesso.")

                create_user_location_fallbacks()

                # --------------------------------------
                # Commit das Alterações
                # --------------------------------------
                db.session.commit()
                app.logger.info("População de dados iniciais concluída com sucesso.")

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao popular dados iniciais: {str(e)}")
            raise
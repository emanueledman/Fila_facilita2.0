import uuid
from datetime import datetime, time, timedelta
import bcrypt
import random
from app import db
from app.models import (
    InstitutionType, Institution, Branch, BranchSchedule, Department, Queue,
    InstitutionService, ServiceCategory, ServiceTag, User, UserRole, Ticket, UserPreference,
    UserBehavior, UserLocationFallback, NotificationLog, AuditLog, Weekday
)

def populate_initial_data(app):
    """
    Popula o banco de dados com dados iniciais para testes, com foco na Conservatória dos Registos (10 filiais).
    Inclui 8 instituições (4 bancos: BAI, BFA, BIC, Keve; 2 saúde: Hospital Josina Machel, Clínica Sagrada Esperança;
    2 administrativos: SIAC, Conservatória). Conservatória tem 10 filiais, bancos e SIAC 3 cada, hospitais 5 cada.
    Cada filial tem 1 departamento com 3 filas (1 24/7, 2 horário comercial). Cada fila tem 10 tickets, todos 'Atendido'.
    Inclui 5 usuários (1 teste: nMSnRc8jpYQbnrxujg5JZcHzFKP2, edmannews5@gmail.com; 4 regulares).
    Usa 35 bairros únicos de Luanda para filiais, sem repetições.
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
                # Bairros de Luanda (35 únicos)
                # --------------------------------------
                neighborhoods = [
                    {"name": "Ingombota", "latitude": -8.8167, "longitude": 13.2332},
                    {"name": "Maianga", "latitude": -8.8147, "longitude": 13.2302},
                    {"name": "Talatona", "latitude": -8.9167, "longitude": 13.1833},
                    {"name": "Kilamba", "latitude": -8.9333, "longitude": 13.2667},
                    {"name": "Cazenga", "latitude": -8.8500, "longitude": 13.2833},
                    {"name": "Viana", "latitude": -8.9035, "longitude": 13.3741},
                    {"name": "Rangel", "latitude": -8.8300, "longitude": 13.2500},
                    {"name": "Samba", "latitude": -8.8333, "longitude": 13.2333},
                    {"name": "Cacuaco", "latitude": -8.7833, "longitude": 13.3667},
                    {"name": "Belas", "latitude": -8.9333, "longitude": 13.2000},
                    {"name": "Sambizanga", "latitude": -8.8050, "longitude": 13.2400},
                    {"name": "Vila Alice", "latitude": -8.8200, "longitude": 13.2450},
                    {"name": "Prenda", "latitude": -8.8250, "longitude": 13.2300},
                    {"name": "Mutamba", "latitude": -8.8130, "longitude": 13.2350},
                    {"name": "Maculusso", "latitude": -8.8180, "longitude": 13.2380},
                    {"name": "Alvalade", "latitude": -8.8300, "longitude": 13.2400},
                    {"name": "Bairro Operário", "latitude": -8.8150, "longitude": 13.2500},
                    {"name": "Bairro Azul", "latitude": -8.8100, "longitude": 13.2450},
                    {"name": "Patrice Lumumba", "latitude": -8.8200, "longitude": 13.2550},
                    {"name": "Nova Vida", "latitude": -8.9000, "longitude": 13.2600},
                    {"name": "Zango", "latitude": -8.9500, "longitude": 13.3500},
                    {"name": "Camama", "latitude": -8.9200, "longitude": 13.2200},
                    {"name": "Benfica", "latitude": -8.9500, "longitude": 13.1800},
                    {"name": "Palanca", "latitude": -8.8700, "longitude": 13.2700},
                    {"name": "Morro Bento", "latitude": -8.9100, "longitude": 13.1900},
                    {"name": "Coqueiros", "latitude": -8.8050, "longitude": 13.2300},
                    {"name": "Futungo de Belas", "latitude": -8.9700, "longitude": 13.1600},
                    {"name": "Lar do Patriota", "latitude": -8.8900, "longitude": 13.2400},
                    {"name": "Bairro Popular", "latitude": -8.8350, "longitude": 13.2600},
                    {"name": "Hoji Ya Henda", "latitude": -8.8400, "longitude": 13.2800},
                    {"name": "Ngola Kiluanji", "latitude": -8.8500, "longitude": 13.2650},
                    {"name": "Cassenda", "latitude": -8.8300, "longitude": 13.2350},
                    {"name": "Rocha Pinto", "latitude": -8.8400, "longitude": 13.2450},
                    {"name": "Vila Estoril", "latitude": -8.8200, "longitude": 13.2300},
                    {"name": "Kinaxixi", "latitude": -8.8170, "longitude": 13.2400}
                ]

                # --------------------------------------
                # Dados de Instituições com Bairros Únicos
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
                                "name": "Agência Ingombota",
                                "location": "Rua Rainha Ginga, Ingombota, Luanda",
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
                                "location": "Via Expressa, Talatona, Luanda",
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
                                "latitude": -8.8147,
                                "longitude": 13.2302,
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
                            },
                            {
                                "name": "Agência Cazenga",
                                "location": "Avenida dos Combatentes, Cazenga, Luanda",
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
                                "name": "Agência Samba",
                                "location": "Rua Principal, Samba, Luanda",
                                "neighborhood": "Samba",
                                "latitude": -8.8333,
                                "longitude": 13.2333,
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
                                "name": "Agência Cacuaco",
                                "location": "Estrada Principal, Cacuaco, Luanda",
                                "neighborhood": "Cacuaco",
                                "latitude": -8.7833,
                                "longitude": 13.3667,
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
                                "name": "Agência Belas",
                                "location": "Estrada de Belas, Belas, Luanda",
                                "neighborhood": "Belas",
                                "latitude": -8.9333,
                                "longitude": 13.2000,
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
                                "name": "Agência Sambizanga",
                                "location": "Rua Principal, Sambizanga, Luanda",
                                "neighborhood": "Sambizanga",
                                "latitude": -8.8050,
                                "longitude": 13.2400,
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
                                "name": "Agência Vila Alice",
                                "location": "Rua da Vila, Vila Alice, Luanda",
                                "neighborhood": "Vila Alice",
                                "latitude": -8.8200,
                                "longitude": 13.2450,
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
                        "description": "Serviços de saúde pública em Luanda",
                        "institution_type_id": institution_type_map["Saúde"],
                        "services": [
                            {"name": "Consulta Geral", "category_id": category_map["Consulta Médica"], "description": "Atendimento clínico geral"},
                            {"name": "Exames Laboratoriais", "category_id": category_map["Exames"], "description": "Exames de sangue e urina"},
                            {"name": "Triagem", "category_id": category_map["Triagem"], "description": "Triagem de pacientes"},
                            {"name": "Internamento", "category_id": category_map["Internamento"], "description": "Cuidados hospitalares"},
                            {"name": "Cirurgia de Urgência", "category_id": category_map["Cirurgia"], "description": "Cirurgias de emergência"}
                        ],
                        "branches": [
                            {
                                "name": "Unidade Prenda",
                                "location": "Rua da Saúde, Prenda, Luanda",
                                "neighborhood": "Prenda",
                                "latitude": -8.8250,
                                "longitude": 13.2300,
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
                                                "num_counters": 5,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Laboratoriais",
                                                "prefix": "EL",
                                                "daily_limit": 80,
                                                "num_counters": 3,
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
                                "name": "Unidade Mutamba",
                                "location": "Avenida 4 de Fevereiro, Mutamba, Luanda",
                                "neighborhood": "Mutamba",
                                "latitude": -8.8130,
                                "longitude": 13.2350,
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
                                                "num_counters": 5,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Laboratoriais",
                                                "prefix": "EL",
                                                "daily_limit": 80,
                                                "num_counters": 3,
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
                                "name": "Unidade Maculusso",
                                "location": "Rua do Hospital, Maculusso, Luanda",
                                "neighborhood": "Maculusso",
                                "latitude": -8.8180,
                                "longitude": 13.2380,
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
                                                "num_counters": 5,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Laboratoriais",
                                                "prefix": "EL",
                                                "daily_limit": 80,
                                                "num_counters": 3,
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
                                "name": "Unidade Alvalade",
                                "location": "Rua da Unidade, Alvalade, Luanda",
                                "neighborhood": "Alvalade",
                                "latitude": -8.8300,
                                "longitude": 13.2400,
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
                                                "num_counters": 5,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Laboratoriais",
                                                "prefix": "EL",
                                                "daily_limit": 80,
                                                "num_counters": 3,
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
                                "name": "Unidade Bairro Operário",
                                "location": "Rua do Hospital, Bairro Operário, Luanda",
                                "neighborhood": "Bairro Operário",
                                "latitude": -8.8150,
                                "longitude": 13.2500,
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
                                                "num_counters": 5,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Laboratoriais",
                                                "prefix": "EL",
                                                "daily_limit": 80,
                                                "num_counters": 3,
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
                        "description": "Serviços de saúde privada em Luanda",
                        "institution_type_id": institution_type_map["Saúde"],
                        "services": [
                            {"name": "Consulta Especializada", "category_id": category_map["Consulta Médica"], "description": "Consultas com especialistas"},
                            {"name": "Exames Diagnósticos", "category_id": category_map["Exames"], "description": "Exames de imagem"},
                            {"name": "Fisioterapia", "category_id": category_map["Fisioterapia"], "description": "Reabilitação física"},
                            {"name": "Vacinação", "category_id": category_map["Vacinação"], "description": "Serviços de imunização"},
                            {"name": "Odontologia", "category_id": category_map["Odontologia"], "description": "Cuidados dentários"}
                        ],
                        "branches": [
                            {
                                "name": "Unidade Bairro Azul",
                                "location": "Rua da Clínica, Bairro Azul, Luanda",
                                "neighborhood": "Bairro Azul",
                                "latitude": -8.8100,
                                "longitude": 13.2450,
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
                                                "num_counters": 5,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Diagnósticos",
                                                "prefix": "ED",
                                                "daily_limit": 80,
                                                "num_counters": 3,
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
                                "name": "Unidade Patrice Lumumba",
                                "location": "Rua da Saúde, Patrice Lumumba, Luanda",
                                "neighborhood": "Patrice Lumumba",
                                "latitude": -8.8200,
                                "longitude": 13.2550,
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
                                                "num_counters": 5,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Diagnósticos",
                                                "prefix": "ED",
                                                "daily_limit": 80,
                                                "num_counters": 3,
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
                                "name": "Unidade Nova Vida",
                                "location": "Avenida da Saúde, Nova Vida, Luanda",
                                "neighborhood": "Nova Vida",
                                "latitude": -8.9000,
                                "longitude": 13.2600,
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
                                                "num_counters": 5,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Diagnósticos",
                                                "prefix": "ED",
                                                "daily_limit": 80,
                                                "num_counters": 3,
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
                                "name": "Unidade Zango",
                                "location": "Rua da Clínica, Zango, Luanda",
                                "neighborhood": "Zango",
                                "latitude": -8.9500,
                                "longitude": 13.3500,
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
                                                "num_counters": 5,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Diagnósticos",
                                                "prefix": "ED",
                                                "daily_limit": 80,
                                                "num_counters": 3,
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
                                "name": "Unidade Camama",
                                "location": "Rua do Hospital, Camama, Luanda",
                                "neighborhood": "Camama",
                                "latitude": -8.9200,
                                "longitude": 13.2200,
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
                                                "num_counters": 5,
                                                "tags": ["Saúde", "Consulta", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Exames Diagnósticos",
                                                "prefix": "ED",
                                                "daily_limit": 80,
                                                "num_counters": 3,
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
                        "description": "Serviços Integrados de Atendimento ao Cidadão",
                        "institution_type_id": institution_type_map["Administrativo"],
                        "services": [
                            {"name": "Emissão de BI", "category_id": category_map["Documentos"], "description": "Emissão de bilhete de identidade"},
                            {"name": "Registo Civil", "category_id": category_map["Registros"], "description": "Registos de nascimento e casamento"},
                            {"name": "Renovação de Licenças", "category_id": category_map["Licenças"], "description": "Renovação de licenças diversas"}
                        ],
                        "branches": [
                            {
                                "name": "Unidade Benfica",
                                "location": "Rua do SIAC, Benfica, Luanda",
                                "neighborhood": "Benfica",
                                "latitude": -8.9500,
                                "longitude": 13.1800,
                                "departments": [
                                    {
                                        "name": "Atendimento ao Cidadão",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de BI",
                                                "prefix": "BI",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Documentos", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Licenças",
                                                "prefix": "RL",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Licenças"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Palanca",
                                "location": "Rua do Cidadão, Palanca, Luanda",
                                "neighborhood": "Palanca",
                                "latitude": -8.8700,
                                "longitude": 13.2700,
                                "departments": [
                                    {
                                        "name": "Atendimento ao Cidadão",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de BI",
                                                "prefix": "BI",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Documentos", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Licenças",
                                                "prefix": "RL",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Licenças"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Morro Bento",
                                "location": "Rua do SIAC, Morro Bento, Luanda",
                                "neighborhood": "Morro Bento",
                                "latitude": -8.9100,
                                "longitude": 13.1900,
                                "departments": [
                                    {
                                        "name": "Atendimento ao Cidadão",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de BI",
                                                "prefix": "BI",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Documentos", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Licenças",
                                                "prefix": "RL",
                                                "daily_limit": 100,
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
                        "description": "Serviços de registo civil e comercial",
                        "institution_type_id": institution_type_map["Administrativo"],
                        "services": [
                            {"name": "Registo Comercial", "category_id": category_map["Registros"], "description": "Registo de empresas"},
                            {"name": "Registo Civil", "category_id": category_map["Registros"], "description": "Registos de nascimento e casamento"},
                            {"name": "Renovação de Licenças", "category_id": category_map["Licenças"], "description": "Renovação de licenças"},
                            {"name": "Autenticação de Documentos", "category_id": category_map["Autenticação"], "description": "Autenticação de documentos oficiais"},
                            {"name": "Registo Predial", "category_id": category_map["Registros"], "description": "Registo de propriedades"},
                            {"name": "Certidão de Nascimento", "category_id": category_map["Documentos"], "description": "Emissão de certidões de nascimento"},
                            {"name": "Certidão de Casamento", "category_id": category_map["Documentos"], "description": "Emissão de certidões de casamento"},
                            {"name": "Registo de Óbito", "category_id": category_map["Registros"], "description": "Registo de óbitos"}
                        ],
                        "branches": [
                            {
                                "name": "Conservatória Coqueiros",
                                "location": "Rua Major Kanhangulo, Coqueiros, Luanda",
                                "neighborhood": "Coqueiros",
                                "latitude": -8.8050,
                                "longitude": 13.2300,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RCOM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Futungo de Belas",
                                "location": "Rua dos Registos, Futungo de Belas, Luanda",
                                "neighborhood": "Futungo de Belas",
                                "latitude": -8.9700,
                                "longitude": 13.1600,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RCOM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Lar do Patriota",
                                "location": "Rua da Conservatória, Lar do Patriota, Luanda",
                                "neighborhood": "Lar do Patriota",
                                "latitude": -8.8900,
                                "longitude": 13.2400,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RCOM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Bairro Popular",
                                "location": "Avenida da Justiça, Bairro Popular, Luanda",
                                "neighborhood": "Bairro Popular",
                                "latitude": -8.8350,
                                "longitude": 13.2600,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RCOM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Hoji Ya Henda",
                                "location": "Rua do Registo, Hoji Ya Henda, Luanda",
                                "neighborhood": "Hoji Ya Henda",
                                "latitude": -8.8400,
                                "longitude": 13.2800,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RCOM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Ngola Kiluanji",
                                "location": "Rua da Justiça, Ngola Kiluanji, Luanda",
                                "neighborhood": "Ngola Kiluanji",
                                "latitude": -8.8500,
                                "longitude": 13.2650,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RCOM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Cassenda",
                                "location": "Rua do Registo, Cassenda, Luanda",
                                "neighborhood": "Cassenda",
                                "latitude": -8.8300,
                                "longitude": 13.2350,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RCOM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Rocha Pinto",
                                "location": "Rua da Conservatória, Rocha Pinto, Luanda",
                                "neighborhood": "Rocha Pinto",
                                "latitude": -8.8400,
                                "longitude": 13.2450,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RCOM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Vila Estoril",
                                "location": "Rua do Registo, Vila Estoril, Luanda",
                                "neighborhood": "Vila Estoril",
                                "latitude": -8.8200,
                                "longitude": 13.2300,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RCOM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Autenticação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Kinaxixi",
                                "location": "Rua da Justiça, Kinaxixi, Luanda",
                                "neighborhood": "Kinaxixi",
                                "latitude": -8.8170,
                                "longitude": 13.2400,
                                "departments": [
                                    {
                                        "name": "Atendimento Registral",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RCOM",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 2,
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
                # Criar Instituições
                # --------------------------------------
                def create_institutions():
                    institution_map = {}
                    for inst_data in institutions_data:
                        if not exists(Institution, name=inst_data["name"]):
                            inst = Institution(
                                id=inst_data["id"],
                                name=inst_data["name"],
                                description=inst_data["description"],
                                institution_type_id=inst_data["institution_type_id"]
                            )
                            db.session.add(inst)
                            db.session.flush()
                            app.logger.debug(f"Instituição criada: {inst_data['name']}")
                        institution_map[inst_data["name"]] = Institution.query.filter_by(name=inst_data["name"]).first().id
                    app.logger.info("Instituições criadas ou recuperadas com sucesso.")
                    return institution_map

                institution_map = create_institutions()

                # --------------------------------------
                # Criar Serviços
                # --------------------------------------
                def create_services():
                    service_map = {}
                    for inst_data in institutions_data:
                        inst_id = institution_map[inst_data["name"]]
                        for service_data in inst_data["services"]:
                            service_key = f"{inst_data['name']}_{service_data['name']}"
                            if not exists(InstitutionService, institution_id=inst_id, name=service_data["name"]):
                                service = InstitutionService(
                                    id=str(uuid.uuid4()),
                                    institution_id=inst_id,
                                    name=service_data["name"],
                                    category_id=service_data["category_id"],
                                    description=service_data["description"]
                                )
                                db.session.add(service)
                                db.session.flush()
                                app.logger.debug(f"Serviço criado: {service_data['name']} para {inst_data['name']}")
                            service_map[service_key] = InstitutionService.query.filter_by(
                                institution_id=inst_id, name=service_data["name"]
                            ).first().id
                    app.logger.info("Serviços criados ou recuperados com sucesso.")
                    return service_map

                service_map = create_services()

                # --------------------------------------
                # Criar Tags de Serviço
                # --------------------------------------
                def create_service_tags():
                    tags = [
                        "Bancário", "Atendimento", "Empréstimo", "Investimento",
                        "Saúde", "Consulta", "Exames", "Internamento", "Fisioterapia",
                        "Administrativo", "Documentos", "Registros", "Licenças", "Autenticação", "24h"
                    ]
                    for tag_name in tags:
                        try:
                            # Tentar buscar a tag usando o campo 'tag_name' (ou ajustar para o campo correto)
                            if not exists(ServiceTag, tag_name=tag_name):
                                tag = ServiceTag(
                                    id=str(uuid.uuid4()),
                                    tag_name=tag_name  # Usar 'tag_name' em vez de 'name'
                                )
                                db.session.add(tag)
                                db.session.flush()
                                app.logger.debug(f"Tag de serviço criada: {tag_name}")
                        except AttributeError as e:
                            app.logger.error(f"Erro ao acessar propriedade de ServiceTag: {str(e)}")
                            app.logger.warning(f"Tentando campo alternativo para tag: {tag_name}")
                            # Fallback: criar tag sem verificar existência, se o campo estiver errado
                            tag = ServiceTag(
                                id=str(uuid.uuid4()),
                                tag_name=tag_name
                            )
                            db.session.add(tag)
                            db.session.flush()
                            app.logger.debug(f"Tag de serviço criada (fallback): {tag_name}")
                    app.logger.info("Tags de serviço criadas ou recuperadas com sucesso.")

                create_service_tags()

                # --------------------------------------
                # Criar Filiais
                # --------------------------------------
                def create_branches():
                    branch_map = {}
                    for inst_data in institutions_data:
                        inst_id = institution_map[inst_data["name"]]
                        inst_name = inst_data["name"]
                        for branch_data in inst_data["branches"]:
                            branch_key = f"{inst_name}_{branch_data['name']}"
                            if not exists(Branch, institution_id=inst_id, name=branch_data["name"]):
                                branch = Branch(
                                    id=str(uuid.uuid4()),
                                    institution_id=inst_id,
                                    name=branch_data["name"],
                                    location=branch_data["location"],
                                    neighborhood=branch_data["neighborhood"],
                                    latitude=branch_data["latitude"],
                                    longitude=branch_data["longitude"]
                                )
                                db.session.add(branch)
                                db.session.flush()
                                app.logger.debug(f"Filial criada: {branch_data['name']} para {inst_name}")
                            branch_map[branch_key] = Branch.query.filter_by(
                                institution_id=inst_id, name=branch_data["name"]
                            ).first().id
                    app.logger.info("Filiais criadas ou recuperadas com sucesso.")
                    return branch_map

                branch_map = create_branches()

                # --------------------------------------
                # Criar Horários de Filiais
                # --------------------------------------
                
                # --------------------------------------
                # Criar Horários de Filiais
                # --------------------------------------
                def create_branch_schedules():
                    for inst_data in institutions_data:
                        inst_id = institution_map[inst_data["name"]]
                        inst_type = InstitutionType.query.get(inst_data["institution_type_id"]).name
                        for branch_data in inst_data["branches"]:
                            branch_id = branch_map[f"{inst_data['name']}_{branch_data['name']}"]
                            is_24h = any(
                                "24h" in queue_data["tags"]
                                for dept in branch_data["departments"]
                                for queue_data in dept["queues"]
                            )
                            # Definir horários com base no tipo de instituição
                            if inst_type == "Saúde":
                                open_time = time(0, 0) if is_24h else time(6, 0)
                                end_time = time(20, 59) if is_24h else time(17, 0)
                                days_open = [1, 2, 3, 4, 5, 6] if not is_24h else [1, 2, 3, 4, 5, 6, 7]
                            elif inst_type == "Administrativo":
                                open_time = time(0, 0) if is_24h else time(8, 0)
                                end_time = time(20, 59) if is_24h else time(15, 0)
                                days_open = [1, 2, 3, 4, 5] if not is_24h else [1, 2, 3, 4, 5, 6, 7]
                            else:  # Bancário
                                open_time = time(0, 0) if is_24h else time(6, 0)
                                end_time = time(20, 59) if is_24h else time(15, 0)
                                days_open = [1, 2, 3, 4, 5] if not is_24h else [1, 2, 3, 4, 5, 6, 7]
                            
                            # Criar horários para cada dia da semana
                            for day in range(1, 8):  # 1=Segunda, 7=Domingo
                                if not exists(BranchSchedule, branch_id=branch_id, weekday_id=day):
                                    schedule = BranchSchedule(
                                        id=str(uuid.uuid4()),
                                        branch_id=branch_id,
                                        weekday_id=day,
                                        open_time=open_time,
                                        end_time=end_time,
                                        is_closed=day not in days_open
                                    )
                                    db.session.add(schedule)
                                    db.session.flush()
                                    app.logger.debug(
                                        f"Horário criado para filial {branch_data['name']} no dia {day}: "
                                        f"{'Fechado' if schedule.is_closed else f'{open_time}–{end_time}'}"
                                    )
                    app.logger.info("Horários de filiais criados ou recuperados com sucesso.")

                create_branch_schedules()

                # --------------------------------------
                # Criar Departamentos
                # --------------------------------------
                def create_departments():
                    department_map = {}
                    for inst_data in institutions_data:
                        inst_name = inst_data["name"]
                        for branch_data in inst_data["branches"]:
                            branch_id = branch_map[f"{inst_name}_{branch_data['name']}"]
                            for dept_data in branch_data["departments"]:
                                dept_key = f"{inst_name}_{branch_data['name']}_{dept_data['name']}"
                                if not exists(Department, branch_id=branch_id, name=dept_data["name"]):
                                    dept = Department(
                                        id=str(uuid.uuid4()),
                                        branch_id=branch_id,
                                        name=dept_data["name"],
                                        sector=dept_data["sector"]
                                    )
                                    db.session.add(dept)
                                    db.session.flush()
                                    app.logger.debug(f"Departamento criado: {dept_data['name']} em {branch_data['name']}")
                                department_map[dept_key] = Department.query.filter_by(
                                    branch_id=branch_id, name=dept_data["name"]
                                ).first().id
                    app.logger.info("Departamentos criados ou recuperados com sucesso.")
                    return department_map

                department_map = create_departments()

                # --------------------------------------
                # Criar Filas
                # --------------------------------------
                def create_queues():
                    queue_map = {}
                    for inst_data in institutions_data:
                        inst_name = inst_data["name"]
                        for branch_data in inst_data["branches"]:
                            branch_id = branch_map[f"{inst_name}_{branch_data['name']}"]
                            for dept_data in branch_data["departments"]:
                                dept_id = department_map[f"{inst_name}_{branch_data['name']}_{dept_data['name']}"]
                                for queue_data in dept_data["queues"]:
                                    queue_key = f"{inst_name}_{branch_data['name']}_{dept_data['name']}_{queue_data['service_name']}"
                                    service_key = f"{inst_name}_{queue_data['service_name']}"
                                    if not exists(Queue, id=queue_data["id"]):
                                        queue = Queue(
                                            id=queue_data["id"],
                                            department_id=dept_id,
                                            service_id=service_map[service_key],
                                            prefix=queue_data["prefix"],
                                            daily_limit=queue_data["daily_limit"],
                                            num_counters=queue_data["num_counters"]
                                        )
                                        db.session.add(queue)
                                        db.session.flush()
                                        # Associar tags
                                        for tag_name in queue_data["tags"]:
                                            tag = ServiceTag.query.filter_by(name=tag_name).first()
                                            if tag and tag not in queue.tags:
                                                queue.tags.append(tag)
                                                db.session.flush()
                                        app.logger.debug(
                                            f"Fila criada: {queue_data['service_name']} em {dept_data['name']}, "
                                            f"filial {branch_data['name']}"
                                        )
                                    queue_map[queue_key] = queue_data["id"]
                    app.logger.info("Filas criadas ou recuperadas com sucesso.")
                    return queue_map

                queue_map = create_queues()

                # --------------------------------------
                # Criar Usuários
                # --------------------------------------
                def create_users():
                    user_map = {}
                    users_data = [
                        {
                            "id": "nMSnRc8jpYQbnrxujg5JZcHzFKP2",
                            "email": "edmannews5@gmail.com",
                            "password": "Teste@123",
                            "first_name": "Edman",
                            "last_name": "Silva",
                            "phone_number": "+244923456789",
                            "is_test_user": True
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "email": "joao.silva@example.com",
                            "password": "Senha@123",
                            "first_name": "João",
                            "last_name": "Silva",
                            "phone_number": "+244912345678",
                            "is_test_user": False
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "email": "maria.santos@example.com",
                            "password": "Senha@123",
                            "first_name": "Maria",
                            "last_name": "Santos",
                            "phone_number": "+244923456780",
                            "is_test_user": False
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "email": "pedro.gomes@example.com",
                            "password": "Senha@123",
                            "first_name": "Pedro",
                            "last_name": "Gomes",
                            "phone_number": "+244934567891",
                            "is_test_user": False
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "email": "ana.ferreira@example.com",
                            "password": "Senha@123",
                            "first_name": "Ana",
                            "last_name": "Ferreira",
                            "phone_number": "+244945678902",
                            "is_test_user": False
                        }
                    ]
                    for user_data in users_data:
                        if not exists(User, id=user_data["id"]):
                            user = User(
                                id=user_data["id"],
                                email=user_data["email"],
                                password=hash_password(user_data["password"]),
                                first_name=user_data["first_name"],
                                last_name=user_data["last_name"],
                                phone_number=user_data["phone_number"],
                                is_active=True,
                                created_at=datetime.utcnow(),
                                updated_at=datetime.utcnow()
                            )
                            db.session.add(user)
                            db.session.flush()
                            # Associar papel de cliente
                            client_role = UserRole.query.filter_by(name="client").first()
                            if client_role:
                                user.roles.append(client_role)
                                db.session.flush()
                            app.logger.debug(f"Usuário criado: {user_data['email']}")
                        user_map[user_data["email"]] = user_data["id"]
                    app.logger.info("Usuários criados ou recuperados com sucesso.")
                    return user_map

                user_map = create_users()

                # --------------------------------------
                # Criar Preferências de Usuários
                # --------------------------------------
                def create_user_preferences():
                    preferences_data = [
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "institution_id": institution_map["Conservatória dos Registos"],
                            "is_favorite": True,
                            "is_client": True
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "institution_id": institution_map["Hospital Josina Machel"],
                            "is_favorite": True,
                            "is_client": True
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "institution_id": institution_map["Banco BAI"],
                            "is_favorite": False,
                            "is_client": True
                        },
                        {
                            "user_id": user_map["joao.silva@example.com"],
                            "institution_id": institution_map["Banco BFA"],
                            "is_favorite": True,
                            "is_client": True
                        },
                        {
                            "user_id": user_map["joao.silva@example.com"],
                            "institution_id": institution_map["SIAC"],
                            "is_favorite": False,
                            "is_client": True
                        },
                        {
                            "user_id": user_map["maria.santos@example.com"],
                            "institution_id": institution_map["Clínica Sagrada Esperança"],
                            "is_favorite": True,
                            "is_client": True
                        },
                        {
                            "user_id": user_map["maria.santos@example.com"],
                            "institution_id": institution_map["Conservatória dos Registos"],
                            "is_favorite": False,
                            "is_client": True
                        },
                        {
                            "user_id": user_map["pedro.gomes@example.com"],
                            "institution_id": institution_map["Banco BIC"],
                            "is_favorite": True,
                            "is_client": True
                        },
                        {
                            "user_id": user_map["pedro.gomes@example.com"],
                            "institution_id": institution_map["Hospital Josina Machel"],
                            "is_favorite": False,
                            "is_client": True
                        },
                        {
                            "user_id": user_map["ana.ferreira@example.com"],
                            "institution_id": institution_map["Banco Keve"],
                            "is_favorite": True,
                            "is_client": True
                        },
                        {
                            "user_id": user_map["ana.ferreira@example.com"],
                            "institution_id": institution_map["SIAC"],
                            "is_favorite": False,
                            "is_client": True
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "branch_id": branch_map["Conservatória dos Registos_Conservatória Coqueiros"],
                            "is_favorite": True,
                            "is_client": True
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "branch_id": branch_map["Hospital Josina Machel_Unidade Prenda"],
                            "is_favorite": True,
                            "is_client": True
                        }
                    ]
                    for pref_data in preferences_data:
                        if not exists(
                            UserPreference,
                            user_id=pref_data["user_id"],
                            institution_id=pref_data.get("institution_id"),
                            branch_id=pref_data.get("branch_id")
                        ):
                            pref = UserPreference(
                                id=str(uuid.uuid4()),
                                user_id=pref_data["user_id"],
                                institution_id=pref_data.get("institution_id"),
                                branch_id=pref_data.get("branch_id"),
                                is_favorite=pref_data["is_favorite"],
                                is_client=pref_data["is_client"]
                            )
                            db.session.add(pref)
                            db.session.flush()
                            app.logger.debug(f"Preferência criada para usuário {pref_data['user_id']}")
                    app.logger.info("Preferências de usuários criadas ou recuperadas com sucesso.")

                create_user_preferences()

                # --------------------------------------
                # Criar Comportamentos de Usuários
                # --------------------------------------
                def create_user_behaviors():
                    behaviors_data = [
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "service_id": service_map["Conservatória dos Registos_Registo Civil"],
                            "interaction_count": 4,
                            "last_interaction": datetime.utcnow() - timedelta(days=1)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "service_id": service_map["Hospital Josina Machel_Consulta Geral"],
                            "interaction_count": 3,
                            "last_interaction": datetime.utcnow() - timedelta(days=2)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "service_id": service_map["Banco BAI_Atendimento Bancário"],
                            "interaction_count": 3,
                            "last_interaction": datetime.utcnow() - timedelta(days=3)
                        },
                        {
                            "user_id": user_map["joao.silva@example.com"],
                            "service_id": service_map["Banco BFA_Atendimento Bancário"],
                            "interaction_count": 2,
                            "last_interaction": datetime.utcnow() - timedelta(days=4)
                        },
                        {
                            "user_id": user_map["joao.silva@example.com"],
                            "service_id": service_map["SIAC_Emissão de BI"],
                            "interaction_count": 1,
                            "last_interaction": datetime.utcnow() - timedelta(days=5)
                        },
                        {
                            "user_id": user_map["maria.santos@example.com"],
                            "service_id": service_map["Clínica Sagrada Esperança_Consulta Especializada"],
                            "interaction_count": 2,
                            "last_interaction": datetime.utcnow() - timedelta(days=6)
                        },
                        {
                            "user_id": user_map["maria.santos@example.com"],
                            "service_id": service_map["Conservatória dos Registos_Registo Comercial"],
                            "interaction_count": 1,
                            "last_interaction": datetime.utcnow() - timedelta(days=7)
                        },
                        {
                            "user_id": user_map["pedro.gomes@example.com"],
                            "service_id": service_map["Banco BIC_Empréstimos"],
                            "interaction_count": 2,
                            "last_interaction": datetime.utcnow() - timedelta(days=8)
                        },
                        {
                            "user_id": user_map["pedro.gomes@example.com"],
                            "service_id": service_map["Hospital Josina Machel_Exames Laboratoriais"],
                            "interaction_count": 1,
                            "last_interaction": datetime.utcnow() - timedelta(days=9)
                        },
                        {
                            "user_id": user_map["ana.ferreira@example.com"],
                            "service_id": service_map["Banco Keve_Investimentos"],
                            "interaction_count": 2,
                            "last_interaction": datetime.utcnow() - timedelta(days=10)
                        },
                        {
                            "user_id": user_map["ana.ferreira@example.com"],
                            "service_id": service_map["SIAC_Renovação de Licenças"],
                            "interaction_count": 1,
                            "last_interaction": datetime.utcnow() - timedelta(days=11)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "branch_id": branch_map["Conservatória dos Registos_Conservatória Coqueiros"],
                            "interaction_count": 4,
                            "last_interaction": datetime.utcnow() - timedelta(days=1)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "branch_id": branch_map["Hospital Josina Machel_Unidade Prenda"],
                            "interaction_count": 3,
                            "last_interaction": datetime.utcnow() - timedelta(days=2)
                        }
                    ]
                    for behavior_data in behaviors_data:
                        if not exists(
                            UserBehavior,
                            user_id=behavior_data["user_id"],
                            service_id=behavior_data.get("service_id"),
                            branch_id=behavior_data.get("branch_id")
                        ):
                            behavior = UserBehavior(
                                id=str(uuid.uuid4()),
                                user_id=behavior_data["user_id"],
                                service_id=behavior_data.get("service_id"),
                                branch_id=behavior_data.get("branch_id"),
                                interaction_count=behavior_data["interaction_count"],
                                last_interaction=behavior_data["last_interaction"]
                            )
                            db.session.add(behavior)
                            db.session.flush()
                            app.logger.debug(f"Comportamento criado para usuário {behavior_data['user_id']}")
                    app.logger.info("Comportamentos de usuários criados ou recuperados com sucesso.")

                create_user_behaviors()

                # --------------------------------------
                # Criar Logs de Auditoria
                # --------------------------------------
                def create_audit_logs():
                    audit_logs_data = [
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "action": "create_ticket",
                            "description": "Usuário criou ticket para Registo Civil",
                            "timestamp": datetime.utcnow() - timedelta(days=1)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "action": "create_ticket",
                            "description": "Usuário criou ticket para Consulta Geral",
                            "timestamp": datetime.utcnow() - timedelta(days=2)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "action": "create_ticket",
                            "description": "Usuário criou ticket para Atendimento Bancário",
                            "timestamp": datetime.utcnow() - timedelta(days=3)
                        },
                        {
                            "user_id": user_map["joao.silva@example.com"],
                            "action": "create_ticket",
                            "description": "Usuário criou ticket para Atendimento Bancário",
                            "timestamp": datetime.utcnow() - timedelta(days=4)
                        },
                        {
                            "user_id": user_map["maria.santos@example.com"],
                            "action": "create_ticket",
                            "description": "Usuário criou ticket para Consulta Especializada",
                            "timestamp": datetime.utcnow() - timedelta(days=5)
                        },
                        {
                            "user_id": user_map["pedro.gomes@example.com"],
                            "action": "create_ticket",
                            "description": "Usuário criou ticket para Empréstimos",
                            "timestamp": datetime.utcnow() - timedelta(days=6)
                        },
                        {
                            "user_id": user_map["ana.ferreira@example.com"],
                            "action": "create_ticket",
                            "description": "Usuário criou ticket para Investimentos",
                            "timestamp": datetime.utcnow() - timedelta(days=7)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "action": "login",
                            "description": "Usuário fez login no sistema",
                            "timestamp": datetime.utcnow() - timedelta(days=1)
                        },
                        {
                            "user_id": user_map["joao.silva@example.com"],
                            "action": "login",
                            "description": "Usuário fez login no sistema",
                            "timestamp": datetime.utcnow() - timedelta(days=2)
                        },
                        {
                            "user_id": user_map["maria.santos@example.com"],
                            "action": "login",
                            "description": "Usuário fez login no sistema",
                            "timestamp": datetime.utcnow() - timedelta(days=3)
                        },
                        {
                            "user_id": user_map["pedro.gomes@example.com"],
                            "action": "login",
                            "description": "Usuário fez login no sistema",
                            "timestamp": datetime.utcnow() - timedelta(days=4)
                        },
                        {
                            "user_id": user_map["ana.ferreira@example.com"],
                            "action": "login",
                            "description": "Usuário fez login no sistema",
                            "timestamp": datetime.utcnow() - timedelta(days=5)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "action": "update_profile",
                            "description": "Usuário atualizou perfil",
                            "timestamp": datetime.utcnow() - timedelta(days=6)
                        },
                        {
                            "user_id": user_map["joao.silva@example.com"],
                            "action": "update_profile",
                            "description": "Usuário atualizou perfil",
                            "timestamp": datetime.utcnow() - timedelta(days=7)
                        },
                        {
                            "user_id": user_map["maria.santos@example.com"],
                            "action": "update_profile",
                            "description": "Usuário atualizou perfil",
                            "timestamp": datetime.utcnow() - timedelta(days=8)
                        },
                        {
                            "user_id": user_map["pedro.gomes@example.com"],
                            "action": "update_profile",
                            "description": "Usuário atualizou perfil",
                            "timestamp": datetime.utcnow() - timedelta(days=9)
                        },
                        {
                            "user_id": user_map["ana.ferreira@example.com"],
                            "action": "update_profile",
                            "description": "Usuário atualizou perfil",
                            "timestamp": datetime.utcnow() - timedelta(days=10)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "action": "view_queue",
                            "description": "Usuário visualizou fila de Registo Civil",
                            "timestamp": datetime.utcnow() - timedelta(days=1)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "action": "view_queue",
                            "description": "Usuário visualizou fila de Consulta Geral",
                            "timestamp": datetime.utcnow() - timedelta(days=2)
                        },
                        {
                            "user_id": user_map["joao.silva@example.com"],
                            "action": "view_queue",
                            "description": "Usuário visualizou fila de Atendimento Bancário",
                            "timestamp": datetime.utcnow() - timedelta(days=3)
                        },
                        {
                            "user_id": user_map["maria.santos@example.com"],
                            "action": "view_queue",
                            "description": "Usuário visualizou fila de Consulta Especializada",
                            "timestamp": datetime.utcnow() - timedelta(days=4)
                        },
                        {
                            "user_id": user_map["pedro.gomes@example.com"],
                            "action": "view_queue",
                            "description": "Usuário visualizou fila de Empréstimos",
                            "timestamp": datetime.utcnow() - timedelta(days=5)
                        }
                    ]
                    for log_data in audit_logs_data:
                        if not exists(AuditLog, user_id=log_data["user_id"], action=log_data["action"], timestamp=log_data["timestamp"]):
                            log = AuditLog(
                                id=str(uuid.uuid4()),
                                user_id=log_data["user_id"],
                                action=log_data["action"],
                                description=log_data["description"],
                                timestamp=log_data["timestamp"]
                            )
                            db.session.add(log)
                            db.session.flush()
                            app.logger.debug(f"Log de auditoria criado: {log_data['action']} para usuário {log_data['user_id']}")
                    app.logger.info("Logs de auditoria criados ou recuperados com sucesso.")

                create_audit_logs()

                # --------------------------------------
                # Criar Logs de Notificação
                # --------------------------------------
                def create_notification_logs():
                    notification_logs_data = [
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "message": "Seu ticket para Registo Civil foi emitido",
                            "sent_at": datetime.utcnow() - timedelta(days=1)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "message": "Seu ticket para Consulta Geral foi emitido",
                            "sent_at": datetime.utcnow() - timedelta(days=2)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "message": "Seu ticket para Atendimento Bancário foi emitido",
                            "sent_at": datetime.utcnow() - timedelta(days=3)
                        },
                        {
                            "user_id": user_map["joao.silva@example.com"],
                            "message": "Seu ticket para Atendimento Bancário foi emitido",
                            "sent_at": datetime.utcnow() - timedelta(days=4)
                        },
                        {
                            "user_id": user_map["maria.santos@example.com"],
                            "message": "Seu ticket para Consulta Especializada foi emitido",
                            "sent_at": datetime.utcnow() - timedelta(days=5)
                        },
                        {
                            "user_id": user_map["pedro.gomes@example.com"],
                            "message": "Seu ticket para Empréstimos foi emitido",
                            "sent_at": datetime.utcnow() - timedelta(days=6)
                        },
                        {
                            "user_id": user_map["ana.ferreira@example.com"],
                            "message": "Seu ticket para Investimentos foi emitido",
                            "sent_at": datetime.utcnow() - timedelta(days=7)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "message": "Seu ticket para Registo Civil foi atendido",
                            "sent_at": datetime.utcnow() - timedelta(days=1, minutes=10)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "message": "Seu ticket para Consulta Geral foi atendido",
                            "sent_at": datetime.utcnow() - timedelta(days=2, minutes=10)
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "message": "Seu ticket para Atendimento Bancário foi atendido",
                            "sent_at": datetime.utcnow() - timedelta(days=3, minutes=10)
                        },
                        {
                            "user_id": user_map["joao.silva@example.com"],
                            "message": "Seu ticket para Atendimento Bancário foi atendido",
                            "sent_at": datetime.utcnow() - timedelta(days=4, minutes=10)
                        },
                        {
                            "user_id": user_map["maria.santos@example.com"],
                            "message": "Seu ticket para Consulta Especializada foi atendido",
                            "sent_at": datetime.utcnow() - timedelta(days=5, minutes=10)
                        },
                        {
                            "user_id": user_map["ana.ferreira@example.com"],
                            "message": "Seu ticket para Investimentos foi atendido",
                            "sent_at": datetime.utcnow() - timedelta(days=7, minutes=10)
                        }
                    ]
                    for log_data in notification_logs_data:
                        if not exists(NotificationLog, user_id=log_data["user_id"], message=log_data["message"], sent_at=log_data["sent_at"]):
                            log = NotificationLog(
                                id=str(uuid.uuid4()),
                                user_id=log_data["user_id"],
                                message=log_data["message"],
                                sent_at=log_data["sent_at"]
                            )
                            db.session.add(log)
                            db.session.flush()
                            app.logger.debug(f"Log de notificação criado: {log_data['message']} para usuário {log_data['user_id']}")
                    app.logger.info("Logs de notificação criados ou recuperados com sucesso.")

                create_notification_logs()

                # --------------------------------------
                # Criar Localizações Alternativas de Usuários
                # --------------------------------------
                def create_user_location_fallbacks():
                    location_fallbacks_data = [
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "latitude": -8.8167,
                            "longitude": 13.2332,
                            "neighborhood": "Ingombota"
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "latitude": -8.8250,
                            "longitude": 13.2300,
                            "neighborhood": "Prenda"
                        },
                        {
                            "user_id": user_map["joao.silva@example.com"],
                            "latitude": -8.8147,
                            "longitude": 13.2302,
                            "neighborhood": "Maianga"
                        },
                        {
                            "user_id": user_map["maria.santos@example.com"],
                            "latitude": -8.8100,
                            "longitude": 13.2450,
                            "neighborhood": "Bairro Azul"
                        },
                        {
                            "user_id": user_map["pedro.gomes@example.com"],
                            "latitude": -8.8300,
                            "longitude": 13.2500,
                            "neighborhood": "Rangel"
                        },
                        {
                            "user_id": user_map["ana.ferreira@example.com"],
                            "latitude": -8.9333,
                            "longitude": 13.2000,
                            "neighborhood": "Belas"
                        },
                        {
                            "user_id": user_map["edmannews5@gmail.com"],
                            "latitude": -8.8050,
                            "longitude": 13.2300,
                            "neighborhood": "Coqueiros"
                        },
                        {
                            "user_id": user_map["joao.silva@example.com"],
                            "latitude": -8.9167,
                            "longitude": 13.1833,
                            "neighborhood": "Talatona"
                        }
                    ]
                    for loc_data in location_fallbacks_data:
                        if not exists(
                            UserLocationFallback,
                            user_id=loc_data["user_id"],
                            latitude=loc_data["latitude"],
                            longitude=loc_data["longitude"]
                        ):
                            loc = UserLocationFallback(
                                id=str(uuid.uuid4()),
                                user_id=loc_data["user_id"],
                                latitude=loc_data["latitude"],
                                longitude=loc_data["longitude"],
                                neighborhood=loc_data["neighborhood"]
                            )
                            db.session.add(loc)
                            db.session.flush()
                            app.logger.debug(f"Localização alternativa criada para usuário {loc_data['user_id']}: {loc_data['neighborhood']}")
                    app.logger.info("Localizações alternativas de usuários criadas ou recuperadas com sucesso.")

                create_user_location_fallbacks()

                # --------------------------------------
                # Criar Tickets
                # --------------------------------------
                def create_tickets():
                    # Função auxiliar para gerar QR code único
                    def generate_unique_qr_code():
                        while True:
                            qr_code = str(uuid.uuid4())[:8].upper()
                            if not exists(Ticket, qr_code=qr_code):
                                return qr_code

                    # Função auxiliar para validar horário do ticket
                    def get_valid_ticket_time(queue_id, base_date):
                        queue = Queue.query.get(queue_id)
                        branch = Branch.query.join(Department).filter(Department.id == queue.department_id).first()
                        schedule = BranchSchedule.query.filter_by(
                            branch_id=branch.id,
                            weekday_id=base_date.isoweekday()
                        ).first()
                        if schedule.is_closed:
                            # Tentar o dia anterior
                            new_date = base_date - timedelta(days=1)
                            while new_date.isoweekday() == base_date.isoweekday() or \
                                  BranchSchedule.query.filter_by(
                                      branch_id=branch.id,
                                      weekday_id=new_date.isoweekday()
                                  ).first().is_closed:
                                new_date -= timedelta(days=1)
                            base_date = new_date
                            schedule = BranchSchedule.query.filter_by(
                                branch_id=branch.id,
                                weekday_id=base_date.isoweekday()
                            ).first()
                        open_time = schedule.open_time
                        end_time = schedule.end_time
                        # Gerar hora aleatória dentro do horário operacional
                        open_minutes = open_time.hour * 60 + open_time.minute
                        end_minutes = end_time.hour * 60 + end_time.minute
                        random_minutes = random.randint(open_minutes, end_minutes - 10)
                        ticket_time = datetime(
                            base_date.year, base_date.month, base_date.day,
                            random_minutes // 60, random_minutes % 60
                        )
                        return ticket_time

                    # Criar tickets específicos para o usuário de teste
                    test_user_tickets = [
                        # 4 tickets para Registo Civil (Conservatória)
                        {
                            "queue_key": "Conservatória dos Registos_Conservatória Coqueiros_Atendimento Registral_Registo Civil",
                            "count": 2
                        },
                        {
                            "queue_key": "Conservatória dos Registos_Conservatória Futungo de Belas_Atendimento Registral_Registo Civil",
                            "count": 2
                        },
                        # 3 tickets para Consulta Geral (Hospital Josina Machel)
                        {
                            "queue_key": "Hospital Josina Machel_Unidade Prenda_Clínica Geral_Consulta Geral",
                            "count": 2
                        },
                        {
                            "queue_key": "Hospital Josina Machel_Unidade Mutamba_Clínica Geral_Consulta Geral",
                            "count": 1
                        },
                        # 3 tickets para Atendimento Bancário (Banco BAI)
                        {
                            "queue_key": "Banco BAI_Agência Ingombota_Atendimento ao Cliente_Atendimento Bancário",
                            "count": 2
                        },
                        {
                            "queue_key": "Banco BAI_Agência Talatona_Atendimento ao Cliente_Atendimento Bancário",
                            "count": 1
                        }
                    ]

                    test_user_id = user_map["edmannews5@gmail.com"]
                    ticket_count = 0
                    used_queues = set()

                    for ticket_data in test_user_tickets:
                        queue_id = queue_map[ticket_data["queue_key"]]
                        if queue_id in used_queues:
                            continue  # Evitar múltiplos tickets na mesma fila
                        for i in range(ticket_data["count"]):
                            base_date = datetime.utcnow() - timedelta(days=i + 1)
                            issued_at = get_valid_ticket_time(queue_id, base_date)
                            ticket = Ticket(
                                id=str(uuid.uuid4()),
                                queue_id=queue_id,
                                user_id=test_user_id,
                                ticket_number=f"{Queue.query.get(queue_id).prefix}{1000 + ticket_count:04d}",
                                qr_code=generate_unique_qr_code(),
                                issued_at=issued_at,
                                attended_at=issued_at + timedelta(minutes=10),
                                expires_at=issued_at.replace(hour=23, minute=59, second=59) + timedelta(days=1),
                                status="Atendido",
                                counter_number=random.randint(1, Queue.query.get(queue_id).num_counters)
                            )
                            db.session.add(ticket)
                            db.session.flush()
                            ticket_count += 1
                            used_queues.add(queue_id)
                            app.logger.debug(
                                f"Ticket criado para usuário de teste: {ticket.ticket_number} em {ticket_data['queue_key']}"
                            )

                    # Criar 10 tickets por fila, distribuindo entre usuários
                    for queue_key, queue_id in queue_map.items():
                        existing_tickets = Ticket.query.filter_by(queue_id=queue_id).count()
                        tickets_needed = 10 - existing_tickets
                        if tickets_needed <= 0:
                            continue
                        user_ids = list(user_map.values())
                        random.shuffle(user_ids)
                        user_index = 0
                        for i in range(tickets_needed):
                            user_id = user_ids[user_index % len(user_ids)]
                            # Verificar se o usuário já tem ticket nessa fila
                            if Ticket.query.filter_by(queue_id=queue_id, user_id=user_id).count() > 0:
                                user_index += 1
                                continue
                            base_date = datetime.utcnow() - timedelta(days=i + 1)
                            issued_at = get_valid_ticket_time(queue_id, base_date)
                            ticket = Ticket(
                                id=str(uuid.uuid4()),
                                queue_id=queue_id,
                                user_id=user_id,
                                ticket_number=f"{Queue.query.get(queue_id).prefix}{1000 + ticket_count:04d}",
                                qr_code=generate_unique_qr_code(),
                                issued_at=issued_at,
                                attended_at=issued_at + timedelta(minutes=10),
                                expires_at=issued_at.replace(hour=23, minute=59, second=59) + timedelta(days=1),
                                status="Atendido",
                                counter_number=random.randint(1, Queue.query.get(queue_id).num_counters)
                            )
                            db.session.add(ticket)
                            db.session.flush()
                            ticket_count += 1
                            user_index += 1
                            app.logger.debug(f"Ticket criado: {ticket.ticket_number} em {queue_key}")
                    app.logger.info(f"Tickets criados com sucesso. Total: {ticket_count}")

                create_tickets()

                # --------------------------------------
                # Commit Final
                # --------------------------------------
                db.session.commit()
                app.logger.info("População de dados iniciais concluída com sucesso.")
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro durante população de dados: {str(e)}")
            raise
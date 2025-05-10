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
                        {"name": "Bancário", "description": "Serviços financeiros e bancários", "logo_url": "https://example.com/icons/bank.png"},
                        {"name": "Saúde", "description": "Serviços de saúde e atendimento médico", "logo_url": "https://image.similarpng.com/file/similarpng/very-thumbnail/2020/07/health-care-medical-concept-vector-PNG.png"},
                        {"name": "Administrativo", "description": "Serviços administrativos e atendimento ao cidadão", "logo_url": "https://example.com/icons/admin.png"},
                        {"name": "Educação", "description": "Serviços educacionais e acadêmicos", "logo_url": "https://img.freepik.com/vetores-premium/design-de-logotipo-da-escola-de-educacao_586739-1339.jpg?w=360"},
                        {"name": "Transportes", "description": "Serviços de transporte e logística", "logo_url": "https://www.pensamentoverde.com.br/wp-content/uploads/2022/08/quais-sao-os-meios-de-transportes-mais-sustentaveis-1.png"},
                        {"name": "Comercial", "description": "Serviços comerciais e varejo", "logo_url": "https://example.com/icons/commercial.png"}
                    ]
                    type_map = {}
                    for inst_type in types:
                        if not exists(InstitutionType, name=inst_type["name"]):
                            it = InstitutionType(
                                id=str(uuid.uuid4()),
                                name=inst_type["name"],
                                description=inst_type["description"],
                                logo_url=inst_type["logo_url"]
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
                    {"name": "Rangel", "latitude": -8.8300, "longitude": 13.2500},
                    {"name": "Samba", "latitude": -8.8200, "longitude": 13.2400},
                    {"name": "Cacuaco", "latitude": -8.7767, "longitude": 13.3667},
                    {"name": "Benfica", "latitude": -8.9500, "longitude": 13.1500},
                    {"name": "Zango", "latitude": -8.9200, "longitude": 13.4000},
                    {"name": "Patriota", "latitude": -8.9000, "longitude": 13.2000},
                    {"name": "Golfe", "latitude": -8.8700, "longitude": 13.2700},
                    {"name": "Camama", "latitude": -8.8900, "longitude": 13.2400},
                    {"name": "Prenda", "latitude": -8.8300, "longitude": 13.2300},
                    {"name": "Vila Alice", "latitude": -8.8200, "longitude": 13.2600},
                    {"name": "Rocha Pinto", "latitude": -8.8400, "longitude": 13.2500},
                    {"name": "Sambizanga", "latitude": -8.8000, "longitude": 13.2400},
                    {"name": "Neves Bendinha", "latitude": -8.8100, "longitude": 13.2500},
                    {"name": "Maculusso", "latitude": -8.8150, "longitude": 13.2350},
                    {"name": "Alvalade", "latitude": -8.8250, "longitude": 13.2300},
                    {"name": "Miramar", "latitude": -8.8100, "longitude": 13.2200},
                    {"name": "Bairro Operário", "latitude": -8.8200, "longitude": 13.2450},
                    {"name": "Cassenda", "latitude": -8.8350, "longitude": 13.2400},
                    {"name": "Bairro Azul", "latitude": -8.8000, "longitude": 13.2300},
                    {"name": "Hoji Ya Henda", "latitude": -8.8500, "longitude": 13.2900},
                    {"name": "Palanca", "latitude": -8.8600, "longitude": 13.2800},
                    {"name": "Tala Hady", "latitude": -8.8450, "longitude": 13.2750},
                    {"name": "Kikolo", "latitude": -8.7800, "longitude": 13.3600},
                    {"name": "Morro Bento", "latitude": -8.9100, "longitude": 13.1900},
                    {"name": "Nova Vida", "latitude": -8.8800, "longitude": 13.2600},
                    {"name": "Funda", "latitude": -8.7600, "longitude": 13.3800},
                    {"name": "Sapú", "latitude": -8.8700, "longitude": 13.2500},
                    {"name": "Bairro Popular", "latitude": -8.8300, "longitude": 13.2600},
                    {"name": "Valódia", "latitude": -8.8400, "longitude": 13.2400}
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
                        "logo_url": "https://www.bancobai.ao/media/1635/icones-104.png",
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
                        "logo_url": "https://mir-s3-cdn-cf.behance.net/projects/404/34bf0d202655285.Y3JvcCwxMTYyLDkwOSwxOTUsMA.png",
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
                        "logo_url": "https://d1yjjnpx0p53s8.cloudfront.net/styles/logo-thumbnail/s3/042016/untitled-1_14.png?itok=KwyRI5ev",
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
                                "latitude": -8.8200,
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
                                "name": "Agência Cacuaco",
                                "location": "Rua Principal, Cacuaco, Luanda",
                                "neighborhood": "Cacuaco",
                                "latitude": -8.7767,
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
                        "logo_url": "https://d1yjjnpx0p53s8.cloudfront.net/styles/logo-thumbnail/s3/112013/keve_0.png?itok=zvzyUwOa",
                        "services": [
                            {"name": "Atendimento Bancário", "category_id": category_map["Conta"], "description": "Gestão de contas"},
                            {"name": "Empréstimos", "category_id": category_map["Empréstimo"], "description": "Empréstimos pessoais e empresariais"},
                            {"name": "Investimentos", "category_id": category_map["Investimento"], "description": "Consultoria de investimentos"}
                        ],
                        "branches": [
                            {
                                "name": "Agência Benfica",
                                "location": "Rua Principal, Benfica, Luanda",
                                "neighborhood": "Benfica",
                                "latitude": -8.9500,
                                "longitude": 13.1500,
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
                                "name": "Agência Zango",
                                "location": "Rua Principal, Zango, Luanda",
                                "neighborhood": "Zango",
                                "latitude": -8.9200,
                                "longitude": 13.4000,
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
                                "name": "Agência Patriota",
                                "location": "Rua Principal, Patriota, Luanda",
                                "neighborhood": "Patriota",
                                "latitude": -8.9000,
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
                            }
                        ]
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Hospital Josina Machel",
                        "description": "Serviços de saúde públicos em Luanda",
                        "institution_type_id": institution_type_map["Saúde"],
                        "logo_url": "https://www.hospitaljosinamachel.ao/images/logo.png",
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
                            },
                            {
                                "name": "Unidade Golfe",
                                "location": "Rua Principal, Golfe, Luanda",
                                "neighborhood": "Golfe",
                                "latitude": -8.8700,
                                "longitude": 13.2700,
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
                                "name": "Unidade Camama",
                                "location": "Rua Principal, Camama, Luanda",
                                "neighborhood": "Camama",
                                "latitude": -8.8900,
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
                        "logo_url": "https://www.clinicasagradaesperanca.ao/images/logo.png",
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
                                "name": "Unidade Prenda",
                                "location": "Rua Principal, Prenda, Luanda",
                                "neighborhood": "Prenda",
                                "latitude": -8.8300,
                                "longitude": 13.2300,
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
                                "name": "Unidade Vila Alice",
                                "location": "Rua Principal, Vila Alice, Luanda",
                                "neighborhood": "Vila Alice",
                                "latitude": -8.8200,
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
                                "name": "Unidade Rocha Pinto",
                                "location": "Rua Principal, Rocha Pinto, Luanda",
                                "neighborhood": "Rocha Pinto",
                                "latitude": -8.8400,
                                "longitude": 13.2500,
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
                                "name": "Unidade Sambizanga",
                                "location": "Rua Principal, Sambizanga, Luanda",
                                "neighborhood": "Sambizanga",
                                "latitude": -8.8000,
                                "longitude": 13.2400,
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
                        "logo_url": "https://www.siac.gv.ao/images/site/SIAC_logotipo.jpg",
                        "services": [
                            {"name": "Emissão de BI", "category_id": category_map["Documentos"], "description": "Emissão de bilhete de identidade"},
                            {"name": "Registo Civil", "category_id": category_map["Registros"], "description": "Registos civis"},
                            {"name": "Renovação de Licenças", "category_id": category_map["Licenças"], "description": "Renovação de licenças administrativas"}
                        ],
                        "branches": [
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
                            },
                            {
                                "name": "SIAC Samba",
                                "location": "Rua Principal, Samba, Luanda",
                                "neighborhood": "Samba",
                                "latitude": -8.8200,
                                "longitude": 13.2400,
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
                                "name": "SIAC Cacuaco",
                                "location": "Rua Principal, Cacuaco, Luanda",
                                "neighborhood": "Cacuaco",
                                "latitude": -8.7767,
                                "longitude": 13.3667,
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
                                "name": "SIAC Benfica",
                                "location": "Rua Principal, Benfica, Luanda",
                                "neighborhood": "Benfica",
                                "latitude": -8.9500,
                                "longitude": 13.1500,
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
                                "name": "SIAC Zango",
                                "location": "Rua Principal, Zango, Luanda",
                                "neighborhood": "Zango",
                                "latitude": -8.9200,
                                "longitude": 13.4000,
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
                                "name": "SIAC Patriota",
                                "location": "Rua Principal, Patriota, Luanda",
                                "neighborhood": "Patriota",
                                "latitude": -8.9000,
                                "longitude": 13.2000,
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
                                "name": "SIAC Golfe",
                                "location": "Rua Principal, Golfe, Luanda",
                                "neighborhood": "Golfe",
                                "latitude": -8.8700,
                                "longitude": 13.2700,
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
                                "name": "SIAC Camama",
                                "location": "Rua Principal, Camama, Luanda",
                                "neighborhood": "Camama",
                                "latitude": -8.8900,
                                "longitude": 13.2400,
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
                                "name": "SIAC Prenda",
                                "location": "Rua Principal, Prenda, Luanda",
                                "neighborhood": "Prenda",
                                "latitude": -8.8300,
                                "longitude": 13.2300,
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
                                "name": "SIAC Vila Alice",
                                "location": "Rua Principal, Vila Alice, Luanda",
                                "neighborhood": "Vila Alice",
                                "latitude": -8.8200,
                                "longitude": 13.2600,
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
                # Hospital Geral de Luanda
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Hospital Geral de Luanda",
                        "description": "Serviços de saúde públicos em Luanda",
                        "institution_type_id": institution_type_map["Saúde"],
                        "logo_url": "https://www.hospitalgeralluanda.ao/images/logo.png",
                        "services": [
                            {"name": "Consulta Geral", "category_id": category_map["Consulta Médica"], "description": "Consultas médicas gerais"},
                            {"name": "Exames Laboratoriais", "category_id": category_map["Exames"], "description": "Exames de diagnóstico"},
                            {"name": "Triagem", "category_id": category_map["Triagem"], "description": "Atendimento inicial e triagem"},
                            {"name": "Internamento", "category_id": category_map["Internamento"], "description": "Serviços de internamento hospitalar"},
                            {"name": "Cirurgia de Urgência", "category_id": category_map["Cirurgia"], "description": "Cirurgias de emergência"}
                        ],
                        "branches": [
                            {
                                "name": "Unidade Alvalade",
                                "location": "Rua Principal, Alvalade, Luanda",
                                "neighborhood": "Alvalade",
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
                                "name": "Unidade Miramar",
                                "location": "Rua Principal, Miramar, Luanda",
                                "neighborhood": "Miramar",
                                "latitude": -8.8100,
                                "longitude": 13.2200,
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
                                "name": "Unidade Bairro Operário",
                                "location": "Rua Principal, Bairro Operário, Luanda",
                                "neighborhood": "Bairro Operário",
                                "latitude": -8.8200,
                                "longitude": 13.2450,
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
                                "name": "Unidade Cassenda",
                                "location": "Rua Principal, Cassenda, Luanda",
                                "neighborhood": "Cassenda",
                                "latitude": -8.8350,
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
                                "name": "Unidade Bairro Azul",
                                "location": "Rua Principal, Bairro Azul, Luanda",
                                "neighborhood": "Bairro Azul",
                                "latitude": -8.8000,
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
                                "name": "Unidade Hoji Ya Henda",
                                "location": "Rua Principal, Hoji Ya Henda, Luanda",
                                "neighborhood": "Hoji Ya Henda",
                                "latitude": -8.8500,
                                "longitude": 13.2900,
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
                                "name": "Unidade Palanca",
                                "location": "Rua Principal, Palanca, Luanda",
                                "neighborhood": "Palanca",
                                "latitude": -8.8600,
                                "longitude": 13.2800,
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
                                "name": "Unidade Tala Hady",
                                "location": "Rua Principal, Tala Hady, Luanda",
                                "neighborhood": "Tala Hady",
                                "latitude": -8.8450,
                                "longitude": 13.2750,
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
                                "name": "Unidade Kikolo",
                                "location": "Rua Principal, Kikolo, Luanda",
                                "neighborhood": "Kikolo",
                                "latitude": -8.7800,
                                "longitude": 13.3600,
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
                                "name": "Unidade Morro Bento",
                                "location": "Rua Principal, Morro Bento, Luanda",
                                "neighborhood": "Morro Bento",
                                "latitude": -8.9100,
                                "longitude": 13.1900,
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
                        "name": "Conservatória dos Registos",
                        "description": "Serviços de registo civil e comercial em Luanda",
                        "institution_type_id": institution_type_map["Administrativo"],
                        "logo_url": "https://www.conservatoriaregistros.gov.ao/images/logo.png",
                        "services": [
                            {"name": "Registo Comercial", "category_id": category_map["Registros"], "description": "Registo de empresas"},
                            {"name": "Registo Civil", "category_id": category_map["Registros"], "description": "Registo de nascimento, casamento e óbito"},
                            {"name": "Autenticação de Documentos", "category_id": category_map["Documentos"], "description": "Autenticação de documentos oficiais"}
                        ],
                        "branches": [
                            {
                                "name": "Conservatória Ingombota",
                                "location": "Rua Rainha Ginga, Ingombota, Luanda",
                                "neighborhood": "Ingombota",
                                "latitude": -8.8167,
                                "longitude": 13.2332,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Talatona",
                                "location": "Via Expressa, Talatona, Luanda",
                                "neighborhood": "Talatona",
                                "latitude": -8.9180,
                                "longitude": 13.1840,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Viana",
                                "location": "Rua Principal, Viana, Luanda",
                                "neighborhood": "Viana",
                                "latitude": -8.9040,
                                "longitude": 13.3750,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Kilamba",
                                "location": "Avenida do Kilamba, Kilamba, Luanda",
                                "neighborhood": "Kilamba",
                                "latitude": -8.9340,
                                "longitude": 13.2670,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Cazenga",
                                "location": "Avenida dos Combatentes, Cazenga, Luanda",
                                "neighborhood": "Cazenga",
                                "latitude": -8.8510,
                                "longitude": 13.2840,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Maianga",
                                "location": "Rua Joaquim Kapango, Maianga, Luanda",
                                "neighborhood": "Maianga",
                                "latitude": -8.8150,
                                "longitude": 13.2310,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
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
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Samba",
                                "location": "Rua Principal, Samba, Luanda",
                                "neighborhood": "Samba",
                                "latitude": -8.8200,
                                "longitude": 13.2400,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Cacuaco",
                                "location": "Rua Principal, Cacuaco, Luanda",
                                "neighborhood": "Cacuaco",
                                "latitude": -8.7767,
                                "longitude": 13.3667,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Benfica",
                                "location": "Rua Principal, Benfica, Luanda",
                                "neighborhood": "Benfica",
                                "latitude": -8.9500,
                                "longitude": 13.1500,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Zango",
                                "location": "Rua Principal, Zango, Luanda",
                                "neighborhood": "Zango",
                                "latitude": -8.9200,
                                "longitude": 13.4000,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Patriota",
                                "location": "Rua Principal, Patriota, Luanda",
                                "neighborhood": "Patriota",
                                "latitude": -8.9000,
                                "longitude": 13.2000,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Golfe",
                                "location": "Rua Principal, Golfe, Luanda",
                                "neighborhood": "Golfe",
                                "latitude": -8.8700,
                                "longitude": 13.2700,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Camama",
                                "location": "Rua Principal, Camama, Luanda",
                                "neighborhood": "Camama",
                                "latitude": -8.8900,
                                "longitude": 13.2400,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Conservatória Prenda",
                                "location": "Rua Principal, Prenda, Luanda",
                                "neighborhood": "Prenda",
                                "latitude": -8.8300,
                                "longitude": 13.2300,
                                "departments": [
                                    {
                                        "name": "Atendimento Administrativo",
                                        "sector": "Administrativo",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Comercial",
                                                "prefix": "RC",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo Civil",
                                                "prefix": "RV",
                                                "daily_limit": 120,
                                                "num_counters": 5,
                                                "tags": ["Administrativo", "Registros", "24h"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Autenticação de Documentos",
                                                "prefix": "AD",
                                                "daily_limit": 80,
                                                "num_counters": 3,
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

                def create_branch_schedules(branch_id, institution_type, is_24h=False):
                    weekdays = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY, Weekday.SATURDAY, Weekday.SUNDAY]
                    for day in weekdays:
                        if not exists(BranchSchedule, branch_id=branch_id, weekday=day):
                            if institution_type == "Saúde":
                                open_time = time(0, 0) if is_24h else time(8, 0)
                                end_time = time(23, 59) if is_24h else time(17, 0)
                            elif institution_type == "Administrativo":
                                open_time = time(0, 0) if is_24h else time(8, 0)
                                end_time = time(23, 59) if is_24h else time(16, 0)
                            else:  # Bancário
                                open_time = time(0, 0) if is_24h else time(8, 0)
                                end_time = time(23, 59) if is_24h else time(15, 0)
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
                            institution_type_id=inst_data["institution_type_id"],
                            logo_url=inst_data["logo_url"]
                        )
                        db.session.add(i)
                        db.session.flush()
                        app.logger.debug(f"Instituição criada: {inst_data['name']}")
                        create_institution_services(i.id, inst_data["services"])
                        for branch_data in inst_data["branches"]:
                            create_branch(i.id, branch_data, institution_type)
                        return i
                    i = Institution.query.filter_by(name=inst_data["name"]).first()
                    i.logo_url = inst_data["logo_url"]
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

                    # Usuários regulares
                    for i in range(4):
                        email = f"user_{i+1}@queue.com"
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
                    test_user = User.query.filter_by(id="nMSnRc8jpYQbnrxujg5JZcHzFKP2").first()
                    if test_user:
                        test_prefs = [
                            {
                                "institution_name": "Conservatória dos Registos",
                                "neighborhood": "Ingombota",
                                "is_client": True,
                                "is_favorite": True,
                                "visit_count": 10,
                                "preference_score": 80
                            },
                            {
                                "institution_name": "Hospital Josina Machel",
                                "neighborhood": "Maianga",
                                "is_client": True,
                                "is_favorite": False,
                                "visit_count": 5,
                                "preference_score": 60
                            },
                            {
                                "institution_name": "Banco BAI",
                                "neighborhood": "Talatona",
                                "is_client": True,
                                "is_favorite": False,
                                "visit_count": 3,
                                "preference_score": 50
                            }
                        ]
                        for pref in test_prefs:
                            inst = Institution.query.filter_by(name=pref["institution_name"]).first()
                            if not inst:
                                app.logger.warning(f"Instituição {pref['institution_name']} não encontrada para preferência do usuário {test_user.id}")
                                continue
                            if not exists(UserPreference, user_id=test_user.id, institution_id=inst.id):
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
                                app.logger.debug(f"Preferência criada para usuário {test_user.id}: {pref['institution_name']}")
                            else:
                                app.logger.debug(f"Preferência já existe para usuário {test_user.id}: {pref['institution_name']}")

                    # Preferências para outros usuários
                    regular_users = User.query.filter(User.id != test_user.id).all()
                    for user in regular_users:
                        prefs = [
                            {
                                "institution_name": "Conservatória dos Registos",
                                "neighborhood": "Talatona",
                                "is_client": True,
                                "is_favorite": False,
                                "visit_count": 3,
                                "preference_score": 50
                            },
                            {
                                "institution_name": "Banco BFA",
                                "neighborhood": "Maianga",
                                "is_client": True,
                                "is_favorite": True,
                                "visit_count": 4,
                                "preference_score": 60
                            }
                        ]
                        for pref in prefs:
                            inst = Institution.query.filter_by(name=pref["institution_name"]).first()
                            if not inst:
                                app.logger.warning(f"Instituição {pref['institution_name']} não encontrada para preferência do usuário {user.id}")
                                continue
                            if not exists(UserPreference, user_id=user.id, institution_id=inst.id):
                                up = UserPreference(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
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
                                app.logger.debug(f"Preferência criada para usuário {user.id}: {pref['institution_name']}")
                            else:
                                app.logger.debug(f"Preferência já existe para usuário {user.id}: {pref['institution_name']}")

                    db.session.flush()
                    app.logger.info("Preferências de usuário criadas ou recuperadas com sucesso.")

                create_user_preferences()

                # --------------------------------------
                # Criar Tickets (10 por fila, todos 'Atendido')
                # --------------------------------------
                def create_tickets():
                    now = datetime.utcnow()
                    queues = Queue.query.all()
                    for queue in queues:
                        # Verificar se já existem tickets suficientes
                        existing_tickets = Ticket.query.filter_by(queue_id=queue.id).count()
                        if existing_tickets >= 10:
                            app.logger.debug(f"Fila {queue.id} já possui {existing_tickets} tickets. Pulando criação.")
                            continue
                            
                        # Criar 10 tickets por fila
                        for i in range(10 - existing_tickets):
                            # Armazenar apenas o número como inteiro
                            ticket_number = i + 1
                            # Usar o prefixo apenas para exibição/QR code
                            display_number = f"{queue.prefix}{i+1:03d}"
                            qr_code = f"QR_{display_number}_{queue.id[:8]}"
                            
                            if not exists(Ticket, queue_id=queue.id, ticket_number=ticket_number):
                                t = Ticket(
                                    id=str(uuid.uuid4()),
                                    queue_id=queue.id,
                                    user_id=users[i % len(users)].id,
                                    ticket_number=ticket_number,  # Número inteiro
                                    qr_code=qr_code,
                                    status="Atendido",
                                    issued_at=now - timedelta(days=1, hours=i),
                                    attended_at=now - timedelta(days=1, hours=i, minutes=5),
                                    counter=(i % queue.num_counters) + 1,
                                    service_time=5.0,
                                    trade_available=False
                                )
                                db.session.add(t)
                                app.logger.debug(f"Ticket criado: {display_number} para fila {queue.id}")
                        db.session.flush()
                    app.logger.info("Tickets criados ou recuperados com sucesso.")
                create_tickets()

                # --------------------------------------
                # Criar Comportamento de Usuário
                # --------------------------------------
                def create_user_behavior():
                    now = datetime.utcnow()
                    for user in users:
                        behaviors = [
                            {
                                "action": "queue_selected",
                                "value": "Registo Comercial",
                                "timestamp": now - timedelta(days=2)
                            },
                            {
                                "action": "branch_visited",
                                "value": "Conservatória Ingombota",
                                "timestamp": now - timedelta(days=1)
                            }
                        ]
                        for behavior in behaviors:
                            # Mapear 'value' para os campos corretos
                            service_id = None
                            branch_id = None
                            institution_id = None
                            if behavior["action"] == "queue_selected":
                                service = InstitutionService.query.filter_by(name=behavior["value"]).first()
                                if service:
                                    service_id = service.id
                                    institution_id = service.institution_id
                            elif behavior["action"] == "branch_visited":
                                branch = Branch.query.filter_by(name=behavior["value"]).first()
                                if branch:
                                    branch_id = branch.id
                                    institution_id = branch.institution_id

                            if not exists(UserBehavior, user_id=user.id, action=behavior["action"], 
                                        service_id=service_id, branch_id=branch_id):
                                ub = UserBehavior(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    institution_id=institution_id,
                                    service_id=service_id,
                                    branch_id=branch_id,
                                    action=behavior["action"],
                                    timestamp=behavior["timestamp"]
                                )
                                db.session.add(ub)
                                app.logger.debug(f"Comportamento criado para usuário {user.id}: {behavior['action']} - {behavior['value']}")
                            else:
                                app.logger.debug(f"Comportamento já existe para usuário {user.id}: {behavior['action']} - {behavior['value']}")
                        db.session.flush()
                    app.logger.info("Comportamentos de usuário criados ou recuperados com sucesso.")
                create_user_behavior()

                # --------------------------------------
                # Criar Localização de Fallback
                # --------------------------------------
                def create_user_location_fallback():
                    now = datetime.utcnow()
                    for user in users:
                        if not exists(UserLocationFallback, user_id=user.id):
                            ulf = UserLocationFallback(
                                id=str(uuid.uuid4()),
                                user_id=user.id,
                                neighborhood="Ingombota",
                                address="Ingombota, Luanda",
                                updated_at=now
                            )
                            db.session.add(ulf)
                            app.logger.debug(f"Localização de fallback criada para usuário {user.id}: Ingombota")
                        else:
                            app.logger.debug(f"Localização de fallback já existe para usuário {user.id}")
                    db.session.flush()
                    app.logger.info("Localizações de fallback criadas ou recuperadas com sucesso.")
                create_user_location_fallback()

                # --------------------------------------
                # Criar Logs de Notificação
                # --------------------------------------
                def create_notification_logs():
                    now = datetime.utcnow()
                    for user in users:
                        branch = Branch.query.filter_by(name="Conservatória Ingombota").first()
                        queue = Queue.query.join(InstitutionService).filter(InstitutionService.name=="Registo Comercial").first()
                        notifications = [
                            {
                                "message": "Seu ticket foi emitido com sucesso (ticket_issued).",
                                "sent_at": now - timedelta(days=1)
                            },
                            {
                                "message": "Seu ticket foi chamado. Dirija-se ao balcão (ticket_called).",
                                "sent_at": now - timedelta(days=1, hours=1)
                            }
                        ]
                        for notif in notifications:
                            if not exists(NotificationLog, user_id=user.id, message=notif["message"], sent_at=notif["sent_at"]):
                                nl = NotificationLog(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    branch_id=branch.id if branch else None,
                                    queue_id=queue.id if queue else None,
                                    message=notif["message"],
                                    sent_at=notif["sent_at"],
                                    status="Delivered"
                                )
                                db.session.add(nl)
                                app.logger.debug(f"Notificação criada para usuário {user.id}: {notif['message']}")
                            else:
                                app.logger.debug(f"Notificação já existe para usuário {user.id}: {notif['message']}")
                        db.session.flush()
                    app.logger.info("Logs de notificação criados ou recuperados com sucesso.")
                create_notification_logs()

                # --------------------------------------
                # Criar Logs de Auditoria
                # --------------------------------------
                def create_audit_logs():
                    now = datetime.utcnow()
                    for user in users:
                        audits = [
                            {
                                "action": "user_login",
                                "details": f"Usuário {user.email} fez login no sistema.",
                                "timestamp": now - timedelta(days=2),
                                "resource_type": "user",
                                "resource_id": user.id
                            },
                            {
                                "action": "ticket_issued",
                                "details": f"Usuário {user.email} emitiu um ticket.",
                                "timestamp": now - timedelta(days=1),
                                "resource_type": "ticket",
                                "resource_id": str(uuid.uuid4())
                            }
                        ]
                        for audit in audits:
                            if not exists(AuditLog, user_id=user.id, action=audit["action"], details=audit["details"]):
                                al = AuditLog(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    action=audit["action"],
                                    resource_type=audit["resource_type"],
                                    resource_id=audit["resource_id"],
                                    details=audit["details"],
                                    timestamp=audit["timestamp"]
                                )
                                db.session.add(al)
                                app.logger.debug(f"Log de auditoria criado para usuário {user.id}: {audit['action']}")
                            else:
                                app.logger.debug(f"Log de auditoria já existe para usuário {user.id}: {audit['action']}")
                        db.session.flush()
                    app.logger.info("Logs de auditoria criados ou recuperados com sucesso.")
                create_audit_logs()

                # --------------------------------------
                # Commit Final
                # --------------------------------------
                db.session.commit()
                app.logger.info("População de dados iniciais concluída com sucesso.")

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro durante a população de dados: {str(e)}")
            raise


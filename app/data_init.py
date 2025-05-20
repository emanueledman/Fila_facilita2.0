import uuid
from datetime import datetime, time, timedelta
import bcrypt
from app import db
from app.models import (
    AttendantQueue, InstitutionType, Institution, Branch, BranchSchedule, Department, Queue,
    InstitutionService, ServiceCategory, ServiceTag, User, UserRole, Ticket, UserPreference,
    UserBehavior, UserLocationFallback, NotificationLog, AuditLog, Weekday
)

def populate_initial_data(app):
    """
    Popula o banco de dados com dados iniciais para testes, mantendo Hospital Geral de Luanda e Conservatória dos Registos,
    adicionando 7 bancos (BAI, BFA, BPC, BIC, Banco Económico, Millenium Atlântico, Banco Sol) e 2 hospitais
    (Josina Machel, Sagrada Esperança). Inclui usuários administrativos (1 SYSTEM_ADMIN, 1 INSTITUTION_ADMIN por instituição,
    1 BRANCH_ADMIN por filial, 2 ATTENDANT por filial). Cada filial tem 1 departamento com filas específicas.
    Cada fila tem 10 tickets 'Atendido'. Usa bairros únicos de Luanda. Mantém idempotência e logs em português.
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
                        {"name": "Bancário", "description": "Serviços financeiros e bancários", "logo_url": "https://previews.123rf.com/images/sylverarts/sylverarts1407/sylverarts140700183/29716987-s%C3%ADmbolo-banc%C3%A1rio-do-vetor-%C3%ADcone-do-sistema-financeiro-circula%C3%A7%C3%A3o-do-dinheiro-ilustra%C3%A7%C3%A3o-do-ciclo.jpg"},
                        {"name": "Saúde", "description": "Serviços de saúde e atendimento médico", "logo_url": "https://st4.depositphotos.com/5161043/24508/v/450/depositphotos_245083494-stock-illustration-hospital-logo-symbols-template-icons.jpg"},
                        {"name": "Administrativo", "description": "Serviços administrativos e atendimento ao cidadão", "logo_url": "https://img.myloview.com.br/posters/icone-de-logotipo-para-administracao-de-empresas-gerenciamento-de-documentos-arquivos-700-115713639.jpg"},
                        {"name": "Educação", "description": "Serviços educacionais e acadêmicos", "logo_url": "https://img.freepik.com/vetores-premium/design-de-logotipo-da-escola-de-educacao_586739-1339.jpg?w=360"},
                        {"name": "Transportes", "description": "Serviços de transporte e logística", "logo_url": "https://www.pensamentoverde.com.br/wp-content/uploads/2022/08/quais-sao-os-meios-de-transportes-mais-sustentaveis-1.png"},
                        {"name": "Comercial", "description": "Serviços comerciais e varejo", "logo_url": "https://st5.depositphotos.com/87503270/72000/v/450/depositphotos_720006748-stock-illustration-happy-shop-logo-design-template.jpg"}
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
                        {"name": "Crédito", "description": "Solicitação e gestão de empréstimos", "parent_id": None},
                        {"name": "Atendimento", "description": "Suporte e esclarecimentos gerais", "parent_id": None},
                        {"name": "Saúde", "description": "Serviços de saúde e atendimento médico", "parent_id": None},
                        {"name": "Consulta Médica", "description": "Consultas gerais e especializadas", "parent_id": None},
                        {"name": "Exames", "description": "Exames laboratoriais e diagnósticos", "parent_id": None},
                        {"name": "Licenças", "description": "Renovação de Licenças", "parent_id": None},
                        {"name": "Triagem", "description": "Triagem e atendimento inicial", "parent_id": None},
                        {"name": "Internamento", "description": "Serviços de internamento hospitalar", "parent_id": None},
                        {"name": "Cirurgia", "description": "Procedimentos cirúrgicos", "parent_id": None},
                        {"name": "Vacinação", "description": "Serviços de imunização", "parent_id": None},
                        {"name": "Administrativo", "description": "Serviços administrativos e atendimento ao cidadão", "parent_id": None},
                        {"name": "Documentos", "description": "Emissão e renovação de documentos", "parent_id": None},
                        {"name": "Registros", "description": "Registros civis e comerciais", "parent_id": None},
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
                        ("Conta", "Bancário"), ("Crédito", "Bancário"), ("Atendimento", "Bancário"),
                        ("Consulta Médica", "Saúde"), ("Exames", "Saúde"), ("Triagem", "Saúde"),
                        ("Internamento", "Saúde"), ("Cirurgia", "Saúde"), ("Vacinação", "Saúde"),
                        ("Documentos", "Administrativo"), ("Registros", "Administrativo"),
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
                ]

                # --------------------------------------
                # Dados de Instituições
                # --------------------------------------
                institutions_data = [
                    # Hospital Geral de Luanda (do código original)
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
                            {"name": "Cirurgia de Urgência", "category_id": category_map["Cirurgia"], "description": "Cirurgias de emergência"},
                            {"name": "Vacinação", "category_id": category_map["Vacinação"], "description": "Serviços de imunização"}
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                
                    # Hospital Josina Machel (novo)
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Hospital Josina Machel",
                        "description": "Hospital público de referência em Luanda",
                        "institution_type_id": institution_type_map["Saúde"],
                        "logo_url": "https://www.hospitaljosinamachel.ao/images/logo.png",
                        "services": [
                            {"name": "Consulta Geral", "category_id": category_map["Consulta Médica"], "description": "Consultas médicas gerais"},
                            {"name": "Exames Laboratoriais", "category_id": category_map["Exames"], "description": "Exames de diagnóstico"},
                            {"name": "Internamento", "category_id": category_map["Internamento"], "description": "Serviços de internamento hospitalar"},
                            {"name": "Vacinação", "category_id": category_map["Vacinação"], "description": "Serviços de imunização"}
                        ],
                        "branches": [
                            {
                                "name": "Unidade Vila Alice",
                                "location": "Rua Principal, Vila Alice, Luanda",
                                "neighborhood": "Vila Alice",
                                "latitude": -8.8200,
                                "longitude": 13.2600,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Neves Bendinha",
                                "location": "Rua Principal, Neves Bendinha, Luanda",
                                "neighborhood": "Neves Bendinha",
                                "latitude": -8.8100,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Maculusso",
                                "location": "Rua Principal, Maculusso, Luanda",
                                "neighborhood": "Maculusso",
                                "latitude": -8.8150,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # Clínica Sagrada Esperança (novo)
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Clínica Sagrada Esperança",
                        "description": "Clínica privada de excelência em Luanda",
                        "institution_type_id": institution_type_map["Saúde"],
                        "logo_url": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQrYR68el3AWYc2rLU8hZPkcev23YlpdF6Z_A&s",
                        "services": [
                            {"name": "Consulta Geral", "category_id": category_map["Consulta Médica"], "description": "Consultas médicas gerais"},
                            {"name": "Exames Laboratoriais", "category_id": category_map["Exames"], "description": "Exames de diagnóstico"},
                            {"name": "Internamento", "category_id": category_map["Internamento"], "description": "Serviços de internamento hospitalar"},
                            {"name": "Vacinação", "category_id": category_map["Vacinação"], "description": "Serviços de imunização"}
                        ],
                        "branches": [
                            {
                                "name": "Unidade Zango",
                                "location": "Rua Principal, Zango, Luanda",
                                "neighborhood": "Zango",
                                "latitude": -8.9200,
                                "longitude": 13.4000,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Patriota",
                                "location": "Rua Principal, Patriota, Luanda",
                                "neighborhood": "Patriota",
                                "latitude": -8.9000,
                                "longitude": 13.2000,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # Banco BAI
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Banco BAI",
                        "description": "Serviços bancários em Luanda",
                        "institution_type_id": institution_type_map["Bancário"],
                        "logo_url": "https://upload.wikimedia.org/wikipedia/commons/4/4f/BAI_-_.jpg",
                        "services": [
                            {"name": "Abertura de Conta", "category_id": category_map["Conta"], "description": "Abertura de contas correntes e poupança"},
                            {"name": "Crédito Pessoal", "category_id": category_map["Crédito"], "description": "Empréstimos pessoais e financiamentos"},
                            {"name": "Atendimento ao Cliente", "category_id": category_map["Atendimento"], "description": "Suporte e esclarecimentos gerais"}
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
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
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
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Maianga",
                                "location": "Rua Joaquim Kapango, Maianga, Luanda",
                                "neighborhood": "Maianga",
                                "latitude": -8.8150,
                                "longitude": 13.2310,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # Banco BFA
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Banco BFA",
                        "description": "Banco líder em Angola, parte do grupo CaixaBank",
                        "institution_type_id": institution_type_map["Bancário"],
                        "logo_url": "https://mir-s3-cdn-cf.behance.net/projects/404/34bf0d202655285.Y3JvcCwxMTYyLDkwOSwxOTUsMA.png",
                        "services": [
                            {"name": "Abertura de Conta", "category_id": category_map["Conta"], "description": "Abertura de contas correntes e poupança"},
                            {"name": "Crédito Pessoal", "category_id": category_map["Crédito"], "description": "Empréstimos pessoais e financiamentos"},
                            {"name": "Atendimento ao Cliente", "category_id": category_map["Atendimento"], "description": "Suporte e esclarecimentos gerais"}
                        ],
                        "branches": [
                            {
                                "name": "Agência Vila Alice",
                                "location": "Rua Principal, Vila Alice, Luanda",
                                "neighborhood": "Vila Alice",
                                "latitude": -8.8200,
                                "longitude": 13.2600,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Rocha Pinto",
                                "location": "Rua Principal, Rocha Pinto, Luanda",
                                "neighborhood": "Rocha Pinto",
                                "latitude": -8.8400,
                                "longitude": 13.2500,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Sambizanga",
                                "location": "Rua Principal, Sambizanga, Luanda",
                                "neighborhood": "Sambizanga",
                                "latitude": -8.8000,
                                "longitude": 13.2400,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # Banco BPC
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Banco BPC",
                        "description": "Banco estatal com ampla rede de serviços financeiros",
                        "institution_type_id": institution_type_map["Bancário"],
                        "logo_url": "https://audiconta-angola.com/wp-content/uploads/2019/05/BPC.jpg",
                        "services": [
                            {"name": "Abertura de Conta", "category_id": category_map["Conta"], "description": "Abertura de contas correntes e poupança"},
                            {"name": "Crédito Pessoal", "category_id": category_map["Crédito"], "description": "Empréstimos pessoais e financiamentos"},
                            {"name": "Atendimento ao Cliente", "category_id": category_map["Atendimento"], "description": "Suporte e esclarecimentos gerais"}
                        ],
                        "branches": [
                            {
                                "name": "Agência Neves Bendinha",
                                "location": "Rua Principal, Neves Bendinha, Luanda",
                                "neighborhood": "Neves Bendinha",
                                "latitude": -8.8100,
                                "longitude": 13.2500,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Maculusso",
                                "location": "Rua Principal, Maculusso, Luanda",
                                "neighborhood": "Maculusso",
                                "latitude": -8.8150,
                                "longitude": 13.2350,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
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
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # Banco BIC
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Banco BIC",
                        "description": "Banco com forte presença em Angola, focado em inovação",
                        "institution_type_id": institution_type_map["Bancário"],
                        "logo_url": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ5M0tHA7JdqCgeFgFF5OzTC3Rus8PQM3wlRQ&s",
                        "services": [
                            {"name": "Abertura de Conta", "category_id": category_map["Conta"], "description": "Abertura de contas correntes e poupança"},
                            {"name": "Crédito Pessoal", "category_id": category_map["Crédito"], "description": "Empréstimos pessoais e financiamentos"},
                            {"name": "Atendimento ao Cliente", "category_id": category_map["Atendimento"], "description": "Suporte e esclarecimentos gerais"}
                        ],
                        "branches": [
                            {
                                "name": "Agência Golfe",
                                "location": "Rua Principal, Golfe, Luanda",
                                "neighborhood": "Golfe",
                                "latitude": -8.8700,
                                "longitude": 13.2700,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Camama",
                                "location": "Rua Principal, Camama, Luanda",
                                "neighborhood": "Camama",
                                "latitude": -8.8900,
                                "longitude": 13.2400,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Prenda",
                                "location": "Rua Principal, Prenda, Luanda",
                                "neighborhood": "Prenda",
                                "latitude": -8.8300,
                                "longitude": 13.2300,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # Banco Económico
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Banco Económico",
                        "description": "Banco focado em soluções financeiras para empresas e indivíduos",
                        "institution_type_id": institution_type_map["Bancário"],
                        "logo_url": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQxu8_LmKv4d9Q313Vy3F8oSFO_8glxazcfhw&s",
                        "services": [
                            {"name": "Abertura de Conta", "category_id": category_map["Conta"], "description": "Abertura de contas correntes e poupança"},
                            {"name": "Crédito Pessoal", "category_id": category_map["Crédito"], "description": "Empréstimos pessoais e financiamentos"},
                            {"name": "Atendimento ao Cliente", "category_id": category_map["Atendimento"], "description": "Suporte e esclarecimentos gerais"}
                        ],
                        "branches": [
                            {
                                "name": "Agência Alvalade",
                                "location": "Rua Principal, Alvalade, Luanda",
                                "neighborhood": "Alvalade",
                                "latitude": -8.8250,
                                "longitude": 13.2300,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Miramar",
                                "location": "Rua Principal, Miramar, Luanda",
                                "neighborhood": "Miramar",
                                "latitude": -8.8100,
                                "longitude": 13.2200,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Bairro Operário",
                                "location": "Rua Principal, Bairro Operário, Luanda",
                                "neighborhood": "Bairro Operário",
                                "latitude": -8.8200,
                                "longitude": 13.2450,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # Banco Millenium Atlântico
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Banco Atlântico",
                        "description": "Banco moderno com serviços financeiros inovadores",
                        "institution_type_id": institution_type_map["Bancário"],
                        "logo_url": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTXFCFqT9tZyCHjwjfvmDnWYjUNwEMY4WY1tg&s",
                        "services": [
                            {"name": "Abertura de Conta", "category_id": category_map["Conta"], "description": "Abertura de contas correntes e poupança"},
                            {"name": "Crédito Pessoal", "category_id": category_map["Crédito"], "description": "Empréstimos pessoais e financiamentos"},
                            {"name": "Atendimento ao Cliente", "category_id": category_map["Atendimento"], "description": "Suporte e esclarecimentos gerais"}
                        ],
                        "branches": [
                            {
                                "name": "Agência Cassenda",
                                "location": "Rua Principal, Cassenda, Luanda",
                                "neighborhood": "Cassenda",
                                "latitude": -8.8350,
                                "longitude": 13.2400,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Bairro Azul",
                                "location": "Rua Principal, Bairro Azul, Luanda",
                                "neighborhood": "Bairro Azul",
                                "latitude": -8.8000,
                                "longitude": 13.2300,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Hoji Ya Henda",
                                "location": "Rua Principal, Hoji Ya Henda, Luanda",
                                "neighborhood": "Hoji Ya Henda",
                                "latitude": -8.8500,
                                "longitude": 13.2900,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # Banco Sol
                    
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Conservatória dos Registos de Angola",
                        "description": "Serviços de registo civil, comercial e identificação em Luanda",
                        "institution_type_id": institution_type_map["Administrativo"],
                        "logo_url": "https://rna.ao/rna.ao/wp-content/uploads/2022/09/Registo-Civil.jpg",
                        "services": [
                            {"name": "Registo Comercial", "category_id": category_map["Registros"], "description": "Registo de empresas e atividades comerciais"},
                            {"name": "Registo Civil", "category_id": category_map["Registros"], "description": "Registo de nascimento, casamento e óbito"},
                            {"name": "Autenticação de Documentos", "category_id": category_map["Documentos"], "description": "Autenticação de documentos oficiais"},
                            {"name": "Emissão de Bilhete de Identidade", "category_id": category_map["Identificação"], "description": "Emissão de bilhete de identidade angolano"},
                            {"name": "Renovação de Bilhete de Identidade", "category_id": category_map["Renovações"], "description": "Renovação de bilhete de identidade expirado"},
                            {"name": "Emissão de Cédula Pessoal", "category_id": category_map["Identificação"], "description": "Emissão de cédula pessoal para cidadãos"},
                            {"name": "Certidão de Nascimento", "category_id": category_map["Certidões"], "description": "Emissão de certidão de nascimento"},
                            {"name": "Certidão de Casamento", "category_id": category_map["Certidões"], "description": "Emissão de certidão de casamento"},
                            {"name": "Certidão de Óbito", "category_id": category_map["Certidões"], "description": "Emissão de certidão de óbito"},
                            {"name": "Registo de Propriedade", "category_id": category_map["Registros"], "description": "Registo de bens imóveis"},
                            {"name": "Emissão de Passaporte", "category_id": category_map["Identificação"], "description": "Emissão de passaporte angolano"},
                            {"name": "Renovação de Passaporte", "category_id": category_map["Renovações"], "description": "Renovação de passaporte expirado"},
                            {"name": "Reconhecimento de Assinatura", "category_id": category_map["Documentos"], "description": "Reconhecimento de assinaturas em documentos"},
                            {"name": "Registo de Testamento", "category_id": category_map["Registros"], "description": "Registo de testamentos e últimas vontades"},
                            {"name": "Emissão de Certificado de Habilitações", "category_id": category_map["Documentos"], "description": "Certificação de habilitações académicas"}
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Bilhete de Identidade",
                                                "prefix": "BI",
                                                "daily_limit": 150,
                                                "num_counters": 6,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Bilhete de Identidade",
                                                "prefix": "RBI",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Cédula Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Nascimento",
                                                "prefix": "CN",
                                                "daily_limit": 110,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Casamento",
                                                "prefix": "CC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Óbito",
                                                "prefix": "CO",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Propriedade",
                                                "prefix": "RP",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Passaporte",
                                                "prefix": "EP",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Passaporte",
                                                "prefix": "RPP",
                                                "daily_limit": 40,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Reconhecimento de Assinatura",
                                                "prefix": "RA",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Testamento",
                                                "prefix": "RT",
                                                "daily_limit": 30,
                                                "num_counters": 1,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Certificado de Habilitações",
                                                "prefix": "CH",
                                                "daily_limit": 70,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Bilhete de Identidade",
                                                "prefix": "BI",
                                                "daily_limit": 150,
                                                "num_counters": 6,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Bilhete de Identidade",
                                                "prefix": "RBI",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Cédula Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Nascimento",
                                                "prefix": "CN",
                                                "daily_limit": 110,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Casamento",
                                                "prefix": "CC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Óbito",
                                                "prefix": "CO",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Propriedade",
                                                "prefix": "RP",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Passaporte",
                                                "prefix": "EP",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Passaporte",
                                                "prefix": "RPP",
                                                "daily_limit": 40,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Reconhecimento de Assinatura",
                                                "prefix": "RA",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Testamento",
                                                "prefix": "RT",
                                                "daily_limit": 30,
                                                "num_counters": 1,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Certificado de Habilitações",
                                                "prefix": "CH",
                                                "daily_limit": 70,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Bilhete de Identidade",
                                                "prefix": "BI",
                                                "daily_limit": 150,
                                                "num_counters": 6,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Bilhete de Identidade",
                                                "prefix": "RBI",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Cédula Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Nascimento",
                                                "prefix": "CN",
                                                "daily_limit": 110,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Casamento",
                                                "prefix": "CC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Óbito",
                                                "prefix": "CO",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Propriedade",
                                                "prefix": "RP",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Passaporte",
                                                "prefix": "EP",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Passaporte",
                                                "prefix": "RPP",
                                                "daily_limit": 40,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Reconhecimento de Assinatura",
                                                "prefix": "RA",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Testamento",
                                                "prefix": "RT",
                                                "daily_limit": 30,
                                                "num_counters": 1,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Certificado de Habilitações",
                                                "prefix": "CH",
                                                "daily_limit": 70,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Bilhete de Identidade",
                                                "prefix": "BI",
                                                "daily_limit": 150,
                                                "num_counters": 6,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Bilhete de Identidade",
                                                "prefix": "RBI",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Cédula Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Nascimento",
                                                "prefix": "CN",
                                                "daily_limit": 110,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Casamento",
                                                "prefix": "CC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Óbito",
                                                "prefix": "CO",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Propriedade",
                                                "prefix": "RP",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Passaporte",
                                                "prefix": "EP",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Passaporte",
                                                "prefix": "RPP",
                                                "daily_limit": 40,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Reconhecimento de Assinatura",
                                                "prefix": "RA",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Testamento",
                                                "prefix": "RT",
                                                "daily_limit": 30,
                                                "num_counters": 1,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Certificado de Habilitações",
                                                "prefix": "CH",
                                                "daily_limit": 70,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Bilhete de Identidade",
                                                "prefix": "BI",
                                                "daily_limit": 150,
                                                "num_counters": 6,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Bilhete de Identidade",
                                                "prefix": "RBI",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Cédula Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Nascimento",
                                                "prefix": "CN",
                                                "daily_limit": 110,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Casamento",
                                                "prefix": "CC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Óbito",
                                                "prefix": "CO",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Propriedade",
                                                "prefix": "RP",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Passaporte",
                                                "prefix": "EP",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Passaporte",
                                                "prefix": "RPP",
                                                "daily_limit": 40,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Reconhecimento de Assinatura",
                                                "prefix": "RA",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Testamento",
                                                "prefix": "RT",
                                                "daily_limit": 30,
                                                "num_counters": 1,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Certificado de Habilitações",
                                                "prefix": "CH",
                                                "daily_limit": 70,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Bilhete de Identidade",
                                                "prefix": "BI",
                                                "daily_limit": 150,
                                                "num_counters": 6,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Bilhete de Identidade",
                                                "prefix": "RBI",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Cédula Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Nascimento",
                                                "prefix": "CN",
                                                "daily_limit": 110,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Casamento",
                                                "prefix": "CC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Óbito",
                                                "prefix": "CO",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Propriedade",
                                                "prefix": "RP",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Passaporte",
                                                "prefix": "EP",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Passaporte",
                                                "prefix": "RPP",
                                                "daily_limit": 40,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Reconhecimento de Assinatura",
                                                "prefix": "RA",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Testamento",
                                                "prefix": "RT",
                                                "daily_limit": 30,
                                                "num_counters": 1,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Certificado de Habilitações",
                                                "prefix": "CH",
                                                "daily_limit": 70,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Bilhete de Identidade",
                                                "prefix": "BI",
                                                "daily_limit": 150,
                                                "num_counters": 6,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Bilhete de Identidade",
                                                "prefix": "RBI",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Cédula Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Nascimento",
                                                "prefix": "CN",
                                                "daily_limit": 110,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Casamento",
                                                "prefix": "CC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Óbito",
                                                "prefix": "CO",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Propriedade",
                                                "prefix": "RP",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Passaporte",
                                                "prefix": "EP",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Passaporte",
                                                "prefix": "RPP",
                                                "daily_limit": 40,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Reconhecimento de Assinatura",
                                                "prefix": "RA",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Testamento",
                                                "prefix": "RT",
                                                "daily_limit": 30,
                                                "num_counters": 1,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Certificado de Habilitações",
                                                "prefix": "CH",
                                                "daily_limit": 70,
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
                                                "with": ["Administrativo", "Documentos"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Bilhete de Identidade",
                                                "prefix": "BI",
                                                "daily_limit": 150,
                                                "num_counters": 6,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Bilhete de Identidade",
                                                "prefix": "RBI",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Cédula Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Nascimento",
                                                "prefix": "CN",
                                                "daily_limit": 110,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Casamento",
                                                "prefix": "CC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Óbito",
                                                "prefix": "CO",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Propriedade",
                                                "prefix": "RP",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Passaporte",
                                                "prefix": "EP",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Passaporte",
                                                "prefix": "RPP",
                                                "daily_limit": 40,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Reconhecimento de Assinatura",
                                                "prefix": "RA",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Testamento",
                                                "prefix": "RT",
                                                "daily_limit": 30,
                                                "num_counters": 1,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Certificado de Habilitações",
                                                "prefix": "CH",
                                                "daily_limit": 70,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Bilhete de Identidade",
                                                "prefix": "BI",
                                                "daily_limit": 150,
                                                "num_counters": 6,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Bilhete de Identidade",
                                                "prefix": "RBI",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Cédula Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Nascimento",
                                                "prefix": "CN",
                                                "daily_limit": 110,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Casamento",
                                                "prefix": "CC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Óbito",
                                                "prefix": "CO",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Propriedade",
                                                "prefix": "RP",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Passaporte",
                                                "prefix": "EP",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Passaporte",
                                                "prefix": "RPP",
                                                "daily_limit": 40,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Reconhecimento de Assinatura",
                                                "prefix": "RA",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Testamento",
                                                "prefix": "RT",
                                                "daily_limit": 30,
                                                "num_counters": 1,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Certificado de Habilitações",
                                                "prefix": "CH",
                                                "daily_limit": 70,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Bilhete de Identidade",
                                                "prefix": "BI",
                                                "daily_limit": 150,
                                                "num_counters": 6,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Bilhete de Identidade",
                                                "prefix": "RBI",
                                                "daily_limit": 100,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Cédula Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Nascimento",
                                                "prefix": "CN",
                                                "daily_limit": 110,
                                                "num_counters": 4,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Casamento",
                                                "prefix": "CC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Certidão de Óbito",
                                                "prefix": "CO",
                                                "daily_limit": 60,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Certidões"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Propriedade",
                                                "prefix": "RP",
                                                "daily_limit": 80,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Passaporte",
                                                "prefix": "EP",
                                                "daily_limit": 50,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Identificação"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Renovação de Passaporte",
                                                "prefix": "RPP",
                                                "daily_limit": 40,
                                                "num_counters": 2,
                                                "tags": ["Administrativo", "Renovações"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Reconhecimento de Assinatura",
                                                "prefix": "RA",
                                                "daily_limit": 90,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Registo de Testamento",
                                                "prefix": "RT",
                                                "daily_limit": 30,
                                                "num_counters": 1,
                                                "tags": ["Administrativo", "Registros"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Emissão de Certificado de Habilitações",
                                                "prefix": "CH",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Administrativo", "Documentos"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Banco Sol",
                        "description": "Banco voltado para inclusão financeira em Angola",
                        "institution_type_id": institution_type_map["Bancário"],
                        "logo_url": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRZLxB6gD1IQahZQhTliRy3Bnda6lhAXGYxYA&s",
                        "services": [
                            {"name": "Abertura de Conta", "category_id": category_map["Conta"], "description": "Abertura de contas correntes e poupança"},
                            {"name": "Crédito Pessoal", "category_id": category_map["Crédito"], "description": "Empréstimos pessoais e financiamentos"},
                            {"name": "Atendimento ao Cliente", "category_id": category_map["Atendimento"], "description": "Suporte e esclarecimentos gerais"}
                        ],
                        "branches": [
                            {
                                "name": "Agência Palanca",
                                "location": "Rua Principal, Palanca, Luanda",
                                "neighborhood": "Palanca",
                                "latitude": -8.8600,
                                "longitude": 13.2800,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Tala Hady",
                                "location": "Rua Principal, Tala Hady, Luanda",
                                "neighborhood": "Tala Hady",
                                "latitude": -8.8450,
                                "longitude": 13.2750,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Agência Kikolo",
                                "location": "Rua Principal, Kikolo, Luanda",
                                "neighborhood": "Kikolo",
                                "latitude": -8.7800,
                                "longitude": 13.3600,
                                "departments": [
                                    {
                                        "name": "Atendimento Bancário",
                                        "sector": "Bancário",
                                        "queues": [
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Abertura de Conta",
                                                "prefix": "AC",
                                                "daily_limit": 100,
                                                "num_counters": 3,
                                                "tags": ["Bancário", "Conta"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Crédito Pessoal",
                                                "prefix": "CP",
                                                "daily_limit": 80,
                                                "num_counters": 2,
                                                "tags": ["Bancário", "Crédito"]
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Atendimento ao Cliente",
                                                "prefix": "AT",
                                                "daily_limit": 120,
                                                "num_counters": 4,
                                                "tags": ["Bancário", "Atendimento", "24h"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # Hospital Josina Machel
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Hospital Josina Machel",
                        "description": "Hospital público de referência em Luanda",
                        "institution_type_id": institution_type_map["Saúde"],
                        "logo_url": "https://www.hospitaljosinamachel.ao/images/logo.png",
                        "services": [
                            {"name": "Consulta Geral", "category_id": category_map["Consulta Médica"], "description": "Consultas médicas gerais"},
                            {"name": "Exames Laboratoriais", "category_id": category_map["Exames"], "description": "Exames de diagnóstico"},
                            {"name": "Internamento", "category_id": category_map["Internamento"], "description": "Serviços de internamento hospitalar"},
                            {"name": "Vacinação", "category_id": category_map["Vacinação"], "description": "Serviços de imunização"}
                        ],
                        "branches": [
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Rangel",
                                "location": "Rua do Rangel, Rangel, Luanda",
                                "neighborhood": "Rangel",
                                "latitude": -8.8300,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Samba",
                                "location": "Rua Principal, Samba, Luanda",
                                "neighborhood": "Samba",
                                "latitude": -8.8200,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Cacuaco",
                                "location": "Rua Principal, Cacuaco, Luanda",
                                "neighborhood": "Cacuaco",
                                "latitude": -8.7767,
                                "longitude": 13.3667,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Benfica",
                                "location": "Rua Principal, Benfica, Luanda",
                                "neighborhood": "Benfica",
                                "latitude": -8.9500,
                                "longitude": 13.1500,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    # Clínica Sagrada Esperança
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Clínica Sagrada Esperança",
                        "description": "Clínica privada de excelência em Luanda",
                        "institution_type_id": institution_type_map["Saúde"],
                        "logo_url": "https://www.clinicasagradaesperanca.ao/images/logo.png",
                        "services": [
                            {"name": "Consulta Geral", "category_id": category_map["Consulta Médica"], "description": "Consultas médicas gerais"},
                            {"name": "Exames Laboratoriais", "category_id": category_map["Exames"], "description": "Exames de diagnóstico"},
                            {"name": "Internamento", "category_id": category_map["Internamento"], "description": "Serviços de internamento hospitalar"},
                            {"name": "Vacinação", "category_id": category_map["Vacinação"], "description": "Serviços de imunização"}
                        ],
                        "branches": [
                            {
                                "name": "Unidade Kilamba",
                                "location": "Avenida do Kilamba, Kilamba, Luanda",
                                "neighborhood": "Kilamba",
                                "latitude": -8.9340,
                                "longitude": 13.2670,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Cazenga",
                                "location": "Avenida dos Combatentes, Cazenga, Luanda",
                                "neighborhood": "Cazenga",
                                "latitude": -8.8510,
                                "longitude": 13.2840,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Viana",
                                "location": "Rua Principal, Viana, Luanda",
                                "neighborhood": "Viana",
                                "latitude": -8.9040,
                                "longitude": 13.3750,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Bairro Popular",
                                "location": "Rua Principal, Bairro Popular, Luanda",
                                "neighborhood": "Bairro Popular",
                                "latitude": -8.8300,
                                "longitude": 13.2600,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "name": "Unidade Valódia",
                                "location": "Rua Principal, Valódia, Luanda",
                                "neighborhood": "Valódia",
                                "latitude": -8.8400,
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
                                            },
                                            {
                                                "id": str(uuid.uuid4()),
                                                "service_name": "Vacinação",
                                                "prefix": "VC",
                                                "daily_limit": 70,
                                                "num_counters": 3,
                                                "tags": ["Saúde", "Vacinação"]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]

                # --------------------------------------
                # Criar Instituições, Filiais, Departamentos, Filas e Tickets
                # --------------------------------------
                def create_institution(data):
                    if not exists(Institution, name=data["name"]):
                        institution = Institution(
                            id=data["id"],
                            name=data["name"],
                            description=data["description"],
                            institution_type_id=data["institution_type_id"],
                            logo_url=data["logo_url"]
                        )
                        db.session.add(institution)
                        db.session.flush()
                        app.logger.debug(f"Instituição criada: {data['name']}")
                    else:
                        institution = Institution.query.filter_by(name=data["name"]).first()
                    return institution

                def create_institution_service(institution, service_data):
                    if not exists(InstitutionService, institution_id=institution.id, name=service_data["name"]):
                        service = InstitutionService(
                            id=str(uuid.uuid4()),
                            institution_id=institution.id,
                            name=service_data["name"],
                            category_id=service_data["category_id"],
                            description=service_data["description"]
                        )
                        db.session.add(service)
                        db.session.flush()
                        app.logger.debug(f"Serviço criado: {service_data['name']} para {institution.name}")
                    return InstitutionService.query.filter_by(institution_id=institution.id, name=service_data["name"]).first()

                def exists(model, **kwargs):
                    """Verifica se um registro existe no banco com os filtros fornecidos."""
                    return model.query.filter_by(**kwargs).first() is not None

                def generate_unique_totem_password(base_password, branch_id):
                    """Gera uma senha única baseada no nome, adicionando sufixos numéricos se necessário."""
                    password = base_password
                    suffix = 0
                    
                    # Verificar se a senha já existe em outra filial (excluindo a própria filial)
                    while True:
                        # Buscar filiais com o mesmo hash de senha
                        hash_to_check = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                        existing_branch = Branch.query.filter(
                            Branch.totem_password_hash == hash_to_check,
                            Branch.id != branch_id
                        ).first()
                        
                        if not existing_branch:
                            return password
                        
                        # Se houver colisão, adicionar sufixo numérico
                        suffix += 1
                        password = f"{base_password}_{suffix}"
                        app.logger.debug(f"Tentando senha alternativa para evitar colisão: {password}")

                def create_branch(institution, branch_data):
                    """Cria ou retorna uma filial existente para a instituição."""
                    if not exists(Branch, institution_id=institution.id, name=branch_data["name"]):
                        branch = Branch(
                            id=str(uuid.uuid4()),
                            institution_id=institution.id,
                            name=branch_data["name"],
                            location=branch_data["location"],
                            neighborhood=branch_data["neighborhood"],
                            latitude=branch_data["latitude"],
                            longitude=branch_data["longitude"]
                        )
                        # Usar o nome da filial como base para a senha
                        base_password = branch_data["name"]
                        totem_password = generate_unique_totem_password(base_password, branch.id)
                        branch.set_totem_password(totem_password)
                        db.session.add(branch)
                        db.session.flush()
                        app.logger.info(f"Filial criada: {branch_data['name']} para {institution.name} com senha de totem: {totem_password}")
                    else:
                        branch = Branch.query.filter_by(institution_id=institution.id, name=branch_data["name"]).first()
                        # Garantir que filiais existentes tenham senha (caso não tenham)
                        if not branch.totem_password_hash:
                            base_password = branch_data["name"]
                            totem_password = generate_unique_totem_password(base_password, branch.id)
                            branch.set_totem_password(totem_password)
                            db.session.flush()
                            app.logger.info(f"Senha de totem definida para filial existente: {branch_data['name']} com senha: {totem_password}")
                    return branch
                
                def create_branch_schedule(branch):
                    for day in Weekday:
                        if not exists(BranchSchedule, branch_id=branch.id, weekday=day):
                            schedule = BranchSchedule(
                                id=str(uuid.uuid4()),
                                branch_id=branch.id,
                                weekday=day,
                                open_time=time(7, 0),
                                end_time=time(3, 0),
                                is_closed=False
                            )
                            db.session.add(schedule)
                            db.session.flush()
                    app.logger.debug(f"Horários criados para filial: {branch.name}")

                def create_department(branch, dept_data):
                    if not exists(Department, branch_id=branch.id, name=dept_data["name"]):
                        department = Department(
                            id=str(uuid.uuid4()),
                            branch_id=branch.id,
                            name=dept_data["name"],
                            sector=dept_data["sector"]
                        )
                        db.session.add(department)
                        db.session.flush()
                        app.logger.debug(f"Departamento criado: {dept_data['name']} para {branch.name}")
                    else:
                        department = Department.query.filter_by(branch_id=branch.id, name=dept_data["name"]).first()
                    return department

                def create_queue(department, queue_data):
                    service = InstitutionService.query.filter_by(
                        institution_id=department.branch.institution_id,
                        name=queue_data["service_name"]
                    ).first()
                    if not service:
                        app.logger.error(f"Serviço {queue_data['service_name']} não encontrado para instituição {department.branch.institution_id}")
                        raise ValueError(f"Serviço {queue_data['service_name']} não encontrado")
                    if not exists(Queue, department_id=department.id, service_id=service.id):
                        queue = Queue(
                            id=queue_data["id"],
                            department_id=department.id,
                            service_id=service.id,
                            prefix=queue_data["prefix"],
                            daily_limit=queue_data["daily_limit"],
                            num_counters=queue_data["num_counters"],
                            active_tickets=0,
                            current_ticket=0,
                            avg_wait_time=5.0,
                            last_service_time=2.0,
                            last_counter=0
                        )
                        db.session.add(queue)
                        db.session.flush()
                        for tag in queue_data["tags"]:
                            if not exists(ServiceTag, queue_id=queue.id, tag=tag):
                                service_tag = ServiceTag(
                                    id=str(uuid.uuid4()),
                                    queue_id=queue.id,
                                    tag=tag
                                )
                                db.session.add(service_tag)
                                db.session.flush()
                        app.logger.debug(f"Fila criada: {queue_data['service_name']} para {department.name}")
                    else:
                        queue = Queue.query.filter_by(department_id=department.id, service_id=service.id).first()
                    return queue

                def create_tickets(queue):
                    for i in range(10):
                        ticket_number = i + 1
                        display_number = f"{queue.prefix}{i+1:03d}"
                        qr_code = f"QR_{display_number}_{queue.id[:8]}"
                        if not exists(Ticket, queue_id=queue.id, ticket_number=ticket_number):
                            ticket = Ticket(
                                id=str(uuid.uuid4()),
                                queue_id=queue.id,
                                ticket_number=ticket_number,
                                qr_code=qr_code,
                                status="Atendido",
                                issued_at=datetime.now() - timedelta(days=1),
                                attended_at=datetime.now() - timedelta(hours=1),
                                counter=(i % queue.num_counters) + 1,
                                service_time=5.0,
                                trade_available=False
                            )
                            db.session.add(ticket)
                            db.session.flush()
                            app.logger.debug(f"Ticket criado: {display_number} para fila {queue.service.name}")

                # Processar instituições
                for inst_data in institutions_data:
                    institution = create_institution(inst_data)
                    for service_data in inst_data["services"]:
                        create_institution_service(institution, service_data)
                    for branch_data in inst_data["branches"]:
                        branch = create_branch(institution, branch_data)
                        create_branch_schedule(branch)
                        for dept_data in branch_data["departments"]:
                            department = create_department(branch, dept_data)
                            for queue_data in dept_data["queues"]:
                                queue = create_queue(department, queue_data)
                                create_tickets(queue)

                # --------------------------------------
                # Criar Usuários Administrativos e Atendentes
                # --------------------------------------
                def create_user(email, password, role, institution_id=None, branch_id=None):
                    if not exists(User, email=email):
                        user = User(
                            id=str(uuid.uuid4()),
                            email=email,
                            name=f"{role.value} {email.split('@')[0]}",
                            password_hash= hash_password(password),
                            user_role=role,
                            institution_id=institution_id,
                            branch_id=branch_id,
                            created_at=datetime.utcnow(),
                            active=True
                        )
                        db.session.add(user)
                        db.session.flush()
                        app.logger.debug(f"Usuário criado: {email} com papel {role}")
                    else:
                        user = User.query.filter_by(email=email).first()
                    return user

                # Criar SYSTEM_ADMIN
                create_user(
                    email="system_admin@queue.com",
                    password="Admin123!",
                    role=UserRole.SYSTEM_ADMIN
                )

                # Criar INSTITUTION_ADMIN para cada instituição
                for inst_data in institutions_data:
                    inst = Institution.query.filter_by(name=inst_data["name"]).first()
                    create_user(
                        email=f"inst_admin_{normalize_string(inst_data['name'])}@queue.com",
                        password="InstAdmin123!",
                        role=UserRole.INSTITUTION_ADMIN,
                        institution_id=inst.id
                    )

                # Criar BRANCH_ADMIN e ATTENDANT para cada filial
                for inst_data in institutions_data:
                    inst = Institution.query.filter_by(name=inst_data["name"]).first()
                    for branch_data in inst_data["branches"]:
                        branch = Branch.query.filter_by(institution_id=inst.id, name=branch_data["name"]).first()
                        # BRANCH_ADMIN
                        create_user(
                            email=f"branch_admin_{normalize_string(branch_data['name'])}@queue.com",
                            password="BranchAdmin123!",
                            role=UserRole.BRANCH_ADMIN,
                            institution_id=inst.id,
                            branch_id=branch.id
                        )
                        # ATTENDANT (2 por filial)
                        for i in range(1, 3):
                            attendant = create_user(
                                email=f"attendant_{normalize_string(branch_data['name'])}_{i}@queue.com",
                                password="Attendant123!",
                                role=UserRole.ATTENDANT,
                                institution_id=inst.id,
                                branch_id=branch.id
                            )
                            # Associar atendente a até duas filas da filial
                            queues = Queue.query.join(Department).filter(Department.branch_id == branch.id).limit(2).all()
                            for queue in queues:
                                if not exists(AttendantQueue, user_id=attendant.id, queue_id=queue.id):
                                    association = AttendantQueue(
                                        user_id=attendant.id,
                                        queue_id=queue.id
                                    )
                                    db.session.add(association)
                                    db.session.flush()
                                    app.logger.debug(f"Atendente {attendant.email} associado à fila {queue.service.name} ({queue.id})")

                # --------------------------------------
                # Commit das alterações
                # --------------------------------------
                db.session.commit()
                app.logger.info("População de dados iniciais concluída com sucesso.")

                # --------------------------------------
                # Retornar dados criados em formato JSON
                # --------------------------------------
                result = {
                    "institutions": [],
                    "users": []
                }

                for inst_data in institutions_data:
                    inst = Institution.query.filter_by(name=inst_data["name"]).first()
                    inst_info = {
                        "id": inst.id,
                        "name": inst.name,
                        "description": inst.description,
                        "institution_type_id": inst.institution_type_id,
                        "logo_url": inst.logo_url,
                        "services": [
                            {
                                "id": s.id,
                                "name": s.name,
                                "category_id": s.category_id,
                                "description": s.description
                            } for s in InstitutionService.query.filter_by(institution_id=inst.id).all()
                        ],
                        "branches": []
                    }
                    for branch_data in inst_data["branches"]:
                        branch = Branch.query.filter_by(institution_id=inst.id, name=branch_data["name"]).first()
                        branch_info = {
                            "id": branch.id,
                            "name": branch.name,
                            "location": branch.location,
                            "neighborhood": branch.neighborhood,
                            "latitude": branch.latitude,
                            "longitude": branch.longitude,
                            "departments": []
                        }
                        for dept_data in branch_data["departments"]:
                            dept = Department.query.filter_by(branch_id=branch.id, name=dept_data["name"]).first()
                            dept_info = {
                                "id": dept.id,
                                "name": dept.name,
                                "sector": dept.sector,
                                "queues": [
                                    {
                                        "id": q.id,
                                        "service_name": q.service.name,
                                        "prefix": q.prefix,
                                        "daily_limit": q.daily_limit,
                                        "num_counters": q.num_counters,
                                        "tags": [t.tag for t in ServiceTag.query.filter_by(queue_id=q.id).all()],
                                        "tickets": [
                                            {
                                                "id": t.id,
                                                "ticket_number": t.ticket_number,
                                                "status": t.status,
                                                "issued_at": t.issued_at.isoformat(),
                                                "attended_at": t.attended_at.isoformat() if t.attended_at else None
                                            } for t in Ticket.query.filter_by(queue_id=q.id).all()
                                        ]
                                    } for q in Queue.query.filter_by(department_id=dept.id).all()
                                ]
                            }
                            branch_info["departments"].append(dept_info)
                        inst_info["branches"].append(branch_info)
                    result["institutions"].append(inst_info)

                for user in User.query.all():
                    result["users"].append({
                        "id": user.id,
                        "email": user.email,
                        "role": user.user_role.value,
                        "institution_id": user.institution_id,
                        "branch_id": user.branch_id
                    })

                return result

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao popular dados iniciais: {str(e)}")
            raise
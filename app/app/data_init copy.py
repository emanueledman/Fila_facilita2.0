import uuid
from datetime import time, datetime, timedelta
from .models import AuditLog, Institution, Queue, User, Ticket, Department, UserPreference, UserRole, QueueSchedule, Weekday, Branch, ServiceCategory, ServiceTag
from . import db
import os
from sqlalchemy.exc import SQLAlchemyError

# Dados de teste fornecidos
import uuid
from datetime import time, datetime, timedelta
from .models import AuditLog, Institution, Queue, User, Ticket, Department, UserPreference, UserRole, QueueSchedule, Weekday, Branch, ServiceCategory, ServiceTag
from . import db
import os
from sqlalchemy.exc import SQLAlchemyError

# Dados de teste expandidos
institutions_data = [
    # 1. Hospital Josina Machel (Saúde)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd094",
        "name": "Hospital Josina Machel",
        "description": "Hospital público de referência em Luanda",
        "branches": [
            {
                "name": "Unidade Ingombota",
                "location": "Rua dos Hospitais, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd095",
                                "service": "Consulta Geral",
                                "category_id": None,
                                "prefix": "CG",
                                "open_time": time(8, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Consulta", "Geral", "Saúde"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd105",
                                "service": "Exames Laboratoriais",
                                "category_id": None,
                                "prefix": "EL",
                                "open_time": time(7, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(7, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(7, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(7, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(7, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(7, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Exames", "Laboratório", "Saúde"]
                            }
                        ]
                    },
                    {
                        "name": "Emergência",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd096",
                                "service": "Emergência",
                                "category_id": None,
                                "prefix": "EM",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
                                "daily_limit": 30,
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
                                "tags": ["Emergência", "Saúde"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Talatona",
                "location": "Via Expressa, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd098",
                                "service": "Consulta Geral",
                                "category_id": None,
                                "prefix": "CG",
                                "open_time": time(8, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Consulta", "Geral", "Saúde"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Cazenga",
                "location": "Rua Principal, Cazenga, Luanda",
                "neighborhood": "Cazenga",
                "latitude": -8.8500,
                "longitude": 13.2833,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd106",
                                "service": "Consulta Geral",
                                "category_id": None,
                                "prefix": "CG",
                                "open_time": time(8, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Consulta", "Geral", "Saúde"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 2. Banco de Fomento Angola (Bancário)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd099",
        "name": "Banco de Fomento Angola",
        "description": "Banco comercial em Luanda",
        "branches": [
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
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd100",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd107",
                                "service": "Abertura de Conta",
                                "category_id": None,
                                "prefix": "AC",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Conta", "Bancário"]
                            }
                        ]
                    },
                    {
                        "name": "Caixa",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd101",
                                "service": "Caixa",
                                "category_id": None,
                                "prefix": "CX",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 25,
                                "num_counters": 6,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Caixa", "Bancário"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Talatona",
                "location": "Condomínio Belas Business Park, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd103",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Viana",
                "location": "Estrada de Viana, Viana, Luanda",
                "neighborhood": "Viana",
                "latitude": -8.9035,
                "longitude": 13.3741,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd108",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 3. Unitel Angola (Telecomunicações)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd109",
        "name": "Unitel Angola",
        "description": "Operadora de telecomunicações líder em Angola",
        "branches": [
            {
                "name": "Loja Ingombota",
                "location": "Avenida Lenine, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Telecomunicações",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd110",
                                "service": "Suporte ao Cliente",
                                "category_id": None,
                                "prefix": "SC",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 25,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(13, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Suporte", "Telecomunicações"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd111",
                                "service": "Aquisição de Linha",
                                "category_id": None,
                                "prefix": "AL",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(13, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Linha", "Telecomunicações"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Talatona",
                "location": "Belas Shopping, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Telecomunicações",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd112",
                                "service": "Suporte ao Cliente",
                                "category_id": None,
                                "prefix": "SC",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 25,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(13, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Suporte", "Telecomunicações"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Huambo",
                "location": "Avenida da Independência, Huambo",
                "neighborhood": "Cidade Alta",
                "latitude": -12.7761,
                "longitude": 15.7392,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Telecomunicações",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd113",
                                "service": "Suporte ao Cliente",
                                "category_id": None,
                                "prefix": "SC",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 25,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(13, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Suporte", "Telecomunicações"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Lobito",
                "location": "Rua 15 de Agosto, Lobito, Benguela",
                "neighborhood": "Comercial",
                "latitude": -12.3487,
                "longitude": 13.5465,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Telecomunicações",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd114",
                                "service": "Suporte ao Cliente",
                                "category_id": None,
                                "prefix": "SC",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 25,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(13, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Suporte", "Telecomunicações"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 4. Administração Municipal de Luanda (Administração Pública)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd115",
        "name": "Administração Municipal de Luanda",
        "description": "Serviços administrativos municipais em Luanda",
        "branches": [
            {
                "name": "Sede Ingombota",
                "location": "Rua Amílcar Cabral, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Registos",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd116",
                                "service": "Emissão de Bilhete de Identidade",
                                "category_id": None,
                                "prefix": "BI",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 30,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Bilhete", "Registos", "Administração"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd117",
                                "service": "Registo de Nascimento",
                                "category_id": None,
                                "prefix": "RN",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Nascimento", "Registos", "Administração"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Posto Cazenga",
                "location": "Rua do Comércio, Cazenga, Luanda",
                "neighborhood": "Cazenga",
                "latitude": -8.8500,
                "longitude": 13.2833,
                "departments": [
                    {
                        "name": "Registos",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd118",
                                "service": "Emissão de Bilhete de Identidade",
                                "category_id": None,
                                "prefix": "BI",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 30,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Bilhete", "Registos", "Administração"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Posto Viana",
                "location": "Estrada de Viana, Viana, Luanda",
                "neighborhood": "Viana",
                "latitude": -8.9035,
                "longitude": 13.3741,
                "departments": [
                    {
                        "name": "Registos",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd119",
                                "service": "Emissão de Bilhete de Identidade",
                                "category_id": None,
                                "prefix": "BI",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 30,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Bilhete", "Registos", "Administração"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 5. Shoprite Angola (Varejo)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd120",
        "name": "Shoprite Angola",
        "description": "Supermercado de varejo em Angola",
        "branches": [
            {
                "name": "Loja Talatona",
                "location": "Belas Shopping, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Varejo",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd121",
                                "service": "Devoluções",
                                "category_id": None,
                                "prefix": "DV",
                                "open_time": time(9, 0),
                                "end_time": time(20, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(9, 0), "end_time": time(18, 0)}
                                ],
                                "tags": ["Devolução", "Varejo"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd122",
                                "service": "Reclamações",
                                "category_id": None,
                                "prefix": "RC",
                                "open_time": time(9, 0),
                                "end_time": time(20, 0),
                                "daily_limit": 10,
                                "num_counters": 1,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(9, 0), "end_time": time(18, 0)}
                                ],
                                "tags": ["Reclamação", "Varejo"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Kilamba",
                "location": "Avenida Comandante Gika, Kilamba, Luanda",
                "neighborhood": "Kilamba",
                "latitude": -8.9333,
                "longitude": 13.2667,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Varejo",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd123",
                                "service": "Devoluções",
                                "category_id": None,
                                "prefix": "DV",
                                "open_time": time(9, 0),
                                "end_time": time(20, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(9, 0), "end_time": time(18, 0)}
                                ],
                                "tags": ["Devolução", "Varejo"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Benguela",
                "location": "Avenida 10 de Fevereiro, Benguela",
                "neighborhood": "Centro",
                "latitude": -12.5905,
                "longitude": 13.4167,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Varejo",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd124",
                                "service": "Devoluções",
                                "category_id": None,
                                "prefix": "DV",
                                "open_time": time(9, 0),
                                "end_time": time(20, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(9, 0), "end_time": time(18, 0)}
                                ],
                                "tags": ["Devolução", "Varejo"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 6. Universidade Agostinho Neto (Educação)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd125",
        "name": "Universidade Agostinho Neto",
        "description": "Principal universidade pública de Angola",
        "branches": [
            {
                "name": "Campus Camama",
                "location": "Estrada de Camama, Luanda",
                "neighborhood": "Camama",
                "latitude": -8.9233,
                "longitude": 13.2333,
                "departments": [
                    {
                        "name": "Secretaria Acadêmica",
                        "sector": "Educação",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd126",
                                "service": "Matrícula",
                                "category_id": None,
                                "prefix": "MT",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Matrícula", "Educação"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd127",
                                "service": "Declarações",
                                "category_id": None,
                                "prefix": "DC",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Declaração", "Educação"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Campus Huambo",
                "location": "Cidade Universitária, Huambo",
                "neighborhood": "Académico",
                "latitude": -12.7761,
                "longitude": 15.7392,
                "departments": [
                    {
                        "name": "Secretaria Acadêmica",
                        "sector": "Educação",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd128",
                                "service": "Matrícula",
                                "category_id": None,
                                "prefix": "MT",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Matrícula", "Educação"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Campus Benguela",
                "location": "Avenida Dr. Fausto Frazão, Benguela",
                "neighborhood": "Universitário",
                "latitude": -12.5905,
                "longitude": 13.4167,
                "departments": [
                    {
                        "name": "Secretaria Acadêmica",
                        "sector": "Educação",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd129",
                                "service": "Matrícula",
                                "category_id": None,
                                "prefix": "MT",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Matrícula", "Educação"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 7. Banco BAI (Bancário)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd130",
        "name": "Banco Angolano de Investimentos",
        "description": "Banco comercial líder em Angola",
        "branches": [
            {
                "name": "Agência Maianga",
                "location": "Rua Che Guevara, Maianga, Luanda",
                "neighborhood": "Maianga",
                "latitude": -8.8147,
                "longitude": 13.2302,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd131",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd132",
                                "service": "Crédito Pessoal",
                                "category_id": None,
                                "prefix": "CP",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 10,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Crédito", "Bancário"]
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
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd133",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Huambo",
                "location": "Avenida Norton de Matos, Huambo",
                "neighborhood": "Cidade Alta",
                "latitude": -12.7761,
                "longitude": 15.7392,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd134",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 8. Movicel Angola (Telecomunicações)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd135",
        "name": "Movicel Angola",
        "description": "Operadora de telecomunicações em Angola",
        "branches": [
            {
                "name": "Loja Ingombota",
                "location": "Avenida 4 de Fevereiro, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Telecomunicações",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd136",
                                "service": "Suporte ao Cliente",
                                "category_id": None,
                                "prefix": "SC",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 25,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(13, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Suporte", "Telecomunicações"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd137",
                                "service": "Aquisição de Linha",
                                "category_id": None,
                                "prefix": "AL",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(13, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Linha", "Telecomunicações"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Kilamba",
                "location": "Avenida Comandante Gika, Kilamba, Luanda",
                "neighborhood": "Kilamba",
                "latitude": -8.9333,
                "longitude": 13.2667,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Telecomunicações",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd138",
                                "service": "Suporte ao Cliente",
                                "category_id": None,
                                "prefix": "SC",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 25,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(13, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Suporte", "Telecomunicações"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Benguela",
                "location": "Rua Monsenhor Keiling, Benguela",
                "neighborhood": "Centro",
                "latitude": -12.5905,
                "longitude": 13.4167,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Telecomunicações",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd139",
                                "service": "Suporte ao Cliente",
                                "category_id": None,
                                "prefix": "SC",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 25,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(13, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Suporte", "Telecomunicações"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 9. Hospital Divina Providência (Saúde)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd140",
        "name": "Hospital Divina Providência",
        "description": "Hospital privado em Luanda",
        "branches": [
            {
                "name": "Unidade Talatona",
                "location": "Rua Principal, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd141",
                                "service": "Consulta Geral",
                                "category_id": None,
                                "prefix": "CG",
                                "open_time": time(8, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Consulta", "Geral", "Saúde"]
                            }
                        ]
                    },
                    {
                        "name": "Emergência",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd142",
                                "service": "Emergência",
                                "category_id": None,
                                "prefix": "EM",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
                                "daily_limit": 30,
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
                                "tags": ["Emergência", "Saúde"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Kilamba",
                "location": "Avenida Central, Kilamba, Luanda",
                "neighborhood": "Kilamba",
                "latitude": -8.9333,
                "longitude": 13.2667,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd143",
                                "service": "Consulta Geral",
                                "category_id": None,
                                "prefix": "CG",
                                "open_time": time(8, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Consulta", "Geral", "Saúde"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 10. ENDE - Empresa Nacional de Distribuição de Electricidade (Serviços Públicos)

    # 10. ENDE - Empresa Nacional de Distribuição de Electricidade (Serviços Públicos)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd144",
        "name": "ENDE Angola",
        "description": "Empresa de distribuição de electricidade em Angola",
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
                        "sector": "Serviços Públicos",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd145",
                                "service": "Nova Ligação",
                                "category_id": None,
                                "prefix": "NL",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Ligação", "Electricidade", "Serviços Públicos"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd146",
                                "service": "Reclamações",
                                "category_id": None,
                                "prefix": "RC",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Reclamação", "Electricidade", "Serviços Públicos"]
                            }
                        ]
                    },
                    {
                        "name": "Pagamentos",
                        "sector": "Serviços Públicos",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd147",
                                "service": "Pagamento de Faturas",
                                "category_id": None,
                                "prefix": "PF",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 30,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Pagamento", "Fatura", "Serviços Públicos"]
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
                        "sector": "Serviços Públicos",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd148",
                                "service": "Nova Ligação",
                                "category_id": None,
                                "prefix": "NL",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Ligação", "Electricidade", "Serviços Públicos"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Huambo",
                "location": "Avenida Norton de Matos, Huambo",
                "neighborhood": "Cidade Alta",
                "latitude": -12.7761,
                "longitude": 15.7392,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Serviços Públicos",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd149",
                                "service": "Nova Ligação",
                                "category_id": None,
                                "prefix": "NL",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Ligação", "Electricidade", "Serviços Públicos"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Benguela",
                "location": "Rua 31 de Janeiro, Benguela",
                "neighborhood": "Centro",
                "latitude": -12.5905,
                "longitude": 13.4167,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Serviços Públicos",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd150",
                                "service": "Nova Ligação",
                                "category_id": None,
                                "prefix": "NL",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Ligação", "Electricidade", "Serviços Públicos"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 11. EPAL - Empresa Pública de Águas de Luanda (Serviços Públicos)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd151",
        "name": "EPAL Angola",
        "description": "Empresa de distribuição de água em Luanda",
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
                        "sector": "Serviços Públicos",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd152",
                                "service": "Nova Ligação de Água",
                                "category_id": None,
                                "prefix": "NA",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Ligação", "Água", "Serviços Públicos"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd153",
                                "service": "Reclamações",
                                "category_id": None,
                                "prefix": "RC",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Reclamação", "Água", "Serviços Públicos"]
                            }
                        ]
                    },
                    {
                        "name": "Pagamentos",
                        "sector": "Serviços Públicos",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd154",
                                "service": "Pagamento de Faturas",
                                "category_id": None,
                                "prefix": "PF",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 30,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Pagamento", "Fatura", "Serviços Públicos"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Cazenga",
                "location": "Rua do Comércio, Cazenga, Luanda",
                "neighborhood": "Cazenga",
                "latitude": -8.8500,
                "longitude": 13.2833,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Serviços Públicos",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd155",
                                "service": "Nova Ligação de Água",
                                "category_id": None,
                                "prefix": "NA",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Ligação", "Água", "Serviços Públicos"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Viana",
                "location": "Estrada de Viana, Viana, Luanda",
                "neighborhood": "Viana",
                "latitude": -8.9035,
                "longitude": 13.3741,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Serviços Públicos",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd156",
                                "service": "Nova Ligação de Água",
                                "category_id": None,
                                "prefix": "NA",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Ligação", "Água", "Serviços Públicos"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 12. Banco Económico Angola (Bancário)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd157",
        "name": "Banco Económico Angola",
        "description": "Banco comercial com serviços financeiros em Angola",
        "branches": [
            {
                "name": "Agência Ingombota",
                "location": "Avenida Lenine, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd158",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd159",
                                "service": "Abertura de Conta",
                                "category_id": None,
                                "prefix": "AC",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Conta", "Bancário"]
                            }
                        ]
                    },
                    {
                        "name": "Caixa",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd160",
                                "service": "Caixa",
                                "category_id": None,
                                "prefix": "CX",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 25,
                                "num_counters": 6,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Caixa", "Bancário"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Kilamba",
                "location": "Avenida Comandante Gika, Kilamba, Luanda",
                "neighborhood": "Kilamba",
                "latitude": -8.9333,
                "longitude": 13.2667,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd161",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Lobito",
                "location": "Avenida da Independência, Lobito, Benguela",
                "neighborhood": "Comercial",
                "latitude": -12.3487,
                "longitude": 13.5465,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd162",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 13. Instituto Nacional de Segurança Social (Administração Pública)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd163",
        "name": "INSS Angola",
        "description": "Instituto de segurança social em Angola",
        "branches": [
            {
                "name": "Sede Ingombota",
                "location": "Rua Amílcar Cabral, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Registos",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd164",
                                "service": "Inscrição de Contribuinte",
                                "category_id": None,
                                "prefix": "IC",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 25,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Inscrição", "Segurança Social", "Administração"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd165",
                                "service": "Consulta de Contribuições",
                                "category_id": None,
                                "prefix": "CC",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Contribuições", "Segurança Social", "Administração"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Posto Talatona",
                "location": "Rua Principal, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Registos",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd166",
                                "service": "Inscrição de Contribuinte",
                                "category_id": None,
                                "prefix": "IC",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 25,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Inscrição", "Segurança Social", "Administração"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Posto Huambo",
                "location": "Avenida da República, Huambo",
                "neighborhood": "Cidade Alta",
                "latitude": -12.7761,
                "longitude": 15.7392,
                "departments": [
                    {
                        "name": "Registos",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd167",
                                "service": "Inscrição de Contribuinte",
                                "category_id": None,
                                "prefix": "IC",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 25,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Inscrição", "Segurança Social", "Administração"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 14. Kero Hipermercado (Varejo)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd168",
        "name": "Kero Hipermercado",
        "description": "Cadeia de hipermercados em Angola",
        "branches": [
            {
                "name": "Loja Kilamba",
                "location": "Avenida Comandante Gika, Kilamba, Luanda",
                "neighborhood": "Kilamba",
                "latitude": -8.9333,
                "longitude": 13.2667,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Varejo",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd169",
                                "service": "Devoluções",
                                "category_id": None,
                                "prefix": "DV",
                                "open_time": time(9, 0),
                                "end_time": time(20, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(9, 0), "end_time": time(18, 0)}
                                ],
                                "tags": ["Devolução", "Varejo"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd170",
                                "service": "Reclamações",
                                "category_id": None,
                                "prefix": "RC",
                                "open_time": time(9, 0),
                                "end_time": time(20, 0),
                                "daily_limit": 10,
                                "num_counters": 1,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(9, 0), "end_time": time(18, 0)}
                                ],
                                "tags": ["Reclamação", "Varejo"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Talatona",
                "location": "Belas Shopping, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Varejo",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd171",
                                "service": "Devoluções",
                                "category_id": None,
                                "prefix": "DV",
                                "open_time": time(9, 0),
                                "end_time": time(20, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(9, 0), "end_time": time(18, 0)}
                                ],
                                "tags": ["Devolução", "Varejo"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Huambo",
                "location": "Avenida da Independência, Huambo",
                "neighborhood": "Cidade Alta",
                "latitude": -12.7761,
                "longitude": 15.7392,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Varejo",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd172",
                                "service": "Devoluções",
                                "category_id": None,
                                "prefix": "DV",
                                "open_time": time(9, 0),
                                "end_time": time(20, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(9, 0), "end_time": time(18, 0)}
                                ],
                                "tags": ["Devolução", "Varejo"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Benguela",
                "location": "Avenida 10 de Fevereiro, Benguela",
                "neighborhood": "Centro",
                "latitude": -12.5905,
                "longitude": 13.4167,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Varejo",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd173",
                                "service": "Devoluções",
                                "category_id": None,
                                "prefix": "DV",
                                "open_time": time(9, 0),
                                "end_time": time(20, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(20, 0)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(9, 0), "end_time": time(18, 0)}
                                ],
                                "tags": ["Devolução", "Varejo"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 15. Ministério das Finanças - Serviço de Impostos (Administração Pública)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd174",
        "name": "Ministério das Finanças - Serviço de Impostos",
        "description": "Serviços fiscais e de tributação em Angola",
        "branches": [
            {
                "name": "Sede Ingombota",
                "location": "Avenida 4 de Fevereiro, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Atendimento Fiscal",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd175",
                                "service": "Declaração de Impostos",
                                "category_id": None,
                                "prefix": "DI",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Impostos", "Fiscal", "Administração"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd176",
                                "service": "Pagamento de Impostos",
                                "category_id": None,
                                "prefix": "PI",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 25,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Pagamento", "Impostos", "Administração"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Posto Cazenga",
                "location": "Rua Principal, Cazenga, Luanda",
                "neighborhood": "Cazenga",
                "latitude": -8.8500,
                "longitude": 13.2833,
                "departments": [
                    {
                        "name": "Atendimento Fiscal",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd177",
                                "service": "Declaração de Impostos",
                                "category_id": None,
                                "prefix": "DI",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Impostos", "Fiscal", "Administração"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Posto Huambo",
                "location": "Avenida da República, Huambo",
                "neighborhood": "Cidade Alta",
                "latitude": -12.7761,
                "longitude": 15.7392,
                "departments": [
                    {
                        "name": "Atendimento Fiscal",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd178",
                                "service": "Declaração de Impostos",
                                "category_id": None,
                                "prefix": "DI",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Impostos", "Fiscal", "Administração"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 16. Clínica Sagrada Esperança (Saúde)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd179",
        "name": "Clínica Sagrada Esperança",
        "description": "Clínica privada de saúde em Angola",
        "branches": [
            {
                "name": "Unidade Ingombota",
                "location": "Avenida Murtala Mohammed, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd180",
                                "service": "Consulta Geral",
                                "category_id": None,
                                "prefix": "CG",
                                "open_time": time(8, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Consulta", "Geral", "Saúde"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd181",
                                "service": "Exames Laboratoriais",
                                "category_id": None,
                                "prefix": "EL",
                                "open_time": time(7, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(7, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(7, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(7, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(7, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(7, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Exames", "Laboratório", "Saúde"]
                            }
                        ]
                    },
                    {
                        "name": "Emergência",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd182",
                                "service": "Emergência",
                                "category_id": None,
                                "prefix": "EM",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
                                "daily_limit": 30,
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
                                "tags": ["Emergência", "Saúde"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Talatona",
                "location": "Via Expressa, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd183",
                                "service": "Consulta Geral",
                                "category_id": None,
                                "prefix": "CG",
                                "open_time": time(8, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Consulta", "Geral", "Saúde"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Benguela",
                "location": "Rua 31 de Janeiro, Benguela",
                "neighborhood": "Centro",
                "latitude": -12.5905,
                "longitude": 13.4167,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd184",
                                "service": "Consulta Geral",
                                "category_id": None,
                                "prefix": "CG",
                                "open_time": time(8, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Consulta", "Geral", "Saúde"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 17. Banco de Poupança e Crédito (Bancário)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd185",
        "name": "Banco de Poupança e Crédito",
        "description": "Banco estatal com serviços financeiros em Angola",
        "branches": [
            {
                "name": "Agência Maianga",
                "location": "Rua Che Guevara, Maianga, Luanda",
                "neighborhood": "Maianga",
                "latitude": -8.8147,
                "longitude": 13.2302,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd186",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd187",
                                "service": "Crédito Pessoal",
                                "category_id": None,
                                "prefix": "CP",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 10,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Crédito", "Bancário"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Cazenga",
                "location": "Rua do Comércio, Cazenga, Luanda",
                "neighborhood": "Cazenga",
                "latitude": -8.8500,
                "longitude": 13.2833,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd188",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Huambo",
                "location": "Avenida Norton de Matos, Huambo",
                "neighborhood": "Cidade Alta",
                "latitude": -12.7761,
                "longitude": 15.7392,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd189",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Benguela",
                "location": "Rua 31 de Janeiro, Benguela",
                "neighborhood": "Centro",
                "latitude": -12.5905,
                "longitude": 13.4167,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd190",
                                "service": "Atendimento Geral",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Atendimento", "Bancário"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 18. Universidade Católica de Angola (Educação)

    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd191",
        "name": "Universidade Católica de Angola",
        "description": "Universidade privada em Angola",
        "branches": [
            {
                "name": "Campus Palanca",
                "location": "Rua do Palanca, Luanda",
                "neighborhood": "Palanca",
                "latitude": -8.8333,
                "longitude": 13.2500,
                "departments": [
                    {
                        "name": "Secretaria Acadêmica",
                        "sector": "Educação",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd192",
                                "service": "Matrícula",
                                "category_id": None,
                                "prefix": "MT",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Matrícula", "Educação", "Universidade"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd193",
                                "service": "Emissão de Certificados",
                                "category_id": None,
                                "prefix": "EC",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Certificado", "Educação", "Universidade"]
                            }
                        ]
                    },
                    {
                        "name": "Tesouraria",
                        "sector": "Educação",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd194",
                                "service": "Pagamento de Propinas",
                                "category_id": None,
                                "prefix": "PP",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 25,
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
                                "tags": ["Pagamento", "Propinas", "Educação"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Campus Talatona",
                "location": "Via Expressa, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Secretaria Acadêmica",
                        "sector": "Educação",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd195",
                                "service": "Matrícula",
                                "category_id": None,
                                "prefix": "MT",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Matrícula", "Educação", "Universidade"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Campus Huambo",
                "location": "Avenida Norton de Matos, Huambo",
                "neighborhood": "Cidade Alta",
                "latitude": -12.7761,
                "longitude": 15.7392,
                "departments": [
                    {
                        "name": "Secretaria Acadêmica",
                        "sector": "Educação",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd196",
                                "service": "Matrícula",
                                "category_id": None,
                                "prefix": "MT",
                                "open_time": time(8, 0),
                                "end_time": time(16, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(16, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Matrícula", "Educação", "Universidade"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 19. Unitel Angola (Telecomunicações)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd197",
        "name": "Unitel Angola",
        "description": "Operadora de telecomunicações líder em Angola",
        "branches": [
            {
                "name": "Loja Ingombota",
                "location": "Avenida 4 de Fevereiro, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Telecomunicações",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd198",
                                "service": "Nova Linha",
                                "category_id": None,
                                "prefix": "NL",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 30,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(14, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Linha", "Telecomunicações", "Atendimento"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd199",
                                "service": "Reclamações",
                                "category_id": None,
                                "prefix": "RC",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(14, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Reclamação", "Telecomunicações", "Atendimento"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd200",
                                "service": "Suporte Técnico",
                                "category_id": None,
                                "prefix": "ST",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 15,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(14, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Suporte", "Técnico", "Telecomunicações"]
                            }
                        ]
                    },
                    {
                        "name": "Vendas",
                        "sector": "Telecomunicações",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd201",
                                "service": "Venda de Planos",
                                "category_id": None,
                                "prefix": "VP",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 25,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(14, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Planos", "Vendas", "Telecomunicações"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Talatona",
                "location": "Belas Shopping, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Telecomunicações",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd202",
                                "service": "Nova Linha",
                                "category_id": None,
                                "prefix": "NL",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 30,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(14, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Linha", "Telecomunicações", "Atendimento"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Benguela",
                "location": "Avenida 10 de Fevereiro, Benguela",
                "neighborhood": "Centro",
                "latitude": -12.5905,
                "longitude": 13.4167,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Telecomunicações",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd203",
                                "service": "Nova Linha",
                                "category_id": None,
                                "prefix": "NL",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 30,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(14, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Linha", "Telecomunicações", "Atendimento"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Loja Huambo",
                "location": "Avenida da Independência, Huambo",
                "neighborhood": "Cidade Alta",
                "latitude": -12.7761,
                "longitude": 15.7392,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Telecomunicações",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd204",
                                "service": "Nova Linha",
                                "category_id": None,
                                "prefix": "NL",
                                "open_time": time(8, 0),
                                "end_time": time(18, 0),
                                "daily_limit": 30,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(18, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(9, 0), "end_time": time(14, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Linha", "Telecomunicações", "Atendimento"]
                            }
                        ]
                    }
                ]
            }
        ]
    },
    # 20. Serviço de Identificação Civil e Criminal (Administração Pública)
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd205",
        "name": "Serviço de Identificação Civil e Criminal",
        "description": "Serviço de emissão de documentos de identificação em Angola",
        "branches": [
            {
                "name": "Posto Ingombota",
                "location": "Rua Amílcar Cabral, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Emissão de Documentos",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd206",
                                "service": "Emissão de Bilhete de Identidade",
                                "category_id": None,
                                "prefix": "BI",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 25,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Bilhete", "Identidade", "Administração"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd207",
                                "service": "Registo Criminal",
                                "category_id": None,
                                "prefix": "RC",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Registo", "Criminal", "Administração"]
                            },
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd208",
                                "service": "Renovação de Bilhete",
                                "category_id": None,
                                "prefix": "RB",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 20,
                                "num_counters": 4,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Renovação", "Bilhete", "Administração"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Posto Cazenga",
                "location": "Rua Principal, Cazenga, Luanda",
                "neighborhood": "Cazenga",
                "latitude": -8.8500,
                "longitude": 13.2833,
                "departments": [
                    {
                        "name": "Emissão de Documentos",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd209",
                                "service": "Emissão de Bilhete de Identidade",
                                "category_id": None,
                                "prefix": "BI",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 25,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Bilhete", "Identidade", "Administração"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Posto Huambo",
                "location": "Avenida da República, Huambo",
                "neighborhood": "Cidade Alta",
                "latitude": -12.7761,
                "longitude": 15.7392,
                "departments": [
                    {
                        "name": "Emissão de Documentos",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd210",
                                "service": "Emissão de Bilhete de Identidade",
                                "category_id": None,
                                "prefix": "BI",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 25,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Bilhete", "Identidade", "Administração"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Posto Benguela",
                "location": "Rua 31 de Janeiro, Benguela",
                "neighborhood": "Centro",
                "latitude": -12.5905,
                "longitude": 13.4167,
                "departments": [
                    {
                        "name": "Emissão de Documentos",
                        "sector": "Administração Pública",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd211",
                                "service": "Emissão de Bilhete de Identidade",
                                "category_id": None,
                                "prefix": "BI",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 25,
                                "num_counters": 5,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(8, 0), "end_time": time(15, 0)},
                                    {"weekday": Weekday.SATURDAY, "is_closed": True},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Bilhete", "Identidade", "Administração"]
                            }
                        ]
                    }
                ]
            }
        ]
    }
]


def initial_data(app):
    """
    Popula o banco de dados com dados iniciais para testes, incluindo instituições, filiais, departamentos e filas.
    Cada instituição tem filiais em diferentes bairros de Luanda, com 15 senhas por fila.
    Mantém idempotência, logs em português, IDs fixos para filas principais, e compatibilidade com models.py.
    Usa bcrypt para senhas e respeita todos os relacionamentos.
    Suporta modelos de ML com dados suficientes para treinamento inicial.
    """
    with app.app_context():
        try:
            # Desativar autoflush para evitar problemas durante a inserção
            with db.session.no_autoflush:
                app.logger.info("Iniciando população de dados iniciais...")

                # --------------------------------------
                # Criar Categorias de Serviço
                # --------------------------------------
                def create_service_categories():
                    """
                    Cria categorias de serviço necessárias (Saúde, Consulta Médica, Bancário).
                    Retorna um mapa de nomes para IDs.
                    """
                    categories = []
                    for inst in institutions_data:
                        for branch in inst['branches']:
                            for dept in branch['departments']:
                                for queue in dept['queues']:
                                    if queue.get('category_id') is not None:
                                        category_name = queue['category_id']
                                        if category_name not in [cat['name'] for cat in categories]:
                                            categories.append({'name': category_name, 'description': f'Serviços de {category_name}', 'parent_id': None})

                    category_map = {}
                    for cat in categories:
                        existing_cat = ServiceCategory.query.filter_by(name=cat['name']).first()
                        if existing_cat:
                            category_map[cat['name']] = existing_cat.id
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

                    app.logger.info("Categorias de serviço criadas com sucesso.")
                    return category_map

                category_map = create_service_categories()

                # --------------------------------------
                # Funções Auxiliares para Criação de Entidades
                # --------------------------------------
                def create_queue(department_id, queue_data):
                    """
                    Cria uma fila com agendamentos e tags, conforme models.py.
                    """
                    existing_queue = Queue.query.filter_by(id=queue_data['id']).first()
                    if existing_queue:
                        app.logger.info(f"Fila {queue_data['service']} já existe com ID {queue_data['id']}, pulando.")
                        return existing_queue

                    queue = Queue(
                        id=queue_data['id'],
                        department_id=department_id,
                        service=queue_data['service'],
                        category_id=category_map.get(queue_data['category_id'], None),  # Usando o mapeamento de categorias
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
                        existing_schedule = QueueSchedule.query.filter_by(queue_id=queue.id, weekday=schedule['weekday']).first()
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

                    # Criar tags
                    for tag_name in queue_data['tags']:
                        existing_tag = ServiceTag.query.filter_by(queue_id=queue.id, tag=tag_name).first()
                        if existing_tag:
                            continue
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
                    existing_dept = Department.query.filter_by(branch_id=branch_id, name=dept_data['name']).first()
                    if existing_dept:
                        app.logger.info(f"Departamento {dept_data['name']} já existe na filial, pulando.")
                        return existing_dept

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
                    existing_branch = Branch.query.filter_by(institution_id=institution_id, name=branch_data['name']).first()
                    if existing_branch:
                        app.logger.info(f"Filial {branch_data['name']} já existe na instituição, pulando.")
                        return existing_branch

                    branch = Branch(
                        id=str(uuid.uuid4()),
                        institution_id=institution_id,
                        name=branch_data['name'],
                        location=branch_data['location'],
                        neighborhood=branch_data['neighborhood'],  # Usando o bairro da estrutura
                        latitude=branch_data['latitude'],          # Usando a latitude da estrutura
                        longitude=branch_data['longitude']         # Usando a longitude da estrutura
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
                    existing_inst = Institution.query.filter_by(id=inst_data['id']).first()
                    if existing_inst:
                        app.logger.info(f"Instituição {inst_data['name']} já existe com ID {inst_data['id']}, pulando.")
                        return existing_inst

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

                # Criar instituições
                app.logger.info("Criando instituições...")
                for inst_data in institutions_data:
                    create_institution(inst_data)
                app.logger.info("Instituições, filiais, departamentos e filas criados com sucesso.")

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro ao popular dados: {str(e)}")
            raise
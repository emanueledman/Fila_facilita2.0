import uuid
from datetime import time, datetime, timedelta
from .models import AuditLog, Institution, Queue, User, Ticket, Department, UserPreference, UserRole, QueueSchedule, Weekday, Branch, ServiceCategory, ServiceTag, InstitutionType
from . import db
import os
from sqlalchemy.exc import SQLAlchemyError

# Dados de teste para 5 instituições, cada uma com 3 filiais
institutions_data = [
    {
        "id": "018d6313-5bf1-7062-a3bd-0e99679fd099",
        "name": "SIAC",
        "description": "Serviço Integrado de Atendimento ao Cidadão em Luanda",
        "institution_type_id": None,  # Será preenchido com Administrativo
        "branches": [
            {
                "name": "Unidade Ingombota",
                "location": "Avenida 4 de Fevereiro, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8167,
                "longitude": 13.2332,
                "departments": [
                    {
                        "name": "Atendimento ao Cidadão",
                        "sector": "Administrativo",
                        "queues": [
                            {
                                "id": "018d6313-5bf1-7062-a3bd-0e99679fd100",
                                "service": "Atendimento Geral 24/7",
                                "category_id": None,  # Será preenchido com Administrativo
                                "prefix": "AG",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
                                "daily_limit": 100,
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
                                "tags": ["Atendimento", "Administrativo", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Emissão de Documentos",
                                "category_id": None,  # Será preenchido com Documentos
                                "prefix": "ED",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 100,
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
                                "tags": ["Documentos", "Administrativo"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Maianga",
                "location": "Rua Che Guevara, Maianga, Luanda",
                "neighborhood": "Maianga",
                "latitude": -8.8147,
                "longitude": 13.2302,
                "departments": [
                    {
                        "name": "Atendimento ao Cidadão",
                        "sector": "Administrativo",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Atendimento Geral 24/7",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
                                "daily_limit": 100,
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
                                "tags": ["Atendimento", "Administrativo", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Emissão de Documentos",
                                "category_id": None,
                                "prefix": "ED",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 100,
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
                                "tags": ["Documentos", "Administrativo"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Talatona",
                "location": "Condomínio Belas Business Park, Talatona, Luanda",
                "neighborhood": "Talatona",
                "latitude": -8.9167,
                "longitude": 13.1833,
                "departments": [
                    {
                        "name": "Atendimento ao Cidadão",
                        "sector": "Administrativo",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Atendimento Geral 24/7",
                                "category_id": None,
                                "prefix": "AG",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
                                "daily_limit": 100,
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
                                "tags": ["Atendimento", "Administrativo", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Emissão de Documentos",
                                "category_id": None,
                                "prefix": "ED",
                                "open_time": time(8, 0),
                                "end_time": time(15, 0),
                                "daily_limit": 100,
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
                                "tags": ["Documentos", "Administrativo"]
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
        "institution_type_id": None,  # Será preenchido com Bancário
        "branches": [
            {
                "name": "Agência Ingombota",
                "location": "Avenida Lenine, Ingombota, Luanda",
                "neighborhood": "Ingombota",
                "latitude": -8.8160,
                "longitude": 13.2340,
                "departments": [
                    {
                        "name": "Atendimento ao Cliente",
                        "sector": "Bancário",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Atendimento Bancário 24/7",
                                "category_id": None,  # Será preenchido com Bancário
                                "prefix": "AB",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
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
                                "tags": ["Bancário", "Atendimento", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Abertura de Conta",
                                "category_id": None,  # Será preenchido com Conta
                                "prefix": "AC",
                                "open_time": time(8, 30),
                                "end_time": time(15, 30),
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
                                "tags": ["Bancário", "Conta"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Kilamba",
                "location": "Cidade do Kilamba, Luanda",
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
                                "service": "Atendimento Bancário 24/7",
                                "category_id": None,
                                "prefix": "AB",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
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
                                "tags": ["Bancário", "Atendimento", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Abertura de Conta",
                                "category_id": None,
                                "prefix": "AC",
                                "open_time": time(8, 30),
                                "end_time": time(15, 30),
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
                                "tags": ["Bancário", "Conta"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Agência Cazenga",
                "location": "Rua do Mercado, Cazenga, Luanda",
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
                                "service": "Atendimento Bancário 24/7",
                                "category_id": None,
                                "prefix": "AB",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
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
                                "tags": ["Bancário", "Atendimento", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Abertura de Conta",
                                "category_id": None,
                                "prefix": "AC",
                                "open_time": time(8, 30),
                                "end_time": time(15, 30),
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
                                "tags": ["Bancário", "Conta"]
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
        "institution_type_id": None,  # Será preenchido com Saúde
        "branches": [
            {
                "name": "Unidade Central",
                "location": "Avenida Ho Chi Minh, Luanda",
                "neighborhood": "Maianga",
                "latitude": -8.8145,
                "longitude": 13.2290,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Consulta Médica 24/7",
                                "category_id": None,  # Será preenchido com Consulta Médica
                                "prefix": "CM",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
                                "daily_limit": 100,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(0, 0), "end_time": time(23, 59)}
                                ],
                                "tags": ["Saúde", "Consulta", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Exames Laboratoriais",
                                "category_id": None,  # Será preenchido com Exames
                                "prefix": "EL",
                                "open_time": time(7, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 100,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(7, 0), "end_time": time(12, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Saúde", "Exames"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Viana",
                "location": "Estrada de Viana, Viana, Luanda",
                "neighborhood": "Viana",
                "latitude": -8.9035,
                "longitude": 13.3741,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Consulta Médica 24/7",
                                "category_id": None,
                                "prefix": "CM",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
                                "daily_limit": 100,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(0, 0), "end_time": time(23, 59)}
                                ],
                                "tags": ["Saúde", "Consulta", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Exames Laboratoriais",
                                "category_id": None,
                                "prefix": "EL",
                                "open_time": time(7, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 100,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(7, 0), "end_time": time(12, 0)},
                                    {"weekday": Weekday.SUNDAY, "is_closed": True}
                                ],
                                "tags": ["Saúde", "Exames"]
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Unidade Rangel",
                "location": "Avenida Deolinda Rodrigues, Rangel, Luanda",
                "neighborhood": "Rangel",
                "latitude": -8.8300,
                "longitude": 13.2500,
                "departments": [
                    {
                        "name": "Consulta Geral",
                        "sector": "Saúde",
                        "queues": [
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Consulta Médica 24/7",
                                "category_id": None,
                                "prefix": "CM",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
                                "daily_limit": 100,
                                "num_counters": 3,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(0, 0), "end_time": time(23, 59)},
                                    {"weekday": Weekday.SUNDAY, "open_time": time(0, 0), "end_time": time(23, 59)}
                                ],
                                "tags": ["Saúde", "Consulta", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Exames Laboratoriais",
                                "category_id": None,
                                "prefix": "EL",
                                "open_time": time(7, 0),
                                "end_time": time(17, 0),
                                "daily_limit": 100,
                                "num_counters": 2,
                                "schedules": [
                                    {"weekday": Weekday.MONDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.TUESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.WEDNESDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.THURSDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.FRIDAY, "open_time": time(7, 0), "end_time": time(17, 0)},
                                    {"weekday": Weekday.SATURDAY, "open_time": time(7, 0), "end_time": time(12, 0)},
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
        "name": "Banco BAI",
        "description": "Serviços bancários em Luanda",
        "institution_type_id": None,  # Será preenchido com Bancário
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
                                "service": "Atendimento Bancário 24/7",
                                "category_id": None,  # Será preenchido com Bancário
                                "prefix": "AB",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
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
                                "tags": ["Bancário", "Atendimento", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Empréstimos",
                                "category_id": None,  # Será preenchido com Empréstimo
                                "prefix": "EM",
                                "open_time": time(8, 30),
                                "end_time": time(15, 30),
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
                                "service": "Atendimento Bancário 24/7",
                                "category_id": None,
                                "prefix": "AB",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
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
                                "tags": ["Bancário", "Atendimento", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Empréstimos",
                                "category_id": None,
                                "prefix": "EM",
                                "open_time": time(8, 30),
                                "end_time": time(15, 30),
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
                                "service": "Atendimento Bancário 24/7",
                                "category_id": None,
                                "prefix": "AB",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
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
                                "tags": ["Bancário", "Atendimento", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Empréstimos",
                                "category_id": None,
                                "prefix": "EM",
                                "open_time": time(8, 30),
                                "end_time": time(15, 30),
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
        "institution_type_id": None,  # Será preenchido com Bancário
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
                                "service": "Atendimento Bancário 24/7",
                                "category_id": None,  # Será preenchido com Bancário
                                "prefix": "AB",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
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
                                "tags": ["Bancário", "Atendimento", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Investimentos",
                                "category_id": None,  # Será preenchido com Investimento
                                "prefix": "IN",
                                "open_time": time(8, 30),
                                "end_time": time(15, 30),
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
                                "service": "Atendimento Bancário 24/7",
                                "category_id": None,
                                "prefix": "AB",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
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
                                "tags": ["Bancário", "Atendimento", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Investimentos",
                                "category_id": None,
                                "prefix": "IN",
                                "open_time": time(8, 30),
                                "end_time": time(15, 30),
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
                                "service": "Atendimento Bancário 24/7",
                                "category_id": None,
                                "prefix": "AB",
                                "open_time": time(0, 0),
                                "end_time": time(23, 59),
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
                                "tags": ["Bancário", "Atendimento", "24/7"]
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "service": "Investimentos",
                                "category_id": None,
                                "prefix": "IN",
                                "open_time": time(8, 30),
                                "end_time": time(15, 30),
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
    }
]

import uuid
from datetime import time, datetime, timedelta
from .models import AuditLog, Institution, Queue, User, Ticket, Department, UserPreference, UserRole, QueueSchedule, Weekday, Branch, ServiceCategory, ServiceTag, InstitutionType
from . import db
import os
from sqlalchemy.exc import SQLAlchemyError

# Dados de teste (mantidos idênticos ao fornecidos anteriormente)
institutions_data = [
    # ... (os dados de teste fornecidos anteriormente, com 5 instituições, 3 filiais cada, etc.)
    # Para evitar repetição, assumo que você tem os dados completos da resposta anterior
]

def populate_initial_data(app):
    """
    Popula o banco de dados com dados iniciais para testes, incluindo 5 instituições (SIAC, Banco BIC, Hospital Josina Machel, Banco BAI, Banco BFA),
    cada uma com 3 filiais em Luanda. Cada filial tem 2 filas (1 24/7 e 1 com horário comercial). Cada fila tem 50 tickets.
    Mantém idempotência, logs em português, e compatibilidade com models.py atualizado (incluindo is_client).
    Usa bcrypt para senhas e respeita todos os relacionamentos, incluindo InstitutionType e UserPreference.
    Suporta modelos de ML com dados suficientes para treinamento inicial.
    """
    with app.app_context():
        try:
            # Desativar autoflush para evitar problemas durante a inserção
            with db.session.no_autoflush:
                app.logger.info("Iniciando população de dados iniciais...")

                # --------------------------------------
                # Criar Tipos de Instituição
                # --------------------------------------
                def create_institution_types():
                    types = [
                        {'name': 'Administrativo', 'description': 'Serviços administrativos e atendimento ao cidadão'},
                        {'name': 'Bancário', 'description': 'Serviços financeiros e bancários'},
                        {'name': 'Saúde', 'description': 'Serviços de saúde e atendimento médico'}
                    ]
                    type_map = {}
                    for inst_type in types:
                        existing_type = db.session.query(InstitutionType).filter(InstitutionType.name == inst_type['name']).first()
                        if existing_type:
                            type_map[inst_type['name']] = existing_type.id
                            continue
                        institution_type = InstitutionType(
                            id=str(uuid.uuid4()),
                            name=inst_type['name'],
                            description=inst_type['description']
                        )
                        db.session.add(institution_type)
                        db.session.flush()
                        type_map[inst_type['name']] = institution_type.id
                    app.logger.info("Tipos de instituição criados com sucesso.")
                    return type_map

                institution_type_map = create_institution_types()

                # Atualizar institution_type_id nos dados de teste
                for inst in institutions_data:
                    if inst['name'] == 'SIAC':
                        inst['institution_type_id'] = institution_type_map['Administrativo']
                    elif inst['name'] in ['Banco BIC', 'Banco BAI', 'Banco BFA']:
                        inst['institution_type_id'] = institution_type_map['Bancário']
                    elif inst['name'] == 'Hospital Josina Machel':
                        inst['institution_type_id'] = institution_type_map['Saúde']

                # --------------------------------------
                # Criar Categorias de Serviço
                # --------------------------------------
                def create_service_categories():
                    categories = [
                        {'name': 'Saúde', 'description': 'Serviços de saúde e atendimento médico', 'parent_id': None},
                        {'name': 'Consulta Médica', 'description': 'Consultas gerais e especializadas', 'parent_id': None},
                        {'name': 'Administrativo', 'description': 'Serviços administrativos municipais e atendimento ao cidadão', 'parent_id': None},
                        {'name': 'Bancário', 'description': 'Serviços financeiros e bancários', 'parent_id': None},
                        {'name': 'Documentos', 'description': 'Emissão e renovação de documentos', 'parent_id': None},
                        {'name': 'Exames', 'description': 'Exames laboratoriais e diagnósticos', 'parent_id': None},
                        {'name': 'Conta', 'description': 'Abertura e gestão de contas bancárias', 'parent_id': None},
                        {'name': 'Empréstimo', 'description': 'Solicitação e gestão de empréstimos', 'parent_id': None},
                        {'name': 'Investimento', 'description': 'Serviços de investimento financeiro', 'parent_id': None}
                    ]
                    category_map = {}
                    for cat in categories:
                        existing_cat = db.session.query(ServiceCategory).filter(ServiceCategory.name == cat['name']).first()
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
                    for cat_name, parent_name in [
                        ('Consulta Médica', 'Saúde'),
                        ('Exames', 'Saúde'),
                        ('Documentos', 'Administrativo'),
                        ('Conta', 'Bancário'),
                        ('Empréstimo', 'Bancário'),
                        ('Investimento', 'Bancário')
                    ]:
                        cat = db.session.query(ServiceCategory).filter(ServiceCategory.name == cat_name).first()
                        if cat and not cat.parent_id:
                            cat.parent_id = category_map[parent_name]
                            db.session.flush()
                    app.logger.info("Categorias de serviço criadas com sucesso.")
                    return category_map

                category_map = create_service_categories()

                # Atualizar category_id nas filas dos dados de teste
                for inst in institutions_data:
                    for branch in inst['branches']:
                        for dept in branch['departments']:
                            for queue in dept['queues']:
                                if 'Saúde' in queue['tags'] and 'Consulta' in queue['tags']:
                                    queue['category_id'] = category_map['Consulta Médica']
                                elif 'Saúde' in queue['tags'] and 'Exames' in queue['tags']:
                                    queue['category_id'] = category_map['Exames']
                                elif 'Administrativo' in queue['tags'] and 'Documentos' in queue['tags']:
                                    queue['category_id'] = category_map['Documentos']
                                elif 'Administrativo' in queue['tags']:
                                    queue['category_id'] = category_map['Administrativo']
                                elif 'Bancário' in queue['tags'] and 'Conta' in queue['tags']:
                                    queue['category_id'] = category_map['Conta']
                                elif 'Bancário' in queue['tags'] and 'Empréstimo' in queue['tags']:
                                    queue['category_id'] = category_map['Empréstimo']
                                elif 'Bancário' in queue['tags'] and 'Investimento' in queue['tags']:
                                    queue['category_id'] = category_map['Investimento']
                                elif 'Bancário' in queue['tags']:
                                    queue['category_id'] = category_map['Bancário']

                # --------------------------------------
                # Bairros de Luanda
                # --------------------------------------
                neighborhoods = [
                    {'name': 'Ingombota', 'latitude': -8.8167, 'longitude': 13.2332},
                    {'name': 'Maianga', 'latitude': -8.8147, 'longitude': 13.2302},
                    {'name': 'Talatona', 'latitude': -8.9167, 'longitude': 13.1833},
                    {'name': 'Kilamba', 'latitude': -8.9333, 'longitude': 13.2667},
                    {'name': 'Cazenga', 'latitude': -8.8500, 'longitude': 13.2833},
                    {'name': 'Viana', 'latitude': -8.9035, 'longitude': 13.3741},
                    {'name': 'Rangel', 'latitude': -8.8300, 'longitude': 13.2500}
                ]

                # --------------------------------------
                # Funções Auxiliares para Criação de Entidades
                # --------------------------------------
                def create_queue(department_id, queue_data):
                    existing_queue = db.session.query(Queue).filter(Queue.id == queue_data['id']).first()
                    if not existing_queue:
                        existing_queue = db.session.query(Queue).filter(
                            Queue.department_id == department_id, 
                            Queue.service == queue_data['service'],
                            Queue.prefix == queue_data['prefix']
                        ).first()
                    
                    if existing_queue:
                        app.logger.info(f"Fila {queue_data['service']} já existe com ID {existing_queue.id}, pulando.")
                        return existing_queue

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

                    for schedule in queue_data['schedules']:
                        existing_schedule = db.session.query(QueueSchedule).filter(
                            QueueSchedule.queue_id == queue.id, 
                            QueueSchedule.weekday == schedule['weekday']
                        ).first()
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

                    for tag_name in queue_data['tags']:
                        existing_tag = db.session.query(ServiceTag).filter(
                            ServiceTag.queue_id == queue.id, 
                            ServiceTag.tag == tag_name
                        ).first()
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
                    existing_dept = db.session.query(Department).filter(
                        Department.branch_id == branch_id, 
                        Department.name == dept_data['name']
                    ).first()
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
                    existing_branch = db.session.query(Branch).filter(
                        Branch.institution_id == institution_id, 
                        Branch.name == branch_data['name']
                    ).first()
                    if existing_branch:
                        app.logger.info(f"Filial {branch_data['name']} já existe na instituição, pulando.")
                        for dept_data in branch_data['departments']:
                            existing_dept = db.session.query(Department).filter(
                                Department.branch_id == existing_branch.id, 
                                Department.name == dept_data['name']
                            ).first()
                            if not existing_dept:
                                create_department(existing_branch.id, dept_data)
                            else:
                                for queue_data in dept_data['queues']:
                                    create_queue(existing_dept.id, queue_data)
                        return existing_branch

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
                    existing_inst = db.session.query(Institution).filter(Institution.name == inst_data['name']).first()
                    if existing_inst:
                        app.logger.info(f"Instituição {inst_data['name']} já existe, atualizando filiais se necessário.")
                        for branch_data in inst_data['branches']:
                            existing_branch = db.session.query(Branch).filter(
                                Branch.institution_id == existing_inst.id, 
                                Branch.name == branch_data['name']
                            ).first()
                            if not existing_branch:
                                create_branch(existing_inst.id, branch_data)
                            else:
                                for dept_data in branch_data['departments']:
                                    existing_dept = db.session.query(Department).filter(
                                        Department.branch_id == existing_branch.id, 
                                        Department.name == dept_data['name']
                                    ).first()
                                    if not existing_dept:
                                        create_department(existing_branch.id, dept_data)
                                    else:
                                        for queue_data in dept_data['queues']:
                                            create_queue(existing_dept.id, queue_data)
                        return existing_inst

                    institution = Institution(
                        id=inst_data['id'],
                        name=inst_data['name'],
                        description=inst_data['description'],
                        institution_type_id=inst_data['institution_type_id']
                    )
                    db.session.add(institution)
                    db.session.flush()

                    for branch_data in inst_data['branches']:
                        create_branch(institution.id, branch_data)

                    return institution

                app.logger.info("Criando ou atualizando instituições...")
                for inst_data in institutions_data:
                    create_institution(inst_data)
                app.logger.info("Instituições, filiais, departamentos e filas criados ou atualizados com sucesso.")

                # --------------------------------------
                # Criar Usuários
                # --------------------------------------
                def create_users():
                    users = []
                    if not db.session.query(User).filter(User.email == 'sysadmin@queue.com').first():
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

                    for inst in db.session.query(Institution).all():
                        email = f'admin_{inst.name.lower().replace(" ", "_")}@queue.com'
                        if not db.session.query(User).filter(User.email == email).first():
                            admin = User(
                                id=str(uuid.uuid4()),
                                email=email,
                                name=f'Admin {inst.name}',
                                user_role=UserRole.INSTITUTION_ADMIN,
                                institution_id=inst.id,
                                created_at=datetime.utcnow(),
                                active=True
                            )
                            admin.set_password('admin123')
                            db.session.add(admin)
                            users.append(admin)

                    for dept in db.session.query(Department).all():
                        inst_name = dept.branch.institution.name.lower().replace(" ", "_")
                        branch_name = dept.branch.name.lower().replace(" ", "_")
                        email = f'manager_{dept.name.lower().replace(" ", "_")}_{inst_name}_{branch_name}@queue.com'
                        if not db.session.query(User).filter(User.email == email).first():
                            manager = User(
                                id=str(uuid.uuid4()),
                                email=email,
                                name=f'Gerente {dept.name} {dept.branch.name}',
                                user_role=UserRole.DEPARTMENT_ADMIN,
                                department_id=dept.id,
                                institution_id=dept.branch.institution_id,
                                created_at=datetime.utcnow(),
                                active=True
                            )
                            manager.set_password('manager123')
                            db.session.add(manager)
                            users.append(manager)

                    user_count = db.session.query(User).filter(User.user_role == UserRole.USER).count()
                    if user_count < 15:
                        for i in range(15 - user_count):
                            email = f'user_{i}@queue.com'
                            if not db.session.query(User).filter(User.email == email).first():
                                user = User(
                                    id=str(uuid.uuid4()),
                                    email=email,
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
                    now = datetime.utcnow()
                    user_list = db.session.query(User).filter(User.user_role == UserRole.USER).limit(15).all()
                    categories = db.session.query(ServiceCategory).all()
                    institutions = db.session.query(Institution).all()
                    
                    ticket_counts = {}
                    for user in user_list:
                        ticket_counts[user.id] = {}
                        counts = (
                            db.session.query(Branch.institution_id, db.func.count(Ticket.id).label('ticket_count'))
                            .join(Queue, Ticket.queue_id == Queue.id)
                            .join(Department, Queue.department_id == Department.id)
                            .join(Branch, Department.branch_id == Branch.id)
                            .filter(Ticket.user_id == user.id)
                            .group_by(Branch.institution_id)
                            .all()
                        )
                        for inst_id, count in counts:
                            ticket_counts[user.id][inst_id] = count

                    for i, user in enumerate(user_list):
                        for j in range(3):
                            category = categories[(i + j) % len(categories)]
                            institution = institutions[(i + j) % len(institutions)]
                            neighborhood = neighborhoods[(i + j) % len(neighborhoods)]['name']
                            is_client = ticket_counts[user.id].get(institution.id, 0) >= 3
                            preference_score = min(ticket_counts[user.id].get(institution.id, 0) * 10, 50) if is_client else 0

                            existing_pref = db.session.query(UserPreference).filter(
                                UserPreference.user_id == user.id, 
                                UserPreference.service_category_id == category.id,
                                UserPreference.institution_id == institution.id
                            ).first()
                            if not existing_pref:
                                preference = UserPreference(
                                    id=str(uuid.uuid4()),
                                    user_id=user.id,
                                    service_category_id=category.id,
                                    institution_type_id=institution.institution_type_id,
                                    institution_id=institution.id,
                                    neighborhood=neighborhood,
                                    preference_score=preference_score,
                                    is_client=is_client,
                                    created_at=now,
                                    updated_at=now
                                )
                                db.session.add(preference)
                                # Cachear preferência no Redis (opcional)
                                try:
                                    app.redis_client.setex(
                                        f"user_preference:{user.id}:{institution.id}",
                                        timedelta(days=7),
                                        str(preference_score)
                                    )
                                except Exception as e:
                                    app.logger.warning(f"Erro ao cachear preferência no Redis: {str(e)}")
                    db.session.flush()
                    app.logger.info("Preferências de usuário criadas com sucesso (3 por usuário, com is_client).")

                create_user_preferences()

                # --------------------------------------
                # Criar Tickets
                # --------------------------------------
                def create_tickets():
                    now = datetime.utcnow()
                    for queue in db.session.query(Queue).all():
                        existing_tickets = db.session.query(Ticket).filter(Ticket.queue_id == queue.id).count()
                        if existing_tickets >= 50:
                            app.logger.info(f"Fila {queue.service} já tem {existing_tickets} tickets, pulando.")
                            continue

                        department = db.session.query(Department).filter(Department.id == queue.department_id).first()
                        branch_id = department.branch_id
                        branch_code = branch_id[-4:]

                        for i in range(50 - existing_tickets):
                            max_ticket_number = db.session.query(db.func.max(Ticket.ticket_number)).filter(Ticket.queue_id == queue.id).scalar() or 0
                            ticket_number = max_ticket_number + i + 1
                            qr_code = f"{queue.prefix}{ticket_number:03d}-{queue.id[:8]}-{branch_code}"
                            if db.session.query(Ticket).filter(Ticket.qr_code == qr_code).first():
                                qr_code = f"{queue.prefix}{ticket_number:03d}-{queue.id[:8]}-{branch_code}-{int(now.timestamp())}"

                            status = 'Atendido' if i % 2 == 0 else 'Pendente'
                            issued_at = now - timedelta(days=i % 14, hours=i % 24)
                            ticket = Ticket(
                                id=str(uuid.uuid4()),
                                queue_id=queue.id,
                                user_id=db.session.query(User).filter(User.user_role == UserRole.USER).offset(i % 15).first().id,
                                ticket_number=ticket_number,
                                qr_code=qr_code,
                                priority=1 if i % 5 == 0 else 0,
                                is_physical=False,
                                status=status,
                                issued_at=issued_at,
                                expires_at=issued_at + timedelta(days=1),
                                counter=(i % queue.num_counters) + 1 if status == 'Atendido' else None,
                                service_time=300.0 + (i % 5) * 60 if status == 'Atendido' else 0.0,
                                trade_available=False
                            )
                            db.session.add(ticket)
                            # Cachear ticket no Redis (opcional)
                            try:
                                app.redis_client.setex(
                                    f"ticket:{ticket.id}",
                                    timedelta(days=1),
                                    ticket.qr_code
                                )
                            except Exception as e:
                                app.logger.warning(f"Erro ao cachear ticket no Redis: {str(e)}")
                        queue.active_tickets = db.session.query(Ticket).filter(
                            Ticket.queue_id == queue.id, Ticket.status == 'Pendente'
                        ).count()
                        app.logger.info(f"50 tickets criados para a fila {queue.service}.")
                    db.session.flush()
                    app.logger.info("Tickets criados com sucesso para todas as filas.")

                create_tickets()

                # --------------------------------------
                # Criar Logs de Auditoria
                # --------------------------------------
                def create_audit_logs():
                    now = datetime.utcnow()
                    users = db.session.query(User).limit(20).all()
                    actions = [
                        'USER_LOGIN', 'TICKET_CREATED', 'TICKET_UPDATED', 'QUEUE_MODIFIED',
                        'USER_PROFILE_UPDATED', 'DEPARTMENT_UPDATED'
                    ]
                    existing_logs = db.session.query(AuditLog).count()
                    if existing_logs >= 100:
                        app.logger.info("Logs de auditoria já existem, pulando.")
                        return

                    for i in range(100 - existing_logs):
                        user = users[i % len(users)]
                        action = actions[i % len(actions)]
                        log = AuditLog(
                            id=str(uuid.uuid4()),
                            user_id=user.id,
                            action=action,
                            entity_type='USER' if action in ['USER_LOGIN', 'USER_PROFILE_UPDATED'] else 'TICKET' if action in ['TICKET_CREATED', 'TICKET_UPDATED'] else 'QUEUE' if action == 'QUEUE_MODIFIED' else 'DEPARTMENT',
                            entity_id=str(uuid.uuid4()),
                            description=f"{action} realizado por {user.email}",
                            created_at=now - timedelta(days=i % 30, hours=i % 24)
                        )
                        db.session.add(log)
                    db.session.flush()
                    app.logger.info("Logs de auditoria criados com sucesso.")

                create_audit_logs()

                # --------------------------------------
                # Commit Final
                # --------------------------------------
                db.session.commit()
                app.logger.info("População de dados iniciais concluída com sucesso.")

        except SQLAlchemyError as e:
            db.session.rollback()
            app.logger.error(f"Erro ao popular dados iniciais: {str(e)}")
            raise
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Erro inesperado ao popular dados: {str(e)}")
            raise
import os
from datetime import timedelta

class Config:
    # Configuração base
    DEBUG = False
    TESTING = False
    
    # Configuração do banco de dados
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Se estiver no Render.com, use o DATABASE_URL fornecido
    if 'RENDER' in os.environ:
        SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', '').replace(
            'postgres://', 'postgresql://')
    else:
        SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///queue.db')
    
    # Configuração JWT
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', '00974655')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)  # Token válido por 1 hora
    
    # Configuração CORS
    CORS_HEADERS = 'Content-Type'

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    # Configurações específicas para produção
    pass

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

# Configuração baseada no ambiente
config_by_name = {
    'dev': DevelopmentConfig,
    'prod': ProductionConfig,
    'test': TestingConfig
}

def get_config():
    env = os.environ.get('FLASK_ENV', 'dev')
    return config_by_name[env]
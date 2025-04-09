# app/config.py
import os
from datetime import timedelta

class Config:
    # Configuração base
    DEBUG = False
    TESTING = False
    
    # Configuração do banco de dados
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///queue.db').replace('postgres://', 'postgresql://')
    
    # Configuração JWT
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', '974655')  # Pega do .env ou usa valor padrão
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)  # Token válido por 1 hora
    
    # Configuração CORS
    CORS_HEADERS = 'Content-Type'

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///queue.db').replace('postgres://', 'postgresql://')

class ProductionConfig(Config):
    # Configurações específicas para produção
    SQLALCHEMY_ECHO = False  # Desativa logs SQL em produção

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
    env = os.getenv('FLASK_ENV', 'dev')
    return config_by_name[env]
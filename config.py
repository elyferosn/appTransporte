"""Centraliza configurações da aplicação e do banco de dados."""

import os
import secrets
from urllib.parse import quote_plus
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name('.env'), override=False)



def _database_url():
    url = os.environ.get('DATABASE_URL')
    if url:
        return url

    user = os.environ.get('POSTGRES_USER')
    password = os.environ.get('POSTGRES_PASSWORD')
    database = os.environ.get('POSTGRES_DB')
    if user and password and database:
        host_port = os.environ.get('POSTGRES_PORT', '5432')
        return (
            f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}"
            f"@127.0.0.1:{host_port}/{quote_plus(database)}"
        )
    return 'postgresql+psycopg://localhost/app_transporte'

class Config:
    """Opções padrão para acesso ao banco, sessão e ambiente Flask."""

    # Exemplo: postgresql+psycopg://usuario:senha@localhost:5432/app_transporte
    SQLALCHEMY_DATABASE_URI = _database_url()
    if SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            'postgres://', 'postgresql+psycopg://', 1
        )
    elif SQLALCHEMY_DATABASE_URI.startswith('postgresql://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            'postgresql://', 'postgresql+psycopg://', 1
        )
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True, 'hide_parameters': True}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Defina SECRET_KEY no ambiente de produção. O valor aleatório de reserva
    # protege o desenvolvimento local e muda quando o processo é reiniciado.
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

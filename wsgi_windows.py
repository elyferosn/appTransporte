"""Waitress para Windows: HTTP de teste ou HTTPS por proxy local."""
import logging
import argparse
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import time

from dotenv import load_dotenv

PROJECT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', default=str(PROJECT / '.env'))
    args = parser.parse_args()
    load_dotenv(Path(args.env_file).resolve(), override=True)
    mode = os.environ.get('APP_NETWORK_MODE', 'local')
    if mode not in {'local', 'http-test', 'https'}:
        raise ValueError('APP_NETWORK_MODE invalido')
    if not os.environ.get('SECRET_KEY'):
        raise ValueError('SECRET_KEY persistente obrigatoria')
    from sqlalchemy.engine import make_url
    url = make_url(os.environ.get('DATABASE_URL', ''))
    if url.drivername != 'postgresql+psycopg' or url.host != '127.0.0.1':
        raise ValueError('O banco deve ser PostgreSQL via 127.0.0.1')
    logs = PROJECT / 'logs'
    logs.mkdir(exist_ok=True)
    handler = RotatingFileHandler(logs / 'aplicativo.log', maxBytes=2_000_000,
                                  backupCount=5, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    from app import app
    from models import db
    from run import inicializar_banco
    from sqlalchemy import text
    from waitress import serve
    app.config.update(DEBUG=False, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=mode == 'https')
    allowed_hosts = [s.strip() for s in os.environ.get('APP_ALLOWED_HOSTS', '').split(',') if s.strip()]
    if mode != 'local' and not allowed_hosts:
        raise ValueError('Defina APP_ALLOWED_HOSTS com os nomes/IPs autorizados')
    if allowed_hosts:
        app.config['TRUSTED_HOSTS'] = allowed_hosts
    deadline = time.monotonic() + 120
    while True:
        try:
            with app.app_context():
                db.session.execute(text('SELECT 1'))
                db.session.remove()
            break
        except Exception:
            with app.app_context():
                db.session.remove()
            if time.monotonic() >= deadline:
                logging.error('PostgreSQL indisponivel apos 120 segundos')
                raise SystemExit(1)
            time.sleep(2)
    # Inicializacao unica antes das threads, sem corrida na primeira requisicao.
    inicializar_banco()
    app.extensions['esquema_inicializado'] = True
    options = dict(host='0.0.0.0' if mode == 'http-test' else '127.0.0.1',
                   port=int(os.environ.get('APP_PORT', '5300')), threads=4,
                   clear_untrusted_proxy_headers=True)
    if mode == 'https':
        options.update(trusted_proxy='127.0.0.1', trusted_proxy_count=1,
                       trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-host',
                                              'x-forwarded-proto', 'x-forwarded-port'})
    logging.info('Waitress iniciado: modo=%s porta=%s', mode, options['port'])
    serve(app, **options)


if __name__ == '__main__':
    main()

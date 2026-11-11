"""Restauro em banco NOVO. Nunca limpa ou substitui bancos/configuracoes existentes."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

from dotenv import set_key, dotenv_values
import psycopg
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from banco import inventory, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--postgres-bin', required=True)
    parser.add_argument('--backup', required=True, help='Diretorio contendo dump e manifesto')
    parser.add_argument('--porta', type=int, required=True)
    parser.add_argument('--banco', required=True, help='Nome novo/exclusivo; recusa se existir')
    parser.add_argument('--papel', default='app_transporte_runtime')
    parser.add_argument('--config-saida', required=True, help='Arquivo de segredos NOVO, fora do pacote')
    parser.add_argument('--config-papel-existente', help='Configuracao anterior no destino, para reutilizar o segredo do mesmo papel')
    args = parser.parse_args()
    for name in [args.banco, args.papel]:
        if not re.fullmatch('[a-z][a-z0-9_]{2,62}', name):
            raise RuntimeError('Nome de banco/papel invalido')
    folder = Path(args.backup).resolve()
    config = Path(args.config_saida).resolve()
    if config.exists():
        raise RuntimeError('Arquivo de configuracao ja existe; preservado')
    manifest = json.loads((folder / 'manifesto.json').read_text(encoding='utf-8'))
    dump = folder / 'app_transporte.dump'
    if sha256(dump) != manifest['dump_sha256']:
        raise RuntimeError('Hash do backup divergiu')
    admin_user = input('Usuario administrativo PostgreSQL do DESTINO: ').strip()
    admin_password = getpass.getpass('Senha administrativa do DESTINO: ')
    kwargs = dict(host='127.0.0.1', port=args.porta, user=admin_user,
                  password=admin_password, connect_timeout=10)
    report = {'success': False, 'database': args.banco, 'port': args.porta,
              'other_databases_modified': False, 'activated': False}
    with psycopg.connect(dbname='postgres', autocommit=True, **kwargs) as admin:
        version = int(admin.execute("SELECT current_setting('server_version_num')").fetchone()[0])
        if version // 10000 != manifest['server_version_num'] // 10000:
            raise RuntimeError('Use a mesma versao principal do PostgreSQL do backup')
        if admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', (args.banco,)).fetchone():
            raise RuntimeError('Banco ja existe: preservado; escolha um nome exclusivo')
        existing_role = admin.execute('SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s', (args.papel,)).fetchone()
        if existing_role:
            if not existing_role[0] or any(existing_role[1:]):
                raise RuntimeError('Papel existente tem atributos incompativeis; preservado')
            memberships = admin.execute('SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=%s',(args.papel,)).fetchone()[0]
            if memberships:
                raise RuntimeError('Papel existente possui grupos; revisar privilegios antes de reutilizar')
            if args.config_papel_existente:
                prior = make_url(dotenv_values(args.config_papel_existente)['DATABASE_URL'])
                if (prior.username,prior.host,prior.port)!=(args.papel,'127.0.0.1',args.porta):
                    raise RuntimeError('Configuracao anterior nao corresponde ao papel/servidor')
                runtime_password = prior.password
            else:
                runtime_password = getpass.getpass('Senha existente do papel dedicado (nao sera alterada): ')
        else:
            runtime_password = secrets.token_urlsafe(40)
            # Persiste o segredo gerado antes da criacao do papel, para permitir recuperacao se houver falha.
        config.parent.mkdir(parents=True, exist_ok=True)
        config.touch(exist_ok=False)
        secured = subprocess.run(['icacls',str(config),'/inheritance:r','/grant:r',
                                  '*S-1-5-18:F','*S-1-5-32-544:F','*S-1-5-19:R'],capture_output=True)
        if secured.returncode:
            raise RuntimeError('Nao foi possivel proteger o arquivo de credenciais; nenhum segredo escrito')
        runtime_url = URL.create('postgresql+psycopg', username=args.papel,
                                 password=runtime_password, host='127.0.0.1',
                                 port=args.porta, database=args.banco)
        for key, value in {'DATABASE_URL':runtime_url.render_as_string(hide_password=False),
                           'SECRET_KEY':secrets.token_hex(32), 'APP_NETWORK_MODE':'local',
                           'APP_ALLOWED_HOSTS':'localhost,127.0.0.1', 'APP_PORT':'5300'}.items():
            set_key(str(config), key, value)
        if not existing_role:
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS').format(sql.Identifier(args.papel), sql.Literal(runtime_password)))
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(args.banco)))
    environment = os.environ.copy()
    environment['PGPASSWORD'] = admin_password
    environment['PGCONNECT_TIMEOUT'] = '10'
    restored = subprocess.run([str(Path(args.postgres_bin) / 'pg_restore.exe'),
                               '-h','127.0.0.1','-p',str(args.porta),'-U',admin_user,
                               '-d',args.banco,'--no-owner','--no-acl','--exit-on-error',
                               '--single-transaction',str(dump)], env=environment,
                              capture_output=True)
    if restored.returncode:
        raise RuntimeError('Restauro falhou; banco isolado preservado para diagnostico, sem ativacao')
    admin_url = runtime_url.set(username=admin_user,password=admin_password)
    engine = create_engine(admin_url, hide_parameters=True)
    with engine.connect() as connection:
        if inventory(connection) != manifest['tables']:
            raise RuntimeError('Contagens/valores/esquema divergem do backup; nao ativar')
    with psycopg.connect(dbname=args.banco, **kwargs) as admin:
        if admin.execute('SELECT count(*) FROM pg_constraint WHERE contype IN (\'f\',\'c\') AND NOT convalidated').fetchone()[0]:
            raise RuntimeError('Restricoes nao validadas no destino')
        admin.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(args.banco), sql.Identifier(args.papel)))
        admin.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(args.papel)))
        admin.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}').format(sql.Identifier(args.papel)))
        admin.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(args.papel)))
        admin.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO {}').format(sql.Identifier(args.papel)))
        admin.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO {}').format(sql.Identifier(args.papel)))
        checked = 0
        for name in manifest['tables']:
            if 'id' not in [c[0] for c in manifest['tables'][name]['columns']]:
                continue
            seq = admin.execute("SELECT pg_get_serial_sequence(%s,'id')", ('public.'+name,)).fetchone()[0]
            if seq:
                schema, seqname = seq.split('.',1)
                value, called = admin.execute(sql.SQL('SELECT last_value,is_called FROM {}.{}').format(sql.Identifier(schema),sql.Identifier(seqname))).fetchone()
                maximum = admin.execute(sql.SQL('SELECT max(id) FROM public.{}').format(sql.Identifier(name))).fetchone()[0]
                if maximum is not None and (value+1 if called else value) <= maximum:
                    admin.execute('SELECT setval(CAST(%s AS regclass),%s,true)', (seq,maximum))
                checked += 1
    runtime = create_engine(runtime_url, hide_parameters=True)
    with runtime.connect() as connection:
        if inventory(connection) != manifest['tables']:
            raise RuntimeError('Conta dedicada nao validou integralmente o destino')
    report.update(success=True, all_values_match=True, sequences_checked=checked,
                  dedicated_role=args.papel, credentials_in_report=False,
                  configuration=str(config), backup_sha256=manifest['dump_sha256'])
    report_path = config.parent / (args.banco + '_restauro.json')
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    engine.dispose()
    runtime.dispose()
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('RESTAURO_NAO_ATIVADO:',type(error).__name__,file=sys.stderr)
        if type(error) is RuntimeError:
            print(str(error),file=sys.stderr)
        raise SystemExit(1)

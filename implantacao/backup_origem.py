"""pg_dump e manifesto usam o MESMO snapshot, inclusive com gravacoes concorrentes."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from banco import inventory, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--postgres-bin', required=True)
    parser.add_argument('--saida', required=True)
    parser.add_argument('--final-com-gravacoes-pausadas', action='store_true',
                        help='Registra confirmacao do operador; nao pausa processos automaticamente')
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    url = make_url(dotenv_values(project / '.env')['DATABASE_URL'])
    if url.host != '127.0.0.1' or url.drivername != 'postgresql+psycopg':
        raise RuntimeError('Destino efetivo nao e o PostgreSQL local esperado')
    folder = Path(args.saida).resolve()
    if folder == project or project in folder.parents:
        raise RuntimeError('Backup deve ficar fora do pacote/repositorio de codigo')
    folder.mkdir(parents=True, exist_ok=False)
    dump_file = folder / 'app_transporte.dump'
    engine = create_engine(url, hide_parameters=True)
    environment = os.environ.copy()
    environment['PGPASSWORD'] = url.password or ''
    environment['PGCONNECT_TIMEOUT'] = '10'
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as connection:
        with connection.begin():
            connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            identity = connection.execute(text('SELECT host(inet_server_addr()),inet_server_port(),current_database(),current_user')).one()
            snapshot = connection.execute(text('SELECT pg_export_snapshot()')).scalar_one()
            server = connection.execute(text("SELECT current_setting('server_version_num')")).scalar_one()
            command = [str(Path(args.postgres_bin) / 'pg_dump.exe'), '-h', url.host,
                       '-p', str(url.port or 5432), '-U', url.username, '-d', url.database,
                       '-Fc', '--no-owner', '--no-acl', '--snapshot=' + snapshot,
                       '-f', str(dump_file)]
            process = subprocess.run(command, env=environment, capture_output=True)
            if process.returncode:
                raise RuntimeError('pg_dump falhou; backup nao aprovado')
            tables = inventory(connection)
    engine.dispose()
    listing = subprocess.run([str(Path(args.postgres_bin) / 'pg_restore.exe'), '--list', str(dump_file)], capture_output=True)
    if listing.returncode or not dump_file.stat().st_size:
        raise RuntimeError('Arquivo de backup nao reconhecido pelo pg_restore')
    manifest = {'created_local': datetime.now(ZoneInfo('America/Sao_Paulo')).isoformat(),
                'connection': list(identity), 'server_version_num': int(server),
                'dump_sha256': sha256(dump_file), 'same_snapshot': True, 'tables': tables,
                'runtime_files': 'Nenhum anexo/upload identificado. Dados ativos no PostgreSQL; municipios_ibge.json e assets seguem no codigo.',
                'credentials_included': False,
                'purpose': 'corte_final' if args.final_com_gravacoes_pausadas else 'preparacao',
                'operator_confirms_writes_paused': args.final_com_gravacoes_pausadas}
    (folder / 'manifesto.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'backup': str(dump_file), 'connection': list(identity),
                      'tables': len(tables), 'same_snapshot': True}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('BACKUP_FALHOU:', type(error).__name__, file=sys.stderr)
        raise SystemExit(1)

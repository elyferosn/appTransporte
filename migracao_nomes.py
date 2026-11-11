"""Migracao aditiva/idempotente dos nomes opcionais, sem regravar cadastros."""
from pathlib import Path
import argparse
import getpass
import json

from dotenv import dotenv_values
from sqlalchemy import String, create_engine, inspect
from sqlalchemy.engine import make_url


def migrar_nomes_cidadaos(engine):
    adicionadas = []
    with engine.begin() as conexao:
        if conexao.dialect.name == 'postgresql':
            conexao.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        inspetor = inspect(conexao)
        colunas = {c['name']: c for c in inspetor.get_columns('cidadaos')}
        for campo in ('nome_social', 'apelido'):
            if campo in colunas:
                tipo = colunas[campo]['type']
                if not isinstance(tipo, String) or (tipo.length is not None and tipo.length < 200):
                    raise RuntimeError(f'Coluna {campo} existente requer revisao do tipo/tamanho; preservada')
            else:
                conexao.exec_driver_sql(f'ALTER TABLE "cidadaos" ADD COLUMN "{campo}" VARCHAR(200)')
                adicionadas.append(campo)
    return adicionadas


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', default=str(Path(__file__).with_name('.env')))
    parser.add_argument('--aplicar', action='store_true')
    parser.add_argument('--relatorio', default=str(Path(__file__).resolve().parent.parent / 'resultado_migracao_nomes.json'))
    args = parser.parse_args()
    url = make_url(dotenv_values(args.env_file)['DATABASE_URL'])
    if url.drivername != 'postgresql+psycopg' or url.host != '127.0.0.1':
        raise RuntimeError('Confirme uma conexao PostgreSQL local por 127.0.0.1')
    if args.aplicar:
        print('Destino:',url.host,url.port or 5432,url.database)
        admin = input('Usuario PostgreSQL proprietario/administrador para a migracao: ').strip()
        password = getpass.getpass('Senha PostgreSQL (nao sera salva): ')
        url = url.set(username=admin,password=password)
    engine = create_engine(url, hide_parameters=True)
    if args.aplicar:
        with engine.connect() as conexao:
            quantidade_antes = conexao.exec_driver_sql('SELECT count(*) FROM cidadaos').scalar_one()
        result = {'adicionadas':migrar_nomes_cidadaos(engine), 'aplicada':True,
                  'host':url.host, 'porta':url.port or 5432, 'banco':url.database,
                  'cadastros_antes':quantidade_antes}
        with engine.connect() as conexao:
            result['cadastros_depois'] = conexao.exec_driver_sql('SELECT count(*) FROM cidadaos').scalar_one()
        Path(args.relatorio).write_bytes(json.dumps(result,ensure_ascii=False,indent=2).encode('utf-8'))
    else:
        with engine.connect() as conexao:
            conexao.exec_driver_sql('SET TRANSACTION READ ONLY')
            existentes = {c['name'] for c in inspect(conexao).get_columns('cidadaos')}
            result = {'faltantes':sorted({'nome_social','apelido'}-existentes),'alteracoes_executadas':False}
    engine.dispose()
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Migracao nao concluida:',type(error).__name__)
        if type(error) is RuntimeError:print(str(error))
        raise SystemExit(1)

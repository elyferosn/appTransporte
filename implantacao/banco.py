"""Conferencia integral sem registrar linhas ou credenciais."""
from datetime import date, datetime
import hashlib
import json
from sqlalchemy import MetaData, inspect, select


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(connection):
    names = inspect(connection).get_schema_names()
    extra = set(names) - {'public', 'information_schema', 'pg_catalog'}
    if any(not n.startswith('pg_') for n in extra):
        raise RuntimeError('Esquemas adicionais exigem revisao antes do backup/restauro')
    metadata = MetaData()
    metadata.reflect(bind=connection, schema='public')
    result = {}
    for table in metadata.sorted_tables:
        if not list(table.primary_key.columns):
            raise RuntimeError('Tabela sem chave primaria exige criterio de comparacao')
        digest = hashlib.sha256()
        count = 0
        for row in connection.execute(select(table).order_by(*table.primary_key.columns)):
            values = [v.isoformat() if isinstance(v, (date, datetime)) else v for v in row]
            digest.update(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
            digest.update(b'\n')
            count += 1
        result[table.name] = {'count': count, 'sha256': digest.hexdigest(),
                              'columns': [[c.name, str(c.type)] for c in table.columns]}
    return result

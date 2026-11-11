"""Cria tabelas e adapta o esquema para instalações já existentes."""

from datetime import datetime
import json
from pathlib import Path
import unicodedata

from sqlalchemy import inspect, text
from sqlalchemy.exc import ProgrammingError

from models import Agenda, Agendamento, Chamado, Cidade, LocalDestino, db
from migracao_nomes import migrar_nomes_cidadaos


def normalizar_nome_cidade(nome):
    """Gera uma chave de busca sem acentos e sem diferença entre maiúsculas."""
    texto = unicodedata.normalize("NFKD", nome or "")
    return "".join(caractere for caractere in texto if not unicodedata.combining(caractere)).casefold()


def migrar_tabela_cidades():
    """Adiciona UF/código IBGE e permite nomes repetidos em UFs diferentes."""
    inspetor = inspect(db.engine)
    colunas = {coluna["name"] for coluna in inspetor.get_columns("cidades")}
    unicos_nome = any(
        set(item.get("column_names") or []) == {"nome"}
        for item in inspetor.get_unique_constraints("cidades")
    ) or any(
        item.get("unique") and item.get("column_names") == ["nome"]
        for item in inspetor.get_indexes("cidades")
    )
    if db.engine.dialect.name == "postgresql":
        unicos_codigo = any(
            set(item.get("column_names") or []) == {"codigo_ibge"}
            for item in inspetor.get_unique_constraints("cidades")
        ) or any(
            item.get("unique") and item.get("column_names") == ["codigo_ibge"]
            for item in inspetor.get_indexes("cidades")
        )
        tipos = {
            "nome_busca": "VARCHAR(150)",
            "uf": "VARCHAR(2)",
            "codigo_ibge": "INTEGER",
        }
        with db.engine.begin() as conexao:
            for coluna, tipo in tipos.items():
                if coluna not in colunas:
                    conexao.exec_driver_sql(
                        f'ALTER TABLE "cidades" ADD COLUMN "{coluna}" {tipo}'
                    )
            if unicos_nome:
                restricoes = [
                    item["name"] for item in inspetor.get_unique_constraints("cidades")
                    if set(item.get("column_names") or []) == {"nome"}
                ]
                for restricao in restricoes:
                    conexao.exec_driver_sql(
                        f'ALTER TABLE "cidades" DROP CONSTRAINT "{restricao}"'
                    )
                for indice in inspetor.get_indexes("cidades"):
                    if indice.get("unique") and indice.get("column_names") == ["nome"]:
                        conexao.exec_driver_sql(f'DROP INDEX "{indice["name"]}"')
            if not unicos_codigo:
                conexao.exec_driver_sql(
                    'ALTER TABLE "cidades" ADD CONSTRAINT '
                    '"uq_cidades_codigo_ibge" UNIQUE ("codigo_ibge")'
                )
        return
    if {"uf", "codigo_ibge", "nome_busca"}.issubset(colunas) and not unicos_nome:
        return

    conexao = db.engine.raw_connection()
    try:
        cursor = conexao.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        colunas_atuais = {linha[1] for linha in cursor.execute('PRAGMA table_info("cidades")')}
        cursor.execute("BEGIN")
        cursor.execute('DROP TABLE IF EXISTS "cidades_nova"')
        cursor.execute(
            'CREATE TABLE "cidades_nova" ('
            'id INTEGER PRIMARY KEY, nome VARCHAR(150) NOT NULL, nome_busca VARCHAR(150), uf VARCHAR(2), '
            'codigo_ibge INTEGER UNIQUE, ativo INTEGER NOT NULL DEFAULT 1)'
        )
        dados = cursor.execute('SELECT * FROM "cidades" ORDER BY id').fetchall()
        nomes_colunas = [linha[1] for linha in cursor.execute('PRAGMA table_info("cidades")')]
        posicoes = {nome: indice for indice, nome in enumerate(nomes_colunas)}
        for linha in dados:
            cursor.execute(
                'INSERT INTO "cidades_nova" (id, nome, nome_busca, uf, codigo_ibge, ativo) VALUES (?, ?, ?, ?, ?, ?)',
                (linha[posicoes["id"]], linha[posicoes["nome"]],
                 normalizar_nome_cidade(linha[posicoes["nome"]]),
                 linha[posicoes["uf"]] if "uf" in colunas_atuais else None,
                 linha[posicoes["codigo_ibge"]] if "codigo_ibge" in colunas_atuais else None,
                 linha[posicoes["ativo"]] if "ativo" in colunas_atuais else 1),
            )
        cursor.execute('DROP TABLE "cidades"')
        cursor.execute('ALTER TABLE "cidades_nova" RENAME TO "cidades"')
        cursor.execute('CREATE INDEX IF NOT EXISTS "ix_cidades_nome" ON "cidades" (nome)')
        cursor.execute('CREATE INDEX IF NOT EXISTS "ix_cidades_nome_busca" ON "cidades" (nome_busca)')
        cursor.execute('CREATE INDEX IF NOT EXISTS "ix_cidades_uf" ON "cidades" (uf)')
        conexao.commit()
        cursor.execute("PRAGMA foreign_keys=ON")
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()


def preencher_municipios_ibge():
    """Carrega a lista oficial IBGE empacotada, sem depender de internet."""
    arquivo = Path(__file__).parent / "data" / "municipios_ibge.json"
    municipios = json.loads(arquivo.read_text(encoding="utf-8"))
    if (Cidade.query.filter(Cidade.codigo_ibge.isnot(None)).count() == len(municipios)
            and Cidade.query.filter(Cidade.nome_busca.is_(None)).count() == 0):
        return
    existentes = Cidade.query.all()
    por_codigo = {cidade.codigo_ibge: cidade for cidade in existentes if cidade.codigo_ibge}
    por_nome_uf = {(cidade.nome.casefold(), (cidade.uf or "").upper()): cidade for cidade in existentes}
    alterado = False
    for cidade in existentes:
        nome_busca = normalizar_nome_cidade(cidade.nome)
        if cidade.nome_busca != nome_busca:
            cidade.nome_busca = nome_busca
            alterado = True
    for municipio in municipios:
        codigo = municipio["codigo_ibge"]
        nome = municipio["nome"]
        uf = municipio["uf"]
        cidade = (por_codigo.get(codigo) or por_nome_uf.get((nome.casefold(), uf))
                  or por_nome_uf.get((nome.casefold(), "")))
        if cidade is None:
            cidade = Cidade(nome=nome, nome_busca=normalizar_nome_cidade(nome), uf=uf,
                            codigo_ibge=codigo, ativo=1)
            db.session.add(cidade)
            por_codigo[codigo] = cidade
            por_nome_uf[(nome.casefold(), uf)] = cidade
            alterado = True
        else:
            nome_busca = normalizar_nome_cidade(nome)
            if (cidade.nome != nome or cidade.nome_busca != nome_busca or cidade.uf != uf
                    or cidade.codigo_ibge != codigo or cidade.ativo != 1):
                cidade.nome, cidade.uf, cidade.codigo_ibge = nome, uf, codigo
                cidade.nome_busca = nome_busca
                cidade.ativo = 1
                alterado = True
    if alterado:
        db.session.commit()


def migrar_chamados_para_locais():
    """Converte chamados antigos para os vínculos com LocalDestino."""
    with db.engine.connect() as conexao:
        colunas = {coluna["name"] for coluna in inspect(conexao).get_columns("chamados")}
        if "destino_local" not in colunas:
            return
        antigos = [dict(linha._mapping) for linha in conexao.exec_driver_sql(
            "SELECT * FROM chamados ORDER BY id"
        )]

    def localizar_ou_criar(nome, cidade, cep, bairro, rua, numero, referencia, fallback):
        nome = (nome or fallback).strip().upper()
        dados_local = {
            "cidade": (cidade or "").strip().upper() or None,
            "cep": "".join(c for c in (cep or "") if c.isdigit()) or None,
            "bairro": (bairro or "").strip().upper() or None,
            "rua": (rua or "").strip().upper() or None,
            "numero": (numero or "").strip().upper() or None,
            "referencia": (referencia or "").strip().upper() or None,
        }
        existentes = LocalDestino.query.filter(
            db.func.lower(LocalDestino.nome) == nome.lower()
        ).all()
        for existente in existentes:
            if all(getattr(existente, campo) == valor for campo, valor in dados_local.items()):
                return existente
        local = LocalDestino(
            nome=nome, **dados_local,
            ativo=1,
        )
        db.session.add(local)
        db.session.flush()
        return local

    chamados_novos = []
    for antigo in antigos:
        cidade_saida = db.session.get(Cidade, antigo.get("saida_cidade_id"))
        local_destino = localizar_ou_criar(
            antigo.get("destino_local"), antigo.get("destino_cidade"),
            antigo.get("destino_cep"), antigo.get("destino_bairro"),
            antigo.get("destino_logradouro"), antigo.get("destino_numero"),
            antigo.get("destino_referencia"), f"DESTINO {antigo['id']}",
        )
        local_saida = localizar_ou_criar(
            antigo.get("saida_nome_local"), cidade_saida.nome if cidade_saida else "",
            antigo.get("saida_cep"), antigo.get("saida_bairro"),
            antigo.get("saida_logradouro"), antigo.get("saida_numero"),
            antigo.get("saida_referencia"), f"SAÍDA {antigo['id']}",
        )
        criado_em = antigo.get("criado_em")
        if isinstance(criado_em, str):
            criado_em = datetime.fromisoformat(criado_em)
        chamados_novos.append(Chamado(
            id=antigo["id"], cidadao_id=antigo["cidadao_id"],
            local_destino_id=local_destino.id, local_saida_id=local_saida.id,
            criado_em=criado_em or datetime.utcnow(),
        ))
    db.session.commit()

    with db.engine.begin() as conexao:
        conexao.exec_driver_sql('DROP TABLE "chamados"')
        Chamado.__table__.create(bind=conexao)
    for chamado in chamados_novos:
        db.session.add(chamado)
    if chamados_novos:
        db.session.commit()


def tornar_cidadao_opcional_no_chamado():
    """Reconstrói chamados antigos para permitir registros sem cidadão vinculado."""
    with db.engine.connect() as conexao:
        colunas_info = inspect(conexao).get_columns("chamados")
        colunas = {coluna["name"] for coluna in colunas_info}
        cidadao = next((coluna for coluna in colunas_info if coluna["name"] == "cidadao_id"), None)
        if not cidadao or cidadao.get("nullable", True):
            return
        registros = [dict(linha._mapping) for linha in conexao.exec_driver_sql(
            "SELECT * FROM chamados ORDER BY id"
        )]
    with db.engine.begin() as conexao:
        conexao.exec_driver_sql('ALTER TABLE "chamados" RENAME TO "chamados_com_cidadao_obrigatorio"')
        Chamado.__table__.create(bind=conexao)
        colunas_modelo = {coluna.name for coluna in Chamado.__table__.columns}
        for registro in registros:
            valores = {chave: valor for chave, valor in registro.items()
                       if chave in colunas and chave in colunas_modelo}
            if isinstance(valores.get("criado_em"), str):
                valores["criado_em"] = datetime.fromisoformat(valores["criado_em"])
            conexao.execute(Chamado.__table__.insert().values(**valores))
        conexao.exec_driver_sql('DROP TABLE "chamados_com_cidadao_obrigatorio"')


def migrar_enderecos_para_locais():
    """Importa os registros antigos para Locais e remove a tabela desativada."""
    inspetor = inspect(db.engine)
    if not inspetor.has_table("enderecos"):
        return
    colunas = {coluna["name"] for coluna in inspetor.get_columns("enderecos")}
    obrigatorias = {"id", "nome_local", "cidade_id", "cep", "bairro", "logradouro", "numero", "referencia", "ativo"}
    if not obrigatorias.issubset(colunas):
        return
    with db.engine.begin() as conexao:
        conexao.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS migracoes_esquema (chave VARCHAR(100) PRIMARY KEY)"
        )
    chave = "enderecos_para_locais_destino_v1"
    migracao_feita = db.session.execute(
        text("SELECT chave FROM migracoes_esquema WHERE chave = :chave"), {"chave": chave}
    ).first()
    if not migracao_feita:
        with db.engine.connect() as conexao:
            antigos = [dict(linha._mapping) for linha in conexao.exec_driver_sql(
                "SELECT e.*, c.nome AS nome_cidade FROM enderecos e "
                "LEFT JOIN cidades c ON c.id = e.cidade_id ORDER BY e.id"
            )]
        for endereco in antigos:
            valores = {
                "nome": endereco.get("nome_local") or "Residência",
                "cidade": endereco.get("nome_cidade") or "",
                "cep": endereco.get("cep"),
                "bairro": endereco.get("bairro"),
                "rua": endereco.get("logradouro"),
                "numero": endereco.get("numero"),
                "referencia": endereco.get("referencia"),
                "ativo": endereco.get("ativo", 1),
            }
            if not LocalDestino.query.filter_by(**valores).first():
                db.session.add(LocalDestino(**valores))
        db.session.flush()
        db.session.execute(
            text("INSERT INTO migracoes_esquema (chave) VALUES (:chave)"), {"chave": chave}
        )
        db.session.commit()
    with db.engine.begin() as conexao:
        conexao.exec_driver_sql('DROP TABLE IF EXISTS "enderecos"')


def migrar_agendamentos_para_locais():
    """Vincula os endereços antigos de embarque e destino ao cadastro comum."""
    for agendamento in Agendamento.query.order_by(Agendamento.id).all():
        if not agendamento.local_saida_id:
            dados_saida = {
                "nome": f"SAÍDA {agendamento.id}",
                "cidade": agendamento.cidade_embarque or "",
                "cep": "".join(c for c in (agendamento.cep_embarque or "") if c.isdigit()) or None,
                "rua": agendamento.rua_embarque or "",
                "bairro": agendamento.bairro_embarque or "",
                "numero": agendamento.numero_embarque or "",
                "referencia": agendamento.referencia_embarque,
                "ativo": 1,
            }
            local = LocalDestino.query.filter_by(**dados_saida).first()
            if not local:
                local = LocalDestino(**dados_saida)
                db.session.add(local)
                db.session.flush()
            agendamento.local_saida_id = local.id
        if not agendamento.local_destino_id:
            dados_destino = {
                "nome": agendamento.local_destino or f"DESTINO {agendamento.id}",
                "cidade": agendamento.destino_cidade or "",
                "cep": "".join(c for c in (agendamento.destino_cep or "") if c.isdigit()) or None,
                "rua": agendamento.destino_rua or "",
                "bairro": agendamento.destino_bairro or "",
                "numero": agendamento.destino_numero or "",
                "referencia": agendamento.destino_referencia,
                "ativo": 1,
            }
            local = LocalDestino.query.filter_by(**dados_destino).first()
            if not local:
                local = LocalDestino(**dados_destino)
                db.session.add(local)
                db.session.flush()
            agendamento.local_destino_id = local.id
    db.session.commit()


def inicializar_esquema():
    """Cria as tabelas e migra colunas de bancos já utilizados."""
    db.create_all()
    try:
        migrar_nomes_cidadaos(db.engine)
    except ProgrammingError as erro:
        if getattr(erro.orig, 'sqlstate', None) == '42501':
            raise RuntimeError('Execute migracao_nomes.py --aplicar com o proprietario do banco antes de iniciar esta versao.') from None
        raise
    migrar_tabela_cidades()
    campos_novos = {
        "agendas": {
            "data_hora": "DATETIME",
            "motorista_id": "INTEGER",
            "frota_id": "INTEGER",
            "quantidade_vagas": "INTEGER NOT NULL DEFAULT 0",
            "cidade": "VARCHAR(150)",
            "cidade_destino_id": "INTEGER",
            "informacao": "VARCHAR(500)",
        },
        "agendamentos": {
            "agenda_id": "INTEGER",
            "cidadao_id": "INTEGER",
            "local_saida_id": "INTEGER",
            "endereco_embarque": "VARCHAR(500)",
            "cep_embarque": "VARCHAR(9)",
            "cidade_embarque": "VARCHAR(150)",
            "rua_embarque": "VARCHAR(200)",
            "bairro_embarque": "VARCHAR(150)",
            "numero_embarque": "VARCHAR(30)",
            "referencia_embarque": "VARCHAR(200)",
            "telefone_contato": "VARCHAR(30)",
            "observacao": "VARCHAR(500)",
            "local_destino": "VARCHAR(150)",
            "local_destino_id": "INTEGER",
            "destino_cep": "VARCHAR(9)",
            "destino_cidade": "VARCHAR(150)",
            "destino_rua": "VARCHAR(200)",
            "destino_bairro": "VARCHAR(150)",
            "destino_numero": "VARCHAR(30)",
            "destino_referencia": "VARCHAR(200)",
        },
        "chamados": {
            "cidadao_nome": "VARCHAR(200)",
            "usuario_id": "INTEGER",
            "motorista_final": "VARCHAR(200)",
            "motorista_final_id": "INTEGER",
            "data_hora_final": "DATETIME",
        },
        "locais_destino": {
            "cidade_id": "INTEGER",
        },
        "cidadaos": {
            "cns": "VARCHAR(15)",
            "data_nascimento": "DATE",
            "nome_mae": "VARCHAR(200)",
        },
    }
    with db.engine.begin() as conexao:
        for tabela, campos in campos_novos.items():
            existentes = {coluna["name"] for coluna in inspect(conexao).get_columns(tabela)}
            if tabela == "agendas" and "cidade_destino" in existentes and "cidade" not in existentes:
                conexao.exec_driver_sql(
                    'ALTER TABLE "agendas" RENAME COLUMN "cidade_destino" TO "cidade"'
                )
                existentes.remove("cidade_destino")
                existentes.add("cidade")
            for campo, tipo in campos.items():
                if campo not in existentes:
                    conexao.exec_driver_sql(f'ALTER TABLE "{tabela}" ADD COLUMN "{campo}" {tipo}')
        for indice in inspect(conexao).get_indexes("locais_destino"):
            if indice.get("unique") and indice.get("column_names") == ["nome"]:
                conexao.exec_driver_sql(f'DROP INDEX "{indice["name"]}"')
    locais_sem_cidade_id = LocalDestino.query.filter(
        LocalDestino.cidade_id.is_(None), LocalDestino.cidade.isnot(None)
    ).all()
    for local in locais_sem_cidade_id:
        nome_cidade = (local.cidade or "").strip()
        if not nome_cidade:
            continue
        cidade = Cidade.query.filter(db.func.lower(Cidade.nome) == nome_cidade.lower()).first()
        if cidade:
            local.cidade_id = cidade.id
    if locais_sem_cidade_id:
        db.session.commit()
    agendas_antigas = Agenda.query.filter(
        Agenda.cidade_destino_id.is_(None), Agenda.cidade.isnot(None)
    ).all()
    for agenda in agendas_antigas:
        nome = agenda.cidade.strip()
        if not nome:
            continue
        destino = Cidade.query.filter(db.func.lower(Cidade.nome) == nome.lower()).first()
        if not destino:
            destino = Cidade(nome=nome, ativo=1)
            db.session.add(destino)
            db.session.flush()
        agenda.cidade_destino_id = destino.id
    if agendas_antigas:
        db.session.commit()
    migrar_chamados_para_locais()
    tornar_cidadao_opcional_no_chamado()
    migrar_enderecos_para_locais()
    migrar_agendamentos_para_locais()
    preencher_municipios_ibge()
    locais_sem_cidade_id = LocalDestino.query.filter(
        LocalDestino.cidade_id.is_(None), LocalDestino.cidade.isnot(None)
    ).all()
    for local in locais_sem_cidade_id:
        nome_cidade = (local.cidade or "").strip()
        if nome_cidade:
            cidade = Cidade.query.filter(db.func.lower(Cidade.nome) == nome_cidade.lower()).first()
            if cidade:
                local.cidade_id = cidade.id
    if locais_sem_cidade_id:
        db.session.commit()

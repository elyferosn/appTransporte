"""Concentra cadastro, edição, busca e validação dos dados de transporte."""

from datetime import date, datetime, time
import unicodedata
from urllib.parse import urlsplit

from flask import (Blueprint, abort, flash, jsonify, make_response, redirect, render_template,
                   request, session, url_for)
from sqlalchemy import and_, case, or_
from sqlalchemy.exc import IntegrityError

from models import (Agenda, Agendamento, AuditoriaAgenda, AuditoriaAgendamento,
                    AuditoriaCidadao, AuditoriaFrota, AuditoriaMotorista,
                    Chamado, Cidade, Cidadao, Frota, LocalDestino, Motorista,
                    Sessao, db)
from routes.access import (acesso_rota_cadastro, login_obrigatorio,
                           pode_acessar_rota, usuario_atual)

dados_bp = Blueprint("dados", __name__, url_prefix="/dados")
LIMITE_RESULTADOS_BUSCA = 50


def registro_da_ficha(nome_modelo, registro_id):
    """Limita as fichas aos dois cadastros com permissao de consulta existente."""
    modelos = {"chamados": (Chamado, "Chamado"),
               "agendamentos": (Agendamento, "Agendamento")}
    if nome_modelo not in modelos:
        abort(404)
    modelo, titulo = modelos[nome_modelo]
    return db.get_or_404(modelo, registro_id), titulo


def endereco_da_ficha(local, legado=None):
    """Seleciona apenas os campos de endereco; nao mistura dois enderecos."""
    if local is None:
        return legado or {}
    cidade = local.cidade_registro
    return {"nome": local.nome, "rua": local.rua, "numero": local.numero,
            "bairro": local.bairro, "cidade": cidade.nome if cidade else local.cidade,
            "uf": cidade.uf if cidade else None, "cep": local.cep,
            "referencia": local.referencia}


@dados_bp.route("/<nome_modelo>/<int:registro_id>/confirmacao")
@acesso_rota_cadastro
def confirmar_salvo(nome_modelo, registro_id):
    registro, titulo = registro_da_ficha(nome_modelo, registro_id)
    return render_template("registro_salvo.html", nome_modelo=nome_modelo,
                           registro_id=registro.id, titulo=titulo)


@dados_bp.route("/<nome_modelo>/<int:registro_id>/ficha")
@acesso_rota_cadastro
def imprimir_ficha(nome_modelo, registro_id):
    """Ficha com lista explicita de dados de transporte, sem dados clinicos."""
    registro, titulo = registro_da_ficha(nome_modelo, registro_id)
    if nome_modelo == "chamados":
        ficha = {"titulo": titulo, "numero": registro.id,
                 "passageiro": registro.cidadao.nome_exibicao if registro.cidadao else registro.cidadao_nome,
                 "apelido": registro.cidadao.apelido if registro.cidadao else None,
                 "saida": endereco_da_ficha(registro.local_saida),
                 "destino": endereco_da_ficha(registro.local_destino)}
    else:
        saida_legado = {"rua": registro.rua_embarque, "numero": registro.numero_embarque,
                       "bairro": registro.bairro_embarque, "cidade": registro.cidade_embarque,
                       "cep": registro.cep_embarque, "referencia": registro.referencia_embarque}
        if not any(saida_legado.get(campo) for campo in ("rua", "numero", "bairro")):
            saida_legado["endereco_livre"] = registro.endereco_embarque
        destino_legado = {"nome": registro.local_destino, "rua": registro.destino_rua,
                          "numero": registro.destino_numero, "bairro": registro.destino_bairro,
                          "cidade": registro.destino_cidade, "cep": registro.destino_cep,
                          "referencia": registro.destino_referencia}
        ficha = {"titulo": titulo, "numero": registro.id,
                 "passageiro": registro.cidadao.nome_exibicao if registro.cidadao else registro.nome,
                 "apelido": registro.cidadao.apelido if registro.cidadao else None,
                 "telefone": registro.telefone_contato,
                 "saida_em": registro.agenda.data_hora if registro.agenda else None,
                 "cancelado": registro.ativo != 1,
                 "saida": endereco_da_ficha(registro.local_saida_registro, saida_legado),
                 "destino": endereco_da_ficha(registro.local_destino_registro, destino_legado)}
    resposta = make_response(render_template("ficha_motorista.html", ficha=ficha,
                                            nome_modelo=nome_modelo))
    resposta.headers["Cache-Control"] = "no-store, private"
    resposta.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    resposta.headers["Referrer-Policy"] = "no-referrer"
    return resposta


def texto_busca_sem_acento(texto):
    """Normaliza texto digitado para localizar nomes independentemente do acento."""
    normalizado = unicodedata.normalize("NFKD", texto or "")
    return "".join(caractere for caractere in normalizado if not unicodedata.combining(caractere)).casefold()
MODELOS = {"frotas": (Frota, "Frota"), "motoristas": (Motorista, "Motoristas"),
           "cidadaos": (Cidadao, "Cidadão"), "agendas": (Agenda, "Agendas"),
           "agendamentos": (Agendamento, "Agendamentos"),
           "chamados": (Chamado, "Chamados")}

AUDITORIAS = {
    "frotas": (AuditoriaFrota, "frota_id"),
    "motoristas": (AuditoriaMotorista, "motorista_id"),
    "cidadaos": (AuditoriaCidadao, "cidadao_id"),
    "agendas": (AuditoriaAgenda, "agenda_id"),
    "agendamentos": (AuditoriaAgendamento, "agendamento_id"),
}


def registrar_auditoria(nome_modelo, registro, acao):
    """Adiciona o evento de auditoria à mesma transação da alteração."""
    modelo_auditoria, campo_registro = AUDITORIAS[nome_modelo]
    sessao_ativa = Sessao.query.filter_by(
        token=session.get("sessao_token"), ativa=True
    ).first()
    if not sessao_ativa:
        raise ValueError("Não foi possível identificar a sessão do operador.")
    db.session.flush()
    evento = modelo_auditoria(
        **{campo_registro: registro.id},
        usuario_id=sessao_ativa.usuario_id,
        sessao_id=sessao_ativa.id,
        acao=acao,
    )
    db.session.add(evento)


def modelo_por_nome(nome):
    """Localiza o modelo associado ao nome público do cadastro."""
    if nome not in MODELOS:
        abort(404)
    return MODELOS[nome]


def converter(campo, valor):
    """Converte valores de formulário para o tipo definido na coluna."""
    if valor == "":
        return None
    if campo.name in ("cpf", "cns"):
        return "".join(caractere for caractere in valor if caractere.isdigit()) or None
    tipo = campo.type.python_type
    if tipo is date:
        return date.fromisoformat(valor)
    if tipo is int:
        return int(valor)
    if tipo is bool:
        return valor.lower() in ("1", "true", "on", "sim")
    return valor


def converter_cadastro(nome_modelo, campo, valor):
    """Converte os campos dos cadastros e grava textos em maiúsculas."""
    if nome_modelo == "cidadaos" and campo.name in {"nome_social", "apelido"}:
        valor = valor.strip()
        if len(valor) > 200:
            raise ValueError("Nome social e apelido devem ter no máximo 200 caracteres.")
    convertido = converter(campo, valor)
    if nome_modelo in {"frotas", "motoristas", "cidadaos"} and isinstance(convertido, str):
        return convertido.upper()
    return convertido


def validar_cidadao(registro):
    """Exige identificação completa no cadastro individual de cidadão."""
    if not registro.cpf:
        raise ValueError("Informe o CPF do cidadão.")
    if len(registro.cpf) != 11:
        raise ValueError("O CPF deve conter 11 números.")
    if not registro.cns:
        raise ValueError("Informe o Cartão SUS (CNS) do cidadão.")
    if len(registro.cns) != 15:
        raise ValueError("O CNS deve conter 15 números.")
    if not registro.data_nascimento:
        raise ValueError("Informe a data de nascimento do cidadão.")


def filtro_nomes_cidadao(termo):
    padrao = f"%{termo}%"
    return or_(Cidadao.nome.ilike(padrao), Cidadao.nome_social.ilike(padrao),
               Cidadao.apelido.ilike(padrao))


def dados_cidadao(pessoa):
    """Mantem nome completo na API e inclui os campos de apresentacao separados."""
    return {"id": pessoa.id, "nome": pessoa.nome or "",
            "nome_exibicao": pessoa.nome_exibicao, "nome_social": pessoa.nome_social or "",
            "apelido": pessoa.apelido or "", "cpf": pessoa.cpf or "", "cns": pessoa.cns or "",
            "data_nascimento": pessoa.data_nascimento.isoformat() if pessoa.data_nascimento else "",
            "nome_mae": pessoa.nome_mae or ""}


@dados_bp.route("/<nome_modelo>")
@acesso_rota_cadastro
def listar(nome_modelo):
    """Apresenta a tela apropriada para o cadastro solicitado."""
    modelo, titulo = modelo_por_nome(nome_modelo)
    if nome_modelo == "agendas":
        registro_edicao = db.session.get(Agenda, request.args.get("editar", type=int)) if request.args.get("editar") else None
        return render_template("agenda.html", nome_modelo=nome_modelo, titulo=titulo,
                               registros=Agenda.query.order_by(Agenda.data_hora.desc()).limit(LIMITE_RESULTADOS_BUSCA).all(),
                               motoristas=Motorista.query.filter_by(ativo=1).order_by(Motorista.nome).all(),
                               frotas=Frota.query.filter_by(ativo=1).order_by(Frota.frota).all(),
                               cidades_disponiveis=Cidade.query.filter_by(ativo=1).count(),
                               local_saida_inicial=db.session.get(LocalDestino, registro_edicao.local_saida_id if registro_edicao else request.args.get("local_saida_id", type=int)) if (registro_edicao and registro_edicao.local_saida_id) or request.args.get("local_saida_id", type=int) else None,
                               local_destino_inicial=db.session.get(LocalDestino, registro_edicao.local_destino_id if registro_edicao else request.args.get("local_destino_id", type=int)) if (registro_edicao and registro_edicao.local_destino_id) or request.args.get("local_destino_id", type=int) else None,
                               registro_edicao=registro_edicao)
    if nome_modelo == "agendamentos":
        registro_edicao = db.session.get(Agendamento, request.args.get("editar", type=int)) if request.args.get("editar") else None
        if not registro_edicao and request.args.get("novo") != "1":
            consulta = Agendamento.query
            termo = request.args.get("q", "").strip()
            desde = request.args.get("desde", "").strip()
            ate = request.args.get("ate", "").strip()
            situacao = request.args.get("situacao", "").strip()
            if termo:
                padrao = f"%{termo}%"
                consulta = consulta.filter(or_(
                    Agendamento.nome.ilike(padrao),
                    Agendamento.cidadao.has(filtro_nomes_cidadao(termo)),
                    Agendamento.agenda.has(Agenda.cidade.ilike(padrao)),
                    Agendamento.local_destino_registro.has(or_(LocalDestino.nome.ilike(padrao), LocalDestino.cidade.ilike(padrao))),
                    Agendamento.local_saida_registro.has(or_(LocalDestino.nome.ilike(padrao), LocalDestino.cidade.ilike(padrao))),
                ))
            if situacao in {"ativo", "cancelado"}:
                consulta = consulta.filter(Agendamento.ativo == (1 if situacao == "ativo" else 0))
            if desde:
                try:
                    consulta = consulta.join(Agenda).filter(db.func.date(Agenda.data_hora) >= date.fromisoformat(desde).isoformat())
                except ValueError:
                    desde = ""
            if ate:
                try:
                    if not desde:
                        consulta = consulta.join(Agenda)
                    consulta = consulta.filter(db.func.date(Agenda.data_hora) <= date.fromisoformat(ate).isoformat())
                except ValueError:
                    ate = ""
            total = consulta.count()
            registros = consulta.order_by(Agendamento.id.desc()).limit(LIMITE_RESULTADOS_BUSCA).all()
            return render_template("agendamentos_lista.html", titulo=titulo, registros=registros,
                                   total=total, filtros={"q": termo, "desde": desde, "ate": ate, "situacao": situacao})
        return render_template("agendamentos.html", nome_modelo=nome_modelo, titulo=titulo,
                               local_saida_inicial=db.session.get(LocalDestino, registro_edicao.local_saida_id if registro_edicao else request.args.get("local_saida_id", type=int)) if (registro_edicao and registro_edicao.local_saida_id) or request.args.get("local_saida_id", type=int) else None,
                               local_destino_inicial=db.session.get(LocalDestino, registro_edicao.local_destino_id if registro_edicao else request.args.get("local_destino_id", type=int)) if (registro_edicao and registro_edicao.local_destino_id) or request.args.get("local_destino_id", type=int) else None,
                               agenda_selecionada=request.args.get("agenda_id", type=int),
                               cpf_inicial="".join(c for c in request.args.get("cpf", "") if c.isdigit()),
                               endereco_inicial=request.args.get("endereco", ""),
                               cep_inicial=request.args.get("cep", ""),
                               destino_inicial=request.args.get("destino", ""),
                               registro_edicao=registro_edicao)
    if nome_modelo == "chamados":
        registro_edicao = db.session.get(Chamado, request.args.get("editar", type=int)) if request.args.get("editar") else None
        if not registro_edicao and request.args.get("novo") != "1":
            consulta = Chamado.query
            termo = request.args.get("q", "").strip()
            desde = request.args.get("desde", "").strip()
            ate = request.args.get("ate", "").strip()
            situacao = request.args.get("situacao", "").strip()
            if termo:
                padrao = f"%{termo}%"
                consulta = consulta.filter(or_(
                    Chamado.cidadao_nome.ilike(padrao),
                    Chamado.cidadao.has(filtro_nomes_cidadao(termo)),
                    Chamado.local_destino.has(or_(LocalDestino.nome.ilike(padrao), LocalDestino.cidade.ilike(padrao), LocalDestino.rua.ilike(padrao))),
                    Chamado.local_saida.has(or_(LocalDestino.nome.ilike(padrao), LocalDestino.cidade.ilike(padrao), LocalDestino.rua.ilike(padrao))),
                ))
            if situacao == "pendente":
                consulta = consulta.filter(Chamado.cidadao_id.is_(None))
            elif situacao == "identificado":
                consulta = consulta.filter(Chamado.cidadao_id.isnot(None))
            if desde:
                try:
                    consulta = consulta.filter(db.func.date(Chamado.criado_em) >= date.fromisoformat(desde).isoformat())
                except ValueError:
                    desde = ""
            if ate:
                try:
                    consulta = consulta.filter(db.func.date(Chamado.criado_em) <= date.fromisoformat(ate).isoformat())
                except ValueError:
                    ate = ""
            total = consulta.count()
            registros = consulta.order_by(Chamado.id.desc()).limit(LIMITE_RESULTADOS_BUSCA).all()
            return render_template("chamados_lista.html", titulo=titulo, registros=registros,
                                   total=total, filtros={"q": termo, "desde": desde, "ate": ate, "situacao": situacao})
        return render_template("chamados.html", nome_modelo=nome_modelo, titulo=titulo,
                               registro_edicao=registro_edicao)
    campos = [c for c in modelo.__table__.columns if c.name != "id"]
    consulta = modelo.query
    busca_realizada = nome_modelo == "cidadaos" and request.args.get("buscar") == "1"
    nome_busca = ""
    if nome_modelo == "cidadaos":
        cpf_busca = "".join(c for c in request.args.get("cpf", "") if c.isdigit())
        cns_busca = "".join(c for c in request.args.get("cns", "") if c.isdigit())
        nome_busca = request.args.get("nome", "").strip()
        if busca_realizada and cpf_busca:
            consulta = consulta.filter(Cidadao.cpf == cpf_busca)
        if busca_realizada and cns_busca:
            consulta = consulta.filter(Cidadao.cns == cns_busca)
        if busca_realizada and nome_busca:
            consulta = consulta.filter(filtro_nomes_cidadao(nome_busca))
    registro = db.session.get(modelo, request.args.get("editar", type=int)) if request.args.get("editar") else None
    registros = (consulta.order_by(modelo.id.desc()).limit(LIMITE_RESULTADOS_BUSCA).all()
                 if nome_modelo != "cidadaos" or (busca_realizada and (cpf_busca or cns_busca or nome_busca)) else [])
    template = {"frotas": "frotas.html", "motoristas": "motoristas.html",
                "cidadaos": "cidadaos.html"}.get(nome_modelo, "crud.html")
    return render_template(template, nome_modelo=nome_modelo, titulo=titulo,
                           campos=campos, registros=registros, registro=registro,
                           valores_iniciais={"cpf": "".join(c for c in request.args.get("cpf", "") if c.isdigit()), "cns": "".join(c for c in request.args.get("cns", "") if c.isdigit())},
                           return_to=request.args.get("return_to", ""))


@dados_bp.route("/chamados/<int:chamado_id>/finalizar", methods=["GET", "POST"])
@login_obrigatorio
def finalizar_chamado(chamado_id):
    """Registra o motorista e a data/hora em que o chamado foi finalizado."""
    if not pode_acessar_rota(usuario_atual(), "chamados"):
        abort(403)
    chamado = db.get_or_404(Chamado, chamado_id)
    if request.method == "POST":
        motorista_id_texto = request.form.get("motorista_final_id", "").strip()
        data_hora_texto = request.form.get("data_hora_final", "").strip()
        try:
            motorista_id = int(motorista_id_texto)
            motorista = db.session.get(Motorista, motorista_id)
            data_hora_final = datetime.fromisoformat(data_hora_texto)
            if not motorista or motorista.ativo != 1:
                raise ValueError
        except ValueError:
            flash("Selecione um motorista ativo e informe uma data e hora finais válidas.", "erro")
            return render_template("chamado_finalizar.html", chamado=chamado), 400
        chamado.motorista_final_id = motorista.id
        chamado.motorista_final = motorista.nome
        chamado.data_hora_final = data_hora_final
        db.session.commit()
        flash("Chamado finalizado.", "sucesso")
        return redirect(url_for("dados.confirmar_salvo", nome_modelo="chamados", registro_id=chamado.id))
    return render_template("chamado_finalizar.html", chamado=chamado)


def exigir_acesso_agendamentos():
    """Confirma a permissão de agendamentos antes de manter locais de destino."""
    if not pode_acessar_rota(usuario_atual(), "agendamentos"):
        abort(403)


def exigir_acesso_locais():
    """Permite manter a tabela comum a quem usa chamados ou agendamentos."""
    usuario = usuario_atual()
    if not any(pode_acessar_rota(usuario, rota) for rota in ("agendamentos", "chamados")):
        abort(403)


@dados_bp.route("/agendamentos/locais-destino", methods=["GET", "POST"])
@login_obrigatorio
def locais_destino():
    """Lista os destinos cadastrados e permite incluir locais reutilizáveis."""
    exigir_acesso_locais()
    if request.method == "POST":
        local, erro = valores_local_destino(request.form)
        duplicado = local_duplicado(local) if local else None
        if erro:
            flash(erro, "erro")
        elif duplicado:
            flash(f"Este CEP e número já pertencem ao local {duplicado.nome}. Abrindo o cadastro existente.", "erro")
            return redirect(url_for("dados.editar_local_destino", local_id=duplicado.id))
        else:
            db.session.add(LocalDestino(**local))
            try:
                db.session.commit()
                flash("Local de destino cadastrado.", "sucesso")
            except IntegrityError:
                db.session.rollback()
                flash("Não foi possível cadastrar o local de destino.", "erro")
        return redirect(url_for("dados.locais_destino"))
    return render_template("locais_destino.html",
                           locais=LocalDestino.query.order_by(LocalDestino.nome).all(),
                           local_edicao=None)


@dados_bp.route("/agendamentos/locais-destino/<int:local_id>/editar", methods=["GET", "POST"])
@login_obrigatorio
def editar_local_destino(local_id):
    """Atualiza os dados de endereço de um local de destino."""
    exigir_acesso_locais()
    local = db.get_or_404(LocalDestino, local_id)
    if request.method == "POST":
        valores, erro = valores_local_destino(request.form)
        duplicado = local_duplicado(valores, local.id) if valores else None
        if erro:
            flash(erro, "erro")
        elif duplicado:
            flash(f"Este CEP e número já pertencem ao local {duplicado.nome} (ID {duplicado.id}).", "erro")
        else:
            for campo, valor in valores.items():
                setattr(local, campo, valor)
            sincronizar_agendamentos_local(local)
            db.session.commit()
            flash("Local de destino atualizado.", "sucesso")
            return redirect(url_for("dados.locais_destino"))
    return render_template("locais_destino.html",
                           locais=LocalDestino.query.order_by(LocalDestino.nome).all(),
                           local_edicao=local)


@dados_bp.route("/agendamentos/locais-destino/<int:local_id>/excluir", methods=["POST"])
@login_obrigatorio
def excluir_local_destino(local_id):
    """Exclui locais livres ou desativa os que já estão em chamados ou reservas."""
    exigir_acesso_locais()
    local = db.get_or_404(LocalDestino, local_id)
    usado_em_agendamento = Agendamento.query.filter(
        or_(Agendamento.local_destino_id == local.id, Agendamento.local_saida_id == local.id)
    ).first()
    usado_em_chamado = Chamado.query.filter(
        or_(Chamado.local_destino_id == local.id, Chamado.local_saida_id == local.id)
    ).first()
    if usado_em_agendamento or usado_em_chamado:
        local.ativo = 0
        db.session.commit()
        flash("O local está em uso por um chamado ou agendamento e foi desativado.", "sucesso")
    else:
        db.session.delete(local)
        db.session.commit()
        flash("Local de destino excluído.", "sucesso")
    return redirect(url_for("dados.locais_destino"))


def valores_local_destino(formulario):
    """Lê e valida o nome e o endereço de um local de destino."""
    nome = (formulario.get("nome") or "").strip()
    cep = "".join(c for c in (formulario.get("cep") or "") if c.isdigit())
    if not nome:
        return None, "Informe o nome do local de destino."
    if cep and len(cep) != 8:
        return None, "O CEP do local de destino deve conter 8 dígitos."
    try:
        cidade_id = int(formulario.get("cidade_id") or "")
    except (TypeError, ValueError):
        cidade_id = None
    cidade_registro = db.session.get(Cidade, cidade_id) if cidade_id else None
    cidade = cidade_registro.nome if cidade_registro and cidade_registro.ativo == 1 else ""
    rua = (formulario.get("rua") or "").strip()
    bairro = (formulario.get("bairro") or "").strip()
    numero = (formulario.get("numero") or "").strip()
    if not cidade_registro or cidade_registro.ativo != 1:
        return None, "Busque e selecione uma cidade ativa da lista."
    if not rua or not bairro or not numero:
        return None, "Informe rua, bairro e número do local de destino."
    return {
        "nome": nome,
        "cidade_id": cidade_registro.id,
        "cep": cep or None,
        "cidade": cidade,
        "rua": rua,
        "bairro": bairro,
        "numero": numero,
        "referencia": (formulario.get("referencia") or "").strip() or None,
        "ativo": 1 if formulario.get("ativo", "1") == "1" else 0,
    }, None


def local_duplicado(valores, ignorar_id=None):
    """Localiza registros com o mesmo CEP e número ou endereço já cadastrado."""
    cep = "".join(c for c in (valores.get("cep") or "") if c.isdigit())
    numero = (valores.get("numero") or "").strip().upper()
    if cep and numero:
        candidatos = LocalDestino.query.order_by(LocalDestino.id).all()
        for candidato in candidatos:
            cep_existente = "".join(c for c in (candidato.cep or "") if c.isdigit())
            numero_existente = (candidato.numero or "").strip().upper()
            if candidato.id != ignorar_id and cep_existente == cep and numero_existente == numero:
                return candidato
    consulta = LocalDestino.query.filter(
        db.func.lower(LocalDestino.nome) == valores["nome"].lower(),
        db.func.lower(LocalDestino.cidade) == valores["cidade"].lower(),
        db.func.lower(LocalDestino.rua) == valores["rua"].lower(),
        db.func.upper(db.func.trim(LocalDestino.numero)) == numero,
    )
    if ignorar_id is not None:
        consulta = consulta.filter(LocalDestino.id != ignorar_id)
    return consulta.first()


def sincronizar_agendamentos_local(local):
    """Mantém os dados de exibição antigos alinhados ao local compartilhado."""
    reservas = Agendamento.query.filter(
        or_(Agendamento.local_saida_id == local.id, Agendamento.local_destino_id == local.id)
    ).all()
    for reserva in reservas:
        if reserva.local_saida_id == local.id:
            reserva.cidade_embarque = local.cidade
            reserva.cep_embarque = local.cep
            reserva.rua_embarque = local.rua
            reserva.bairro_embarque = local.bairro
            reserva.numero_embarque = local.numero
            reserva.referencia_embarque = local.referencia
            reserva.endereco_embarque = ", ".join(
                parte for parte in (local.rua, local.numero, local.bairro, local.referencia) if parte
            )
        if reserva.local_destino_id == local.id:
            reserva.local_destino = local.nome
            reserva.destino_cidade = local.cidade
            reserva.destino_cep = local.cep
            reserva.destino_rua = local.rua
            reserva.destino_bairro = local.bairro
            reserva.destino_numero = local.numero
            reserva.destino_referencia = local.referencia


@dados_bp.route("/chamados/buscar-cidadao")
@login_obrigatorio
def buscar_cidadao_chamado():
    """Pesquisa cidadão pelos dados informados na tela de chamados."""
    if not pode_acessar_rota(usuario_atual(), "chamados"):
        return jsonify(erro="Você não tem permissão para pesquisar cidadão em chamados."), 403
    cpf = "".join(c for c in request.args.get("cpf", "") if c.isdigit())
    cns = "".join(c for c in request.args.get("cns", "") if c.isdigit())
    nome = request.args.get("nome", "").strip()
    nome_mae = request.args.get("nome_mae", "").strip()
    nascimento_texto = request.args.get("data_nascimento", "").strip()
    if (cpf and len(cpf) != 11) or (cns and len(cns) != 15):
        return jsonify(erro="CPF precisa ter 11 números e CNS precisa ter 15 números."), 400
    if not any((cpf, cns, nome, nome_mae, nascimento_texto)):
        return jsonify(erro="Informe ao menos um dado para pesquisar."), 400
    nascimento = None
    if nascimento_texto:
        try:
            nascimento = date.fromisoformat(nascimento_texto)
        except ValueError:
            return jsonify(erro="Informe uma data de nascimento válida."), 400
    filtros = []
    if cpf:
        filtros.append(Cidadao.cpf == cpf)
    if cns:
        filtros.append(Cidadao.cns == cns)
    if nome:
        filtros.append(filtro_nomes_cidadao(nome))
    if nome_mae:
        filtros.append(Cidadao.nome_mae.ilike(f"%{nome_mae}%"))
    if nascimento:
        filtros.append(Cidadao.data_nascimento == nascimento)
    cidadaos = Cidadao.query.filter(Cidadao.ativo == 1, *filtros).order_by(Cidadao.nome).limit(LIMITE_RESULTADOS_BUSCA).all()
    return jsonify(resultados=[dados_cidadao(pessoa) for pessoa in cidadaos])


@dados_bp.route("/chamados/buscar-motorista")
@login_obrigatorio
def buscar_motorista_chamado():
    """Pesquisa motoristas ativos pelo nome para finalizar um chamado."""
    if not pode_acessar_rota(usuario_atual(), "chamados"):
        abort(403)
    termo = request.args.get("q", "").strip()
    if len(termo) < 2:
        return jsonify(resultados=[])
    motoristas = Motorista.query.filter(
        Motorista.ativo == 1, Motorista.nome.ilike(f"%{termo}%")
    ).order_by(Motorista.nome).limit(LIMITE_RESULTADOS_BUSCA).all()
    return jsonify(resultados=[{
        "id": motorista.id, "nome": motorista.nome or "", "cracha": motorista.cracha,
    } for motorista in motoristas])


@dados_bp.route("/chamados/buscar-local")
@login_obrigatorio
def buscar_local_chamado():
    """Pesquisa locais ativos em uma cidade específica pelo nome, CEP ou logradouro."""
    if not any(pode_acessar_rota(usuario_atual(), rota) for rota in ("chamados", "agendamentos")):
        abort(403)
    termo = request.args.get("q", "").strip()
    cidade = request.args.get("cidade", "").strip()
    cidade_id = request.args.get("cidade_id", type=int)
    if len(termo) < 2 or (not cidade and not cidade_id):
        return jsonify(resultados=[])
    padrao = f"%{termo}%"
    cep_busca = "".join(c for c in termo if c.isdigit())
    consulta = LocalDestino.query.filter(
        LocalDestino.ativo == 1,
        (LocalDestino.cidade_id == cidade_id if cidade_id else db.func.lower(LocalDestino.cidade) == cidade.lower()),
        or_(LocalDestino.nome.ilike(padrao), LocalDestino.rua.ilike(padrao),
            LocalDestino.bairro.ilike(padrao),
            LocalDestino.cep.ilike(padrao),
            LocalDestino.cep.ilike(f"%{cep_busca}%") if cep_busca else False),
    ).order_by(LocalDestino.nome).limit(LIMITE_RESULTADOS_BUSCA)
    return jsonify(resultados=[{
        "id": item.id, "nome_local": item.nome,
        "cidade": item.cidade or "", "cidade_id": item.cidade_id or "",
        "uf": item.cidade_registro.uf if item.cidade_registro else "",
        "cep": item.cep or "", "bairro": item.bairro or "",
        "logradouro": item.rua or "", "numero": item.numero or "",
        "referencia": item.referencia or "",
    } for item in consulta.all()])


@dados_bp.route("/cidades/buscar")
@login_obrigatorio
def buscar_cidades_locais():
    """Busca cidades para os seletores de local, retornando no máximo 50."""
    if not any(pode_acessar_rota(usuario_atual(), rota) for rota in ("chamados", "agendamentos")):
        abort(403)
    termo = texto_busca_sem_acento(request.args.get("q", "").strip())
    if len(termo) < 2:
        return jsonify(resultados=[])
    locais_usados = (db.session.query(db.func.count(LocalDestino.id))
                     .filter(LocalDestino.cidade_id == Cidade.id)
                     .correlate(Cidade).scalar_subquery())
    agendas_usadas = (db.session.query(db.func.count(Agenda.id))
                      .filter(Agenda.cidade_destino_id == Cidade.id)
                      .correlate(Cidade).scalar_subquery())
    chamados_usando_cidade = (db.session.query(db.func.count(db.func.distinct(Chamado.id)))
                              .join(LocalDestino, or_(Chamado.local_destino_id == LocalDestino.id,
                                                      Chamado.local_saida_id == LocalDestino.id))
                              .filter(LocalDestino.cidade_id == Cidade.id)
                              .correlate(Cidade).scalar_subquery())
    agendamentos_usando_cidade = (db.session.query(db.func.count(db.func.distinct(Agendamento.id)))
                                  .join(LocalDestino, or_(Agendamento.local_destino_id == LocalDestino.id,
                                                          Agendamento.local_saida_id == LocalDestino.id))
                                  .filter(LocalDestino.cidade_id == Cidade.id, Agendamento.ativo == 1)
                                  .correlate(Cidade).scalar_subquery())
    uso = locais_usados + agendas_usadas + chamados_usando_cidade + agendamentos_usando_cidade
    cidades = Cidade.query.filter(
        Cidade.ativo == 1, Cidade.nome_busca.ilike(f"%{termo}%")
    ).order_by(uso.desc(), case((Cidade.nome_busca == termo, 0), else_=1),
               Cidade.nome, Cidade.uf).limit(LIMITE_RESULTADOS_BUSCA).all()
    return jsonify(resultados=[{"id": cidade.id, "nome": cidade.nome, "uf": cidade.uf or ""} for cidade in cidades])


@dados_bp.route("/chamados/novo-local", methods=["POST"])
@login_obrigatorio
def novo_local_chamado():
    """Cria um local reutilizável a partir do formulário de chamados."""
    if not any(pode_acessar_rota(usuario_atual(), rota) for rota in ("chamados", "agendamentos")):
        return jsonify(sucesso=False, erro="Você não tem permissão para cadastrar locais."), 403
    try:
        cidade = db.session.get(Cidade, int(request.form.get("cidade_id", "")))
        if not cidade or cidade.ativo != 1:
            raise ValueError("Selecione uma cidade ativa.")
        local = LocalDestino(
            nome=request.form.get("nome_local", "").strip().upper(),
            cidade=cidade.nome,
            cep="".join(c for c in request.form.get("cep", "") if c.isdigit()) or None,
            bairro=request.form.get("bairro", "").strip().upper(),
            rua=request.form.get("logradouro", "").strip().upper(),
            numero=request.form.get("numero", "").strip().upper(),
            referencia=request.form.get("referencia", "").strip().upper() or None,
            ativo=1,
        )
        local, erro = valores_local_destino({
            "nome": local.nome, "cidade": local.cidade, "cidade_id": cidade.id, "cep": local.cep,
            "bairro": local.bairro, "rua": local.rua, "numero": local.numero,
            "referencia": local.referencia,
        })
        if erro:
            raise ValueError(erro)
        local = LocalDestino(**local)
        if not local.bairro or not local.rua or not local.numero:
            raise ValueError("Informe bairro, logradouro e número.")
        if local.cep and len(local.cep) != 8:
            raise ValueError("O CEP deve conter 8 números.")
        existente = local_duplicado({
            "nome": local.nome, "cidade": local.cidade, "rua": local.rua,
            "numero": local.numero, "cep": local.cep,
        })
        if existente:
            if existente.ativo != 1:
                return jsonify(sucesso=False,
                               erro=f"Este CEP e número já pertencem ao local inativo {existente.nome}. Reative-o no cadastro de Locais."), 409
            return jsonify(sucesso=True, duplicado=True,
                           mensagem=f"Este CEP e número já estão cadastrados em {existente.nome}; o local existente foi selecionado.",
                           local={
                               "id": existente.id, "nome_local": existente.nome,
                               "cidade": existente.cidade or "", "cidade_id": existente.cidade_id or "",
                               "uf": existente.cidade_registro.uf if existente.cidade_registro else "",
                               "cep": existente.cep or "",
                               "bairro": existente.bairro or "", "logradouro": existente.rua or "",
                               "numero": existente.numero or "", "referencia": existente.referencia or "",
                           })
        db.session.add(local)
        db.session.commit()
        return jsonify(sucesso=True, local={
            "id": local.id, "nome_local": local.nome,
            "cidade": local.cidade or "", "cidade_id": local.cidade_id or "",
            "uf": local.cidade_registro.uf if local.cidade_registro else "",
            "cep": local.cep or "", "bairro": local.bairro,
            "logradouro": local.rua, "numero": local.numero,
            "referencia": local.referencia or "",
        })
    except (TypeError, ValueError, IntegrityError):
        db.session.rollback()
        return jsonify(sucesso=False, erro="Confira o nome, cidade, bairro, logradouro, número e CEP."), 400


def valores_chamado(formulario):
    """Valida cidadão, endereço de destino e local de saída de um chamado."""
    nome = formulario.get("nome_cidadao", "").strip()
    cpf = "".join(c for c in formulario.get("cpf", "") if c.isdigit())
    cns = "".join(c for c in formulario.get("cns", "") if c.isdigit())
    if not nome:
        return None, "Informe o nome do cidadão."
    cpf_completo = len(cpf) == 11
    cns_completo = len(cns) == 15
    nascimento_texto = formulario.get("data_nascimento", "").strip()
    try:
        nascimento = date.fromisoformat(nascimento_texto) if nascimento_texto else None
    except ValueError:
        return None, "Informe uma data de nascimento válida."
    try:
        cidadao_id = int(formulario.get("cidadao_id", "")) or None
    except (TypeError, ValueError):
        cidadao_id = None
    cidadao = db.session.get(Cidadao, cidadao_id) if cidadao_id else None
    if cidadao_id and (not cidadao or cidadao.ativo != 1):
        return None, "O cidadão selecionado não está ativo."
    if cidadao and cpf and not cpf_completo:
        return None, "Complete o CPF ou remova a seleção do cidadão."
    if cidadao and cns and not cns_completo:
        return None, "Complete o CNS ou remova a seleção do cidadão."
    if cidadao and cpf_completo and cidadao.cpf != cpf:
        return None, "O CPF informado não corresponde ao cidadão localizado."
    if cidadao and cns_completo and cidadao.cns != cns:
        return None, "O CNS informado não corresponde ao cidadão localizado."
    if not cidadao and (cpf_completo or cns_completo):
        filtros = []
        if cpf_completo:
            filtros.append(Cidadao.cpf == cpf)
        if cns_completo:
            filtros.append(Cidadao.cns == cns)
        cidadao = Cidadao.query.filter(Cidadao.ativo == 1, or_(*filtros)).first()
        if cidadao and ((cpf_completo and cidadao.cpf != cpf) or (cns_completo and cidadao.cns != cns)):
            return None, "CPF e CNS informados pertencem a cadastros diferentes."
    if cidadao:
        cidadao_id = cidadao.id

    try:
        local_destino_id = int(formulario.get("local_destino_id", ""))
        local_saida_id = int(formulario.get("local_saida_id", ""))
    except (TypeError, ValueError):
        return None, "Selecione um endereço de destino e um local de saída."
    local_destino = db.session.get(LocalDestino, local_destino_id)
    local_saida = db.session.get(LocalDestino, local_saida_id)
    if not local_destino or local_destino.ativo != 1:
        return None, "Selecione um endereço de destino ativo."
    if not local_saida or local_saida.ativo != 1:
        return None, "Selecione um local de saída ativo."
    valores = {
        "cidadao_id": cidadao.id if cidadao else None,
        "cidadao_nome": cidadao.nome if cidadao else nome,
        "local_destino_id": local_destino.id,
        "local_saida_id": local_saida.id,
    }
    return valores, None


@dados_bp.route("/cidadaos/buscar")
@login_obrigatorio
def buscar_cidadao():
    """Localiza cidadãos ativos por CPF, nome ou data de nascimento."""
    if not pode_acessar_rota(usuario_atual(), "agendamentos"):
        abort(403)
    cpf = "".join(c for c in request.args.get("cpf", "") if c.isdigit())
    cns = "".join(c for c in request.args.get("cns", "") if c.isdigit())
    nome = request.args.get("nome", "").strip()
    nascimento_texto = request.args.get("data_nascimento", "").strip()
    if (cpf and len(cpf) != 11) or (cns and len(cns) != 15):
        return jsonify(encontrado=False, resultados=[])
    if nascimento_texto:
        try:
            nascimento = date.fromisoformat(nascimento_texto)
        except ValueError:
            return jsonify(encontrado=False, resultados=[])
    else:
        nascimento = None
    if not any((cpf, cns, nome, nascimento)):
        return jsonify(encontrado=False, resultados=[])
    filtros = []
    if cpf:
        filtros.append(Cidadao.cpf == cpf)
    if cns:
        filtros.append(Cidadao.cns == cns)
    if nome:
        filtros.append(filtro_nomes_cidadao(nome))
    if nascimento:
        filtros.append(Cidadao.data_nascimento == nascimento)
    cidadaos = Cidadao.query.filter(Cidadao.ativo == 1, *filtros).order_by(Cidadao.nome).limit(LIMITE_RESULTADOS_BUSCA).all()
    resultados = [dados_cidadao(pessoa) for pessoa in cidadaos]
    if not cpf and not cns:
        return jsonify(encontrado=len(resultados) == 1, resultados=resultados)
    cidadao = cidadaos[0] if cidadaos else None
    if not cidadao:
        return jsonify(encontrado=False, resultados=[])
    return jsonify(encontrado=True, **dados_cidadao(cidadao))


@dados_bp.route("/agendamentos/buscar-destino")
@login_obrigatorio
def buscar_agendas_destino():
    """Pesquisa agendas e vagas disponíveis, sempre incluindo a cidade destino."""
    if not pode_acessar_rota(usuario_atual(), "agendamentos"):
        abort(403)
    termos = request.args.get("q", "").strip().split()
    dia = request.args.get("dia", "").strip()
    horario = request.args.get("horario", "").strip()
    consulta = Agenda.query.outerjoin(Cidade)
    if termos:
        filtros = []
        for termo in termos:
            padrao = f"%{termo}%"
            termo_normalizado = texto_busca_sem_acento(termo)
            padrao_sem_acento = f"%{termo_normalizado}%"
            filtros.append(or_(Cidade.nome_busca.ilike(padrao_sem_acento),
                               Agenda.cidade.ilike(padrao),
                               Agenda.informacao.ilike(padrao)))
        consulta = consulta.filter(and_(*filtros))
    if dia:
        try:
            consulta = consulta.filter(db.func.date(Agenda.data_hora) == date.fromisoformat(dia).isoformat())
        except ValueError:
            return jsonify(agendas=[])
    if horario:
        try:
            horario_filtro = time.fromisoformat(horario)
        except ValueError:
            return jsonify(agendas=[])
        consulta = consulta.filter(
            db.extract("hour", Agenda.data_hora) == horario_filtro.hour,
            db.extract("minute", Agenda.data_hora) == horario_filtro.minute,
        )
    agendamento_edicao = db.session.get(Agendamento, request.args.get("editar", type=int)) if request.args.get("editar") else None
    agendas = consulta.order_by(Agenda.data_hora.desc()).limit(LIMITE_RESULTADOS_BUSCA).all()
    if agendamento_edicao and not termos and not dia and not horario:
        agenda_atual = db.session.get(Agenda, agendamento_edicao.agenda_id)
        if agenda_atual and all(item.id != agenda_atual.id for item in agendas):
            agendas = (agendas + [agenda_atual])[-LIMITE_RESULTADOS_BUSCA:]
    return jsonify(agendas=[{
        "id": agenda.id,
        "cidade": (f"{agenda.destino.nome} - {agenda.destino.uf}" if agenda.destino and agenda.destino.uf
                   else agenda.destino.nome if agenda.destino else agenda.cidade or "Destino não informado"),
        "informacao": agenda.informacao or "",
        "data_hora": agenda.data_hora.isoformat() if agenda.data_hora else "",
        "vagas": agenda.vagas_disponiveis + (1 if agendamento_edicao and agendamento_edicao.ativo == 1
                                                and agendamento_edicao.agenda_id == agenda.id
                                                and agendamento_edicao.cidadao and agendamento_edicao.cidadao.ativo == 1 else 0),
    } for agenda in agendas])


@dados_bp.route("/<nome_modelo>/novo", methods=["POST"])
@acesso_rota_cadastro
def criar(nome_modelo):
    """Valida e cria um novo registro do módulo selecionado."""
    modelo, _ = modelo_por_nome(nome_modelo)
    if nome_modelo == "chamados":
        valores, erro = valores_chamado(request.form)
        if erro:
            flash(erro, "erro")
        else:
            valores["usuario_id"] = usuario_atual().id
            registro = Chamado(**valores)
            db.session.add(registro)
            db.session.commit()
            flash("Chamado cadastrado com cidadão vinculado." if valores["cidadao_id"] else
                  "Chamado cadastrado como pendente de identificação do cidadão.", "sucesso")
            return redirect(url_for("dados.confirmar_salvo", nome_modelo=nome_modelo, registro_id=registro.id))
        return redirect(url_for("dados.listar", nome_modelo="chamados"))
    if nome_modelo == "agendas":
        valores, erro = valores_agenda(request.form)
        if erro:
            flash(erro, "erro")
        else:
            registro = Agenda(**valores)
            db.session.add(registro)
            registrar_auditoria(nome_modelo, registro, "insercao")
            db.session.commit()
            flash("Agenda criada.", "sucesso")
        return redirect(url_for("dados.listar", nome_modelo=nome_modelo))
    if nome_modelo == "agendamentos":
        valores, erro = valores_agendamento(request.form)
        if erro:
            flash(erro, "erro")
        else:
            registro = Agendamento(**valores)
            db.session.add(registro)
            registrar_auditoria(nome_modelo, registro, "insercao")
            db.session.commit()
            flash("Agendamento criado.", "sucesso")
            return redirect(url_for("dados.confirmar_salvo", nome_modelo=nome_modelo, registro_id=registro.id))
        return redirect(url_for("dados.listar", nome_modelo=nome_modelo))
    registro = modelo()
    criado = False
    try:
        for campo in modelo.__table__.columns:
            if campo.name not in ("id", "id_esus") and campo.name in request.form:
                setattr(registro, campo.name, converter_cadastro(nome_modelo, campo, request.form[campo.name]))
        if nome_modelo == "cidadaos":
            validar_cidadao(registro)
        db.session.add(registro)
        if nome_modelo in AUDITORIAS:
            registrar_auditoria(nome_modelo, registro, "insercao")
        db.session.commit()
        criado = True
        flash("Registro cadastrado.", "sucesso")
    except ValueError as erro:
        db.session.rollback()
        flash(str(erro), "erro")
    except (TypeError, IntegrityError):
        db.session.rollback()
        flash("Não foi possível cadastrar. Confira os campos obrigatórios e os valores informados.", "erro")
    destino = request.form.get("return_to", "")
    partes = urlsplit(destino)
    if criado and destino and partes.path.startswith("/") and not partes.netloc and not destino.startswith("//"):
        return redirect(destino)
    return redirect(url_for("dados.listar", nome_modelo=nome_modelo))


@dados_bp.route("/<nome_modelo>/<int:registro_id>/editar", methods=["POST"])
@acesso_rota_cadastro
def atualizar(nome_modelo, registro_id):
    """Valida alterações e atualiza o registro selecionado."""
    modelo, _ = modelo_por_nome(nome_modelo)
    registro = db.get_or_404(modelo, registro_id)
    if nome_modelo == "agendas":
        valores, erro = valores_agenda(request.form, registro)
        if erro:
            flash(erro, "erro")
        else:
            for campo, valor in valores.items():
                setattr(registro, campo, valor)
            registrar_auditoria(nome_modelo, registro, "alteracao")
            db.session.commit()
            flash("Agenda atualizada.", "sucesso")
        return redirect(url_for("dados.listar", nome_modelo=nome_modelo))
    if nome_modelo == "agendamentos":
        valores, erro = valores_agendamento(request.form, registro)
        if erro:
            flash(erro, "erro")
        else:
            for campo, valor in valores.items():
                setattr(registro, campo, valor)
            registrar_auditoria(nome_modelo, registro, "alteracao")
            db.session.commit()
            flash("Agendamento atualizado.", "sucesso")
            return redirect(url_for("dados.confirmar_salvo", nome_modelo=nome_modelo, registro_id=registro.id))
        return redirect(url_for("dados.listar", nome_modelo=nome_modelo))
    if nome_modelo == "chamados":
        valores, erro = valores_chamado(request.form)
        if erro:
            flash(erro, "erro")
        else:
            for campo, valor in valores.items():
                setattr(registro, campo, valor)
            registro.usuario_id = usuario_atual().id
            db.session.commit()
            flash("Chamado atualizado e cidadão vinculado." if registro.cidadao_id else
                  "Chamado atualizado como pendente de identificação.", "sucesso")
            return redirect(url_for("dados.confirmar_salvo", nome_modelo=nome_modelo, registro_id=registro.id))
        return redirect(url_for("dados.listar", nome_modelo=nome_modelo))
    try:
        for campo in modelo.__table__.columns:
            if campo.name not in ("id", "id_esus") and campo.name in request.form:
                setattr(registro, campo.name, converter_cadastro(nome_modelo, campo, request.form[campo.name]))
        if nome_modelo == "cidadaos":
            validar_cidadao(registro)
        if nome_modelo in AUDITORIAS:
            registrar_auditoria(nome_modelo, registro, "alteracao")
        db.session.commit()
        flash("Registro atualizado.", "sucesso")
    except ValueError as erro:
        db.session.rollback()
        flash(str(erro), "erro")
    except (TypeError, IntegrityError):
        db.session.rollback()
        flash("Não foi possível atualizar. Confira os valores informados.", "erro")
    return redirect(url_for("dados.listar", nome_modelo=nome_modelo))


@dados_bp.route("/<nome_modelo>/<int:registro_id>/excluir", methods=["POST"])
@acesso_rota_cadastro
def excluir(nome_modelo, registro_id):
    """Remove o registro quando não há vínculos que impeçam a exclusão."""
    modelo, _ = modelo_por_nome(nome_modelo)
    registro = db.get_or_404(modelo, registro_id)
    if nome_modelo == "agendas" and Agendamento.query.filter_by(agenda_id=registro_id).first():
        flash("Não é possível excluir uma agenda que já possui agendamentos.", "erro")
        return redirect(url_for("dados.listar", nome_modelo=nome_modelo))
    db.session.delete(registro)
    db.session.commit()
    flash("Registro excluído.", "sucesso")
    return redirect(url_for("dados.listar", nome_modelo=nome_modelo))


def valores_agenda(formulario, registro_atual=None):
    """Valida os dados da viagem e a capacidade de lugares da frota."""
    try:
        data_hora = datetime.fromisoformat(formulario.get("data_hora", ""))
        motorista_id = int(formulario.get("motorista_id", ""))
        frota_id = int(formulario.get("frota_id", ""))
        frota = db.session.get(Frota, frota_id)
        motorista = db.session.get(Motorista, motorista_id)
        quantidade = int(formulario.get("quantidade_vagas", ""))
        cidade_destino_id = int(formulario.get("cidade_destino_id", ""))
        destino = db.session.get(Cidade, cidade_destino_id)
    except (TypeError, ValueError):
        return None, "Informe data, horário, motorista, frota e quantidade de vagas válidos."
    if not frota or frota.ativo != 1:
        return None, "Selecione uma frota ativa."
    if not motorista or motorista.ativo != 1:
        return None, "Selecione um motorista ativo."
    if not destino or destino.ativo != 1:
        return None, "Selecione uma cidade ou local de destino ativo."
    if quantidade < 1 or quantidade > (frota.lugares or 0):
        return None, f"A quantidade de vagas deve ser entre 1 e {frota.lugares or 0}, conforme a capacidade da frota."
    if registro_atual and registro_atual.id:
        ocupadas = (Agendamento.query.join(Cidadao)
                    .filter(Agendamento.agenda_id == registro_atual.id,
                            Agendamento.ativo == 1, Cidadao.ativo == 1).count())
        if quantidade < ocupadas:
            return None, f"A agenda já tem {ocupadas} vaga(s) ocupada(s); a capacidade não pode ser menor."
    return {"data_hora": data_hora, "motorista_id": motorista_id, "frota_id": frota_id,
            "quantidade_vagas": quantidade, "cidade_destino_id": destino.id,
            "cidade": destino.nome,
            "informacao": formulario.get("informacao", "").strip() or None}, None


def valores_agendamento(formulario, registro_atual=None):
    """Valida cidadão, vagas, endereço, contato e destino do embarque."""
    try:
        agenda_id = int(formulario.get("agenda_id", ""))
    except (TypeError, ValueError):
        return None, "Selecione uma agenda e informe o CPF do cidadão."
    cpf = "".join(caractere for caractere in formulario.get("cpf", "") if caractere.isdigit())
    try:
        cidadao_id = int(formulario.get("cidadao_id", ""))
    except (TypeError, ValueError):
        cidadao_id = None
    if len(cpf) != 11 or not cidadao_id:
        return None, "Informe um CPF válido e selecione um cidadão encontrado."
    agenda = db.session.get(Agenda, agenda_id)
    cidadao = db.session.get(Cidadao, cidadao_id)
    if not agenda or not agenda.data_hora:
        return None, "A agenda selecionada não existe."
    if not agenda.cidade:
        return None, "A agenda precisa ter cidade ou local de destino cadastrado."
    if not cidadao or cidadao.ativo != 1:
        return None, "Selecione um cidadão ativo."
    if "".join(caractere for caractere in (cidadao.cpf or "") if caractere.isdigit()) != cpf:
        return None, "O CPF informado não corresponde ao cidadão localizado."
    existente = Agendamento.query.filter_by(agenda_id=agenda_id, cidadao_id=cidadao_id, ativo=1)
    if registro_atual:
        existente = existente.filter(Agendamento.id != registro_atual.id)
    if existente.first():
        return None, "Este cidadão já está agendado para essa data e horário."
    vagas = agenda.vagas_disponiveis
    if (registro_atual and registro_atual.ativo == 1 and registro_atual.agenda_id == agenda_id
            and registro_atual.cidadao and registro_atual.cidadao.ativo == 1):
        vagas += 1
    if vagas <= 0:
        return None, "Não há vagas disponíveis nessa agenda."
    try:
        local_saida_id = int(formulario.get("local_saida_id", ""))
        local_destino_id = int(formulario.get("local_destino_id", ""))
    except (TypeError, ValueError):
        return None, "Selecione o local de saída e o local de destino cadastrados."
    local_saida = db.session.get(LocalDestino, local_saida_id)
    local_destino = db.session.get(LocalDestino, local_destino_id)
    if not local_saida or not local_destino:
        return None, "Selecione locais de saída e destino válidos."
    if local_saida.ativo != 1 and not (registro_atual and registro_atual.local_saida_id == local_saida.id):
        return None, "O local de saída selecionado está inativo."
    if local_destino.ativo != 1 and not (registro_atual and registro_atual.local_destino_id == local_destino.id):
        return None, "O local de destino selecionado está inativo."
    rua = local_saida.rua or ""
    bairro = local_saida.bairro or ""
    cidade_embarque = local_saida.cidade or ""
    numero = local_saida.numero or ""
    referencia = local_saida.referencia or ""
    telefone_digitos = "".join(caractere for caractere in formulario.get("telefone_contato", "") if caractere.isdigit())
    cep = "".join(caractere for caractere in (local_saida.cep or "") if caractere.isdigit())
    destino_cep = "".join(caractere for caractere in (local_destino.cep or "") if caractere.isdigit())
    destino_cidade = local_destino.cidade or ""
    destino_rua = local_destino.rua or ""
    destino_bairro = local_destino.bairro or ""
    destino_numero = local_destino.numero or ""
    destino_referencia = local_destino.referencia or ""
    observacao = formulario.get("observacao", "").strip()
    if len(telefone_digitos) not in (10, 11):
        return None, "Informe um telefone com DDD e 10 ou 11 números."
    if len(telefone_digitos) == 10:
        telefone = f"({telefone_digitos[:2]}) {telefone_digitos[2:6]}-{telefone_digitos[6:]}"
    else:
        telefone = f"({telefone_digitos[:2]}) {telefone_digitos[2:7]}-{telefone_digitos[7:]}"
    if len(observacao) > 500:
        return None, "A observação deve ter no máximo 500 caracteres."
    local_saida_incompleto = not (rua and bairro and cidade_embarque and numero)
    if local_saida_incompleto and not (registro_atual and registro_atual.local_saida_id == local_saida.id):
        return None, "O local de saída precisa ter cidade, rua, bairro e número cadastrados."
    local_destino_incompleto = not (destino_cidade and destino_rua and destino_bairro and destino_numero)
    if local_destino_incompleto and not (registro_atual and registro_atual.local_destino_id == local_destino.id):
        return None, "O local de destino precisa ter cidade, rua, bairro e número cadastrados."
    if cep and len(cep) != 8:
        return None, "O CEP deve conter 8 dígitos."
    if destino_cep and len(destino_cep) != 8:
        return None, "O CEP do destino deve conter 8 dígitos."
    endereco = ", ".join(parte for parte in (rua, numero, bairro, referencia) if parte)
    return {"agenda_id": agenda_id, "cidadao_id": cidadao_id, "ativo": 1,
            "id_esus": cidadao.id_esus, "cpf": cidadao.cpf, "nome": cidadao.nome,
            "local_saida_id": local_saida.id,
            "endereco_embarque": endereco, "rua_embarque": rua,
            "bairro_embarque": bairro, "cidade_embarque": cidade_embarque,
            "numero_embarque": numero,
            "referencia_embarque": referencia or None,
            "telefone_contato": telefone, "observacao": observacao or None,
            "local_destino": local_destino.nome, "local_destino_id": local_destino.id,
            "cep_embarque": cep or None, "destino_cep": destino_cep or None,
            "destino_cidade": destino_cidade, "destino_rua": destino_rua,
            "destino_bairro": destino_bairro, "destino_numero": destino_numero,
            "destino_referencia": destino_referencia or None}, None

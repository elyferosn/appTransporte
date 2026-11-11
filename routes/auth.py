"""Implementa entrada, encerramento e contexto do usuário autenticado."""

import secrets
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from models import Sessao, Usuario, db
from routes.access import login_obrigatorio, pode_acessar_rota, url_rota_inicial, usuario_atual

auth_bp = Blueprint("auth", __name__)


@auth_bp.app_context_processor
def contexto_global():
    """Compartilha usuário, data e verificação de acesso com os templates."""
    return {"usuario_logado": usuario_atual(), "hoje": datetime.now(),
            "pode_acessar_rota": pode_acessar_rota}


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Valida as credenciais e registra uma sessão com IP e navegador."""
    if usuario_atual():
        return redirect(url_for("main.painel"))
    if request.method == "POST":
        cpf = "".join(c for c in request.form.get("usuario", "") if c.isdigit())
        usuario = Usuario.query.filter_by(usuario=cpf).first()
        if usuario and usuario.status == 1 and check_password_hash(usuario.senha, request.form.get("senha", "")):
            registro = Sessao(token=secrets.token_hex(32), usuario=usuario,
                              ip=request.remote_addr or "desconhecido",
                              user_agent=request.user_agent.string[:500])
            db.session.add(registro)
            db.session.commit()
            session.clear()
            session["sessao_token"] = registro.token
            destino = request.args.get("proxima")
            if usuario.usuario != "00000000000" or not destino:
                destino = url_rota_inicial(usuario)
            elif not destino.startswith("/") or destino.startswith("//"):
                destino = url_rota_inicial(usuario)
            return redirect(destino)
        flash("CPF ou senha inválidos, ou usuário inativo.", "erro")
    return render_template("login.html")


@auth_bp.route("/sair", methods=["POST"])
@login_obrigatorio
def sair():
    """Encerra a sessão atual e remove o token do navegador."""
    registro = Sessao.query.filter_by(token=session.get("sessao_token"), ativa=True).first()
    if registro:
        registro.ativa = False
        registro.encerrada_em = datetime.utcnow()
        db.session.commit()
    session.clear()
    return redirect(url_for("auth.login"))

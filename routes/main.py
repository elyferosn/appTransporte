"""Define as páginas iniciais, o painel administrativo e erros comuns."""

from flask import Blueprint, abort, redirect, render_template, url_for

from routes.access import login_obrigatorio, url_rota_inicial, usuario_atual

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def inicio():
    """Encaminha o usuário ao login ou à página inicial permitida."""
    usuario = usuario_atual()
    return redirect(url_for("auth.login") if not usuario else url_rota_inicial(usuario))


@main_bp.route("/painel")
@login_obrigatorio
def painel():
    """Exibe o painel restrito à conta administradora."""
    if usuario_atual().usuario != "00000000000":
        abort(403)
    return render_template("painel.html")


@main_bp.route("/sem-acesso")
@login_obrigatorio
def sem_acesso():
    """Explica que não há módulos liberados para o usuário."""
    return render_template("sem_acesso.html")


@main_bp.app_errorhandler(403)
def proibido(_erro):
    """Mostra a página de acesso negado."""
    return render_template("erro.html", codigo=403,
                           mensagem="Você não tem permissão para acessar esta página."), 403


@main_bp.app_errorhandler(404)
def nao_encontrado(_erro):
    """Mostra a página para recursos que não existem."""
    return render_template("erro.html", codigo=404,
                           mensagem="A página ou registro solicitado não foi encontrado."), 404

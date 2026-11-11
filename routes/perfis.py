"""Gerencia perfis e os módulos que cada perfil pode acessar."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from models import AcessoPerfil, Perfil, db
from routes.access import acesso
from routes.access import ROTAS_CADASTRO

perfis_bp = Blueprint("perfis", __name__)


def atualizar_campos(perfil):
    """Aplica nome, descrição e lista de módulos ao perfil."""
    perfil.nome = request.form.get("nome", "").strip()
    perfil.descricao = request.form.get("descricao", "").strip()
    rotas_selecionadas = set(request.form.getlist("rotas")) & set(ROTAS_CADASTRO)
    perfil.acessos = [AcessoPerfil(rota=rota) for rota in sorted(rotas_selecionadas)]


@perfis_bp.route("/perfis", methods=["GET", "POST"])
@acesso("pode_gerenciar_perfis")
def listar():
    """Apresenta a tela apropriada para o cadastro solicitado."""
    if request.method == "POST":
        perfil = Perfil()
        atualizar_campos(perfil)
        db.session.add(perfil)
        try:
            db.session.commit()
            flash("Perfil criado.", "sucesso")
        except IntegrityError:
            db.session.rollback()
            flash("Já existe um perfil com esse nome.", "erro")
        return redirect(url_for("perfis.listar"))
    return render_template("perfis.html", perfis=Perfil.query.order_by(Perfil.nome).all(),
                           rotas_cadastro=ROTAS_CADASTRO)


@perfis_bp.route("/perfis/<int:perfil_id>/editar", methods=["GET", "POST"])
@acesso("pode_gerenciar_perfis")
def editar(perfil_id):
    """Abre ou salva as alterações de um registro existente."""
    perfil = db.get_or_404(Perfil, perfil_id)
    if request.method == "POST":
        atualizar_campos(perfil)
        try:
            db.session.commit()
            flash("Perfil atualizado.", "sucesso")
            return redirect(url_for("perfis.listar"))
        except IntegrityError:
            db.session.rollback()
            flash("Já existe um perfil com esse nome.", "erro")
    return render_template("editar_perfil.html", perfil=perfil,
                           rotas_cadastro=ROTAS_CADASTRO,
                           rotas_selecionadas={acesso.rota for acesso in perfil.acessos})

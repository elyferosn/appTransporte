"""Gerencia usuários, credenciais e histórico de sessões."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from models import Perfil, Sessao, Usuario, db
from routes.access import acesso

usuarios_bp = Blueprint("usuarios", __name__)


@usuarios_bp.route("/usuarios")
@acesso("pode_gerenciar_usuarios")
def listar():
    """Lista as contas cadastradas e os perfis disponíveis para atribuição."""
    return render_template("usuarios.html", usuarios=Usuario.query.order_by(Usuario.id).all(),
                           perfis=Perfil.query.order_by(Perfil.nome).all(), usuario_edicao=None)


@usuarios_bp.route("/usuarios/novo", methods=["POST"])
@acesso("pode_gerenciar_usuarios")
def criar():
    """Cria uma conta após validar CPF e tamanho mínimo da senha."""
    cpf = "".join(c for c in request.form.get("usuario", "") if c.isdigit())
    senha = request.form.get("senha", "")
    if len(cpf) != 11 or len(senha) < 8:
        flash("Informe um CPF com 11 dígitos e uma senha com pelo menos 8 caracteres.", "erro")
    else:
        usuario = Usuario(usuario=cpf, nome=request.form.get("nome", "").strip(),
                          senha=generate_password_hash(senha), perfil_id=request.form.get("perfil_id") or None,
                          status=1 if request.form.get("status") == "1" else 0)
        db.session.add(usuario)
        try:
            db.session.commit()
            flash("Usuário criado.", "sucesso")
        except Exception:
            db.session.rollback()
            flash("Não foi possível criar o usuário. Verifique se o CPF já está cadastrado.", "erro")
    return redirect(url_for("usuarios.listar"))


@usuarios_bp.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
@acesso("pode_gerenciar_usuarios")
def editar(usuario_id):
    """Exibe ou salva alterações na conta selecionada."""
    usuario = db.get_or_404(Usuario, usuario_id)
    if usuario.usuario == "00000000000":
        flash("A conta administradora inicial não pode ser alterada aqui.", "erro")
        return redirect(url_for("usuarios.listar"))
    if request.method == "GET":
        return render_template("usuarios.html", usuarios=Usuario.query.order_by(Usuario.id).all(),
                               perfis=Perfil.query.order_by(Perfil.nome).all(), usuario_edicao=usuario)

    senha = request.form.get("senha", "")
    if senha and len(senha) < 8:
        flash("A senha deve ter pelo menos 8 caracteres.", "erro")
        return render_template("usuarios.html", usuarios=Usuario.query.order_by(Usuario.id).all(),
                               perfis=Perfil.query.order_by(Perfil.nome).all(), usuario_edicao=usuario)
    usuario.nome = request.form.get("nome", "").strip()
    usuario.perfil_id = request.form.get("perfil_id") or None
    usuario.status = 1 if request.form.get("status") == "1" else 0
    if senha:
        usuario.senha = generate_password_hash(senha)
    db.session.commit()
    flash("Usuário atualizado.", "sucesso")
    return redirect(url_for("usuarios.listar"))


@usuarios_bp.route("/sessoes")
@acesso("pode_gerenciar_usuarios")
def sessoes():
    """Apresenta o histórico de sessões e seus endereços IP."""
    return render_template("sessoes.html", sessoes=Sessao.query.order_by(Sessao.iniciada_em.desc()).limit(500).all())

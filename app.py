"""Configura a aplicação Flask, registra rotas e aplica proteções globais."""

import hmac
import secrets

from flask import Flask, abort, jsonify, request, session

from config import Config
from database import inicializar_esquema
from models import db
from routes.auth import auth_bp
from routes.dados import dados_bp
from routes.main import main_bp
from routes.perfis import perfis_bp
from routes.usuarios import usuarios_bp


def create_app(config_class=Config):
    """Monta a aplicação e conecta extensões, blueprints e proteções comuns."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    db.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(perfis_bp)
    app.register_blueprint(usuarios_bp)
    app.register_blueprint(dados_bp)

    @app.before_request
    def preparar_esquema():
        """Garante que tabelas e colunas estejam disponíveis antes da primeira requisição."""
        if not app.extensions.get("esquema_inicializado"):
            inicializar_esquema()
            app.extensions["esquema_inicializado"] = True

    @app.context_processor
    def csrf_context():
        """Disponibiliza um token CSRF para os formulários dos templates."""
        def csrf_token():
            """Cria ou reutiliza o token CSRF guardado na sessão do navegador."""
            if "csrf_token" not in session:
                session["csrf_token"] = secrets.token_hex(32)
            return session["csrf_token"]
        return {"csrf_token": csrf_token}

    @app.before_request
    def protect_post_requests():
        """Valida o token CSRF em cada envio de formulário por POST."""
        if request.method == "POST":
            token_sessao = session.get("csrf_token", "")
            token_formulario = request.form.get("csrf_token", "")
            if not token_sessao or not token_formulario or not hmac.compare_digest(token_sessao, token_formulario):
                if request.path == "/dados/chamados/novo-local":
                    return jsonify(sucesso=False, erro="A página expirou. Atualize-a e tente cadastrar o local novamente."), 400
                abort(400, description="Token CSRF inválido ou ausente.")

    return app


app = create_app()

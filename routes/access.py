"""Reúne a leitura da sessão e as regras de autorização por perfil."""

from datetime import datetime, timedelta
from functools import wraps

from flask import abort, jsonify, redirect, request, session, url_for

from models import Sessao, db

ROTAS_CADASTRO = {
    "frotas": "Frotas",
    "motoristas": "Motoristas",
    "cidadaos": "Cidadão",
    "chamados": "Chamados",
    "agendas": "Agendas",
    "agendamentos": "Agendamentos",
}
TEMPO_MAXIMO_INATIVIDADE = timedelta(minutes=30)


def usuario_atual():
    """Resolve a sessão ativa e atualiza o horário da última atividade."""
    token = session.get("sessao_token")
    if not token:
        return None
    registro = Sessao.query.filter_by(token=token, ativa=True).first()
    if not registro:
        session.clear()
        return None
    agora = datetime.utcnow()
    if agora - registro.ultima_atividade >= TEMPO_MAXIMO_INATIVIDADE:
        registro.ativa = False
        registro.encerrada_em = agora
        db.session.commit()
        session.clear()
        return None
    if registro.usuario.status != 1:
        registro.ativa = False
        registro.encerrada_em = agora
        db.session.commit()
        session.clear()
        return None
    registro.ultima_atividade = agora
    db.session.commit()
    return registro.usuario


def login_obrigatorio(view):
    """Impede o acesso à rota quando não existe uma sessão válida."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        """Executa a rota somente após confirmar a autenticação necessária."""
        if not usuario_atual():
            if request.accept_mimetypes.best == "application/json":
                return jsonify(sucesso=False, erro="Sua sessão expirou. Entre novamente e tente salvar o endereço."), 401
            return redirect(url_for("auth.login", proxima=request.path))
        return view(*args, **kwargs)
    return wrapped


def acesso(permissao):
    """Cria um decorador que exige a permissão indicada no perfil."""
    def decorator(view):
        """Aplica a verificação de permissão à rota protegida."""
        @wraps(view)
        @login_obrigatorio
        def wrapped(*args, **kwargs):
            """Executa a rota somente após confirmar a autenticação necessária."""
            usuario = usuario_atual()
            if usuario.usuario == "00000000000":
                return view(*args, **kwargs)
            if not usuario.perfil or not getattr(usuario.perfil, permissao, False):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def pode_acessar_rota(usuario, rota):
    """Informa se o usuário pode abrir o módulo solicitado."""
    if not usuario:
        return False
    if usuario.usuario == "00000000000":
        return True
    return bool(usuario.perfil and any(acesso.rota == rota for acesso in usuario.perfil.acessos))


def url_rota_inicial(usuario):
    """Escolhe a primeira página permitida para o usuário após o login."""
    if usuario and usuario.usuario == "00000000000":
        return url_for("main.painel")
    for rota in ROTAS_CADASTRO:
        if pode_acessar_rota(usuario, rota):
            return url_for("dados.listar", nome_modelo=rota)
    return url_for("main.sem_acesso")


def acesso_rota_cadastro(view):
    """Protege as rotas CRUD conforme o módulo solicitado."""
    @wraps(view)
    @login_obrigatorio
    def wrapped(*args, **kwargs):
        """Executa a rota somente após confirmar a autenticação necessária."""
        usuario = usuario_atual()
        rota = request.view_args.get("nome_modelo") if request.view_args else None
        autorizado = rota in ROTAS_CADASTRO and pode_acessar_rota(usuario, rota)
        if rota not in ROTAS_CADASTRO or not autorizado:
            abort(403)
        return view(*args, **kwargs)
    return wrapped

"""Inicializa os dados básicos e executa o servidor local."""

import subprocess
import sys
import time
from pathlib import Path
from sqlalchemy import text
from werkzeug.security import generate_password_hash
from app import app
from database import inicializar_esquema
from models import Perfil, Usuario, db


def iniciar_postgres():
    """Inicia o serviço do PostgreSQL definido no Compose."""
    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "db"],
            check=True,
            cwd=Path(__file__).resolve().parent,
        )
    except FileNotFoundError:
        sys.exit("Docker não foi encontrado. Instale o Docker e o Compose v2.")
    except subprocess.CalledProcessError:
        # Em instalações Linux em que o socket do Docker exige sudo, repetir
        # o comando permite que o terminal peça a senha normalmente.
        try:
            subprocess.run(
                ["sudo", "docker", "compose", "up", "-d", "db"],
                check=True,
                cwd=Path(__file__).resolve().parent,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            sys.exit(
                "Não foi possível iniciar o PostgreSQL pelo Docker Compose. "
                "Confira se o Compose v2 está instalado e se seu usuário tem "
                "permissão para usar Docker ou sudo."
            )

    prazo = time.monotonic() + 60
    while time.monotonic() < prazo:
        try:
            with app.app_context():
                db.session.execute(text("SELECT 1"))
                db.session.remove()
            print("PostgreSQL está pronto.")
            return
        except Exception:
            with app.app_context():
                db.session.remove()
            time.sleep(1)
    sys.exit("PostgreSQL não ficou pronto em 60 segundos. Confira os logs com: docker compose logs db")


def inicializar_banco():
    """Prepara o esquema e cria a conta administrativa inicial quando necessário."""
    with app.app_context():
        inicializar_esquema()
        perfil = Perfil.query.filter_by(nome="Administrador").first()
        if not perfil:
            perfil = Perfil(nome="Administrador", descricao="Acesso completo ao sistema")
            db.session.add(perfil)
            db.session.commit()
        if not Usuario.query.filter_by(usuario="00000000000").first():
            db.session.add(Usuario(usuario="00000000000", nome="Administrador",
                                   senha=generate_password_hash("pmab350170"),
                                   status=1, perfil=perfil))
            db.session.commit()


if __name__ == "__main__":
    inicializar_banco()
    app.run(debug=app.config.get("DEBUG", False), port=5300,
            host=app.config.get("HOST", "127.0.0.1"))

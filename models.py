"""Define os modelos persistidos usados pelo sistema de transporte."""

from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()


class Usuario(db.Model):
    """Conta usada para autenticar no sistema e receber um perfil de acesso."""

    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(11), unique=True, nullable=False, index=True)
    nome = db.Column(db.String(200), nullable=False, default="Administrador")
    senha = db.Column(db.String(255), nullable=False)
    status = db.Column(db.Integer, nullable=False, default=1)
    perfil_id = db.Column(db.Integer, db.ForeignKey("perfis.id"), nullable=True)
    perfil = db.relationship("Perfil", back_populates="usuarios")
    sessoes = db.relationship("Sessao", back_populates="usuario")


class Perfil(db.Model):
    """Grupo de permissões atribuído aos usuários."""

    __tablename__ = "perfis"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    descricao = db.Column(db.String(255))
    usuarios = db.relationship("Usuario", back_populates="perfil")
    acessos = db.relationship("AcessoPerfil", back_populates="perfil", cascade="all, delete-orphan")


class AcessoPerfil(db.Model):
    """Permissão de acesso a um módulo específico do sistema."""

    __tablename__ = "acessos_perfil"
    __table_args__ = (UniqueConstraint("perfil_id", "rota", name="uq_acesso_perfil_rota"),)

    id = db.Column(db.Integer, primary_key=True)
    perfil_id = db.Column(db.Integer, db.ForeignKey("perfis.id", ondelete="CASCADE"), nullable=False)
    rota = db.Column(db.String(80), nullable=False)
    perfil = db.relationship("Perfil", back_populates="acessos")


class Sessao(db.Model):
    """Registro de login com token, origem de rede e horários de atividade."""

    __tablename__ = "sessoes"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    ip = db.Column(db.String(45), nullable=False)
    user_agent = db.Column(db.String(500))
    iniciada_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ultima_atividade = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    encerrada_em = db.Column(db.DateTime)
    ativa = db.Column(db.Boolean, nullable=False, default=True)
    usuario = db.relationship("Usuario", back_populates="sessoes")


class Frota(db.Model):
    """Veículo disponível para viagens e sua capacidade de passageiros."""

    __tablename__ = "frotas"

    id = db.Column(db.Integer, primary_key=True)
    frota = db.Column(db.Integer, nullable=False)
    marca = db.Column(db.String(200))
    modelo = db.Column(db.String(200))
    lugares = db.Column(db.Integer, default=0)
    ativo = db.Column(db.Integer, default=1)


class Motorista(db.Model):
    """Motorista habilitado para conduzir uma agenda de transporte."""

    __tablename__ = "motoristas"

    id = db.Column(db.Integer, primary_key=True)
    cracha = db.Column(db.Integer, nullable=False)
    nome = db.Column(db.String(200))
    ativo = db.Column(db.Integer, default=1)


class Cidadao(db.Model):
    """Cidadão identificado pelo CPF para fins de agendamento."""

    __tablename__ = "cidadaos"

    id = db.Column(db.Integer, primary_key=True)
    id_esus = db.Column(db.String(200))
    cpf = db.Column(db.String(11), index=True)
    cns = db.Column(db.String(15), index=True)
    nome = db.Column(db.String(200))
    nome_social = db.Column(db.String(200))
    apelido = db.Column(db.String(200))
    data_nascimento = db.Column(db.Date)
    nome_mae = db.Column(db.String(200))
    ativo = db.Column(db.Integer, default=1)

    @property
    def nome_exibicao(self):
        """Nome social preferencial, sem substituir o nome completo cadastrado."""
        return (self.nome_social or "").strip() or (self.nome or "").strip()


class Cidade(db.Model):
    """Cidade ou local selecionável como destino de uma viagem."""

    __tablename__ = "cidades"
    __table_args__ = (UniqueConstraint("codigo_ibge", name="uq_cidades_codigo_ibge"),)

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False, index=True)
    nome_busca = db.Column(db.String(150), index=True)
    uf = db.Column(db.String(2), index=True)
    codigo_ibge = db.Column(db.Integer)
    ativo = db.Column(db.Integer, nullable=False, default=1)


class Chamado(db.Model):
    """Solicitação de transporte com dados do cidadão, destino e saída."""

    __tablename__ = "chamados"

    id = db.Column(db.Integer, primary_key=True)
    cidadao_id = db.Column(db.Integer, db.ForeignKey("cidadaos.id"), nullable=True)
    cidadao_nome = db.Column(db.String(200))
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    local_destino_id = db.Column(db.Integer, db.ForeignKey("locais_destino.id"), nullable=False)
    local_saida_id = db.Column(db.Integer, db.ForeignKey("locais_destino.id"), nullable=False)
    motorista_final = db.Column(db.String(200))
    motorista_final_id = db.Column(db.Integer, db.ForeignKey("motoristas.id"))
    data_hora_final = db.Column(db.DateTime)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    cidadao = db.relationship("Cidadao")
    usuario = db.relationship("Usuario")
    local_destino = db.relationship("LocalDestino", foreign_keys=[local_destino_id])
    local_saida = db.relationship("LocalDestino", foreign_keys=[local_saida_id])
    motorista_final_registro = db.relationship("Motorista", foreign_keys=[motorista_final_id])


class LocalDestino(db.Model):
    """Unidade ou serviço de destino com endereço reutilizável nos agendamentos."""

    __tablename__ = "locais_destino"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False, index=True)
    cidade_id = db.Column(db.Integer, db.ForeignKey("cidades.id"), index=True)
    cep = db.Column(db.String(9))
    cidade = db.Column(db.String(150))
    rua = db.Column(db.String(200))
    bairro = db.Column(db.String(150))
    numero = db.Column(db.String(30))
    referencia = db.Column(db.String(200))
    ativo = db.Column(db.Integer, nullable=False, default=1)
    cidade_registro = db.relationship("Cidade")


class Agenda(db.Model):
    """Viagem com horário, motorista, frota, destino e vagas disponíveis."""

    __tablename__ = "agendas"

    id = db.Column(db.Integer, primary_key=True)
    data_hora = db.Column(db.DateTime, nullable=False)
    motorista_id = db.Column(db.Integer, db.ForeignKey("motoristas.id"), nullable=False)
    frota_id = db.Column(db.Integer, db.ForeignKey("frotas.id"), nullable=False)
    quantidade_vagas = db.Column(db.Integer, nullable=False, default=0)
    cidade = db.Column(db.String(150), nullable=False)
    cidade_destino_id = db.Column(db.Integer, db.ForeignKey("cidades.id"))
    informacao = db.Column(db.String(500))
    motorista = db.relationship("Motorista")
    frota = db.relationship("Frota")
    destino = db.relationship("Cidade")

    @property
    def vagas_disponiveis(self):
        """Calcula quantas vagas restam após os cidadãos ativos agendados."""
        ocupadas = (Agendamento.query.join(Cidadao)
                    .filter(Agendamento.agenda_id == self.id,
                            Agendamento.ativo == 1, Cidadao.ativo == 1).count())
        return max(0, self.quantidade_vagas - ocupadas)


class Agendamento(db.Model):
    """Reserva de uma vaga para um cidadão e seus dados de embarque."""

    __tablename__ = "agendamentos"

    id = db.Column(db.Integer, primary_key=True)
    id_esus = db.Column(db.String(200))
    cpf = db.Column(db.String(11), index=True)
    nome = db.Column(db.String(200))
    ativo = db.Column(db.Integer, default=1)
    agenda_id = db.Column(db.Integer, db.ForeignKey("agendas.id"), nullable=False)
    cidadao_id = db.Column(db.Integer, db.ForeignKey("cidadaos.id"), nullable=False)
    local_saida_id = db.Column(db.Integer, db.ForeignKey("locais_destino.id"))
    endereco_embarque = db.Column(db.String(500), nullable=False)
    cep_embarque = db.Column(db.String(9))
    cidade_embarque = db.Column(db.String(150))
    rua_embarque = db.Column(db.String(200))
    bairro_embarque = db.Column(db.String(150))
    numero_embarque = db.Column(db.String(30))
    referencia_embarque = db.Column(db.String(200))
    telefone_contato = db.Column(db.String(30))
    observacao = db.Column(db.String(500))
    local_destino = db.Column(db.String(150), nullable=False)
    local_destino_id = db.Column(db.Integer, db.ForeignKey("locais_destino.id"))
    destino_cep = db.Column(db.String(9))
    destino_cidade = db.Column(db.String(150))
    destino_rua = db.Column(db.String(200))
    destino_bairro = db.Column(db.String(150))
    destino_numero = db.Column(db.String(30))
    destino_referencia = db.Column(db.String(200))
    agenda = db.relationship("Agenda")
    cidadao = db.relationship("Cidadao")
    local_saida_registro = db.relationship("LocalDestino", foreign_keys=[local_saida_id])
    local_destino_registro = db.relationship("LocalDestino", foreign_keys=[local_destino_id])


class AuditoriaFrota(db.Model):
    """Histórico de inclusões e alterações de veículos da frota."""

    __tablename__ = "auditoria_frotas"

    id = db.Column(db.Integer, primary_key=True)
    frota_id = db.Column(db.Integer, nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    sessao_id = db.Column(db.Integer, db.ForeignKey("sessoes.id"), nullable=False)
    acao = db.Column(db.String(20), nullable=False)
    data_hora = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class AuditoriaMotorista(db.Model):
    """Histórico de inclusões e alterações de motoristas."""

    __tablename__ = "auditoria_motoristas"

    id = db.Column(db.Integer, primary_key=True)
    motorista_id = db.Column(db.Integer, nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    sessao_id = db.Column(db.Integer, db.ForeignKey("sessoes.id"), nullable=False)
    acao = db.Column(db.String(20), nullable=False)
    data_hora = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class AuditoriaCidadao(db.Model):
    """Histórico de inclusões e alterações de cidadãos."""

    __tablename__ = "auditoria_cidadaos"

    id = db.Column(db.Integer, primary_key=True)
    cidadao_id = db.Column(db.Integer, nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    sessao_id = db.Column(db.Integer, db.ForeignKey("sessoes.id"), nullable=False)
    acao = db.Column(db.String(20), nullable=False)
    data_hora = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class AuditoriaAgenda(db.Model):
    """Histórico de inclusões e alterações de agendas."""

    __tablename__ = "auditoria_agendas"

    id = db.Column(db.Integer, primary_key=True)
    agenda_id = db.Column(db.Integer, nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    sessao_id = db.Column(db.Integer, db.ForeignKey("sessoes.id"), nullable=False)
    acao = db.Column(db.String(20), nullable=False)
    data_hora = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class AuditoriaAgendamento(db.Model):
    """Histórico de inclusões e alterações de agendamentos."""

    __tablename__ = "auditoria_agendamentos"

    id = db.Column(db.Integer, primary_key=True)
    agendamento_id = db.Column(db.Integer, nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    sessao_id = db.Column(db.Integer, db.ForeignKey("sessoes.id"), nullable=False)
    acao = db.Column(db.String(20), nullable=False)
    data_hora = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

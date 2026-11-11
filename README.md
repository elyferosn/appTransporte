# Sistema de Gestão de Transporte

Aplicação Flask com cadastro de frotas, motoristas, cidadãos, agendas e agendamentos, além de usuários, perfis de acesso e histórico de sessões.

## Executar no Windows com PostgreSQL local

A instalacao migrada usa `127.0.0.1:5432/app_transporte`, com a conta dedicada `app_transporte_local`. O arquivo `.env` local guarda a conexao e a chave de sessao; nao o versione nem substitua por configuracoes antigas do Docker.

Na pasta deste README, execute:

```powershell
.\iniciar_windows.cmd
```

Abra `http://127.0.0.1:5300`. O comando usa o Python de `.venv` e carrega explicitamente o `.env` do projeto. O servidor inicia sem debug e escuta apenas a maquina local. Feche com `Ctrl+C`. Os logins e hashes de senha importados foram preservados.

O SQLite original e os backups ficaram preservados. A partir da troca, as novas gravacoes devem ocorrer no PostgreSQL; reabrir o SQLite antigo nao recupera alteracoes posteriores. O plano de retorno e os relatorios ficam na pasta superior do projeto.

## Configuracao inicial com Docker (opcional)

As instrucoes abaixo descrevem outra forma de instalar. Na instalacao ja migrada, mantenha a configuracao Docker separada do `.env` definitivo e use uma porta diferente da 5432 ocupada pelo PostgreSQL local.

```bash
cp .env.example .env
# Gere uma senha hexadecimal com: openssl rand -hex 24
# Edite .env e substitua POSTGRES_PASSWORD pela senha gerada.
docker compose up -d

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
set -a
. ./.env
set +a
export DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}"
python run.py
```

O Compose mantém os dados em um volume persistente do Docker. `docker compose down` para o container sem apagar esse volume. A porta fica acessível somente pela própria máquina.

### Levar os dados para outra máquina

Instale Docker e Docker Compose na outra máquina e copie `compose.yaml` e o `.env` por um canal seguro. Para copiar também os registros do banco, gere um backup na máquina de origem:

```bash
docker compose exec -T db pg_dump -U app_transporte -d app_transporte -Fc > app_transporte.dump
```

Na máquina de destino, inicie o PostgreSQL com `docker compose up -d`, copie `app_transporte.dump` e restaure:

```bash
docker compose exec -T db pg_restore -U app_transporte -d app_transporte --clean --if-exists --no-owner < app_transporte.dump
```

O `.env` contém a senha e não deve ser compartilhado em repositórios. Se a senha tiver caracteres especiais, use uma senha codificada para URL em `DATABASE_URL` ou uma senha hexadecimal para simplificar a conexão da aplicação.

Na primeira execução, o sistema cria as tabelas no PostgreSQL configurado, o perfil Administrador e o usuário inicial:

- CPF: `00000000000`
- Senha: `pmab350170`

As senhas são armazenadas com hash. A senha inicial deve ser trocada antes de disponibilizar o sistema. A conta inicial é protegida contra edição pela tela de usuários.

## Configuração

Configure `DATABASE_URL` com a conexão do PostgreSQL antes de iniciar o sistema. O padrão local é `postgresql+psycopg://localhost/app_transporte`; crie esse banco no PostgreSQL ou informe uma URL com usuário, senha e servidor. Exemplo:

```bash
export DATABASE_URL="postgresql+psycopg://usuario:senha@localhost:5432/app_transporte"
```

O sistema não copia automaticamente os dados do antigo arquivo SQLite `instance/banco.db`; essa transferência precisa ser feita separadamente antes de usar o PostgreSQL com os dados existentes.

Defina `SECRET_KEY` com um valor longo e aleatório no ambiente em que o sistema será executado. A chave de reserva é gerada ao iniciar o processo, portanto sessões autenticadas são invalidadas quando a aplicação reinicia sem essa variável configurada.

As permissões de cadastro são atribuídas por perfil e por módulo (frotas, motoristas, cidadãos, agendas e agendamentos). As rotas administrativas de perfis e usuários não são concedidas por essa lista; ficam restritas à conta administradora inicial. O perfil Administrador inicial tem acesso a todos os cadastros. Agendas guardam data e hora, motorista, frota, quantidade de vagas, cidade/local de destino e informação adicional. Agendamentos vinculam cidadão e agenda, registram o local de destino e o endereço de embarque, mostram a disponibilidade e impedem duplicidade e lotação excedida. Na inicialização, a aplicação acrescenta ao banco os campos necessários para essas associações. O CEP pode preencher o endereço por meio do ViaCEP; o endereço também pode ser digitado manualmente. A tabela de sessões registra IP, navegador, início, última atividade e encerramento. A lista de histórico mostra as 500 sessões mais recentes.


## Ficha do motorista

Ao cadastrar ou editar um chamado ou agendamento, a confirmação oferece **Imprimir ficha**. A listagem dos dois cadastros oferece a mesma ação para reimpressão. A ficha abre em uma página própria; o operador aciona a impressão no navegador, em A4.

O acesso usa a mesma permissão de consulta do cadastro. A ficha apresenta somente número, nome, endereços e referências; no agendamento, inclui telefone e horário da agenda, identificado como **saída da viagem**. CPF, CNS, dados de filiação, `observacao` e `Agenda.informacao` não entram na ficha. Os dois últimos são textos livres que podem conter informações clínicas.

O modelo atual não tem telefone/horário previsto em chamados nem campos próprios de horário de atendimento, retorno, cadeira de rodas ou acompanhante. Esses dados não são inventados nem extraídos de observações clínicas. A finalização do chamado não é tratada como previsão de saída.

As viagens já agrupam passageiros por `Agendamento.agenda_id`; `Agenda` vincula horário, motorista e frota. A impressão atual é individual por agendamento. Uma folha única por saída pode ser avaliada sobre esse agrupamento em uma etapa própria.

## Nome social e apelido

O cadastro de cidadãos mantém o nome completo e oferece **Nome social** e **Apelido** como campos opcionais separados. Listagens, seleção de passageiros e fichas usam o nome social quando preenchido; caso contrário, usam o nome completo. O apelido aparece identificado como informação complementar. Os três nomes podem ser usados na busca. Limpar o nome social restaura a exibição do nome completo sem apagar o apelido.

Em bancos existentes, aplique a migração antes de reiniciar esta versão:

```powershell
.\.venv\Scripts\python.exe .\migracao_nomes.py --aplicar
```

O script pede no terminal uma conta PostgreSQL com permissão de alterar a tabela, sem salvar a senha. A conta dedicada de execução continua sem privilégios administrativos. A migração adiciona somente `nome_social VARCHAR(200)` e `apelido VARCHAR(200)`, ambos opcionais, reaproveita colunas compatíveis e não sobrescreve os cadastros. Sem `--aplicar`, o comando apenas confere o esquema.

Em restaurações de backups antigos no outro computador, execute essa migração com o proprietário do banco antes de ativar o Waitress com a conta dedicada. Nenhuma mudança exige commit ou push para ser usada localmente.

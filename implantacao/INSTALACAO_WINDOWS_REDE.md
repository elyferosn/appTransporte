# Instalacao em outro Windows 11, PostgreSQL local e rede interna

Estado: pacote preparado e Waitress testado na origem; destino, rede, DNS e certificado ainda nao informados. Nenhuma instalacao remota, mudanca de firewall, tarefa automatica ou reinicio foi realizado. Nao liberar gravacoes no destino antes da validacao e do corte final.

## Arquitetura

Teste inicial de conectividade: cliente -> HTTP 5300 -> Waitress. Nao enviar senhas pelo HTTP no validador automatizado.

Uso diario: cliente -> HTTPS 443 -> Caddy com certificado confiavel -> Waitress em 127.0.0.1:5300 -> PostgreSQL em 127.0.0.1:PORTA. Somente 443 fica liberada para o CIDR interno autorizado; 5300 permanece local no modo HTTPS. Nao criar regra de entrada para PostgreSQL e nao alterar seus outros bancos, pg_hba.conf ou listen_addresses de forma global.

O certificado deve conter o nome DNS do servico e ter cadeia confiavel nos computadores clientes (CA da organizacao, por exemplo). Instalar a CA confiavel via TI se necessario; nao desabilitar a verificacao TLS nem aceitar avisos como validacao. O certificado/chave privados ficam fora do pacote. O Caddy usa TLS explicito, sem solicitar certificados externos automaticamente.

Waitress funciona no Windows e aceita proxy confiavel explicitamente configurado: [documentacao](https://docs.pylonsproject.org/projects/waitress/en/stable/index.html), [proxy](https://docs.pylonsproject.org/projects/waitress/en/stable/reverse-proxy.html). A tarefa usa LocalService/ServiceAccount, sem login interativo: [Microsoft](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal). Caddy documenta execucao persistente no Windows: [documentacao](https://caddyserver.com/docs/running).

## O que transferir

1. ZIP de codigo, com requirements-windows.lock.txt; sem .env, venv, SQLite, CSV de cidadaos, backups ou logs.
2. Por canal protegido separado: diretorio do backup, contendo app_transporte.dump e manifesto.json. O dump contem os dados de cidadaos e hashes de senha. Verificar SHA-256 apos a transferencia.
3. Configuracao e credenciais novas sao geradas no destino. Nao transportar a conta administrativa ou a senha do PostgreSQL da origem. SECRET_KEY nova invalida cookies anteriores; todos fazem login novamente.
4. Nenhum anexo/upload foi encontrado no codigo. O catalogo municipios_ibge.json, templates e static acompanham o pacote. O CSV antigo e o SQLite sao material historico, nao dependencias de execucao; permanecem preservados na origem. No destino, preservar tambem configuracao, certificados/chave e backups. Logs servem para diagnostico.

## Preparar o destino (PowerShell elevado)

Substituir todos os caminhos, a porta, o DNS e a rede pelos valores realmente conferidos. Os exemplos nao sao valores descobertos do destino.

Instalar Python 3.14 para todos os usuarios, fora de perfis pessoais, e usar PostgreSQL 18.x (mesma versao principal da origem). Conferir binarios, servico e porta sem alterar outros projetos:

```powershell
Get-Service '*postgres*'
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' --version
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -h 127.0.0.1 -p 5432 -U postgres -d postgres -W -c 'SELECT version(), host(inet_server_addr()), inet_server_port(), current_database(), current_user;'
Expand-Archive -LiteralPath 'D:\Transferencia\app_transporte_windows.zip' -DestinationPath 'C:\ProgramData\AppTransporte\app'
Set-Location 'C:\ProgramData\AppTransporte\app'
.\implantacao\preparar_python.ps1 -PythonExe 'C:\Program Files\Python314\python.exe'
```

A pasta de destino e o ambiente virtual devem ser novos. Nao copiar o .venv da origem; ele referencia o Python instalado naquela maquina. O caminho do Python para todos os usuarios pode ser diferente do exemplo.

Para instalar sem internet, extrair tambem o pacote separado de wheels Windows x64/Python 3.14 e acrescentar `-Wheelhouse 'D:\Transferencia\wheels_windows_py314'` ao preparar_python.ps1. Esses wheels sao para a mesma arquitetura/versao de Python da origem, nao para ARM64 ou outra versao de Python. Python e PostgreSQL ja devem estar instalados no destino; seus instaladores nao acompanham o pacote.

Restaurar primeiro em banco de validacao NOVO:

```powershell
.\.venv\Scripts\python.exe .\implantacao\restaurar_destino.py --postgres-bin 'C:\Program Files\PostgreSQL\18\bin' --porta 5432 --backup 'D:\BackupsProtegidos\preparacao' --banco app_transporte_validacao --papel app_transporte_runtime --config-saida 'C:\ProgramData\AppTransporte\segredos\validacao.env'
```

O script pede a senha administrativa no terminal, recusa banco/configuracao existentes, verifica hash, restaura em transacao, confere todas as tabelas e valores contra o manifesto e verifica sequencias/restricoes. Gera papel dedicado sem privilegios administrativos e arquivo de segredo com ACL para administradores, SYSTEM e leitura de LocalService. Nao ativa automaticamente o aplicativo. Se houver erro, preserva os objetos isolados para diagnostico; nao apaga banco de outros projetos nem tenta limpar um banco existente.

## HTTPS e inicializacao sem usuario conectado

Definir IPv4 fixo ou reserva DHCP, DNS interno e CIDR dos clientes autorizados. Colocar binario oficial Caddy, cadeia PEM e chave PEM sob ProgramData\AppTransporte, separados do ZIP. Exemplo:

```powershell
.\implantacao\instalar_inicializacao.ps1 -EnvFile 'C:\ProgramData\AppTransporte\segredos\validacao.env' -AllowedSubnet '192.168.1.0/24' -ServerIPAddress '192.168.1.10' -DnsName 'transporte.exemplo.interno' -Mode Https -CaddyExe 'C:\ProgramData\AppTransporte\ferramentas\caddy.exe' -CertificatePem 'C:\ProgramData\AppTransporte\certificados\fullchain.pem' -PrivateKeyPem 'C:\ProgramData\AppTransporte\certificados\key.pem'
```

O script cria tarefas AppTransporte-WSGI e AppTransporte-HTTPS, disparadas no boot sob LocalService, com reinicio em falha. Nao precisam de usuario conectado. Waitress aguarda o PostgreSQL por ate 120 segundos e inicializa o esquema uma vez antes das threads. O banco permanece em loopback.

A regra de firewall usa somente IP do servidor, TCP 443, CIDR informado e perfis Domain/Private. O script recusa tarefas/regras existentes, portas ocupadas e regras de permissao que possam ampliar o acesso. Nao altera regras de outros projetos. Conferir o perfil de rede com Get-NetConnectionProfile; nao mudar uma rede publica para privada sem verificar que seja a rede interna.

Se for indispensavel teste HTTP inicial, usar -Mode HttpTest, liberar apenas 5300/CIDR e fazer somente o teste de conectividade sem credenciais. Antes da instalacao HTTPS, encerrar e remover SOMENTE a tarefa AppTransporte-WSGI e a regra AppTransporte-HTTP-Teste-LAN criadas para o teste; nao apagar regras genericas. Instalar em seguida o modo HTTPS. O modo HTTP nao e a configuracao diaria.

## Validacao de outro computador

O cliente precisa somente de navegador; o validador opcional usa Python padrao, sem instalar dependencias. Confiar primeiro na CA do certificado. Executar em outro computador da rede:

```powershell
python .\validar_cliente.py --url 'https://transporte.exemplo.interno' --saida '.\validacao_antes_reinicio.json'
```

O script verifica TLS normalmente, solicita a senha master no terminal e um CPF de consulta sem mostra-los, abre um agendamento pelo ID informado e cria/inativa um motorista sintetico. O nome sintetico e o ID sao registrados para identificacao; a exclusao do aplicativo e logica/auditada, portanto esse teste acrescenta um motorista inativo, auditorias e uma sessao encerrada ao banco de validacao. Esses registros NAO vao ao destino final, pois a carga final sera feita em outro banco novo. Nao os confundir com alteracoes inesperadas da carga.

Reiniciar o computador de destino na janela combinada e repetir o acesso a partir do mesmo cliente, sem fazer login no Windows do servidor. Conferir tarefas/logs e repetir o validador com outra saida. O reinicio pode afetar outros sistemas da maquina: combinar a janela antes. Essa etapa e o acesso remoto ainda nao foram executados neste trabalho, pois o destino nao foi informado.

## Corte final sem duas origens de gravacao

1. Combinar a janela. Parar o aplicativo/tarefas de gravacao na origem, confirmar com todos os operadores e impedir reinicio automatico ali. Nao modificar outros servicos da maquina.
2. Gerar backup atualizado na origem, com novo diretorio. O sinalizador registra a confirmacao de pausa, mas nao para processos automaticamente:

```powershell
.\.venv\Scripts\python.exe .\implantacao\backup_origem.py --postgres-bin 'C:\PostgreData\PostgreSQL\18\bin' --saida 'D:\BackupsProtegidos\corte_final_YYYYMMDD_HHMM' --final-com-gravacoes-pausadas
```

3. Transferir dump + manifesto por canal protegido, separados do codigo. Restaurar no destino em OUTRO banco exclusivo, por exemplo app_transporte_final_YYYYMMDD, e configuracao final.env nova. Reutilizar a conta dedicada existente sem rotaciona-la com --config-papel-existente apontando para validacao.env. Nao usar pg_restore --clean no banco de validacao nem em banco de outro projeto.
4. Com clientes ainda bloqueados no destino, conferir o relatorio de restauro, tabelas, dados e sequencias. Trocar SOMENTE a tarefa do aplicativo para o novo ambiente:

```powershell
.\implantacao\trocar_configuracao.ps1 -NewEnvFile 'C:\ProgramData\AppTransporte\segredos\final.env'
```

5. Validar HTTPS, login master, consulta e agendamento no banco definitivo. A primeira carga/contagem deve coincidir integralmente com o manifesto; se repetir a gravacao sintetica no definitivo, documentar o delta conhecido (motorista inativo, auditorias e sessao), sem excluir dados reais.
6. Confirmar que a origem continua parada e que todos os clientes usam o DNS/IP novo. Somente entao liberar gravacoes no destino. Impedir reinicio do launcher antigo; se necessario, o administrador pode desabilitar o LOGIN do papel exclusivo da origem e encerrar apenas suas conexoes, apos verificar que ele nao e compartilhado por outros projetos. Isso nao deve ser aplicado automaticamente a papéis genericos.
7. Preservar origem, banco de validacao, backups e configuracoes anteriores. Depois de gravacoes novas, nao retornar simplesmente a origem antiga: pausar o destino, preservar backup atualizado e transportar o estado completo, incluindo alteracoes e exclusoes, antes de reabrir outro servidor.

## Operacao

Verificar tarefas com Get-ScheduledTask -TaskName 'AppTransporte-*' e logs em app\logs. Manter backup PostgreSQL recorrente, copia protegida fora da maquina e teste de restauracao. Renovar o certificado antes do vencimento e monitorar falhas de tarefa/banco. Nenhum dado pessoal ou senha deve ser incluido em tickets ou relatorios de suporte.

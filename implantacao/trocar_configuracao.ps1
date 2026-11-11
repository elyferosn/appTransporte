# Executar elevado no DESTINO, com ambos os aplicativos fechados para usuarios.
param([Parameter(Mandatory=$true)][string]$NewEnvFile)
$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $project '.venv\Scripts\python.exe'
$nextEnv = (Resolve-Path -LiteralPath $NewEnvFile).Path
$report = Join-Path ([IO.Path]::GetDirectoryName($nextEnv)) 'troca_configuracao.json'
$task = Get-ScheduledTask -TaskName 'AppTransporte-WSGI' -ErrorAction Stop
$oldArguments = $task.Actions[0].Arguments
$match = [regex]::Match($oldArguments,'--env-file "([^"]+)"')
if (-not $match.Success) { throw 'Tarefa existente nao corresponde ao launcher esperado; preservada' }
$oldEnv = $match.Groups[1].Value
if ($nextEnv -eq $oldEnv) { throw 'Escolha um arquivo novo para permitir retorno da configuracao' }
# Valida a conexao e aproveita somente os parametros de rede da configuracao anterior.
& $python -c "from dotenv import dotenv_values,set_key;from sqlalchemy.engine import make_url;import psycopg,sys;a=dotenv_values(sys.argv[1]);b=dotenv_values(sys.argv[2]);u=make_url(b['DATABASE_URL']);assert u.host=='127.0.0.1' and u.drivername=='postgresql+psycopg';c=psycopg.connect(host=u.host,port=u.port,dbname=u.database,user=u.username,password=u.password,connect_timeout=5);c.close();[set_key(sys.argv[2],k,a[k]) for k in ['APP_NETWORK_MODE','APP_ALLOWED_HOSTS','APP_PORT']];" $oldEnv $nextEnv
if ($LASTEXITCODE -ne 0) { throw 'Nova configuracao nao validada; tarefa preservada' }
Stop-ScheduledTask -TaskName 'AppTransporte-WSGI'
$deadline = (Get-Date).AddSeconds(30)
while ((Get-ScheduledTask -TaskName 'AppTransporte-WSGI').State -eq 'Running') {
    if ((Get-Date) -gt $deadline) { throw 'Tarefa nao encerrou; troca cancelada' }
    Start-Sleep -Milliseconds 500
}
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + (Join-Path $project 'wsgi_windows.py') + '" --env-file "' + $nextEnv + '"') -WorkingDirectory $project
Set-ScheduledTask -TaskName 'AppTransporte-WSGI' -Action $action | Out-Null
Start-ScheduledTask -TaskName 'AppTransporte-WSGI'
@{previous_env=$oldEnv;new_env=$nextEnv;validation_required_before_release=$true} | ConvertTo-Json | Set-Content -LiteralPath $report -Encoding UTF8
Write-Host 'Tarefa apontada para novo ambiente; mantenha usuarios bloqueados ate validacao HTTPS e dados.'

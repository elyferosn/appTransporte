# Executar elevado SOMENTE no destino, apos restauro e validacao.
param(
    [Parameter(Mandatory=$true)][string]$EnvFile,
    [Parameter(Mandatory=$true)][string]$AllowedSubnet,
    [Parameter(Mandatory=$true)][string]$ServerIPAddress,
    [Parameter(Mandatory=$true)][string]$DnsName,
    [ValidateSet('HttpTest','Https')][string]$Mode = 'Https',
    [string]$CaddyExe,
    [string]$CertificatePem,
    [string]$PrivateKeyPem
)
$ErrorActionPreference = 'Stop'
$principalCheck = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principalCheck.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Execute como administrador no destino.' }
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$baseDirectory = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'AppTransporte'
$envPath = (Resolve-Path -LiteralPath $EnvFile).Path
foreach ($item in @($project,$envPath)) {
    if (-not $item.StartsWith($baseDirectory + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Instale em ProgramData\AppTransporte; codigo e segredos fora de perfis pessoais.' }
}
if ($DnsName -notmatch '^[a-zA-Z0-9][a-zA-Z0-9.-]*[a-zA-Z0-9]$') { throw 'Nome DNS invalido' }
if ($ServerIPAddress -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { throw 'Informe o IPv4 fixo/reservado do servidor' }
$python = Join-Path $project '.venv\Scripts\python.exe'
& $python -c "import ipaddress,sys;n=ipaddress.ip_network(sys.argv[1],strict=False);assert n.version==4 and n.prefixlen>0;assert ipaddress.ip_address(sys.argv[2]).version==4" $AllowedSubnet $ServerIPAddress
if ($LASTEXITCODE -ne 0) { throw 'Faixa de rede ou IP do servidor invalidos' }
$taskName = 'AppTransporte-WSGI'
$proxyTask = 'AppTransporte-HTTPS'
$ruleName = if ($Mode -eq 'Https') { 'AppTransporte-HTTPS-LAN' } else { 'AppTransporte-HTTP-Teste-LAN' }
foreach ($task in @($taskName,$proxyTask)) {
    if (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) { throw "Tarefa $task ja existe; preservada. Para alterar a instalacao use uma janela de manutencao." }
}
foreach ($rule in @('AppTransporte-HTTPS-LAN','AppTransporte-HTTP-Teste-LAN')) {
    if (Get-NetFirewallRule -Name $rule -ErrorAction SilentlyContinue) { throw "Regra $rule ja existe; preservada. Revise antes de continuar." }
}
$selectedPort = if ($Mode -eq 'Https') { 443 } else { 5300 }
$busy = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 5300 -or ($Mode -eq 'Https' -and $_.LocalPort -eq 443 -and $_.LocalAddress -in @($ServerIPAddress,'0.0.0.0','::')) }
if ($busy) { throw 'Porta do aplicativo/proxy ocupada; nenhum processo existente sera encerrado.' }
# Uma regra nova restrita nao anula permissoes amplas ja existentes.
foreach ($existingRule in (Get-NetFirewallRule -Enabled True -Direction Inbound -Action Allow)) {
    $appFilter = $existingRule | Get-NetFirewallApplicationFilter
    $serviceFilter = $existingRule | Get-NetFirewallServiceFilter
    $program = [Environment]::ExpandEnvironmentVariables($appFilter.Program)
    if ($program -ne 'Any' -and $program -ne $python -and $program -ne $CaddyExe) { continue }
    if ($serviceFilter.Service -ne 'Any') { continue }
    $portFilter = $existingRule | Get-NetFirewallPortFilter
    if ($portFilter.Protocol -notin @('TCP','6','Any','256')) { continue }
    foreach ($localPort in $portFilter.LocalPort) {
        $coversPort = $localPort -eq 'Any' -or $localPort -eq [string]$selectedPort -or ($Mode -eq 'Https' -and $localPort -eq '5300')
        if ($localPort -match '^(\d+)-(\d+)$') { $coversPort = $selectedPort -ge [int]$Matches[1] -and $selectedPort -le [int]$Matches[2] }
        if ($coversPort) { throw "Regra existente pode ampliar o acesso ($($existingRule.Name)); revise-a sem alterar regras de outros projetos." }
    }
}
$logs = Join-Path $project 'logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
& icacls $project /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-19:(OI)(CI)RX' /T /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Falha ao proteger codigo/ambiente virtual' }
& icacls $logs /grant:r '*S-1-5-19:(OI)(CI)M' /T /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Falha ao permitir logs para LocalService' }
& icacls $envPath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' '*S-1-5-19:R' /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Falha ao proteger configuracao' }
$networkMode = if ($Mode -eq 'Https') { 'https' } else { 'http-test' }
$allowedHosts = "$DnsName,$ServerIPAddress,localhost,127.0.0.1"
& $python -c "from dotenv import set_key;import sys;set_key(sys.argv[1],'APP_NETWORK_MODE',sys.argv[2]);set_key(sys.argv[1],'APP_ALLOWED_HOSTS',sys.argv[3]);set_key(sys.argv[1],'APP_PORT','5300')" $envPath $networkMode $allowedHosts
if ($LASTEXITCODE -ne 0) { throw 'Falha ao configurar modo de rede' }
$caddyConfig = Join-Path $baseDirectory 'Caddyfile'
if ($Mode -eq 'Https') {
    foreach ($path in @($CaddyExe,$CertificatePem,$PrivateKeyPem)) {
        if (-not $path -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'HTTPS exige Caddy oficial, certificado PEM e chave PEM locais.' }
        if (-not ([IO.Path]::GetFullPath($path)).StartsWith($baseDirectory + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Guarde Caddy/certificados dentro de ProgramData\AppTransporte.' }
    }
    if (Test-Path -LiteralPath $caddyConfig) { throw 'Caddyfile ja existe; preservado' }
    foreach ($path in @($CaddyExe,$CertificatePem,$PrivateKeyPem)) {
        & icacls $path /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' '*S-1-5-19:RX' /Q | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao ajustar acesso aos arquivos HTTPS' }
    }
    $certPath = $CertificatePem.Replace('\','/')
    $keyPath = $PrivateKeyPem.Replace('\','/')
    @"
{
    admin off
    auto_https off
}
https://$DnsName {
    bind $ServerIPAddress
    tls "$certPath" "$keyPath"
    reverse_proxy 127.0.0.1:5300
}
"@ | Set-Content -LiteralPath $caddyConfig -Encoding ASCII
    & $CaddyExe validate --config $caddyConfig --adapter caddyfile
    if ($LASTEXITCODE -ne 0) { throw 'Configuracao/certificados HTTPS nao validados; tarefas nao criadas' }
}
$principal = New-ScheduledTaskPrincipal -UserId 'S-1-5-19' -LogonType ServiceAccount -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + (Join-Path $project 'wsgi_windows.py') + '" --env-file "' + $envPath + '"') -WorkingDirectory $project
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'App Transporte: Waitress sem login interativo' | Out-Null
if ($Mode -eq 'Https') {
    $proxyAction = New-ScheduledTaskAction -Execute $CaddyExe -Argument ('run --config "' + $caddyConfig + '" --adapter caddyfile') -WorkingDirectory $baseDirectory
    Register-ScheduledTask -TaskName $proxyTask -Action $proxyAction -Trigger $trigger -Principal $principal -Settings $settings -Description 'App Transporte: proxy HTTPS interno' | Out-Null
}
$port = if ($Mode -eq 'Https') { 443 } else { 5300 }
New-NetFirewallRule -Name $ruleName -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -LocalAddress $ServerIPAddress -RemoteAddress $AllowedSubnet -Profile Domain,Private | Out-Null
Start-ScheduledTask -TaskName $taskName
if ($Mode -eq 'Https') { Start-ScheduledTask -TaskName $proxyTask }
Write-Host "Tarefas criadas sem login; porta $port liberada somente para $AllowedSubnet em perfis Domain/Private. Nenhuma regra de PostgreSQL foi criada."
Write-Host 'Valide de outro computador e apos reiniciar antes da liberacao operacional.'

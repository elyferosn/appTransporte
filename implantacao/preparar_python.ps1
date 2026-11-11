param(
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [string]$Wheelhouse
)
$ErrorActionPreference = 'Stop'
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($PythonExe -match '\\Users\\') { throw 'Use Python instalado para todos os usuarios, fora de perfis pessoais, para a tarefa sem login.' }
if (Test-Path -LiteralPath (Join-Path $project '.venv')) { throw 'Ambiente virtual ja existe; preservado. Instale o pacote em uma pasta nova.' }
& $PythonExe -m venv (Join-Path $project '.venv')
if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar ambiente virtual' }
$venvPython = Join-Path $project '.venv\Scripts\python.exe'
if ($Wheelhouse) {
    $wheelPath = (Resolve-Path -LiteralPath $Wheelhouse).Path
    & $venvPython -m pip install --no-index --find-links $wheelPath -r (Join-Path $project 'requirements-windows.lock.txt')
} else {
    & $venvPython -m pip install -r (Join-Path $project 'requirements-windows.lock.txt')
}
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependencias' }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependencias inconsistentes' }
Write-Host 'Ambiente virtual novo preparado; nenhum banco ou firewall foi alterado.'

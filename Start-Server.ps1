param([switch]$Configure, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$taskConfig = Join-Path $PSScriptRoot 'config\server.json'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
    throw 'TRELLIS Python is missing. Run Windows Setup in Server mode first.'
}
if ($Configure) {
    & (Join-Path $PSScriptRoot 'installer\windows\Configure-Server.ps1') -ConfigPath $taskConfig -Python $taskPython
}
& (Join-Path $PSScriptRoot 'installer\windows\Server-Control.ps1') -Action Start -NoBrowser:$NoBrowser

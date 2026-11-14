$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'installer\windows\Server-Control.ps1') -Action Stop

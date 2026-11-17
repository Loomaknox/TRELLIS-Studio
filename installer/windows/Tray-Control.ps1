param(
    [ValidateSet('desktop','server')][string]$Mode='desktop',
    [ValidateSet('Start','Stop','Status','Configure','TestHttps')][string]$Action='Status'
)
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (Test-Path -LiteralPath (Join-Path $taskRoot '.trellis-setup-test')) {
    $env:TRELLIS_PORT='7890'
    $env:TRELLIS_MCP_PORT='7891'
}
$installed=Test-Path -LiteralPath (Join-Path $taskRoot 'bundled-web.json')
if (-not $env:TRELLIS_PORT) { $env:TRELLIS_PORT=$(if ($installed) { '7870' } else { '7860' }) }
if (-not $env:TRELLIS_MCP_PORT) { $env:TRELLIS_MCP_PORT=$(if ($installed) { '7871' } else { '7861' }) }
if ($Mode -eq 'server') {
    if ($Action -eq 'Configure') {
        & (Join-Path $PSScriptRoot 'Configure-Server.ps1') -ConfigPath (Join-Path $taskRoot 'config\server.json') -Python (Join-Path $taskRoot '.venv\Scripts\python.exe')
    } else { & (Join-Path $PSScriptRoot 'Server-Control.ps1') -Action $Action -NoBrowser }
    return
}
if ($Action -eq 'Start') {
    try { $componentLock=[IO.File]::Open((Join-Path $taskRoot '.component-install.lock'),'OpenOrCreate','ReadWrite','None') }
    catch [IO.IOException] { throw 'Another TRELLIS startup or installation is running. Wait for it to finish.' }
    try { & (Join-Path $taskRoot 'Start-Studio.ps1') -SansNavigateur }
    finally { $componentLock.Dispose() }
    return
}
if ($Action -eq 'Stop') { & (Join-Path $taskRoot 'Arreter-TRELLIS.ps1') -WithBridge -IdleOnly; return }
if ($Action -eq 'Configure') { throw 'Choose Server mode to configure network access.' }
if ($Action -eq 'TestHttps') { throw 'Choose Server Internet mode to check HTTPS.' }
$port=[int]$env:TRELLIS_PORT
$url='http://127.0.0.1:'+$port
try {
    $listeners=@(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
    if (-not $listeners.Count) {
        $bridge=@(Get-NetTCPConnection -State Listen -LocalPort ([int]$env:TRELLIS_MCP_PORT) -ErrorAction SilentlyContinue)
        if ($bridge.Count) {
            $owner=Get-CimInstance Win32_Process -Filter "ProcessId=$($bridge[0].OwningProcess)"
            $path=[regex]::Escape((Join-Path $taskRoot 'trellis_mcp.py'))
            if ($bridge.Count -ne 1 -or $bridge[0].LocalAddress -ne '127.0.0.1' -or
                $owner.CommandLine -notmatch ('(?:^|\s)(?:"'+$path+'"|'+$path+')(?=\s|$)')) {
                throw 'The bridge port is used by another application.'
            }
        }
        @{state=$(if ($bridge.Count) {'partial'} else {'stopped'});url=$url} | ConvertTo-Json -Compress
        return
    }
    $owner=Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
    $path=[regex]::Escape((Join-Path $taskRoot 'app.py'))
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1' -or
        $owner.CommandLine -notmatch ('(?:^|\s)(?:"'+$path+'"|'+$path+')(?=\s|$)')) {
        throw 'The Studio port is used by another application.'
    }
    $health=Invoke-RestMethod -Uri ($url+'/api/status') -TimeoutSec 2
    if (-not $health.local) { throw 'The listener did not identify itself as local Studio.' }
    @{state='running';url=$url;busy=[bool]($health.active -or $health.export_active)} | ConvertTo-Json -Compress
} catch { @{state='unavailable';message=$_.Exception.Message} | ConvertTo-Json -Compress }

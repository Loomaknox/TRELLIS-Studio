param(
    [ValidateSet('Start','Stop','Status','TestHttps')][string]$Action='Status',
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$taskConfig = Join-Path $taskRoot 'config\server.json'
$taskScript = Join-Path $taskRoot 'server_app.py'
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
$taskCaddy = Join-Path $taskRoot 'bin\caddy\caddy.exe'
$taskProxyDirectory = Join-Path $taskRoot 'config\caddy'
$taskCaddyConfig = Join-Path $taskProxyDirectory 'Caddyfile'

function Test-Argument([string]$CommandLine,[string]$Value) {
    if (-not $CommandLine) { return $false }
    $escaped = [regex]::Escape($Value)
    return [regex]::IsMatch($CommandLine, '(?:^|\s)(?:"'+$escaped+'"|'+$escaped+')(?=\s|$)', 'IgnoreCase')
}
function Get-ListenerOwner([int]$Port,[string]$Role) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if (-not $listeners.Count) { return $null }
    $owners = @($listeners.OwningProcess | Select-Object -Unique)
    if ($owners.Count -ne 1) { throw "Port $Port belongs to multiple processes; they were preserved." }
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($owners[0])"
    if (-not $owner) { throw "The process on port $Port changed. Try again." }
    if ($Role -eq 'backend') {
        if (-not (Test-Argument $owner.CommandLine $taskScript) -or
            -not (Test-Argument $owner.CommandLine $taskConfig) -or
            @($listeners | Where-Object LocalAddress -ne $taskSettings.host).Count) {
            throw "Port $Port belongs to another application or configuration; it was preserved."
        }
    } else {
        if ($owner.ExecutablePath -ine $taskCaddy -or -not (Test-Argument $owner.CommandLine $taskCaddyConfig) -or
            ($Role -eq 'admin' -and @($listeners | Where-Object LocalAddress -ne '127.0.0.1').Count)) {
            throw "Port $Port belongs to another application or configuration; it was preserved."
        }
    }
    return $owner
}
function Get-ServerState {
    $backend = Get-ListenerOwner ([int]$taskSettings.port) 'backend'
    if (-not $taskSettings.reverse_proxy) { return $(if ($backend) { 'running' } else { 'stopped' }) }
    $edge = Get-ListenerOwner ([int]$taskSettings.proxy_port) 'edge'
    $admin = Get-ListenerOwner ([int]$taskSettings.proxy_admin_port) 'admin'
    if ($edge -and $admin -and $edge.ProcessId -ne $admin.ProcessId) { throw 'The HTTPS listeners have different owners; both were preserved.' }
    if ($backend -and $edge -and $admin) { return 'running' }
    if ($backend -or $edge -or $admin) { return 'partial' }
    return 'stopped'
}
function Stop-Backend {
    $owner = Get-ListenerOwner ([int]$taskSettings.port) 'backend'
    if (-not $owner) { return }
    $nonce = [Guid]::NewGuid().ToString('N')
    $request = Join-Path $taskSettings.data_dir 'stop.request'
    $response = Join-Path $taskSettings.data_dir 'stop.response'
    $pending = Join-Path $taskSettings.data_dir ('.stop-' + $nonce)
    try {
        [IO.File]::WriteAllText($pending, $nonce)
        [IO.File]::Move($pending, $request)
        for ($attempt=0; $attempt -lt 80; $attempt++) {
            Start-Sleep -Milliseconds 250
            if (-not (Test-Path -LiteralPath $response -PathType Leaf)) { continue }
            try { $result = Get-Content -LiteralPath $response -Raw -Encoding UTF8 | ConvertFrom-Json }
            catch { continue }
            if ($result.nonce -cne $nonce) { continue }
            if ($result.busy) { throw 'TRELLIS Server is processing a job. Wait for it to finish, then retry.' }
            if (-not $result.stopped) { throw 'TRELLIS Server rejected the shutdown request.' }
            Wait-Process -Id $owner.ProcessId -Timeout 20 -ErrorAction SilentlyContinue
            if (Get-Process -Id $owner.ProcessId -ErrorAction SilentlyContinue) { throw 'TRELLIS Server is still stopping. No process was forced to exit.' }
            return
        }
        throw 'TRELLIS Server did not acknowledge the shutdown request. No process was forced to exit.'
    } finally {
        if (Test-Path -LiteralPath $pending -PathType Leaf) { Remove-Item -LiteralPath $pending }
        if ((Test-Path -LiteralPath $request -PathType Leaf) -and
            (Get-Content -LiteralPath $request -Raw -ErrorAction SilentlyContinue) -ceq $nonce) {
            Remove-Item -LiteralPath $request -ErrorAction SilentlyContinue
        }
    }
}
function Stop-Proxy {
    $admin = Get-ListenerOwner ([int]$taskSettings.proxy_admin_port) 'admin'
    $edge = Get-ListenerOwner ([int]$taskSettings.proxy_port) 'edge'
    if (-not $admin) {
        if ($edge) { throw 'The HTTPS listener has no control endpoint. It was left running.' }
        return
    }
    if ($edge -and $edge.ProcessId -ne $admin.ProcessId) { throw 'HTTPS listeners changed; they were preserved.' }
    & $taskCaddy stop --address ('127.0.0.1:' + $taskSettings.proxy_admin_port)
    if ($LASTEXITCODE -ne 0) { throw 'Caddy did not acknowledge its graceful shutdown.' }
    Wait-Process -Id $admin.ProcessId -Timeout 20 -ErrorAction SilentlyContinue
    if (Get-Process -Id $admin.ProcessId -ErrorAction SilentlyContinue) { throw 'Caddy is still stopping.' }
}
function Write-ProxyConfig {
    $uri = [Uri]$taskSettings.public_url
    if ($uri.Scheme -ne 'https' -or $uri.DnsSafeHost -notmatch '^[a-zA-Z0-9.-]+$' -or $uri.HostNameType -ne 'Dns') {
        throw 'The Internet address must contain a valid HTTPS domain.'
    }
    $storage = $(if ($taskSettings.proxy_storage) { [string]$taskSettings.proxy_storage } else { Join-Path $taskProxyDirectory 'data' }).Replace('\','/')
    if ($storage -match '[\x00-\x1f{}]') { throw 'This installation path cannot be used for Caddy storage.' }
    $storage = $storage.Replace('"','\"')
    $lines = @(
        '{', ('    admin 127.0.0.1:' + [int]$taskSettings.proxy_admin_port),
        ('    https_port ' + [int]$taskSettings.proxy_port),
        '    auto_https disable_redirects', '    persist_config off',
        '    storage file_system {', ('        root "' + $storage + '"'), '    }', '}',
        ('https://' + $uri.DnsSafeHost + ':' + [int]$taskSettings.proxy_port + ' {'),
        '    bind 0.0.0.0', '    tls {', '        issuer acme {', '            disable_http_challenge',
        ('            alt_tlsalpn_port ' + [int]$taskSettings.proxy_port), '        }', '    }',
        ('    reverse_proxy 127.0.0.1:' + [int]$taskSettings.port), '}'
    )
    New-Item -ItemType Directory -Path $taskProxyDirectory -Force | Out-Null
    [IO.File]::WriteAllLines($taskCaddyConfig, $lines, [Text.UTF8Encoding]::new($false))
    & $taskCaddy validate --config $taskCaddyConfig --adapter caddyfile
    if ($LASTEXITCODE -ne 0) { throw 'The HTTPS proxy configuration did not pass validation.' }
}
function Start-Backend {
    $logs = Join-Path $taskSettings.data_dir 'logs'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    $process = Start-Process -FilePath $taskPython -ArgumentList @('-B','-u',('"'+$taskScript+'"'),'--config',('"'+$taskConfig+'"')) `
        -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs 'server.log') -RedirectStandardError (Join-Path $logs 'server-errors.log')
    for ($attempt=0; $attempt -lt 80 -and -not $process.HasExited; $attempt++) {
        $owner = Get-ListenerOwner ([int]$taskSettings.port) 'backend'
        if ($owner -and ($owner.ProcessId -eq $process.Id -or $owner.ParentProcessId -eq $process.Id)) {
            if (-not $taskSettings.reverse_proxy) { return }
            try {
                $health = Invoke-RestMethod -Uri ('http://127.0.0.1:'+$taskSettings.port+'/server/api/health') -TimeoutSec 2
                if ($health.service -eq 'trellis-server' -and $health.setup_complete) { return }
            } catch { }
        }
        Start-Sleep -Milliseconds 250
    }
    throw "TRELLIS Server did not become ready. See $logs\server-errors.log."
}
function Start-Proxy {
    $logs = Join-Path $taskProxyDirectory 'logs'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    $process = Start-Process -FilePath $taskCaddy -ArgumentList @('run','--config',('"'+$taskCaddyConfig+'"'),'--adapter','caddyfile') `
        -WorkingDirectory $taskProxyDirectory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs 'caddy.log') -RedirectStandardError (Join-Path $logs 'caddy-errors.log')
    for ($attempt=0; $attempt -lt 80 -and -not $process.HasExited; $attempt++) {
        $edge = Get-ListenerOwner ([int]$taskSettings.proxy_port) 'edge'
        $admin = Get-ListenerOwner ([int]$taskSettings.proxy_admin_port) 'admin'
        if ($edge -and $admin -and $edge.ProcessId -eq $process.Id -and $admin.ProcessId -eq $process.Id) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Caddy did not become ready. See $logs\caddy-errors.log."
}

if (-not (Test-Path -LiteralPath $taskConfig -PathType Leaf)) {
    if ($Action -eq 'Status') { @{state='unconfigured'; message='Configure TRELLIS Server first.'} | ConvertTo-Json -Compress; return }
    if ($Action -eq 'Stop') { return }
    throw 'Run Start-Server.ps1 -Configure to set up the server and its administrator.'
}
$taskSettings = Get-Content -LiteralPath $taskConfig -Raw -Encoding UTF8 | ConvertFrom-Json
if ($taskSettings.proxy_executable) { $taskCaddy = [IO.Path]::GetFullPath([string]$taskSettings.proxy_executable) }
if ($Action -eq 'Status') {
    try { @{state=(Get-ServerState); url=$taskSettings.public_url; internet=[bool]$taskSettings.reverse_proxy} | ConvertTo-Json -Compress }
    catch { @{state='unavailable'; message=$_.Exception.Message} | ConvertTo-Json -Compress }
    return
}
if ($Action -eq 'TestHttps') {
    if (-not $taskSettings.reverse_proxy) { throw 'HTTPS diagnostics are available in Internet mode.' }
    if ((Get-ServerState) -ne 'running') { throw 'Start the server and HTTPS proxy before checking the certificate.' }
    $uri=[Uri]$taskSettings.public_url
    $curl=Join-Path $env:SystemRoot 'System32\curl.exe'
    if (-not (Test-Path -LiteralPath $curl -PathType Leaf)) { throw 'Windows curl.exe is required for HTTPS diagnostics.' }
    $route=$uri.DnsSafeHost+':'+$uri.Port+':127.0.0.1:'+$taskSettings.proxy_port
    # Keep the canonical TLS SNI and HTTP Host, avoid NAT reflection, and verify public trust.
    $response=& $curl --silent --show-error --fail --max-time 20 --noproxy '*' --connect-to $route ($taskSettings.public_url+'/server/api/health')
    if ($LASTEXITCODE -ne 0) {
        throw 'HTTPS is not ready. The first certificate can take a few minutes. Check that the domain DNS points to your public IP, router TCP 443 reaches the configured HTTPS port, and the Windows firewall allows Caddy. See config/caddy/logs/caddy-errors.log. This test does not change certificate trust.'
    }
    $health=($response -join '') | ConvertFrom-Json
    if ($health.service -ne 'trellis-server' -or -not $health.setup_complete) { throw 'HTTPS responded but did not identify a configured TRELLIS Server.' }
    Write-Output 'The HTTPS certificate is trusted and the local proxy reaches TRELLIS Server. Test the browser address from a phone on mobile data to confirm access from outside your network.'
    return
}
$hasher = [Security.Cryptography.SHA256]::Create()
try { $identity = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($taskRoot.ToLowerInvariant()))).Replace('-','') }
finally { $hasher.Dispose() }
$mutex = New-Object Threading.Mutex($false, ('Local\TRELLIS-Server-'+$identity))
$acquired = $false
$componentLock = $null
try {
    try { $acquired = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) { throw 'Another TRELLIS Server command is running. Wait for it to finish.' }
    if ($Action -eq 'Start') {
        try { $componentLock=[IO.File]::Open((Join-Path $taskRoot '.component-install.lock'),'OpenOrCreate','ReadWrite','None') }
        catch [IO.IOException] { throw 'Another TRELLIS startup or installation is running. Wait for it to finish.' }
    }
    $state = Get-ServerState
    if ($Action -eq 'Stop') {
        Stop-Backend
        if ($taskSettings.reverse_proxy) { Stop-Proxy }
        Write-Output 'TRELLIS Server has stopped.'
        return
    }
    & $taskPython -B (Join-Path $taskRoot 'server_setup.py') --config $taskConfig --check
    if ($LASTEXITCODE -ne 0) { throw 'Server configuration check failed.' }
    if ($state -ne 'running') {
        $backendStarted = $false
        $proxyStarted = $false
        try {
            if ($taskSettings.reverse_proxy -and -not (Get-ListenerOwner ([int]$taskSettings.proxy_admin_port) 'admin')) {
                & $taskPython -B (Join-Path $taskRoot 'installer\install_caddy.py') --ensure --destination (Split-Path -Parent $taskCaddy)
                if ($LASTEXITCODE -ne 0) { throw 'Could not verify the HTTPS proxy. Run server setup again.' }
                Write-ProxyConfig
            }
            if (-not (Get-ListenerOwner ([int]$taskSettings.port) 'backend')) {
                $backendStarted = $true
                Start-Backend
            }
            if ($taskSettings.reverse_proxy -and -not (Get-ListenerOwner ([int]$taskSettings.proxy_admin_port) 'admin')) {
                $proxyStarted = $true
                Start-Proxy
            }
            if ((Get-ServerState) -ne 'running') { throw 'Server is only partially running. Stop it and try again.' }
        } catch {
            $problem = $_
            $backendIdle = $true
            if ($backendStarted) { try { Stop-Backend } catch { $backendIdle=$false; Write-Warning $_.Exception.Message } }
            if ($proxyStarted -and $backendIdle) { try { Stop-Proxy } catch { Write-Warning $_.Exception.Message } }
            throw $problem
        }
    }
    Write-Output ('TRELLIS Server is running locally: ' + $taskSettings.public_url)
    if ($taskSettings.reverse_proxy) { Write-Output 'The first HTTPS certificate may take a few minutes. DNS and inbound TCP 443 must reach this PC.' }
    if (-not $NoBrowser) { Start-Process $taskSettings.public_url }
} finally {
    if ($componentLock) { $componentLock.Dispose() }
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}

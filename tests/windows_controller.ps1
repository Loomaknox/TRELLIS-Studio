param([string]$Caddy)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$scriptPath=Join-Path $root 'installer\windows\Server-Control.ps1'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($scriptPath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
# Load only functions. Never execute the production script entry point in these fixtures.
foreach ($function in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$false)) {
    . ([scriptblock]::Create($function.Extent.Text))
}
$temp=Join-Path ([IO.Path]::GetTempPath()) ('trellis-controller-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp -Force | Out-Null
$taskRoot=$temp
$taskScript=Join-Path $temp 'server_app.py'
$taskConfig=Join-Path $temp 'config\server.json'
$taskCaddy='Invoke-MockCaddy'
$taskProxyDirectory=Join-Path $temp 'proxy'
$taskCaddyConfig=Join-Path $taskProxyDirectory 'Caddyfile'
$taskSettings=[pscustomobject]@{host='127.0.0.1';port=47863;reverse_proxy=$true;proxy_port=47862;proxy_admin_port=47864;public_url='https://studio.example.com';data_dir=$temp;proxy_storage=$null}
$script:listeners=@(); $script:owners=@{}; $script:waited=0; $script:proxyStopped=0
function Get-NetTCPConnection { param($State,$LocalPort,$ErrorAction) @($script:listeners | Where-Object LocalPort -eq $LocalPort) }
function Get-CimInstance { param($ClassName,$Filter) $id=[int]($Filter -replace '\D',''); $script:owners[$id] }
function Wait-Process { param($Id,$Timeout,$ErrorAction) $script:waited++ }
function Get-Process { param($Id,$ErrorAction) return $null }
function Invoke-MockCaddy { $script:proxyStopped++; $global:LASTEXITCODE=0 }
function Check([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }
function Reject([scriptblock]$Code,[string]$Match) {
    try { & $Code; throw 'Expected rejection was absent.' }
    catch { if ($_.Exception.Message -notmatch $Match) { throw } }
}
function Listen([int]$Port,[int]$Owner,[string]$Address='127.0.0.1') {
    [pscustomobject]@{LocalPort=$Port;OwningProcess=$Owner;LocalAddress=$Address}
}
$script:owners[101]=[pscustomobject]@{ProcessId=101;ParentProcessId=100;CommandLine=('python.exe -u "'+$taskScript+'" --config "'+$taskConfig+'"');ExecutablePath='python.exe'}
$script:owners[102]=[pscustomobject]@{ProcessId=102;CommandLine=('caddy run --config "'+$taskCaddyConfig+'" --adapter caddyfile');ExecutablePath=$taskCaddy}
$script:owners[103]=[pscustomobject]@{ProcessId=103;CommandLine='unrelated.exe';ExecutablePath='unrelated.exe'}
try {
    Check ((Get-ServerState) -eq 'stopped') 'Empty ports must be stopped.'
    $script:listeners=@((Listen 47863 101))
    Check ((Get-ServerState) -eq 'partial') 'Backend alone must be partial.'
    $script:listeners+=@((Listen 47862 102 '0.0.0.0'),(Listen 47864 102))
    Check ((Get-ServerState) -eq 'running') 'Owned listeners should report local running.'
    $script:listeners=@((Listen 47863 103))
    Reject { Get-ServerState } 'another application'
    $script:listeners=@((Listen 47863 101 '0.0.0.0'))
    Reject { Get-ServerState } 'another application'
    $script:listeners=@((Listen 47862 102 '0.0.0.0'),(Listen 47864 102 '0.0.0.0'))
    Reject { Get-ServerState } 'another application'
    $script:owners[101].CommandLine='python.exe "'+$taskScript+'.old" --config "'+$taskConfig+'"'
    $script:listeners=@((Listen 47863 101))
    Reject { Get-ServerState } 'another application'
    $script:owners[101].CommandLine='python.exe "'+$taskScript+'" --config "'+$taskConfig+'"'
    Check (Test-Argument ('python "'+$taskScript+'"') $taskScript) 'Exact quoted argument should match.'
    Check (-not (Test-Argument ('python "'+$taskScript+'suffix"') $taskScript)) 'Substring ownership is unsafe.'

    foreach ($busy in @($true,$false)) {
        # A separate runspace acts as the real file-protocol peer with the exact nonce.
        $peer=[PowerShell]::Create()
        [void]$peer.AddScript({param($folder,$isBusy)
            $request=Join-Path $folder 'stop.request'; $response=Join-Path $folder 'stop.response'
            for ($n=0;$n -lt 100;$n++) {
                if (Test-Path -LiteralPath $request) {
                    $nonce=[IO.File]::ReadAllText($request)
                    [IO.File]::WriteAllText($response,(@{nonce=$nonce;busy=$isBusy;stopped=(-not $isBusy)} | ConvertTo-Json -Compress))
                    return
                }
                Start-Sleep -Milliseconds 50
            }
            throw 'No stop request arrived.'
        }).AddArgument($temp).AddArgument($busy)
        $handle=$peer.BeginInvoke()
        try {
            if ($busy) { Reject { Stop-Backend } 'processing a job' }
            else { Stop-Backend }
            $peer.EndInvoke($handle) | Out-Null
            Check (-not (Test-Path -LiteralPath (Join-Path $temp 'stop.request'))) 'Our consumed request must be cleaned.'
        } finally { $peer.Dispose() }
    }
    Check ($script:waited -eq 1) 'Only accepted shutdown should wait for exit.'
    Check ($script:proxyStopped -eq 0) 'Backend protocol must not stop the proxy.'
    $script:listeners=@((Listen 47862 102 '0.0.0.0'),(Listen 47864 102))
    Stop-Proxy
    Check ($script:proxyStopped -eq 1) 'Owned proxy should receive graceful stop.'
    $script:listeners=@((Listen 47862 103 '0.0.0.0'),(Listen 47864 102))
    Reject { Stop-Proxy } 'another application'
    Check ($script:proxyStopped -eq 1) 'Foreign edge must prevent proxy mutation.'
    $script:listeners=@((Listen 47862 102 '0.0.0.0'))
    Reject { Stop-Proxy } 'no control endpoint'

    if ($Caddy) {
        $taskCaddy=[IO.Path]::GetFullPath($Caddy)
        # Adapt and validate only: no network listener, certificate issuance or trust changes.
        Write-ProxyConfig
        $json=(& $taskCaddy adapt --config $taskCaddyConfig --adapter caddyfile) | ConvertFrom-Json
        Check ($json.admin.listen -eq '127.0.0.1:47864') 'Caddy admin must stay loopback.'
        Check ($json.apps.http.servers.srv0.listen -contains '0.0.0.0:47862') 'NAT HTTPS listener must use internal port.'
        Check ($json.apps.tls.automation.policies[0].issuers[0].challenges.'tls-alpn'.alternate_port -eq 47862) 'ACME must use forwarded TLS port.'
        Check ($json.apps.tls.automation.policies[0].issuers[0].challenges.http.disabled) 'No port 80 challenge should be required.'
        $taskSettings.proxy_storage=Join-Path $temp 'existing certificate store'
        Write-ProxyConfig
        $json=(& $taskCaddy adapt --config $taskCaddyConfig --adapter caddyfile) | ConvertFrom-Json
        Check ($json.storage.root -eq $taskSettings.proxy_storage.Replace('\','/')) 'Custom certificate storage must survive Caddy configuration generation.'

        # Exercise the real firewall helper in WhatIf mode; it must verify the selected
        # executable before any firewall mutation or administrator requirement.
        $firewallDirectory=Join-Path $temp 'installer\windows'
        New-Item -ItemType Directory -Path $firewallDirectory -Force | Out-Null
        New-Item -ItemType Directory -Path (Split-Path -Parent $taskConfig) -Force | Out-Null
        $firewallScript=Join-Path $firewallDirectory 'Configure-Firewall.ps1'
        $manifestPath=Join-Path $temp 'installer\caddy-manifest.json'
        Copy-Item -LiteralPath (Join-Path $root 'installer\windows\Configure-Firewall.ps1') -Destination $firewallScript
        Copy-Item -LiteralPath (Join-Path $root 'installer\caddy-manifest.json') -Destination $manifestPath
        [IO.File]::WriteAllText($taskConfig,(@{reverse_proxy=$true;proxy_port=47862;proxy_executable=$taskCaddy}|ConvertTo-Json -Compress))
        & $firewallScript -ConfigPath $taskConfig -WhatIf
        $manifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $manifest.executable_sha256='0'*64
        [IO.File]::WriteAllText($manifestPath,($manifest|ConvertTo-Json -Compress))
        Reject { & $firewallScript -ConfigPath $taskConfig -WhatIf } 'checksum'
    }
    Write-Output 'PASS: controller ownership, partial states, busy refusal, graceful nonce protocol and proxy preservation.'
    if ($Caddy) { Write-Output 'PASS: generated Caddy configuration validated and adapted.' }
} finally {
    $resolved=[IO.Path]::GetFullPath($temp)
    if ((Split-Path -Parent $resolved) -ne ([IO.Path]::GetTempPath().TrimEnd('\')) -or (Split-Path -Leaf $resolved) -notmatch '^trellis-controller-[a-f0-9]{32}$') {
        throw 'Unexpected fixture cleanup path.'
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

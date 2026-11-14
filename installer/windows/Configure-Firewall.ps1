[CmdletBinding(SupportsShouldProcess=$true)]
param([Parameter(Mandatory=$true)][string]$ConfigPath)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$expected=[IO.Path]::GetFullPath((Join-Path $taskRoot 'config\server.json'))
if([IO.Path]::GetFullPath($ConfigPath) -ine $expected){throw 'Use this installation''s server configuration.'}
$settings=Get-Content -LiteralPath $expected -Raw -Encoding UTF8 | ConvertFrom-Json
if($settings.reverse_proxy -ne $true){throw 'This firewall helper only supports the automatic HTTPS proxy.'}
$port=[int]$settings.proxy_port
if($port -lt 1 -or $port -gt 65535){throw 'Invalid proxy port.'}
$proxyPath=if($settings.proxy_executable){[string]$settings.proxy_executable}else{Join-Path $taskRoot 'bin\caddy\caddy.exe'}
if(-not [IO.Path]::IsPathRooted($proxyPath) -or [IO.Path]::GetPathRoot($proxyPath) -match '^[A-Za-z]:$' -or [IO.Path]::GetFileName($proxyPath) -ine 'caddy.exe'){
    throw 'Use an absolute path to the verified caddy.exe proxy.'
}
$proxyFile=Get-Item -LiteralPath $proxyPath -ErrorAction Stop
if($proxyFile.PSIsContainer -or ($proxyFile.Attributes -band [IO.FileAttributes]::ReparsePoint)){
    throw 'The HTTPS proxy must be a regular verified executable.'
}
$manifest=Get-Content -LiteralPath (Join-Path $taskRoot 'installer\caddy-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if($proxyFile.Length -ne $manifest.executable_bytes -or (Get-FileHash -LiteralPath $proxyFile.FullName -Algorithm SHA256).Hash -ine $manifest.executable_sha256){
    throw 'The HTTPS proxy checksum does not match this installation. Run server setup again.'
}
$program=$proxyFile.FullName
$hash=[Security.Cryptography.SHA256]::Create()
try{$identity=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($taskRoot.ToLowerInvariant())))).Replace('-','').Substring(0,16)}finally{$hash.Dispose()}
$name='TRELLIS-Studio-HTTPS-'+$identity
if(-not $PSCmdlet.ShouldProcess("$program, TCP port $port",'Allow inbound HTTPS for this TRELLIS installation')){return}
$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator approval is required to configure Windows Firewall.'}
$existing=Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue
if($existing){
    $application=$existing | Get-NetFirewallApplicationFilter
    if($existing.Group -ne 'TRELLIS Studio' -or $application.Program -ine $program){throw 'An unrelated firewall rule uses the reserved name. It was preserved.'}
    $existing | Set-NetFirewallRule -DisplayName "TRELLIS Studio HTTPS (TCP $port)" -Direction Inbound -Action Allow -Enabled True -Profile Any -Protocol TCP -LocalPort $port -Program $program | Out-Null
}else{
    New-NetFirewallRule -Name $name -DisplayName "TRELLIS Studio HTTPS (TCP $port)" -Group 'TRELLIS Studio' -Direction Inbound -Action Allow -Enabled True -Profile Any -Protocol TCP -LocalPort $port -Program $program | Out-Null
}
Write-Output 'The scoped TRELLIS HTTPS firewall rule is configured.'

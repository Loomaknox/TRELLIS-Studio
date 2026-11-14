param([Parameter(Mandatory=$true)][string]$Python)
$ErrorActionPreference='Stop'
$sourceRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('trellis-lifecycle-'+[Guid]::NewGuid().ToString('N'))
$processes=@()
function Assert([bool]$Ok,[string]$Message) { if(-not $Ok){throw $Message} }
function Reject([scriptblock]$Code,[string]$Match) {
    try { & $Code; throw 'Expected rejection was absent.' }
    catch { if($_.Exception.Message -notmatch $Match){throw} }
}
try {
    New-Item -ItemType Directory -Path (Join-Path $fixture 'installer\windows'),(Join-Path $fixture 'config'),(Join-Path $fixture 'data') -Force | Out-Null
    foreach($name in @('Start-Server.ps1','Stop-Server.ps1','installer\windows\Server-Control.ps1')) {
        Copy-Item -LiteralPath (Join-Path $sourceRoot $name) -Destination (Join-Path $fixture $name)
    }
    & $Python -B -m venv --without-pip (Join-Path $fixture '.venv')
    if($LASTEXITCODE -ne 0){throw 'Could not create the isolated standard-library fixture.'}
    $pythonFixture=Join-Path $fixture '.venv\Scripts\python.exe'
    [IO.File]::WriteAllText((Join-Path $fixture 'server_setup.py'), 'import sys; sys.exit(0)')
    $backend=@'
import argparse,json,time,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,HTTPServer
parser=argparse.ArgumentParser();parser.add_argument('--config');args=parser.parse_args()
cfg=json.loads(Path(args.config).read_text(encoding='utf-8-sig'));data=Path(cfg['data_dir'])
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(b'{"service":"trellis-server","setup_complete":true}')
    def log_message(self,*args):pass
server=HTTPServer((cfg['host'],cfg['port']),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
while True:
    request=data/'stop.request'
    if request.is_file():
        nonce=request.read_text();request.unlink();busy=(data/'busy').exists()
        (data/'stop.response').write_text(json.dumps(dict(nonce=nonce,busy=busy,stopped=not busy)))
        if not busy:break
    time.sleep(.05)
server.shutdown();server.server_close()
'@
    [IO.File]::WriteAllText((Join-Path $fixture 'server_app.py'),$backend)
    [IO.File]::WriteAllText((Join-Path $fixture 'foreign.py'),$backend)
    $probe=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,0)
    $probe.Start();$port=$probe.LocalEndpoint.Port;$probe.Stop()
    $settings=@{host='127.0.0.1';port=$port;data_dir=(Join-Path $fixture 'data');public_url=('http://127.0.0.1:'+$port);reverse_proxy=$false}
    [IO.File]::WriteAllText((Join-Path $fixture 'config\server.json'),($settings | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    $start=Join-Path $fixture 'Start-Server.ps1'; $stop=Join-Path $fixture 'Stop-Server.ps1'; $control=Join-Path $fixture 'installer\windows\Server-Control.ps1'
    & $start -NoBrowser
    $state=(& $control -Action Status) | ConvertFrom-Json
    Assert ($state.state -eq 'running') 'Real backend did not start.'
    $owned=@(Get-NetTCPConnection -State Listen -LocalPort $port).OwningProcess | Select-Object -Unique
    $processes+=@($owned)
    & $start -NoBrowser
    Assert ((@(Get-NetTCPConnection -State Listen -LocalPort $port).OwningProcess | Select-Object -Unique) -eq $owned) 'Idempotent start changed the owner.'
    [IO.File]::WriteAllText((Join-Path $fixture 'data\busy'),'1')
    Reject { & $stop } 'processing a job'
    Assert ([bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)) 'Busy backend was stopped.'
    Remove-Item -LiteralPath (Join-Path $fixture 'data\busy')
    & $stop
    Assert (-not (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)) 'Graceful shutdown left a listener.'
    & $stop

    $foreign=Start-Process -FilePath $pythonFixture -ArgumentList @('-B',('"'+(Join-Path $fixture 'foreign.py')+'"'),'--config',('"'+(Join-Path $fixture 'config\server.json')+'"')) `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $fixture 'foreign.log') -RedirectStandardError (Join-Path $fixture 'foreign-errors.log')
    $processes+=@($foreign.Id)
    for($attempt=0;$attempt -lt 50;$attempt++) {
        if(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue){break}
        Start-Sleep -Milliseconds 100
    }
    $foreignOwner=@(Get-NetTCPConnection -State Listen -LocalPort $port).OwningProcess | Select-Object -Unique
    $processes+=@($foreignOwner)
    Reject { & $start -NoBrowser } 'another application'
    Reject { & $stop } 'another application'
    Assert ([bool](Get-Process -Id $foreignOwner -ErrorAction SilentlyContinue)) 'Foreign process was terminated.'
    Assert (-not (Test-Path -LiteralPath (Join-Path $fixture 'data\stop.request'))) 'Foreign refusal wrote a stop request.'
    [IO.File]::WriteAllText((Join-Path $fixture 'data\stop.request'),'fixture-cleanup')
    Wait-Process -Id $foreignOwner -Timeout 15 -ErrorAction SilentlyContinue
    Assert (-not (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)) 'Fixture did not exit gracefully.'
    Write-Output 'PASS: real Windows lifecycle on random port, idempotent start, busy refusal, graceful stop, unrelated-process preservation.'
} finally {
    foreach($processId in ($processes | Select-Object -Unique)) {
        $process=Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
        if($process -and $process.CommandLine -like ('*'+$fixture+'*')) { Stop-Process -Id $processId -ErrorAction SilentlyContinue }
    }
    $resolved=[IO.Path]::GetFullPath($fixture)
    if((Split-Path -Parent $resolved) -ne ([IO.Path]::GetTempPath().TrimEnd('\')) -or (Split-Path -Leaf $resolved) -notmatch '^trellis-lifecycle-[a-f0-9]{32}$') {throw 'Unexpected fixture cleanup path.'}
    if(Test-Path -LiteralPath $resolved){Remove-Item -LiteralPath $resolved -Recurse -Force}
}

# Real process handles under Windows PowerShell 5.1; no WSL or network required.
$ErrorActionPreference='Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'installer\windows\Install-Kimodo.ps1')
$taskParent=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$taskFixture=Join-Path $taskParent ('trellis-wsl-probe-'+[Guid]::NewGuid().ToString('N'))
$taskOldMode=$env:TRELLIS_PROBE_FIXTURE_MODE
function Assert-True($Value,$Message) { if(-not $Value){throw $Message} }
try {
    New-Item -ItemType Directory -Path $taskFixture | Out-Null
    $taskExecutable=Join-Path $taskFixture "probe's executable.exe"
    Add-Type -OutputAssembly $taskExecutable -OutputType ConsoleApplication -TypeDefinition @'
using System;
using System.Threading;
public static class ProbeFixture {
    public static void Main(string[] args) {
        if(args.Length != 5 || args[0] != "-d" || args[1] != "Ubuntu-22.04" || args[2] != "--exec" || args[3] != "uname" || args[4] != "-m") Environment.Exit(5);
        string mode = Environment.GetEnvironmentVariable("TRELLIS_PROBE_FIXTURE_MODE");
        if(mode == "timeout") Thread.Sleep(10000);
        if(mode == "large-error") Console.Error.Write(new string('x', 150000));
        Console.WriteLine(mode == "arm" ? "aarch64" : "x86_64");
        Environment.Exit(mode == "failure" ? 1 : 0);
    }
}
'@
    foreach($taskMode in @('success','large-error')) {
        $env:TRELLIS_PROBE_FIXTURE_MODE=$taskMode
        Assert-True (Test-KimodoWslArchitecture $taskExecutable 'Ubuntu-22.04') "Valid architecture was rejected: $taskMode"
    }
    foreach($taskMode in @('failure','arm','timeout')) {
        $env:TRELLIS_PROBE_FIXTURE_MODE=$taskMode
        Assert-True (-not (Test-KimodoWslArchitecture $taskExecutable 'Ubuntu-22.04' 1000)) "Invalid or timed-out probe was accepted: $taskMode"
    }
    Assert-True (-not (Test-KimodoWslArchitecture $taskExecutable 'Ubuntu;bad')) 'Unsafe distribution accepted.'
    Assert-True (-not (Test-KimodoWslArchitecture (Join-Path $taskFixture 'missing.exe') 'Ubuntu-22.04')) 'Missing executable accepted.'
    Write-Output 'Kimodo process probe: passed success, exit failure, wrong architecture, timeout, large stderr and paths with spaces/apostrophes.'
} finally {
    $env:TRELLIS_PROBE_FIXTURE_MODE=$taskOldMode
    if(Test-Path -LiteralPath $taskFixture) {
        $taskResolved=(Resolve-Path -LiteralPath $taskFixture).Path
        if((Split-Path -Parent $taskResolved) -ne $taskParent -or (Split-Path -Leaf $taskResolved) -notmatch '^trellis-wsl-probe-[a-f0-9]{32}$') { throw 'Unexpected fixture path; cleanup stopped.' }
        Remove-Item -LiteralPath $taskResolved -Recurse -Force
    }
}

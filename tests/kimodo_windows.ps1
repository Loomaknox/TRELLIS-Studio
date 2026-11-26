$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskTempRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$taskFixture=Join-Path $taskTempRoot ('trellis-kimodo-windows-'+[Guid]::NewGuid().ToString('N'))
$taskPreviousArgs=$env:TRELLIS_KIMODO_TEST_ARGS
$taskPreviousExit=$env:TRELLIS_KIMODO_TEST_EXIT
$taskPreviousPython=$env:TRELLIS_KIMODO_TEST_PYTHON
$taskPreviousFailure=$env:TRELLIS_KIMODO_TEST_COMPONENT_FAIL
function Assert-True($Value,[string]$Message) { if(-not $Value){throw $Message} }
try {
    New-Item -ItemType Directory -Path $taskFixture -Force | Out-Null
    $taskInstall=Join-Path $taskFixture "Studio space's folder"
    New-Item -ItemType Directory -Path (Join-Path $taskInstall '.venv\Scripts'),(Join-Path $taskInstall 'installer\windows'),(Join-Path $taskInstall '.tools\uv'),(Join-Path $taskInstall 'config') -Force | Out-Null
    $env:TRELLIS_KIMODO_TEST_ARGS=Join-Path $taskFixture 'arguments.txt'
    $env:TRELLIS_KIMODO_TEST_EXIT='0'
    $env:TRELLIS_KIMODO_TEST_PYTHON=Join-Path $taskInstall '.venv\Scripts\python.exe'
    Add-Type -TypeDefinition @'
using System;
using System.IO;
public static class KimodoFixtureProgram {
    public static void Main(string[] args) {
        if (Path.GetFileNameWithoutExtension(Environment.GetCommandLineArgs()[0]) == "uv") {
            if (args.Length > 1 && args[1] == "find") Console.WriteLine(Environment.GetEnvironmentVariable("TRELLIS_KIMODO_TEST_PYTHON"));
            return;
        }
        if (args.Length > 3 && args[0] == "-d" && args[2] == "--exec") {
            // WSL reads host options before passing the Linux command to the distribution.
            if (Environment.CommandLine.Contains("\"-d\"") || Environment.CommandLine.Contains("\"--exec\"")) Environment.Exit(127);
            if (args[3] == "uname") Console.WriteLine(args[1] == "Fixture-ARM" ? "aarch64" : "x86_64");
            Environment.Exit(int.Parse(Environment.GetEnvironmentVariable("TRELLIS_KIMODO_TEST_EXIT") ?? "0"));
            return;
        }
        File.WriteAllLines(Environment.GetEnvironmentVariable("TRELLIS_KIMODO_TEST_ARGS"), args);
        Environment.Exit(int.Parse(Environment.GetEnvironmentVariable("TRELLIS_KIMODO_TEST_EXIT") ?? "0"));
    }
}
'@ -OutputAssembly $env:TRELLIS_KIMODO_TEST_PYTHON -OutputType ConsoleApplication
    . (Join-Path $taskRoot 'installer\windows\Install-Kimodo.ps1')
    $taskRigProbe=Invoke-SetupProcess -FilePath $env:TRELLIS_KIMODO_TEST_PYTHON -Arguments @('-d','Fixture-Default','--exec','true')
    Assert-True ($taskRigProbe.ExitCode -eq 0) 'The UniRig probe must pass bare WSL host options.'
    Assert-True (Test-KimodoWslArchitecture $env:TRELLIS_KIMODO_TEST_PYTHON 'Fixture-Default') 'Kimodo rejected a successful Linux x64 probe.'
    Assert-True (-not (Test-KimodoWslArchitecture $env:TRELLIS_KIMODO_TEST_PYTHON 'Fixture-ARM')) 'Kimodo accepted a non-x64 distribution.'
    $env:TRELLIS_KIMODO_TEST_EXIT='7'
    Assert-True (-not (Test-KimodoWslArchitecture $env:TRELLIS_KIMODO_TEST_PYTHON 'Fixture-Default')) 'Kimodo accepted x64 output from a failed process.'
    $env:TRELLIS_KIMODO_TEST_EXIT='0'
    function Get-Command { param($Name,$ErrorAction); if($Name -eq 'wsl.exe'){[pscustomobject]@{Source='fixture-wsl.exe'}} }
    function Get-KimodoWslDistributions { @([pscustomobject]@{Name='Fixture-Other';Default=$false},[pscustomobject]@{Name='Fixture-Default';Default=$true}) }
    $script:taskProbes=@()
    function Test-KimodoWslArchitecture($Executable,$Distribution) { $script:taskProbes+=@($Distribution);return $true }
    Assert-True ((Resolve-KimodoDistribution $taskInstall '') -eq 'Fixture-Default') 'Default WSL2 distribution was not selected.'
    [IO.File]::WriteAllText((Join-Path $taskInstall 'config\runtime.json'),' {"wsl_distribution":"Fixture-Other"}')
    Assert-True ((Resolve-KimodoDistribution $taskInstall '') -eq 'Fixture-Other') 'Existing runtime preference was not reused.'
    Assert-True ((Resolve-KimodoDistribution $taskInstall 'Fixture-Default') -eq 'Fixture-Default') 'Explicit distribution did not take priority.'
    $taskRejected=$false
    try { Resolve-KimodoDistribution $taskInstall 'Bad;command' | Out-Null } catch { $taskRejected=$true }
    Assert-True $taskRejected 'Unsafe distribution syntax was accepted.'
    function Get-KimodoWslDistributions { @() }
    $taskRejected=$false
    try { Resolve-KimodoDistribution $taskInstall '' | Out-Null } catch { $taskRejected=$_.Exception.Message -like '*wsl --install*' }
    Assert-True $taskRejected 'Missing WSL2 did not produce setup guidance.'
    function Get-KimodoWslDistributions { @([pscustomobject]@{Name='Fixture-Default';Default=$true}) }
    $script:taskPrompts=0
    function Read-Host { param($Prompt);$script:taskPrompts++;return 'NO' }
    $taskRejected=$false
    try { Invoke-KimodoInstallation -Root $taskInstall } catch { $taskRejected=$_.Exception.Message -like '*licenses were not accepted*' }
    Assert-True ($taskRejected -and -not (Test-Path -LiteralPath $env:TRELLIS_KIMODO_TEST_ARGS)) 'Declined licenses ran the installer.'
    $taskPromptCount=$script:taskPrompts
    Invoke-KimodoInstallation -Root $taskInstall -AcceptLicenses -Cache (Join-Path $taskFixture "cache's folder") -ThreadCount 3
    $taskArguments=[IO.File]::ReadAllLines($env:TRELLIS_KIMODO_TEST_ARGS)
    Assert-True ($taskArguments[1] -eq (Join-Path $taskInstall 'installer\install_kimodo.py')) 'Installer path was split or changed.'
    Assert-True ($taskArguments[3] -eq $taskInstall) 'Install root with spaces was not preserved.'
    Assert-True ($taskArguments -contains '--accept-model-licenses') 'Explicit license acceptance was not forwarded.'
    Assert-True ($taskArguments -contains '3') 'Thread count was not forwarded.'
    Assert-True ($taskArguments -contains (Join-Path $taskFixture "cache's folder")) 'Cache path was not preserved.'
    Assert-True ($script:taskPrompts -eq $taskPromptCount) 'Explicit license acceptance prompted again.'
    $env:TRELLIS_KIMODO_TEST_EXIT='1';$taskRejected=$false
    try { Invoke-KimodoInstallation -Root $taskInstall -AcceptLicenses } catch { $taskRejected=$_.Exception.Message -like '*did not finish*' }
    Assert-True $taskRejected 'Installer failure was reported as success.'
    $env:TRELLIS_KIMODO_TEST_EXIT='0'

    # Run the real source bootstrap against harmless local stubs, with no downloads.
    Copy-Item -LiteralPath (Join-Path $taskRoot 'Install-Studio.ps1') -Destination $taskInstall
    Copy-Item -LiteralPath $env:TRELLIS_KIMODO_TEST_PYTHON -Destination (Join-Path $taskInstall '.tools\uv\uv.exe')
    [IO.File]::WriteAllText((Join-Path $taskInstall 'installer\manifest.json'),'{}')
    [IO.File]::WriteAllText((Join-Path $taskInstall 'installer\windows\check-idle.ps1'),'param($InstallRoot,[switch]$IgnoreCurrentProcess); throw "Fixture Studio is active."')
    Remove-Item -LiteralPath $env:TRELLIS_KIMODO_TEST_ARGS
    $taskRejected=$false
    try { & (Join-Path $taskInstall 'Install-Studio.ps1') -WorkshopOnly -WithKimodo -NoLaunch } catch { $taskRejected=$_.Exception.Message -like '*Fixture Studio is active*' }
    Assert-True ($taskRejected -and -not(Test-Path -LiteralPath $env:TRELLIS_KIMODO_TEST_ARGS)) 'Source bootstrap ignored the active Studio guard.'
    [IO.File]::WriteAllText((Join-Path $taskInstall 'installer\windows\check-idle.ps1'),'param($InstallRoot,[switch]$IgnoreCurrentProcess)')
    [IO.File]::WriteAllText((Join-Path $taskInstall 'installer\windows\Install-Kimodo.ps1'),@'
param($InstallRoot,$WslDistribution,[switch]$AcceptModelLicenses)
if($env:TRELLIS_KIMODO_TEST_COMPONENT_FAIL){throw 'Fixture component failure.'}
@{root=$InstallRoot;distribution=$WslDistribution;accepted=[bool]$AcceptModelLicenses}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $InstallRoot 'wrapper.json')
'@)
    [IO.File]::WriteAllText((Join-Path $taskInstall 'Start-Studio.ps1'),"throw 'NoLaunch was ignored.'")
    & (Join-Path $taskInstall 'Install-Studio.ps1') -WorkshopOnly -WithKimodo -NoLaunch -AcceptKimodoModelLicenses -KimodoDistribution 'Fixture-Default'
    $taskReceipt=Get-Content -LiteralPath (Join-Path $taskInstall 'wrapper.json') -Raw|ConvertFrom-Json
    Assert-True ($taskReceipt.accepted -and $taskReceipt.distribution -eq 'Fixture-Default' -and $taskReceipt.root -eq $taskInstall) 'Source bootstrap dropped Kimodo options.'
    Assert-True ([IO.File]::ReadAllLines($env:TRELLIS_KIMODO_TEST_ARGS) -contains '--workshop-only') 'Source bootstrap requested full AI installation.'
    Remove-Item -LiteralPath (Join-Path $taskInstall 'wrapper.json')
    & (Join-Path $taskInstall 'Install-Studio.ps1') -WorkshopOnly -NoLaunch
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $taskInstall 'wrapper.json'))) 'Kimodo installed without an opt-in.'

    # Installed edition paths use the same helper before a Server can start.
    Copy-Item -LiteralPath (Join-Path $taskRoot 'installer\windows\Launch-Installed.ps1') -Destination (Join-Path $taskInstall 'installer\windows')
    New-Item -ItemType Directory -Path (Join-Path $taskInstall '.mcp-venv\Scripts'),(Join-Path $taskInstall 'licenses'),(Join-Path $taskInstall 'engine\MODELS\dinov3') -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $taskInstall '.mcp-venv\Scripts\python.exe'),'fixture')
    [IO.File]::WriteAllText((Join-Path $taskInstall 'bundled-web.json'),'{}')
    [IO.File]::WriteAllText((Join-Path $taskInstall 'licenses\DINOv3-LICENSE.md'),'Fixture license, no model download.')
    [IO.File]::WriteAllText((Join-Path $taskInstall 'engine\MODELS\dinov3\model.safetensors'),'fixture')
    $taskReady=@{}
    foreach($taskRelative in @('installer/setup.py','requirements-windows.txt','requirements-mcp-lock.txt')) {
        [IO.File]::WriteAllText((Join-Path $taskInstall $taskRelative),'fixture')
        $taskReady[$taskRelative]=(Get-FileHash -LiteralPath (Join-Path $taskInstall $taskRelative) -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $taskReady|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $taskInstall '.studio-workshop-ready')
    [IO.File]::WriteAllText((Join-Path $taskInstall 'Start-Server.ps1'),@'
param([switch]$Configure,[switch]$NoBrowser)
if(-not(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'wrapper.json'))){throw 'Server started before Kimodo completed.'}
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'server-started.txt'),'fixture only')
'@)
    function Start-Process { throw 'An external process launch is not expected in this fixture.' }
    function Read-Host { param($Prompt);return 'ACCEPT' }
    foreach($taskMode in @('PrepareWorkshop','Full','ServerSetup')) {
        $taskServer=$taskMode -eq 'ServerSetup'
        if($taskServer){function Start-Process { param($FilePath,$ArgumentList,$WindowStyle);Assert-True ($FilePath -like '*TRELLIS Studio Tray.exe') 'Unexpected fixture process launch.' }}
        & (Join-Path $taskInstall 'installer\windows\Launch-Installed.ps1') -Mode $taskMode -WithKimodo -AcceptKimodoModelLicenses -NoBrowser
        $taskReceipt=Get-Content -LiteralPath (Join-Path $taskInstall 'wrapper.json') -Raw|ConvertFrom-Json
        Assert-True $taskReceipt.accepted "Installed $taskMode dropped license consent."
        Remove-Item -LiteralPath (Join-Path $taskInstall 'wrapper.json')
        if($taskServer){Assert-True (Test-Path -LiteralPath (Join-Path $taskInstall 'server-started.txt')) 'Server fixture did not reach startup.';Remove-Item -LiteralPath (Join-Path $taskInstall 'server-started.txt')}
    }
    & (Join-Path $taskInstall 'installer\windows\Launch-Installed.ps1') -Mode PrepareWorkshop -NoBrowser
    Assert-True (-not(Test-Path -LiteralPath (Join-Path $taskInstall 'wrapper.json'))) 'Installed Workshop added Kimodo by default.'
    $env:TRELLIS_KIMODO_TEST_COMPONENT_FAIL='1';$taskRejected=$false
    try { & (Join-Path $taskInstall 'installer\windows\Launch-Installed.ps1') -Mode ServerSetup -WithKimodo -AcceptKimodoModelLicenses -NoBrowser } catch { $taskRejected=$_.Exception.Message -like '*Fixture component failure*' }
    Assert-True ($taskRejected -and -not(Test-Path -LiteralPath (Join-Path $taskInstall 'server-started.txt'))) 'Server started or hid a failed optional installation.'
    Write-Output 'Kimodo Windows checks passed: opt-in, license refusal, explicit consent, WSL selection/guidance, safe argument propagation and failure handling. No inference or downloads ran.'
} finally {
    $env:TRELLIS_KIMODO_TEST_ARGS=$taskPreviousArgs
    $env:TRELLIS_KIMODO_TEST_EXIT=$taskPreviousExit
    $env:TRELLIS_KIMODO_TEST_PYTHON=$taskPreviousPython
    $env:TRELLIS_KIMODO_TEST_COMPONENT_FAIL=$taskPreviousFailure
    if (Test-Path -LiteralPath $taskFixture) {
        $taskResolved=(Resolve-Path -LiteralPath $taskFixture).Path
        if ((Split-Path -Parent $taskResolved) -ne $taskTempRoot -or (Split-Path -Leaf $taskResolved) -notmatch '^trellis-kimodo-windows-[a-f0-9]{32}$') { throw 'Refusing to remove an unexpected fixture path.' }
        Remove-Item -LiteralPath $taskResolved -Recurse -Force
    }
}

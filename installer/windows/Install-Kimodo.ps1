param(
    [string]$InstallRoot=(Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$WslDistribution='',
    [string]$CacheDirectory='',
    [ValidateRange(1,64)][int]$Threads=8,
    [switch]$AcceptModelLicenses
)
$ErrorActionPreference='Stop'

function Get-KimodoWslDistributions {
    $taskRegistry='HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    if (-not (Test-Path -LiteralPath $taskRegistry)) { return }
    $taskDefault=(Get-ItemProperty -LiteralPath $taskRegistry).DefaultDistribution
    foreach ($taskKey in Get-ChildItem -LiteralPath $taskRegistry) {
        $taskInfo=Get-ItemProperty -LiteralPath $taskKey.PSPath
        if ($taskInfo.Version -eq 2 -and $taskInfo.DistributionName -match '^[A-Za-z0-9_.-]{1,80}$') {
            [pscustomobject]@{Name=[string]$taskInfo.DistributionName; Default=$taskKey.PSChildName -eq $taskDefault}
        }
    }
}

function Test-KimodoWslArchitecture([string]$Executable,[string]$Distribution,[int]$TimeoutMilliseconds=20000) {
    if ($Distribution -notmatch '^[A-Za-z0-9_.-]{1,80}$') { return $false }
    $taskProbe=$null
    try {
        # Own the process handle before waiting. Start-Process can return a Process
        # whose ExitCode stays null after WaitForExit on Windows PowerShell 5.1.
        $taskStart=New-Object System.Diagnostics.ProcessStartInfo
        $taskStart.FileName=$Executable
        $taskStart.Arguments='-d "'+$Distribution+'" --exec uname -m'
        $taskStart.UseShellExecute=$false
        $taskStart.CreateNoWindow=$true
        $taskStart.RedirectStandardOutput=$true
        $taskStart.RedirectStandardError=$true
        $taskProbe=New-Object System.Diagnostics.Process
        $taskProbe.StartInfo=$taskStart
        if (-not $taskProbe.Start()) { return $false }
        $taskOutput=$taskProbe.StandardOutput.ReadToEndAsync()
        $taskError=$taskProbe.StandardError.ReadToEndAsync()
        if (-not $taskProbe.WaitForExit($TimeoutMilliseconds)) {
            # Only this short-lived uname probe is stopped, never the distribution.
            $taskProbe.Kill(); $taskProbe.WaitForExit()
            return $false
        }
        $taskProbe.WaitForExit()
        $taskArchitecture=$taskOutput.GetAwaiter().GetResult().Replace([string][char]0,'').Trim()
        $null=$taskError.GetAwaiter().GetResult()
        return $taskProbe.ExitCode -eq 0 -and $taskArchitecture -eq 'x86_64'
    } catch { return $false }
    finally {
        if ($taskProbe) { $taskProbe.Dispose() }
    }
}

function Resolve-KimodoDistribution([string]$Root,[string]$Requested) {
    $taskWsl=Get-Command wsl.exe -ErrorAction SilentlyContinue
    $taskHelp='Set up WSL2 first: run wsl --install -d Ubuntu-22.04 in an administrator terminal, restart Windows if requested, and finish the Linux first-run setup. Then run Install Kimodo.cmd again. See https://learn.microsoft.com/windows/wsl/install'
    if (-not $taskWsl) { throw $taskHelp }
    if ($Requested -and $Requested -notmatch '^[A-Za-z0-9_.-]{1,80}$') { throw 'Choose a valid registered WSL distribution name.' }
    $taskInstalled=@(Get-KimodoWslDistributions)
    $taskPreferred=@()
    if ($Requested) { $taskPreferred=@($Requested) }
    else {
        foreach ($taskRelative in @('config\generated-animation-runtime.json','config\runtime.json')) {
            $taskPath=Join-Path $Root $taskRelative
            if (Test-Path -LiteralPath $taskPath -PathType Leaf) {
                try {
                    $taskConfig=Get-Content -LiteralPath $taskPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    $taskName=if($taskConfig.distribution){$taskConfig.distribution}else{$taskConfig.wsl_distribution}
                    if ($taskName) { $taskPreferred+=@([string]$taskName) }
                } catch { }
            }
        }
        $taskPreferred+=@($taskInstalled | Sort-Object -Property @{Expression='Default';Descending=$true},Name | ForEach-Object Name)
    }
    $taskSeen=@{}
    foreach ($taskName in $taskPreferred) {
        if ($taskSeen.ContainsKey($taskName)) { continue }
        $taskSeen[$taskName]=$true
        if ($taskName -notin $taskInstalled.Name) { continue }
        if (Test-KimodoWslArchitecture $taskWsl.Source $taskName) { return $taskName }
    }
    if ($Requested) { throw "The selected distribution is not an available WSL2 Linux x64 environment. $taskHelp" }
    throw "No compatible WSL2 Linux x64 distribution was found. $taskHelp"
}

function Invoke-KimodoInstallation {
    param([string]$Root,[string]$Distribution='',[string]$Cache='', [int]$ThreadCount=8,[switch]$AcceptLicenses)
    $taskRoot=[IO.Path]::GetFullPath($Root)
    $taskPython=Join-Path $taskRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'Prepare the Workshop first, then run Install Kimodo.cmd again.' }
    Write-Host 'Kimodo is an optional CPU text-to-motion engine. No NVIDIA GPU or CUDA is required.'
    Write-Host 'Downloads about 9.3 GB of model weights plus a portable compiler and build tools. Keep at least 12 GiB free inside WSL.'
    Write-Host 'Requires WSL2 Linux x64, Python 3.10 or newer, and a CPU with AVX2, FMA and F16C.'
    Write-Host 'NVIDIA Open Model License: https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/'
    Write-Host 'Meta Llama 3 Community License (Q8 text encoder): https://huggingface.co/LocalAI-io/Llama-3-Kimodo-GGML/blob/f583f3ee2b093f6d9ec524463b4152622abf11a6/LICENSE-META-LLAMA-3.txt'
    if (-not $AcceptLicenses -and (Read-Host 'After reading both model licenses, type ACCEPT to accept them, or anything else to exit') -cne 'ACCEPT') {
        throw 'Kimodo model licenses were not accepted. No Kimodo installation was performed.'
    }
    $taskDistribution=Resolve-KimodoDistribution $taskRoot $Distribution
    Write-Host "Preparing Kimodo in WSL distribution: $taskDistribution"
    $taskArguments=@('-u',(Join-Path $taskRoot 'installer\install_kimodo.py'),'--install-root',$taskRoot,
        '--distribution',$taskDistribution,'--accept-model-licenses','--threads',[string]$ThreadCount)
    if ($Cache) { $taskArguments+=@('--cache-dir',[IO.Path]::GetFullPath($Cache)) }
    & $taskPython @taskArguments
    if ($LASTEXITCODE -ne 0) { throw 'Kimodo installation did not finish. Review the diagnostic above and run Install Kimodo.cmd again to resume. Existing models and accounts are preserved.' }
    Write-Host 'Kimodo setup finished. Existing custom settings, if any, were preserved. Restart TRELLIS and check My animations for runtime availability.'
}

# Dot-sourcing exposes the small helpers for the isolated installer checks.
if ($MyInvocation.InvocationName -ne '.') {
    Invoke-KimodoInstallation -Root $InstallRoot -Distribution $WslDistribution -Cache $CacheDirectory `
        -ThreadCount $Threads -AcceptLicenses:$AcceptModelLicenses
}

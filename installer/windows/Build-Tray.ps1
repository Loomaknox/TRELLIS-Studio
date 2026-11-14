param([string]$OutputPath)
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $OutputPath) { $OutputPath=Join-Path $taskRoot 'TRELLIS Studio Tray.exe' }
$compiler=Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    $compiler=Join-Path $env:SystemRoot 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) { throw '.NET Framework 4 is required to build the tray.' }
$output=[IO.Path]::GetFullPath($OutputPath)
New-Item -ItemType Directory -Path (Split-Path -Parent $output) -Force | Out-Null
& $compiler /nologo /target:winexe /optimize+ /platform:anycpu /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll `
    (('/win32icon:')+(Join-Path $PSScriptRoot 'trellis-studio.ico')) (('/out:')+$output) (Join-Path $PSScriptRoot 'StudioTray.cs')
if ($LASTEXITCODE -ne 0) { throw 'The tray application did not compile.' }
Write-Output $output

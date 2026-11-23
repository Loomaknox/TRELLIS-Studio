$ErrorActionPreference='Stop'
$repoRoot=Split-Path -Parent $PSScriptRoot
$probeScript=Join-Path $repoRoot 'installer\windows\Setup-Preflight.ps1'
. $probeScript

$english=Get-SetupPreflight -Language en -InstallRoot $repoRoot -BlenderPath $repoRoot -WslDistribution 'TRELLIS-Test-Not-Registered'
$french=Get-SetupPreflight -Language fr -InstallRoot $repoRoot -BlenderPath $repoRoot -WslDistribution 'TRELLIS-Test-Not-Registered'
foreach ($section in $english.PSObject.Properties) {
    foreach ($field in $section.Value.PSObject.Properties) {
        if ($field.Name -in ('Status','VramNotice','UniRigStatus','Guidance','FreeGiB')) { continue }
        if ($field.Value -cne $french.($section.Name).($field.Name)) {
            throw "Machine field $($section.Name).$($field.Name) differed between locales."
        }
    }
}
if ($english.Blender.Status -cne 'Choose an existing blender.exe.' -or
    $french.Blender.Status -cnotlike 'S?lectionnez un fichier blender.exe existant.' -or
    $french.WSL.Status -cnotlike 'Installez et initialisez Ubuntu*') {
    throw 'The displayed Blender or WSL checks did not use the selected language.'
}

$fixtureGpu=[pscustomobject]@{Supported=$true; Compute='9.9'; MemoryMiB=16384}
. $probeScript -SetupLanguage 1036
$multiview=Get-SetupMultiviewTexture $fixtureGpu
$hi3d=Get-SetupHi3d $fixtureGpu
if ($multiview.Supported -or $multiview.Status -cnotlike 'Capacit?s CUDA NVIDIA compatibles avec MV-Adapter*' -or
    $hi3d.Supported -or $hi3d.Status -cnotlike 'Capacit?s CUDA NVIDIA compatibles avec Hi3D*') {
    throw 'Optional components did not display their incompatible GPU diagnostics in French.'
}
foreach ($capability in (Read-SetupGpuManifest).multiview_texture.compute_capabilities) {
    if (-not $multiview.Status.Contains($capability)) { throw "A supported capability was not displayed: $capability" }
}
$probeResult=Join-Path ([IO.Path]::GetTempPath()) ('trellis-preflight-locale-'+[Guid]::NewGuid()+'.ini')
try {
    & $probeScript -Action ValidateBlender -Language fr -BlenderPath $repoRoot -OutputPath $probeResult
    $ini=Get-Content -LiteralPath $probeResult -Encoding Unicode
    if ($ini -cnotcontains 'Ready=0' -or -not ($ini -clike 'Status=S?lectionnez un fichier blender.exe existant.')) {
        throw 'The Setup INI changed its machine fields or lost the French text.'
    }
} finally {
    if (Test-Path -LiteralPath $probeResult) { Remove-Item -LiteralPath $probeResult }
}
Write-Output 'Setup preflight messages follow the selected language and preserve the machine fields.'

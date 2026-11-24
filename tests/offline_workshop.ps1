$ErrorActionPreference='Stop'
$source=Split-Path -Parent $PSScriptRoot
. (Join-Path $source 'installer/windows/Offline-Workshop.ps1')
$run=(New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ('trellis-offline-'+[guid]::NewGuid().ToString('N')))).FullName
try {
    $dest=New-Item -ItemType Directory -Path (Join-Path $run 'studio')
    $locks=New-Item -ItemType Directory -Path (Join-Path $dest.FullName 'installer/locks') -Force
    Copy-Item -LiteralPath (Join-Path $source 'installer/manifest.json') -Destination $locks.Parent.FullName
    Copy-Item -LiteralPath (Join-Path $source 'installer/locks/offline-workshop-win-cp311.json') -Destination $locks.FullName
    $media=New-Item -ItemType Directory -Path (Join-Path $run 'media')
    [IO.File]::WriteAllBytes((Join-Path $media.FullName 'uv.zip'),[byte[]]@(0,1,2))
    $caught=$null
    try { Initialize-OfflineWorkshop -Root $dest.FullName -Media $media.FullName } catch { $caught=$_.Exception.Message }
    if ($caught -cne 'Offline Workshop checksum mismatch: uv.zip') { throw "Unexpected integrity result: $caught" }
    if ((Get-ChildItem -LiteralPath $dest.FullName -Force).Count -ne 1) { throw 'Validation changed the installation directory.' }
    Write-Output 'Offline Workshop rejected a modified archive before creating runtime files.'
} finally {
    $owned=Get-Item -LiteralPath $run
    if ($owned.Parent.FullName -eq (Get-Item -LiteralPath ([IO.Path]::GetTempPath())).FullName.TrimEnd('\','/') -and $owned.Name -cmatch '^trellis-offline-[a-f0-9]{32}$') {
        Remove-Item -LiteralPath $owned.FullName -Recurse -Force
    }
}

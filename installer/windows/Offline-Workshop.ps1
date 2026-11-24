function Initialize-OfflineWorkshop([string]$Root,[string]$Media,[switch]$VerifyOnly) {
    $mediaDir=(Resolve-Path -LiteralPath $Media -ErrorAction Stop).Path
    $spec=Get-Content -Raw -LiteralPath (Join-Path $Root 'installer/locks/offline-workshop-win-cp311.json') | ConvertFrom-Json
    $foundation=Get-Content -Raw -LiteralPath (Join-Path $Root 'installer/manifest.json') | ConvertFrom-Json
    $uvSource=$foundation.sources.uv
    $animations=@($foundation.assets | Where-Object {$_.group -ceq 'animations'})
    $animationArchives=@($animations | ForEach-Object {[pscustomobject]@{path=[IO.Path]::GetFileName($_.path);sha256=$_.sha256}})
    $uvArchive=[pscustomobject]@{path='uv.zip';sha256=$uvSource.sha256}
    foreach ($entry in @($uvArchive,$spec.python)+@($spec.wheels)+$animationArchives) {
        if ($entry.path -cne [IO.Path]::GetFileName($entry.path) -or $entry.sha256 -cnotmatch '^[a-f0-9]{64}$') {
            throw 'Invalid offline Workshop manifest.'
        }
        $file=Get-Item -LiteralPath (Join-Path $mediaDir $entry.path) -ErrorAction Stop
        if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ine $entry.sha256) {
            throw ('Offline Workshop checksum mismatch: '+$entry.path)
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Root 'bundled-web.json') -PathType Leaf)) {
        throw 'The offline Workshop requires the packaged Studio viewer.'
    }
    if ($VerifyOnly) {
        return @{Python=(Join-Path $Root '.venv/Scripts/python.exe'); Uv=(Join-Path $Root '.tools/offline-workshop-uv-0.13.7/uv.exe'); Media=$mediaDir}
    }
    foreach ($entry in $animations) {
        $dest=Join-Path $Root $entry.path
        if (Test-Path -LiteralPath $dest) {
            if ((Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash -ine $entry.sha256) {
                throw ('A different local animation archive was preserved: '+$entry.path)
            }
        } else {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
            Copy-Item -LiteralPath (Join-Path $mediaDir ([IO.Path]::GetFileName($entry.path))) -Destination $dest
        }
    }
    $tools=Join-Path $Root '.tools'
    $base=Join-Path $tools 'offline-workshop-cpython-3.11.18'
    $uvBase=Join-Path $tools 'offline-workshop-uv-0.13.7'
    New-Item -ItemType Directory -Force -Path $tools | Out-Null
    $stage=New-Item -ItemType Directory -Path (Join-Path $tools ('offline-workshop-'+[guid]::NewGuid().ToString('N')))
    try {
        if (-not (Test-Path -LiteralPath (Join-Path $base 'python.exe') -PathType Leaf)) {
            & tar.exe -xzf (Join-Path $mediaDir $spec.python.path) -C $stage.FullName
            if ($LASTEXITCODE -ne 0) { throw 'Offline CPython extraction failed.' }
            Move-Item -LiteralPath (Join-Path $stage.FullName 'python') -Destination $base -ErrorAction Stop
        }
        if (-not (Test-Path -LiteralPath (Join-Path $uvBase 'uv.exe') -PathType Leaf)) {
            $uvStage=Join-Path $stage.FullName 'uv'
            Expand-Archive -LiteralPath (Join-Path $mediaDir 'uv.zip') -DestinationPath $uvStage
            Move-Item -LiteralPath $uvStage -Destination $uvBase -ErrorAction Stop
        }
    } finally {
        $checked=Get-Item -LiteralPath $stage.FullName -ErrorAction SilentlyContinue
        if ($checked -and $checked.Parent.FullName -eq (Resolve-Path -LiteralPath $tools).Path -and
            $checked.Name -cmatch '^offline-workshop-[a-f0-9]{32}$') {
            Remove-Item -LiteralPath $checked.FullName -Recurse -Force
        }
    }
    return @{Python=(Join-Path $base 'python.exe'); Uv=(Join-Path $uvBase 'uv.exe'); Media=$mediaDir}
}

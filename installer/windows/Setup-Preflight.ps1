param(
    [Alias('Action')][ValidateSet('Probe','ValidateBlender')][string]$PreflightAction='Probe',
    [Alias('OutputPath')][string]$PreflightOutputPath,
    [Alias('InstallRoot')][string]$PreflightInstallRoot,
    [Alias('BlenderPath')][string]$PreflightBlenderPath,
    [Alias('GpuUuid')][string]$PreflightGpuUuid,
    [Alias('WslDistribution')][string]$PreflightWslDistribution,
    [Alias('Language','SetupLanguage')][ValidateSet('en','fr','1033','1036')][string]$PreflightSetupLanguage='en'
)

$setupPreflightFrench=@{
    'The check timed out.'="Le délai de vérification a expiré."
    'Setup GPU runtime manifest is missing. Run a complete Setup package.'="Le manifeste des composants GPU est introuvable. Lancez une version complète de l’installateur."
    'Setup GPU runtime manifest could not be read. Run a complete Setup package.'="Impossible de lire le manifeste des composants GPU. Lancez une version complète de l’installateur."
    'Setup GPU runtime manifest has an unsupported format. Run a complete Setup package.'="Le format du manifeste des composants GPU est incompatible. Lancez une version complète de l’installateur."
    'No NVIDIA CUDA GPU was detected. Workshop is available.'="Aucun GPU NVIDIA compatible CUDA n’a été détecté. L’Atelier est disponible."
    'The NVIDIA driver utility (nvidia-smi) was not found. Workshop is available.'="L’utilitaire du pilote NVIDIA (nvidia-smi) est introuvable. L’Atelier est disponible."
    'The NVIDIA detection check failed. Check the Windows NVIDIA driver.'="La détection de la carte NVIDIA a échoué. Vérifiez le pilote NVIDIA pour Windows."
    'No test runtime is available for this GPU architecture.'="Aucun moteur testé n’est disponible pour cette architecture GPU."
    'The Setup GPU runtime manifest has an invalid Windows profile for this GPU.'="Le manifeste des composants GPU contient un profil Windows invalide pour cette carte."
    'Windows GPU packages are unvalidated. Workshop is available. Kimodo uses the CPU.'="Les composants GPU pour Windows attendent une validation. L’Atelier est disponible. Kimodo utilise le processeur."
    'Update the NVIDIA Windows driver to {0} or newer for {1}.'="Mettez à jour le pilote NVIDIA pour Windows vers la version {0} ou ultérieure pour utiliser {1}."
    'Below the 12 GB VRAM reference. Try TRELLIS.2 at 512. Pixal3D may run out of memory.'="La mémoire vidéo est inférieure aux 12 Go de référence. Essayez TRELLIS.2 en 512. Pixal3D peut manquer de mémoire."
    '{0} is experimental. Setup will test the GPU kernels.'="Le composant {0} est expérimental. L’installation testera les opérations GPU."
    'Setup will verify {0} (Windows).'="L’installation vérifiera le composant {0} (Windows)."
    'The Setup GPU runtime manifest has an invalid driver floor for UniRig.'="La version minimale du pilote UniRig est invalide dans le manifeste des composants GPU."
    'Update the NVIDIA Windows driver to {0} or newer for UniRig.'="Mettez à jour le pilote NVIDIA pour Windows vers la version {0} ou ultérieure pour utiliser UniRig."
    'Setup will verify {0} (UniRig).'="L’installation vérifiera le composant {0} (UniRig)."
    'UniRig on RTX 50 is experimental. Setup tests the CUDA operations before downloading its models.'="UniRig sur RTX 50 est expérimental. L’installation teste les opérations CUDA avant de télécharger les modèles."
    'UniRig uses {0}.'="UniRig utilise {0}."
    'The Setup GPU runtime manifest has an invalid reference for UniRig.'="Le manifeste des composants GPU contient une référence invalide pour UniRig."
    'No tested UniRig package is available for {0} in this Setup.'="Cet installateur ne fournit aucun composant UniRig testé pour {0}."
    'The selected NVIDIA GPU is unavailable. Run detection again.'="Le GPU NVIDIA sélectionné est indisponible. Relancez la détection."
    'The Hi3D hardware policy is missing or invalid. Run a complete Setup package.'="Les conditions matérielles de Hi3D sont absentes ou invalides. Lancez une version complète de l’installateur."
    'Supported NVIDIA compute capabilities for Hi3D: {0}. Workshop and compatible engines remain available.'="Capacités CUDA NVIDIA compatibles avec Hi3D · {0}. L’Atelier et les moteurs compatibles restent disponibles."
    'This Hi3D package requires at least 8 GB of detected VRAM. Other components can still be installed.'="Hi3D requiert au moins 8 Go de mémoire vidéo détectée. Les autres composants restent disponibles."
    'Setup will test Hi3D CUDA kernels on the detected GPU before downloading model weights.'="L’installation testera les opérations CUDA de Hi3D sur le GPU détecté avant de télécharger les poids."
    'Less than 12 GB VRAM. Use Detail Refinement (512). The 1024 pass may run out of memory.'="Moins de 12 Go de mémoire vidéo. Utilisez l’affinage des détails en 512. La passe en 1024 peut manquer de mémoire."
    'For 1024, 12 GB VRAM or more is recommended. Memory use varies with mesh detail and other GPU activity.'="Pour l’affinage en 1024, prévoyez au moins 12 Go de mémoire vidéo. La consommation dépend du détail du maillage et des autres activités du GPU."
    'Blender can be configured later.'="Vous pouvez configurer Blender plus tard."
    'Choose blender.exe.'="Sélectionnez blender.exe."
    'Choose an existing blender.exe.'="Sélectionnez un fichier blender.exe existant."
    'Blender could not report its version. Check the executable.'="Impossible de déterminer la version de Blender. Vérifiez l’exécutable."
    'Blender {0} found.'="Blender {0} détecté."
    'Reference version: 5.2.'="Version de référence · 5.2."
    'Blender was not found. Browse to blender.exe or configure it later.'="Blender est introuvable. Sélectionnez blender.exe ou configurez-le plus tard."
    'Install and initialize Ubuntu 22.04 under WSL2 for UniRig.'="Installez et initialisez Ubuntu 22.04 sous WSL2 pour utiliser UniRig."
    '{0} is registered in WSL2. Setup will check it for UniRig.'="{0} est enregistré dans WSL2. L’installation vérifiera sa compatibilité avec UniRig."
    '{0} uses WSL1. UniRig requires WSL2.'="{0} utilise WSL1. UniRig requiert WSL2."
    'The multiview texture hardware policy is missing or invalid. Use the complete Setup package.'="Les conditions matérielles de MV-Adapter sont absentes ou invalides. Lancez une version complète de l’installateur."
    'Supported NVIDIA compute capabilities for multiview textures: {0}'="Capacités CUDA NVIDIA compatibles avec MV-Adapter · {0}"
    'Multiview texture refinement requires at least 8 GB of detected VRAM.'="L’affinage multivue requiert au moins 8 Go de mémoire vidéo détectée."
    'Setup will test FP16 CUDA on the selected GPU before downloading the model files.'="L’installation testera CUDA en FP16 sur le GPU sélectionné avant de télécharger les modèles."
    '12 GB VRAM or more is recommended. Close other GPU-heavy applications if this pass runs out of memory.'="Prévoyez au moins 12 Go de mémoire vidéo. En cas de manque de mémoire, fermez les autres applications qui sollicitent le GPU."
    'Tested on NVIDIA Ada. Allow 32 GB of system RAM and 16 GiB of disk space in addition to TRELLIS.2.'="Testé sur NVIDIA Ada. Prévoyez 32 Go de RAM et 16 Gio d’espace disque supplémentaires par rapport à TRELLIS.2."
    'The UltraTex hardware policy is missing or invalid. Use the complete Setup package.'="Les conditions matérielles d’UltraTex sont absentes ou invalides. Lancez une version complète de l’installateur."
    'UltraTex preview requires a supported NVIDIA Ampere, Ada or Blackwell GPU.'="L’aperçu UltraTex requiert un GPU NVIDIA Ampere, Ada ou Blackwell compatible."
    'UltraTex preview requires a detected NVIDIA GPU with at least 12 GB of VRAM.'="L’aperçu UltraTex requiert un GPU NVIDIA détecté disposant d’au moins 12 Go de mémoire vidéo."
    'NVIDIA GPU and 12 GB VRAM requirement met. Setup tests CUDA before downloading UltraTex.'="Le GPU NVIDIA et ses 12 Go de mémoire vidéo minimum répondent aux critères. L’installation testera CUDA avant de télécharger UltraTex."
    'Windows disk space could not be checked.'="Impossible de vérifier l’espace disque sous Windows."
    '{0} GiB available on {1}'="{0} Gio disponibles sur {1}"
    'Allow 75 GiB of free disk space for a fresh installation.'="Prévoyez 75 Gio d’espace disque libre pour une nouvelle installation."
    'The native workflows hardware policy is missing or invalid. Use the complete Setup package.'="Les conditions matérielles des profils natifs sont absentes ou invalides. Lancez une version complète de l’installateur."
    'The native workflows require a supported NVIDIA GPU (CUDA capability {0}) and at least {1} MiB of VRAM.'="Les profils natifs requièrent un GPU NVIDIA compatible (capacité CUDA {0}) et au moins {1} Mio de mémoire vidéo."
    'The detected GPU meets the requirements. Setup checks the runtimes on this GPU.'="Le GPU détecté répond aux critères. L’installation vérifiera les composants sur ce GPU."
    'Pass -OutputPath for the Setup INI result.'="Indiquez -OutputPath pour enregistrer le résultat au format INI."
}

function Get-SetupPreflightText([string]$Text, [object[]]$Values=@()) {
    if ($PreflightSetupLanguage -in ('fr','1036') -and $setupPreflightFrench.ContainsKey($Text)) {
        $Text=$setupPreflightFrench[$Text]
    }
    if ($Values.Count) { return $Text -f $Values }
    return $Text
}

function ConvertTo-SetupProcessArgument([string]$Argument) {
    # Quote for the Windows argv parser, including backslashes before quotes.
    $escaped=[regex]::Replace($Argument, '(\\*)"', '$1$1\"')
    return '"' + [regex]::Replace($escaped, '(\\+)$', '$1$1') + '"'
}

function Invoke-SetupProcess {
    param([string]$FilePath, [string[]]$Arguments, [ValidateRange(1,600)][int]$TimeoutSeconds=8)

    $process=New-Object System.Diagnostics.Process
    $process.StartInfo.FileName=$FilePath
    $process.StartInfo.Arguments=($Arguments | ForEach-Object { ConvertTo-SetupProcessArgument $_ }) -join ' '
    $process.StartInfo.UseShellExecute=$false
    $process.StartInfo.RedirectStandardOutput=$true
    $process.StartInfo.RedirectStandardError=$true
    $process.StartInfo.CreateNoWindow=$true
    try {
        [void]$process.Start()
        $stdout=$process.StandardOutput.ReadToEndAsync()
        $stderr=$process.StandardError.ReadToEndAsync()
        $deadline=[Diagnostics.Stopwatch]::StartNew()
        $exited=$process.WaitForExit($TimeoutSeconds * 1000)
        if (-not $exited -and -not $process.HasExited) {
            try { $process.Kill() } catch [InvalidOperationException] { }
        }
        $remaining=[Math]::Max(0, $TimeoutSeconds * 1000 - [int]$deadline.ElapsedMilliseconds)
        if (-not $exited -or -not [Threading.Tasks.Task]::WaitAll(@($stdout,$stderr), $remaining)) {
            return [pscustomobject]@{ExitCode=124; Output=''; Error=(Get-SetupPreflightText 'The check timed out.'); TimedOut=$true}
        }
        return [pscustomobject]@{ExitCode=$process.ExitCode; Output=$stdout.Result; Error=$stderr.Result; TimedOut=$false}
    } catch {
        return [pscustomobject]@{ExitCode=1; Output=''; Error=$_.Exception.Message; TimedOut=$false}
    } finally {
        $process.Dispose()
    }
}

function Read-SetupJson([string]$Root, [string]$RelativePath) {
    if ($Root) {
        try {
            return Get-Content -LiteralPath (Join-Path $Root $RelativePath) -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        } catch { }
    }
    return $null
}

function Read-SetupGpuManifest {
    # NSIS extracts the manifest beside the temporary script before copying the app.
    $manifestPath=Join-Path $PSScriptRoot 'gpu-runtime-profiles.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        $manifestPath=Join-Path $PSScriptRoot '..\gpu-runtime-profiles.json'
    }
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw (Get-SetupPreflightText 'Setup GPU runtime manifest is missing. Run a complete Setup package.')
    }
    try {
        $manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw (Get-SetupPreflightText 'Setup GPU runtime manifest could not be read. Run a complete Setup package.')
    }
    if ($manifest.schema -ne 1 -or $manifest.gpus -isnot [pscustomobject] -or
        $manifest.windows -isnot [pscustomobject] -or $manifest.unirig -isnot [pscustomobject]) {
        throw (Get-SetupPreflightText 'Setup GPU runtime manifest has an unsupported format. Run a complete Setup package.')
    }
    return $manifest
}

function Get-SetupGpu([string]$RequestedUuid, [switch]$AllowReselect) {
    $unavailable=[pscustomobject][ordered]@{
        Name=''; MemoryMiB=0; Driver=''; Compute=''; Uuid=''; Profile=''; WindowsRuntime=''; UniRigRuntime=''
        Supported=$false; UniRigSupported=$false; UniRigStatus=''; Experimental=$false; VramNotice=''
        Status=(Get-SetupPreflightText 'No NVIDIA CUDA GPU was detected. Workshop is available.')
    }
    $nativeSystemDir=if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
        'Sysnative'
    } else {
        'System32'
    }
    $smi=Join-Path $env:SystemRoot (Join-Path $nativeSystemDir 'nvidia-smi.exe')
    if (-not (Test-Path -LiteralPath $smi -PathType Leaf)) {
        $smi=(Get-Command nvidia-smi.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
    }
    if (-not $smi) {
        $unavailable.Status=(Get-SetupPreflightText 'The NVIDIA driver utility (nvidia-smi) was not found. Workshop is available.')
        return $unavailable
    }
    $probe=Invoke-SetupProcess -FilePath $smi -Arguments @('--query-gpu=uuid,name,memory.total,driver_version,compute_cap','--format=csv,noheader,nounits')
    if ($probe.ExitCode -ne 0) {
        $unavailable.Status=(Get-SetupPreflightText 'The NVIDIA detection check failed. Check the Windows NVIDIA driver.')
        return $unavailable
    }
    $manifest=$null
    $manifestError=''
    try { $manifest=Read-SetupGpuManifest } catch { $manifestError=$_.Exception.Message }
    $gpus=@(foreach ($line in $probe.Output -split '\r?\n') {
        $parts=@($line -split ',' | ForEach-Object { $_.Trim() })
        if ($parts.Count -ne 5 -or $parts[0] -notmatch '^GPU-[0-9a-f-]{36}$') { continue }
        $memory=0
        $driver=$null
        [void][int]::TryParse($parts[2], [ref]$memory)
        $driverKnown=[version]::TryParse($parts[3], [ref]$driver)
        $profile=''
        $windowsRuntime=''
        $unirigRuntime=''
        $supported=$false
        $unirigSupported=$false
        $unirigStatus=''
        $experimental=$false
        $vramNotice=''
        if ($manifestError) {
            $status=$manifestError
        } else {
            $plan=$manifest.gpus.PSObject.Properties[$parts[4]].Value
            if (-not $plan) {
                $status=(Get-SetupPreflightText 'No test runtime is available for this GPU architecture.')
            } else {
                $profile=[string]$plan.id
                $experimental=$plan.experimental -eq $true
                $windowsRuntime=[string]$plan.windows
                $unirigRuntime=[string]$plan.unirig
                $windowsPlan=$manifest.windows.PSObject.Properties[$windowsRuntime].Value
                $unirigPlan=$manifest.unirig.PSObject.Properties[$unirigRuntime].Value
                $driverFloor=$null
                if (-not $profile -or ($windowsRuntime -and ($windowsPlan -isnot [pscustomobject] -or -not [version]::TryParse($windowsPlan.driver_min, [ref]$driverFloor)))) {
                    $status=(Get-SetupPreflightText 'The Setup GPU runtime manifest has an invalid Windows profile for this GPU.')
                } elseif (-not $windowsRuntime) {
                    $status=(Get-SetupPreflightText 'Windows GPU packages are unvalidated. Workshop is available. Kimodo uses the CPU.')
                } elseif (-not $driverKnown -or $driver -lt $driverFloor) {
                    $status=Get-SetupPreflightText 'Update the NVIDIA Windows driver to {0} or newer for {1}.' @($driverFloor,$windowsRuntime)
                } else {
                    $supported=$true
                    if ($memory -gt 0 -and $memory -lt [int]$windowsPlan.reference_vram_mib) {
                        $vramNotice=(Get-SetupPreflightText 'Below the 12 GB VRAM reference. Try TRELLIS.2 at 512. Pixal3D may run out of memory.')
                    }
                    if ($experimental) { $status=Get-SetupPreflightText '{0} is experimental. Setup will test the GPU kernels.' @($windowsRuntime) }
                    else { $status=Get-SetupPreflightText 'Setup will verify {0} (Windows).' @($windowsRuntime) }
                }

                if ($unirigPlan -is [pscustomobject]) {
                    # A UniRig-only profile can specify its own Windows driver floor.
                    $unirigDriverFloor=$driverFloor
                    if ($unirigPlan.driver_min) {
                        $unirigDriverFloor=$null
                        [void][version]::TryParse($unirigPlan.driver_min, [ref]$unirigDriverFloor)
                    }
                    if (-not $unirigDriverFloor) {
                        $unirigStatus=(Get-SetupPreflightText 'The Setup GPU runtime manifest has an invalid driver floor for UniRig.')
                    } elseif (-not $driverKnown -or $driver -lt $unirigDriverFloor) {
                        $unirigStatus=Get-SetupPreflightText 'Update the NVIDIA Windows driver to {0} or newer for UniRig.' @($unirigDriverFloor)
                    } else {
                        $unirigSupported=$true
                        $unirigStatus=Get-SetupPreflightText 'Setup will verify {0} (UniRig).' @($unirigRuntime)
                        if ($unirigPlan.experimental -eq $true) {
                            $unirigStatus=(Get-SetupPreflightText 'UniRig on RTX 50 is experimental. Setup tests the CUDA operations before downloading its models.')
                        }
                        if ($supported) { ${status} += ' ' + (Get-SetupPreflightText 'UniRig uses {0}.' @($unirigRuntime)) }
                    }
                } elseif ($unirigRuntime) {
                    $unirigStatus=(Get-SetupPreflightText 'The Setup GPU runtime manifest has an invalid reference for UniRig.')
                } elseif ($profile) {
                    $unirigStatus=Get-SetupPreflightText 'No tested UniRig package is available for {0} in this Setup.' @($profile)
                }
            }
        }
        [pscustomobject][ordered]@{
            Name=$parts[1]; MemoryMiB=$memory; Driver=$parts[3]; Compute=$parts[4]; Uuid=$parts[0]; Profile=$profile
            WindowsRuntime=$windowsRuntime; UniRigRuntime=$unirigRuntime
            Supported=$supported; UniRigSupported=$unirigSupported; Experimental=$experimental; VramNotice=$vramNotice
            UniRigStatus=if ($unirigStatus) { $unirigStatus } else { $status }
            Status=$status
        }
    })
    if ($RequestedUuid) {
        $selected=$gpus | Where-Object Uuid -EQ $RequestedUuid | Select-Object -First 1
        if ($selected) { return $selected }
        if (-not $AllowReselect) {
            $unavailable.Status=(Get-SetupPreflightText 'The selected NVIDIA GPU is unavailable. Run detection again.')
            return $unavailable
        }
    }
    if (-not $gpus.Count) { return $unavailable }
    return $gpus | Sort-Object -Property @{Expression='Supported';Descending=$true},@{Expression='MemoryMiB';Descending=$true},Uuid | Select-Object -First 1
}

function Get-SetupHi3d([psobject]$Gpu) {
    $result=[pscustomobject][ordered]@{Supported=$false; Status=''; VramNotice=''}
    if (-not $Gpu.Supported) {
        $result.Status=$Gpu.Status
        return $result
    }
    try { $policy=(Read-SetupGpuManifest).hi3d }
    catch { $result.Status=$_.Exception.Message; return $result }
    if (-not $policy -or -not $policy.compute_capabilities.Count -or
        [int]$policy.minimum_vram_mib -le 0 -or [int]$policy.recommended_1024_vram_mib -lt [int]$policy.minimum_vram_mib) {
        $result.Status=(Get-SetupPreflightText 'The Hi3D hardware policy is missing or invalid. Run a complete Setup package.')
        return $result
    }
    if ($Gpu.Compute -notin $policy.compute_capabilities) {
        $result.Status=Get-SetupPreflightText 'Supported NVIDIA compute capabilities for Hi3D: {0}. Workshop and compatible engines remain available.' @($policy.compute_capabilities -join ', ')
        return $result
    }
    if ($Gpu.MemoryMiB -lt [int]$policy.minimum_vram_mib) {
        $result.Status=(Get-SetupPreflightText 'This Hi3D package requires at least 8 GB of detected VRAM. Other components can still be installed.')
        return $result
    }
    $result.Supported=$true
    $result.Status=(Get-SetupPreflightText 'Setup will test Hi3D CUDA kernels on the detected GPU before downloading model weights.')
    if ($Gpu.MemoryMiB -lt [int]$policy.recommended_1024_vram_mib) {
        $result.VramNotice=(Get-SetupPreflightText 'Less than 12 GB VRAM. Use Detail Refinement (512). The 1024 pass may run out of memory.')
    } else {
        $result.VramNotice=(Get-SetupPreflightText 'For 1024, 12 GB VRAM or more is recommended. Memory use varies with mesh detail and other GPU activity.')
    }
    return $result
}

function Test-SetupBlender([string]$Path) {
    $result=[pscustomobject][ordered]@{Path=''; Version=''; Ready=$false; Status=(Get-SetupPreflightText 'Blender can be configured later.')}
    if (-not $Path) { return $result }
    try {
        $candidate=Get-Item -LiteralPath $Path -ErrorAction Stop
        if ($candidate.PSIsContainer -or $candidate.Name -ine 'blender.exe') { throw (Get-SetupPreflightText 'Choose blender.exe.') }
        $result.Path=$candidate.FullName
    } catch {
        $result.Status=(Get-SetupPreflightText 'Choose an existing blender.exe.')
        return $result
    }
    $probe=Invoke-SetupProcess -FilePath $result.Path -Arguments @('--version')
    if ($probe.ExitCode -ne 0 -or $probe.Output -notmatch '(?im)^Blender ([0-9]+\.[0-9]+(?:\.[0-9]+)?)\b') {
        $result.Status=(Get-SetupPreflightText 'Blender could not report its version. Check the executable.')
        return $result
    }
    $result.Version=$Matches[1]
    $result.Ready=$true
    $result.Status=Get-SetupPreflightText 'Blender {0} found.' @($result.Version)
    if ($result.Version -notmatch '^5\.2(?:\.|$)') { $result.Status += ' ' + (Get-SetupPreflightText 'Reference version: 5.2.') }
    return $result
}

function Find-SetupBlender([string]$SavedPath) {
    $paths=@($env:TRELLIS_BLENDER, $SavedPath)
    $paths+=@((Get-Command blender.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source)
    $roots=@($env:ProgramW6432, $env:ProgramFiles)
    $roots+=@(Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue | Where-Object { $_.Root -match '^[A-Za-z]:\\$' } | ForEach-Object {
        if ([IO.DriveInfo]::new($_.Root).DriveType -eq [IO.DriveType]::Fixed) {
            $_.Root
            Join-Path $_.Root 'Program Files'
            Join-Path $_.Root 'Applications'
        }
    })
    foreach ($root in $roots | Where-Object { $_ } | Select-Object -Unique) {
        $paths+=@(Join-Path $root 'Blender\blender.exe')
        $paths+=@(Get-ChildItem -LiteralPath (Join-Path $root 'Blender Foundation') -Directory -Filter 'Blender *' -ErrorAction SilentlyContinue |
            Sort-Object -Property @{Expression={ $_.Name -like 'Blender 5.2*' };Descending=$true},@{Expression='Name';Descending=$true} |
            ForEach-Object { Join-Path $_.FullName 'blender.exe' })
    }
    # Validate the preferred executable once. Setup can browse to a different copy.
    $found=$paths | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf -ErrorAction SilentlyContinue) } | Select-Object -First 1
    if ($found) { return Test-SetupBlender -Path $found }
    $result=Test-SetupBlender -Path ''
    $result.Status=(Get-SetupPreflightText 'Blender was not found. Browse to blender.exe or configure it later.')
    return $result
}

function Get-SetupWsl([string]$RequestedDistribution) {
    $registry='HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    $distro=if ($RequestedDistribution) { $RequestedDistribution } else { 'Ubuntu-22.04' }
    $result=[pscustomobject][ordered]@{Distribution=$distro; Ready=$false; Status=(Get-SetupPreflightText 'Install and initialize Ubuntu 22.04 under WSL2 for UniRig.')}
    $registration=Get-ChildItem -LiteralPath $registry -ErrorAction SilentlyContinue | ForEach-Object {
        Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue
    } | Where-Object { $_.DistributionName -eq $distro } | Select-Object -First 1
    if ($registration.Version -eq 2 -and $distro -match '^[A-Za-z0-9_.-]{1,80}$') {
        $result.Ready=$true
        $result.Status=Get-SetupPreflightText '{0} is registered in WSL2. Setup will check it for UniRig.' @($distro)
    } elseif ($registration.Version -eq 1) {
        $result.Status=Get-SetupPreflightText '{0} uses WSL1. UniRig requires WSL2.' @($distro)
    }
    return $result
}

function Get-SetupMultiviewTexture([psobject]$Gpu) {
    $result=[pscustomobject][ordered]@{Supported=$false; Status=''; VramNotice=''}
    if (-not $Gpu.Supported) {
        $result.Status=$Gpu.Status
        return $result
    }
    try { $policy=(Read-SetupGpuManifest).multiview_texture }
    catch { $result.Status=$_.Exception.Message; return $result }
    if (-not $policy -or -not $policy.compute_capabilities.Count -or
        [int]$policy.minimum_vram_mib -le 0 -or [int]$policy.recommended_vram_mib -lt [int]$policy.minimum_vram_mib) {
        $result.Status=(Get-SetupPreflightText 'The multiview texture hardware policy is missing or invalid. Use the complete Setup package.')
        return $result
    }
    if ($Gpu.Compute -notin $policy.compute_capabilities) {
        $result.Status=Get-SetupPreflightText 'Supported NVIDIA compute capabilities for multiview textures: {0}' @($policy.compute_capabilities -join ', ')
        return $result
    }
    if ($Gpu.MemoryMiB -lt [int]$policy.minimum_vram_mib) {
        $result.Status=(Get-SetupPreflightText 'Multiview texture refinement requires at least 8 GB of detected VRAM.')
        return $result
    }
    $result.Supported=$true
    $result.Status=(Get-SetupPreflightText 'Setup will test FP16 CUDA on the selected GPU before downloading the model files.')
    if ($Gpu.MemoryMiB -lt [int]$policy.recommended_vram_mib) {
        $result.VramNotice=(Get-SetupPreflightText '12 GB VRAM or more is recommended. Close other GPU-heavy applications if this pass runs out of memory.')
    }
    return $result
}

function Get-SetupUltraTex([psobject]$Gpu) {
    $result=[pscustomobject][ordered]@{
        Supported=$false; Status=''
        Guidance=(Get-SetupPreflightText 'Tested on NVIDIA Ada. Allow 32 GB of system RAM and 16 GiB of disk space in addition to TRELLIS.2.')
    }
    if (-not $Gpu.Supported) {
        $result.Status=$Gpu.Status
        return $result
    }
    try { $policy=(Read-SetupGpuManifest).ultratex }
    catch { $result.Status=$_.Exception.Message; return $result }
    if (-not $policy -or -not $policy.compute_capabilities.Count -or [int]$policy.minimum_vram_mib -le 0) {
        $result.Status=(Get-SetupPreflightText 'The UltraTex hardware policy is missing or invalid. Use the complete Setup package.')
        return $result
    }
    if ($Gpu.Compute -notin $policy.compute_capabilities) {
        $result.Status=(Get-SetupPreflightText 'UltraTex preview requires a supported NVIDIA Ampere, Ada or Blackwell GPU.')
        return $result
    }
    if ($Gpu.MemoryMiB -lt [int]$policy.minimum_vram_mib) {
        $result.Status=(Get-SetupPreflightText 'UltraTex preview requires a detected NVIDIA GPU with at least 12 GB of VRAM.')
        return $result
    }
    $result.Supported=$true
    $result.Status=(Get-SetupPreflightText 'NVIDIA GPU and 12 GB VRAM requirement met. Setup tests CUDA before downloading UltraTex.')
    return $result
}

function Get-SetupDisk([string]$Root) {
    $result=[pscustomobject][ordered]@{FreeGiB=''; Status=(Get-SetupPreflightText 'Windows disk space could not be checked.')}
    try {
        $drive=[IO.DriveInfo]::new([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Root)))
        $result.FreeGiB=[Math]::Floor($drive.AvailableFreeSpace / 1GB)
        $result.Status=Get-SetupPreflightText '{0} GiB available on {1}' @($result.FreeGiB,$drive.Name)
    } catch { }
    return $result
}

function Get-SetupNativeWorkflows([psobject]$Gpu) {
    $result=[pscustomobject][ordered]@{
        Supported=$false; Status=''; MeshLibLicenseUrl=''
        Guidance=(Get-SetupPreflightText 'Allow 75 GiB of free disk space for a fresh installation.')
    }
    if (-not $Gpu.Supported) {
        $result.Status=$Gpu.Status
        return $result
    }
    try { $policy=(Read-SetupGpuManifest).native_workflows }
    catch { $result.Status=$_.Exception.Message; return $result }
    if (-not $policy -or -not $policy.compute_capabilities.Count -or [int]$policy.minimum_vram_mib -le 0 -or
        $policy.meshlib_license_revision -cnotmatch '^[0-9a-f]{40}$') {
        $result.Status=(Get-SetupPreflightText 'The native workflows hardware policy is missing or invalid. Use the complete Setup package.')
        return $result
    }
    if ($Gpu.Compute -notin $policy.compute_capabilities -or $Gpu.MemoryMiB -lt [int]$policy.minimum_vram_mib) {
        $capabilities=$policy.compute_capabilities -join ', '
        $result.Status=Get-SetupPreflightText 'The native workflows require a supported NVIDIA GPU (CUDA capability {0}) and at least {1} MiB of VRAM.' @($capabilities,$policy.minimum_vram_mib)
        return $result
    }
    $result.MeshLibLicenseUrl="https://github.com/MeshInspector/MeshLib/blob/$($policy.meshlib_license_revision)/LICENSE"
    $result.Supported=$true
    $result.Status=(Get-SetupPreflightText 'The detected GPU meets the requirements. Setup checks the runtimes on this GPU.')
    return $result
}

function Get-SetupInstallPlan([string]$Root) {
    $state=Read-SetupJson -Root $Root -RelativePath 'config\component-install.json'
    $saved=$state.schema -eq 1 -and $state.requested -is [array]
    $existingInstallation=$Root -and (Read-SetupJson -Root $Root -RelativePath 'bundled-web.json')
    $requested=if ($saved) {
        $state.requested
    } elseif ($existingInstallation) {
        # Earlier Windows installers did not record their component choices.
        if ((Test-Path -LiteralPath (Join-Path $Root 'models/trellis2/pipeline.json') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $Root 'engine/MODELS/dinov3/model.safetensors') -PathType Leaf)) {
            'trellis'
            if (Test-Path -LiteralPath (Join-Path $Root 'models/pixal3d/verified.json') -PathType Leaf) { 'pixal3d' }
        }
        if ((Test-Path -LiteralPath (Join-Path $Root 'UniRig/models/skeleton.ckpt') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $Root 'UniRig/models/skin.ckpt') -PathType Leaf)) {
            'unirig'
        }
    }
    $hi3dAccepted=$false
    if ($state.licenses.hi3d) {
        try { $hi3dAccepted=$state.licenses.hi3d -ceq (Read-SetupGpuManifest).hi3d.license_sha256 } catch { }
    }
    $multiviewAccepted=$false
    if ($state.licenses.multiview_texture) {
        try { $multiviewAccepted=$state.licenses.multiview_texture -ceq (Read-SetupGpuManifest).multiview_texture.license_sha256 } catch { }
    }
    $ultraTexAccepted=$false
    if ($state.licenses.ultratex) {
        try { $ultraTexAccepted=$state.licenses.ultratex -ceq (Read-SetupGpuManifest).ultratex.license_sha256 } catch { }
    }
    $nativeWorkflowsAccepted=$false
    if ($state.licenses.meshlib) {
        try {
            $manifest=Read-SetupGpuManifest
            $nativeWorkflowsAccepted=($ultraTexAccepted -or
                $state.licenses.native_workflows -ceq $manifest.ultratex.license_sha256) -and
                $state.licenses.meshlib -ceq $manifest.native_workflows.meshlib_license_revision
        } catch { }
    }
    return [pscustomobject][ordered]@{
        Saved=$saved
        NativeWorkflowsDefault=(-not $saved -and -not $existingInstallation)
        NativeWorkflows='native-workflows' -in $requested
        NativeWorkflowsLicenseAccepted=$nativeWorkflowsAccepted
        Trellis='trellis' -in $requested
        Pixal3D='pixal3d' -in $requested
        UniRig='unirig' -in $requested
        Hi3D='hi3d' -in $requested
        Hi3DLicenseAccepted=$hi3dAccepted
        MultiviewTexture='multiview-texture' -in $requested
        MultiviewTextureLicenseAccepted=$multiviewAccepted
        UltraTex='ultratex' -in $requested
        UltraTexLicenseAccepted=$ultraTexAccepted
        Kimodo='kimodo' -in $requested
    }
}

function Get-SetupPreflight {
    param([string]$InstallRoot, [string]$BlenderPath, [string]$GpuUuid, [string]$WslDistribution,
          [ValidateSet('en','fr','1033','1036')][string]$Language=$PreflightSetupLanguage)

    $PreflightSetupLanguage=$Language
    $config=Read-SetupJson -Root $InstallRoot -RelativePath 'config\runtime.json'
    $automaticGpu=-not $GpuUuid
    if ($automaticGpu) { $GpuUuid=[string]$config.gpu_uuid }
    if (-not $WslDistribution) { $WslDistribution=[string]$config.wsl_distribution }
    $blender=if ($PSBoundParameters.ContainsKey('BlenderPath')) { Test-SetupBlender -Path $BlenderPath } else { Find-SetupBlender -SavedPath ([string]$config.blender_path) }
    $gpu=Get-SetupGpu -RequestedUuid $GpuUuid -AllowReselect:$automaticGpu
    return [pscustomobject][ordered]@{
        GPU=$gpu
        NativeWorkflows=(Get-SetupNativeWorkflows -Gpu $gpu)
        Hi3D=(Get-SetupHi3d -Gpu $gpu)
        MultiviewTexture=(Get-SetupMultiviewTexture -Gpu $gpu)
        UltraTex=(Get-SetupUltraTex -Gpu $gpu)
        Blender=$blender
        WSL=(Get-SetupWsl -RequestedDistribution $WslDistribution)
        Disk=(Get-SetupDisk -Root $InstallRoot)
        Plan=(Get-SetupInstallPlan -Root $InstallRoot)
    }
}

function Write-SetupIni([string]$Path, [psobject]$Data) {
    $lines=foreach ($section in $Data.PSObject.Properties) {
        "[$($section.Name)]"
        foreach ($property in $section.Value.PSObject.Properties) {
            $value=if ($property.Value -is [bool]) { [int]$property.Value } else { ([string]$property.Value) -replace '[\r\n\x00]', ' ' }
            "$($property.Name)=$value"
        }
        ''
    }
    [IO.File]::WriteAllLines($Path, [string[]]$lines, [Text.Encoding]::Unicode)
}

if ($MyInvocation.InvocationName -ne '.') {
    $ErrorActionPreference='Stop'
    if (-not $PreflightOutputPath) { throw (Get-SetupPreflightText 'Pass -OutputPath for the Setup INI result.') }
    if ($PreflightAction -eq 'ValidateBlender') {
        Write-SetupIni -Path $PreflightOutputPath -Data ([pscustomobject]@{Blender=(Test-SetupBlender -Path $PreflightBlenderPath)})
    } else {
        $options=@{}
        foreach ($key in @('InstallRoot','BlenderPath','GpuUuid','WslDistribution')) {
            $parameter='Preflight'+$key
            if ($PSBoundParameters.ContainsKey($parameter)) { $options[$key]=$PSBoundParameters[$parameter] }
        }
        Write-SetupIni -Path $PreflightOutputPath -Data (Get-SetupPreflight @options)
    }
}

$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$windows=Join-Path $root 'installer\windows'

foreach ($name in @('Install-Components.ps1','Launch-Installed.ps1','Manage-Shortcuts.ps1')) {
    $path=Join-Path $windows $name
    $tokens=$null
    $errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw ($errors -join [Environment]::NewLine) }
}

$source=Get-Content -LiteralPath (Join-Path $windows 'StudioSetup.nsi') -Raw -Encoding UTF8
$translations=[regex]::Matches($source,'(?m)^\s*LangString\s+(\w+)\s+\$\{LANG_(ENGLISH|FRENCH)\}')
foreach ($entry in ($translations | Group-Object { $_.Groups[1].Value })) {
    $english=@($entry.Group | Where-Object { $_.Groups[2].Value -eq 'ENGLISH' }).Count
    $french=@($entry.Group | Where-Object { $_.Groups[2].Value -eq 'FRENCH' }).Count
    if ($english -eq 0 -or $english -ne $french) { throw "Unpaired NSIS translation: $($entry.Name)" }
}
foreach ($text in @('!insertmacro MUI_LANGUAGE "French"','!insertmacro MUI_LANGDLL_DISPLAY',
                   '!insertmacro MUI_UNGETLANGUAGE','-SetupLanguage $LANGUAGE','-Language $SetupCulture')) {
    if (-not $source.Contains($text)) { throw "Installer localization is missing: $text" }
}

. (Join-Path $windows 'Install-Components.ps1')
$stage=Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
[void][IO.Directory]::CreateDirectory($stage)
try {
    $setupState=@{components=@{}}
    $setupStatePath=Join-Path $stage 'receipt.json'
    $setupFrench=$true
    $output=(Set-GuidedComponentResult 'workshop' 'ready' 'Verification completed.' 6>&1 | Out-String)
    $expected='Atelier: pr' + [char]0x00EA + 't.'
    if (-not $output.Contains($expected)) { throw "Repair did not present the French text: $output" }
    $receipt=Get-Content -LiteralPath $setupStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($receipt.components.workshop.status -cne 'ready' -or
        $receipt.components.workshop.message -cne 'Verification completed.') {
        throw 'Translating the repair output changed its existing receipt contract.'
    }
    $setupFrench=$false
    $output=(Set-GuidedComponentResult 'workshop' 'ready' 'Verification completed.' 6>&1 | Out-String)
    if (-not $output.Contains('workshop: ready. Verification completed.')) { throw "Wrong English repair output: $output" }
} finally {
    foreach ($file in @($setupStatePath)) {
        if ($file -and [IO.File]::Exists($file)) { [IO.File]::Delete($file) }
    }
    [IO.Directory]::Delete($stage)
}

Write-Host "Windows setup localization passed ($($translations.Count) NSIS strings)."

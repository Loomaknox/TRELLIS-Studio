param([Parameter(Mandatory=$true)][string]$ConfigPath, [Parameter(Mandatory=$true)][string]$Python)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
& (Join-Path $PSScriptRoot 'check-idle.ps1') -InstallRoot $taskRoot -IgnoreCurrentProcess -IgnoreTray
try {$taskConfigureLock=[IO.File]::Open((Join-Path $taskRoot '.component-install.lock'),'OpenOrCreate','ReadWrite','None')}
catch [IO.IOException] {throw 'Another TRELLIS startup, configuration or installation is running. Wait for it to finish.'}
try {
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$taskExisting=$null
if(Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
    $taskExisting=Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
$taskPreview=Test-Path -LiteralPath (Join-Path $taskRoot '.trellis-setup-test') -PathType Leaf
$taskDefaultPort=if($taskPreview){'7892'}else{'7862'}
$taskDefaultData=if($taskPreview){Join-Path $taskRoot 'server-data'}elseif(Test-Path -LiteralPath (Join-Path $taskRoot 'bundled-web.json')){
    Join-Path $env:LOCALAPPDATA 'TRELLIS Studio Server\data'
}else{Join-Path $taskRoot 'server-data'}
if($taskPreview -and $taskExisting -and ($taskExisting.host -ne '127.0.0.1' -or $taskExisting.reverse_proxy -or $taskExisting.tls_cert -or
    $taskExisting.autostart -or $taskExisting.data_dir -ine $taskDefaultData)) {
    throw 'The Setup Test is restricted to its own local server data and loopback access. Existing settings were preserved.'
}
$taskForm=New-Object Windows.Forms.Form
$taskForm.Text='TRELLIS Server Setup'
$taskForm.StartPosition='CenterScreen'
$taskForm.AutoScaleMode='Font'
$taskForm.ClientSize=New-Object Drawing.Size(780,660)
$taskForm.FormBorderStyle='FixedDialog'
$taskForm.MaximizeBox=$false
$taskForm.MinimizeBox=$false
function Add-Label([string]$Text,[int]$X,[int]$Y,[int]$Width,[int]$Height=25) {
    $label=New-Object Windows.Forms.Label
    $label.Text=$Text
    $label.SetBounds($X,$Y,$Width,$Height)
    $taskForm.Controls.Add($label)
    return $label
}
function Add-Field([string]$Name,[string]$Value,[int]$Y,[string]$Picker='') {
    $label=Add-Label $Name 20 ($Y+4) 206
    $field=New-Object Windows.Forms.TextBox
    $field.Text=$Value
    $field.SetBounds(230,$Y,$(if($Picker){432}else{528}),25)
    $taskForm.Controls.Add($field)
    $browse=$null
    if($Picker) {
        $browse=New-Object Windows.Forms.Button
        $browse.Text='Browse'
        $browse.SetBounds(674,($Y-1),84,27)
        $browse.Add_Click({
            if($Picker -eq 'folder') {
                $dialog=New-Object Windows.Forms.FolderBrowserDialog
                $dialog.SelectedPath=$field.Text
            } else {
                $dialog=New-Object Windows.Forms.OpenFileDialog
                $dialog.Filter='PEM files (*.pem;*.crt;*.key)|*.pem;*.crt;*.key|All files (*.*)|*.*'
            }
            try {
                if($dialog.ShowDialog() -eq 'OK') {
                    $field.Text=if($Picker -eq 'folder'){$dialog.SelectedPath}else{$dialog.FileName}
                }
            } finally {$dialog.Dispose()}
        }.GetNewClosure())
        $taskForm.Controls.Add($browse)
    }
    $field.Tag=@{Label=$label; Browse=$browse}
    return $field
}
function Set-FieldVisible($Field,[bool]$Visible) {
    $Field.Visible=$Visible
    $Field.Tag.Label.Visible=$Visible
    if($Field.Tag.Browse){$Field.Tag.Browse.Visible=$Visible}
}
function Existing([string]$Name,[string]$Default='') {
    if($taskExisting -and $null -ne $taskExisting.$Name){return [string]$taskExisting.$Name}
    return $Default
}
$title=Add-Label 'Configure TRELLIS Server' 20 14 738 32
$title.Font=New-Object Drawing.Font($title.Font.FontFamily,15,[Drawing.FontStyle]::Bold)
[void](Add-Label 'Create the administrator locally in your browser. Two-factor authentication is required for administrators; other users can enable it.' 20 52 738 42)
$data=Add-Field 'Library data folder' (Existing 'data_dir' $taskDefaultData) 104 'folder'
$data.ReadOnly=$taskPreview -or [bool]$taskExisting
if($data.ReadOnly){$data.Tag.Browse.Enabled=$false}
[void](Add-Label 'Access mode' 20 146 206)
$access=New-Object Windows.Forms.ComboBox
$access.DropDownStyle='DropDownList'
[void]$access.Items.Add('This PC only (accounts, no network)')
if(-not $taskPreview){$access.Items.AddRange(@('Local network / own HTTPS certificate','Internet / automatic HTTPS with Caddy'))}
$access.SetBounds(230,142,528,27)
$taskForm.Controls.Add($access)
$bind=Add-Field 'IPv4 listen address' (Existing 'host' '127.0.0.1') 184
$port=Add-Field 'Server port' (Existing 'port' $taskDefaultPort) 220
$url=Add-Field 'Browser address' (Existing 'public_url' ('http://127.0.0.1:'+$taskDefaultPort)) 256
$url.ReadOnly=$taskPreview
$cert=Add-Field 'HTTPS certificate (PEM)' (Existing 'tls_cert') 292 'file'
$key=Add-Field 'Private key (PEM)' (Existing 'tls_key') 328 'file'
$oldDomain=''; $oldPublicPort='443'
if($taskExisting.reverse_proxy) {
    $oldUri=[Uri]$taskExisting.public_url
    $oldDomain=$oldUri.DnsSafeHost; $oldPublicPort=[string]$oldUri.Port
}
$domain=Add-Field 'Your public domain' $oldDomain 184
$publicPort=Add-Field 'Public HTTPS port' $oldPublicPort 220
$proxyPort=Add-Field 'HTTPS port on this PC' (Existing 'proxy_port' '443') 256
$backendPort=Add-Field 'Private backend port' $(if($taskExisting.reverse_proxy){[string]$taskExisting.port}else{'7863'}) 292
$adminPort=Add-Field 'Private proxy admin port' (Existing 'proxy_admin_port' '2019') 328
$advanced=New-Object Windows.Forms.CheckBox
$advanced.Text='Advanced ports (public address, private backend and proxy admin)'
$advanced.SetBounds(230,256,528,27)
$advanced.Checked=$taskExisting.reverse_proxy -and ($oldPublicPort -ne '443' -or $taskExisting.port -ne 7863 -or $taskExisting.proxy_admin_port -ne 2019)
$taskForm.Controls.Add($advanced)
$help=Add-Label '' 20 372 738 106
$firewall=New-Object Windows.Forms.CheckBox
$firewall.Text='Allow this HTTPS port in Windows Firewall (administrator approval)'
$firewall.SetBounds(20,488,738,27)
$taskForm.Controls.Add($firewall)
$autostart=New-Object Windows.Forms.CheckBox
$autostart.Text='Start the server and its tray icon when I sign in to Windows'
$autostart.Checked=[bool]$taskExisting.autostart
$autostart.Enabled=-not $taskPreview
$autostart.SetBounds(20,522,738,27)
$taskForm.Controls.Add($autostart)
$privacy=Add-Label 'Settings, accounts, libraries and certificates remain on this PC. Changing access mode preserves the existing server library.' 20 558 738 40
$cancel=New-Object Windows.Forms.Button
$cancel.Text='Cancel'; $cancel.DialogResult='Cancel'; $cancel.SetBounds(548,614,98,29)
$save=New-Object Windows.Forms.Button
$save.Text='Continue'; $save.SetBounds(658,614,100,29)
$taskForm.Controls.Add($cancel); $taskForm.Controls.Add($save)
$taskForm.CancelButton=$cancel; $taskForm.AcceptButton=$save
function Update-AccessFields {
    $internet=$access.SelectedIndex -eq 2
    foreach($field in @($bind,$port,$url,$cert,$key)){Set-FieldVisible $field (-not $internet)}
    foreach($field in @($domain,$publicPort,$proxyPort,$backendPort,$adminPort)){Set-FieldVisible $field $internet}
    $advanced.Visible=$internet
    if($internet){
        $proxyPort.Top=220; $proxyPort.Tag.Label.Top=224
        $publicPort.Top=292; $publicPort.Tag.Label.Top=296
        $backendPort.Top=328; $backendPort.Tag.Label.Top=332
        $adminPort.Top=364; $adminPort.Tag.Label.Top=368
        foreach($field in @($publicPort,$backendPort,$adminPort)){Set-FieldVisible $field $advanced.Checked}
        $help.Top=if($advanced.Checked){408}else{292}
    }else{$help.Top=372}
    $firewall.Top=$help.Top+116
    $autostart.Top=$help.Top+150
    $privacy.Top=$help.Top+186
    $cancel.Top=$save.Top=$help.Top+242
    $taskForm.ClientSize=New-Object Drawing.Size(780,($help.Top+288))
    $firewall.Visible=$internet
    $bind.ReadOnly=$access.SelectedIndex -eq 0
    $cert.Enabled=$key.Enabled=$access.SelectedIndex -eq 1
    $cert.Tag.Browse.Enabled=$key.Tag.Browse.Enabled=$access.SelectedIndex -eq 1
    if($internet) {
        $shownDomain=if($domain.Text.Trim()){$domain.Text.Trim()}else{'your domain'}
        $help.Text="Point $shownDomain (DNS A, and AAAA only if IPv6 works) at your public IP. Forward router TCP 443 to this PC, port $($proxyPort.Text). Caddy obtains and renews the certificate using port 443. If the public browser port differs, forward it too to the same PC port. The router and DNS must be configured by you. Carrier-grade NAT requires an alternative route. Backend and proxy admin stay private on 127.0.0.1."
    } elseif($access.SelectedIndex -eq 1) {
        $help.Text='Use this PC''s LAN IP or DNS name in the browser address, with a certificate trusted by client devices. The address must match the certificate. Use 0.0.0.0 to listen on all IPv4 interfaces. Allow the selected server TCP port in your firewall. No router forwarding is needed for LAN-only access.'
    } else {
        $help.Text='Server accounts and separate libraries are available only on this PC. The browser address must use http://127.0.0.1:<port> or localhost. The single-user Desktop mode remains available from its own shortcut.'
    }
}
$access.Add_SelectedIndexChanged({
    if($access.SelectedIndex -eq 0){$bind.Text='127.0.0.1'; $url.Text='http://127.0.0.1:'+$port.Text}
    elseif($access.SelectedIndex -eq 1 -and $bind.Text -eq '127.0.0.1'){$bind.Text='0.0.0.0'; $url.Text='https://'}
    Update-AccessFields
})
$domain.Add_TextChanged({Update-AccessFields})
$proxyPort.Add_TextChanged({Update-AccessFields})
$publicPort.Add_TextChanged({Update-AccessFields})
$advanced.Add_CheckedChanged({Update-AccessFields})
$port.Add_TextChanged({if($access.SelectedIndex -eq 0){$url.Text='http://127.0.0.1:'+$port.Text}})
$access.SelectedIndex=if($taskExisting.reverse_proxy){2}elseif($taskExisting -and ($taskExisting.host -ne '127.0.0.1' -or $taskExisting.tls_cert)){1}else{0}
# Preserve saved values after the selection event.
if($taskExisting -and -not $taskPreview -and -not $taskExisting.reverse_proxy){$bind.Text=$taskExisting.host; $url.Text=$taskExisting.public_url}
function Get-ServerPreferences {
    $settings=@{data_dir=$data.Text.Trim(); autostart=$autostart.Checked; reverse_proxy=($access.SelectedIndex -eq 2)}
    # Preserve migration paths: existing firewall rules and ACME registrations use them.
    foreach($name in @('proxy_executable','proxy_storage')) {
        if($taskExisting -and $taskExisting.$name){$settings[$name]=[string]$taskExisting.$name}
    }
    if($settings.reverse_proxy) {
        $name=$domain.Text.Trim()
        if($name -match '[/\\:@\s]'){throw 'Enter a domain only, without https://, a port or a path.'}
        $suffix=if($publicPort.Text.Trim() -eq '443'){''}else{':'+$publicPort.Text.Trim()}
        $settings.host='127.0.0.1'; $settings.port=$backendPort.Text.Trim()
        $settings.public_url='https://'+$name+$suffix
        $settings.proxy_port=$proxyPort.Text.Trim(); $settings.proxy_admin_port=$adminPort.Text.Trim()
        $settings.tls_cert=''; $settings.tls_key=''
    } else {
        $settings.host=$bind.Text.Trim(); $settings.port=$port.Text.Trim(); $settings.public_url=$url.Text.Trim()
        $settings.tls_cert=if($access.SelectedIndex -eq 1){$cert.Text.Trim()}else{''}
        $settings.tls_key=if($access.SelectedIndex -eq 1){$key.Text.Trim()}else{''}
    }
    return $settings
}
function Invoke-SettingsCheck($Settings) {
    # This validation process never spawns background services.
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$Python
    $info.Arguments='-B "'+(Join-Path $taskRoot 'server_setup.py')+'" --config "'+$ConfigPath+'" --validate-only'
    $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true; $info.RedirectStandardError=$true; $info.RedirectStandardOutput=$true
    $info.StandardErrorEncoding=[Text.UTF8Encoding]::new($false)
    $info.EnvironmentVariables['PYTHONIOENCODING']='utf-8'
    $process=[Diagnostics.Process]::Start($info)
    try {
        $errorTask=$process.StandardError.ReadToEndAsync(); $outputTask=$process.StandardOutput.ReadToEndAsync()
        $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Settings|ConvertTo-Json -Compress))
        $process.StandardInput.BaseStream.Write($bytes,0,$bytes.Length)
        $process.StandardInput.BaseStream.Flush(); $process.StandardInput.Close()
        if(-not $process.WaitForExit(15000)){throw 'Configuration validation timed out. Close setup and retry.'}
        if($process.ExitCode -ne 0){throw $errorTask.Result.Trim()}
    } finally {$process.Dispose()}
}
$save.Add_Click({
    try {
        $taskForm.Tag=Get-ServerPreferences
        Invoke-SettingsCheck $taskForm.Tag
        $taskForm.DialogResult='OK'
    } catch {[void][Windows.Forms.MessageBox]::Show($taskForm,$_.Exception.Message,'Check your server settings','OK','Warning')}
})
try {
    while($true) {
        if($taskForm.ShowDialog() -ne 'OK'){throw 'Server setup was cancelled. Previous saved settings were preserved.'}
        try {
            $settings=$taskForm.Tag
            if($settings.reverse_proxy) {
                $proxyDirectory=if($settings.proxy_executable){Split-Path -Parent $settings.proxy_executable}else{Join-Path $taskRoot 'bin\caddy'}
                & $Python -B (Join-Path $taskRoot 'installer\install_caddy.py') --ensure --destination $proxyDirectory
                if($LASTEXITCODE -ne 0){throw 'The verified HTTPS proxy could not be installed. Check the download message and retry.'}
            }
            $OutputEncoding=[Text.UTF8Encoding]::new($false)
            $settings | ConvertTo-Json -Compress | & $Python -B (Join-Path $taskRoot 'server_setup.py') --config $ConfigPath
            if($LASTEXITCODE -ne 0){throw 'Server setup did not finish. Review the message above, then retry. Accounts already created are retained.'}
            if($settings.reverse_proxy -and $firewall.Checked) {
                $arguments='-NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $PSScriptRoot 'Configure-Firewall.ps1')+'" -ConfigPath "'+$ConfigPath+'"'
                $ruleProcess=Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -ArgumentList $arguments -Verb RunAs -WindowStyle Hidden -PassThru -Wait
                if($ruleProcess.ExitCode -ne 0){throw 'Settings were saved, but the HTTPS firewall rule could not be created. Retry or uncheck the firewall option to configure it yourself.'}
            }
            & (Join-Path $PSScriptRoot 'Manage-Shortcuts.ps1') -InstallRoot $taskRoot -Action ServerStartup
            break
        } catch {
            $answer=[Windows.Forms.MessageBox]::Show($_.Exception.Message,'TRELLIS Server setup','RetryCancel','Warning')
            if($answer -ne 'Retry'){throw}
            $taskForm.DialogResult='None'
        }
    }
} finally {$taskForm.Dispose()}
} finally {$taskConfigureLock.Dispose()}

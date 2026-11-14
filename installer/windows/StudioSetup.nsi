Unicode true
ManifestDPIAware true
RequestExecutionLevel user
Name "TRELLIS Studio"
OutFile "${OUTPUT_EXE}"
InstallDir "$LOCALAPPDATA\Programs\TRELLIS Studio"
InstallDirRegKey HKCU "Software\TRELLIS Studio" "InstallDir"
SetCompressor /SOLID lzma
ShowInstDetails show
VIProductVersion "${STUDIO_VERSION}.0"
VIAddVersionKey "ProductName" "TRELLIS Studio"
VIAddVersionKey "FileDescription" "TRELLIS Studio Windows Setup"
VIAddVersionKey "FileVersion" "${STUDIO_VERSION}"
VIAddVersionKey "ProductVersion" "${STUDIO_VERSION}"
VIAddVersionKey "CompanyName" "TRELLIS Studio contributors"
VIAddVersionKey "LegalCopyright" "TRELLIS Studio contributors (MIT)"

!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"
!include "nsDialogs.nsh"
!define ARP "Software\Microsoft\Windows\CurrentVersion\Uninstall\TRELLIS Studio"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION StartStudio
!define MUI_FINISHPAGE_RUN_TEXT "$(LaunchLabel)"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!define MUI_ICON "${PAYLOAD_ROOT}\installer\windows\trellis-studio.ico"
!define MUI_UNICON "${PAYLOAD_ROOT}\installer\windows\trellis-studio.ico"

Var InstallFull
Var FullRadio
Var InstallServer
Var ServerRadio
Var CreateDesktopShortcut
Var DesktopCheckbox
Var InstallKimodo
Var KimodoCheckbox
Var AcceptKimodoLicenses
Var KimodoLicenseCheckbox
Var KimodoArguments

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
Page custom ShowInstallMode SaveInstallMode
Page custom ShowComponentMode SaveComponentMode
Page custom ShowKimodoOptions SaveKimodoOptions
Page custom ShowShortcutOptions SaveShortcutOptions
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

LangString LaunchLabel ${LANG_ENGLISH} "Open TRELLIS from its tray icon"
LangString WrongPlatform ${LANG_ENGLISH} "TRELLIS Studio requires Windows x64 on an Intel or AMD processor."
LangString DifferentInstall ${LANG_ENGLISH} "The selected folder already contains a source installation. Setup did not change it."
LangString StudioRunning ${LANG_ENGLISH} "This copy of TRELLIS or its installer is still running. Stop Desktop / Server, then quit its tray icon before continuing. No process was stopped."
LangString MarkerFailed ${LANG_ENGLISH} "Setup could not prepare the installation folder: $INSTDIR. Check that the folder is writable and run Setup again."
LangString PayloadFailed ${LANG_ENGLISH} "Setup could not copy all application files to $INSTDIR. Close any program using those files and run Setup again."
LangString CloseForUninstall ${LANG_ENGLISH} "This copy of TRELLIS Studio is running in the background. Stop it and continue uninstalling? Your library will be kept."
LangString BusyUninstall ${LANG_ENGLISH} "Studio is running a generation or export. Let it finish before uninstalling."
LangString CannotCloseForUninstall ${LANG_ENGLISH} "Stop TRELLIS Studio or TRELLIS Server from the Start menu and close any MCP client or component installer, then try again."
LangString InstallModeTitle ${LANG_ENGLISH} "Choose how to use TRELLIS"
LangString InstallModeSubtitle ${LANG_ENGLISH} "Choose the edition before selecting the components."
LangString DesktopModeChoice ${LANG_ENGLISH} "TRELLIS Desktop (single user)"
LangString DesktopModeDescription ${LANG_ENGLISH} "Use your local library on this PC without creating an account."
LangString ServerChoice ${LANG_ENGLISH} "TRELLIS Server (multi-user)"
LangString ServerDescription ${LANG_ENGLISH} "Choose local access, your LAN certificate, or Internet access with your domain and automatic HTTPS. Configure the data folder, optional startup and first administrator."
LangString ComponentModeTitle ${LANG_ENGLISH} "Choose the components"
LangString ComponentModeSubtitle ${LANG_ENGLISH} "Choose the workshop or install the generation and rigging engines as well."
LangString WorkshopChoice ${LANG_ENGLISH} "Workshop only"
LangString WorkshopDescription ${LANG_ENGLISH} "Library, 3D viewer and GLB import/export. Setup downloads Python dependencies; no AI models or NVIDIA GPU required."
LangString FullChoice ${LANG_ENGLISH} "Full Studio (TRELLIS.2, UniRig and Pixal3D)"
LangString FullDescription ${LANG_ENGLISH} "About 29 GiB of models plus dependencies. Requires NVIDIA CUDA, Blender and Ubuntu 22.04 in WSL2."
LangString InstallingServer ${LANG_ENGLISH} "Preparing the server. Continue in the TRELLIS PowerShell window and complete administrator setup in the browser."
LangString ServerFailed ${LANG_ENGLISH} "Server setup did not finish. Review the console messages and run Setup again to resume."
LangString InstallingFull ${LANG_ENGLISH} "Installing the engines. Continue in the TRELLIS Studio PowerShell window."
LangString InstallingWorkshop ${LANG_ENGLISH} "Preparing the Workshop and tray application. Python dependencies are downloaded automatically."
LangString WorkshopFailed ${LANG_ENGLISH} "The application files are installed, but Workshop preparation did not finish. Review the console and run Setup again to resume."
LangString FullFailed ${LANG_ENGLISH} "The workshop is installed, but the full setup did not finish. See $INSTDIR\logs\full-setup.log and run Setup again to resume."
LangString FullConsoleFailed ${LANG_ENGLISH} "The workshop is installed, but Setup could not open the console. Run Setup again or install the engines from the Start menu."
LangString ShortcutOptionsTitle ${LANG_ENGLISH} "Shortcuts"
LangString ShortcutOptionsSubtitle ${LANG_ENGLISH} "Choose where to open TRELLIS Studio."
LangString StartMenuDescription ${LANG_ENGLISH} "The Start menu opens a tray icon to start, stop and open TRELLIS. Quitting the icon keeps the application running."
LangString DesktopChoice ${LANG_ENGLISH} "Create a desktop shortcut"
LangString ShortcutError ${LANG_ENGLISH} "Studio files are installed, but one or more shortcuts could not be created. You can launch Studio with $INSTDIR\installer\windows\Launch.cmd."
LangString KimodoTitle ${LANG_ENGLISH} "Optional motion generation"
LangString KimodoSubtitle ${LANG_ENGLISH} "Available with Workshop or Full Studio, in both Desktop and Server."
LangString KimodoChoice ${LANG_ENGLISH} "Install Kimodo text-to-motion (optional)"
LangString KimodoDescription ${LANG_ENGLISH} "Create reusable humanoid animations from text on the CPU. About 9.3 GB of model weights plus portable build tools. No NVIDIA GPU or CUDA required."
LangString KimodoRequirements ${LANG_ENGLISH} "Needs WSL2 Linux x64, Python 3.10+, an AVX2/FMA/F16C CPU and 12 GiB free in WSL. Setup guides you if WSL is missing; Windows may require a restart."
LangString KimodoNvidiaLicense ${LANG_ENGLISH} "Read the NVIDIA Open Model License"
LangString KimodoLlamaLicense ${LANG_ENGLISH} "Read the Meta Llama 3 Community License (text encoder)"
LangString KimodoAccept ${LANG_ENGLISH} "I have read and accept both model licenses for the optional Kimodo installation."
LangString KimodoLicenseRequired ${LANG_ENGLISH} "Accept both model licenses to install Kimodo, or clear the optional Kimodo selection."

Function .onInit
  ; Ignore language preferences saved by previous bilingual installers.
  StrCpy $LANGUAGE ${LANG_ENGLISH}
  StrCpy $InstallFull "0"
  StrCpy $InstallServer "0"
  IfFileExists "$INSTDIR\config\server.json" 0 +2
  StrCpy $InstallServer "1"
  StrCpy $CreateDesktopShortcut "0"
  StrCpy $InstallKimodo "0"
  StrCpy $AcceptKimodoLicenses "0"
  ${IfNot} ${IsNativeAMD64}
    MessageBox MB_ICONSTOP "$(WrongPlatform)" /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
FunctionEnd

Function ShowInstallMode
  !insertmacro MUI_HEADER_TEXT "$(InstallModeTitle)" "$(InstallModeSubtitle)"
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateFirstRadioButton} 0 6u 100% 13u "$(DesktopModeChoice)"
  Pop $1
  ${NSD_CreateLabel} 13u 23u -13u 25u "$(DesktopModeDescription)"
  Pop $0
  ${NSD_CreateAdditionalRadioButton} 0 55u 100% 13u "$(ServerChoice)"
  Pop $ServerRadio
  ${NSD_CreateLabel} 13u 72u -13u 34u "$(ServerDescription)"
  Pop $0
  ${If} $InstallServer == "1"
    ${NSD_Check} $ServerRadio
  ${Else}
    ${NSD_Check} $1
  ${EndIf}
  nsDialogs::Show
FunctionEnd

Function SaveInstallMode
  ${NSD_GetState} $ServerRadio $InstallServer
FunctionEnd

Function ShowComponentMode
  !insertmacro MUI_HEADER_TEXT "$(ComponentModeTitle)" "$(ComponentModeSubtitle)"
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateFirstRadioButton} 0 6u 100% 13u "$(WorkshopChoice)"
  Pop $1
  ${NSD_CreateLabel} 13u 23u -13u 25u "$(WorkshopDescription)"
  Pop $0
  ${NSD_CreateAdditionalRadioButton} 0 55u 100% 13u "$(FullChoice)"
  Pop $FullRadio
  ${NSD_CreateLabel} 13u 72u -13u 34u "$(FullDescription)"
  Pop $0
  ${If} $InstallFull == "1"
    ${NSD_Check} $FullRadio
  ${Else}
    ${NSD_Check} $1
  ${EndIf}
  nsDialogs::Show
FunctionEnd

Function SaveComponentMode
  ${NSD_GetState} $FullRadio $InstallFull
FunctionEnd

Function OpenKimodoNvidiaLicense
  ExecShell "open" "https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/"
FunctionEnd

Function OpenKimodoLlamaLicense
  ExecShell "open" "https://huggingface.co/LocalAI-io/Llama-3-Kimodo-GGML/blob/f583f3ee2b093f6d9ec524463b4152622abf11a6/LICENSE-META-LLAMA-3.txt"
FunctionEnd

Function KimodoChoiceChanged
  ${NSD_GetState} $KimodoCheckbox $InstallKimodo
  EnableWindow $KimodoLicenseCheckbox $InstallKimodo
FunctionEnd

Function KimodoLicenseChanged
  ${NSD_GetState} $KimodoLicenseCheckbox $AcceptKimodoLicenses
FunctionEnd

Function ShowKimodoOptions
  !insertmacro MUI_HEADER_TEXT "$(KimodoTitle)" "$(KimodoSubtitle)"
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateCheckbox} 0 3u 100% 15u "$(KimodoChoice)"
  Pop $KimodoCheckbox
  ${NSD_OnClick} $KimodoCheckbox KimodoChoiceChanged
  ${NSD_CreateLabel} 13u 19u -13u 24u "$(KimodoDescription)"
  Pop $0
  ${NSD_CreateLabel} 13u 45u -13u 27u "$(KimodoRequirements)"
  Pop $0
  ${NSD_CreateLink} 13u 76u -13u 10u "$(KimodoNvidiaLicense)"
  Pop $0
  ${NSD_OnClick} $0 OpenKimodoNvidiaLicense
  ${NSD_CreateLink} 13u 90u -13u 10u "$(KimodoLlamaLicense)"
  Pop $0
  ${NSD_OnClick} $0 OpenKimodoLlamaLicense
  ${NSD_CreateCheckbox} 0 104u 100% 22u "$(KimodoAccept)"
  Pop $KimodoLicenseCheckbox
  ${NSD_OnClick} $KimodoLicenseCheckbox KimodoLicenseChanged
  ${If} $InstallKimodo == "1"
    ${NSD_Check} $KimodoCheckbox
  ${EndIf}
  ${If} $AcceptKimodoLicenses == "1"
    ${NSD_Check} $KimodoLicenseCheckbox
  ${EndIf}
  EnableWindow $KimodoLicenseCheckbox $InstallKimodo
  nsDialogs::Show
FunctionEnd

Function SaveKimodoOptions
  ${NSD_GetState} $KimodoCheckbox $InstallKimodo
  ${NSD_GetState} $KimodoLicenseCheckbox $AcceptKimodoLicenses
  ${If} $InstallKimodo == "1"
  ${AndIf} $AcceptKimodoLicenses != "1"
    MessageBox MB_ICONEXCLAMATION "$(KimodoLicenseRequired)" /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Function ShowShortcutOptions
  !insertmacro MUI_HEADER_TEXT "$(ShortcutOptionsTitle)" "$(ShortcutOptionsSubtitle)"
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 6u 100% 20u "$(StartMenuDescription)"
  Pop $0
  ${NSD_CreateCheckbox} 0 31u 100% 16u "$(DesktopChoice)"
  Pop $DesktopCheckbox
  ${If} $CreateDesktopShortcut == "1"
    ${NSD_Check} $DesktopCheckbox
  ${EndIf}
  nsDialogs::Show
FunctionEnd

Function SaveShortcutOptions
  ${NSD_GetState} $DesktopCheckbox $CreateDesktopShortcut
FunctionEnd

Function StartStudio
  ${If} $InstallServer == "1"
    ExecShell "open" "$INSTDIR\TRELLIS Studio Tray.exe" "--mode server --start"
  ${Else}
    ExecShell "open" "$INSTDIR\TRELLIS Studio Tray.exe" "--mode desktop --start"
  ${EndIf}
FunctionEnd

!macro ReadStudioState ExtraArguments
  InitPluginsDir
  File /oname=$PLUGINSDIR\check-idle.ps1 "${PAYLOAD_ROOT}\installer\windows\check-idle.ps1"
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\check-idle.ps1" -InstallRoot "$INSTDIR" ${ExtraArguments}'
  Pop $0
  Pop $1
!macroend

!macro CheckIdle
  !insertmacro ReadStudioState ""
  ${If} $0 != "0"
    DetailPrint "$1"
    MessageBox MB_ICONSTOP "$(StudioRunning)" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
!macroend

!macro ManageShortcuts Mode ExtraArguments
  InitPluginsDir
  File /oname=$PLUGINSDIR\Manage-Shortcuts.ps1 "${PAYLOAD_ROOT}\installer\windows\Manage-Shortcuts.ps1"
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\Manage-Shortcuts.ps1" -InstallRoot "$INSTDIR" -Action ${Mode} ${ExtraArguments}'
  Pop $0
  Pop $1
  ${If} $1 != ""
    DetailPrint "$1"
  ${EndIf}
!macroend

Section "TRELLIS Studio"
  IfFileExists "$INSTDIR\.trellis-managed-install" owned
  IfFileExists "$INSTDIR\bundled-web.json" owned
  IfFileExists "$INSTDIR\app.py" foreign
  ; The previous uninstaller removed the owner marker, but kept its runtime.
  IfFileExists "$INSTDIR\.studio-workshop-ready" 0 check_retained_data
  IfFileExists "$INSTDIR\.component-install.lock" owned
  check_retained_data:
  IfFileExists "$INSTDIR\outputs\*.*" foreign
  Goto owned
  foreign:
    MessageBox MB_ICONSTOP "$(DifferentInstall)" /SD IDOK
    SetErrorLevel 2
    Abort
  owned:
  !insertmacro CheckIdle
  ClearErrors
  SetOutPath "$INSTDIR"
  IfErrors marker_failed
  ; NSIS errors are sticky. A stale flag from an earlier check must not
  ; turn a successful open into an abort with an empty ownership marker.
  ClearErrors
  FileOpen $0 "$INSTDIR\.trellis-managed-install" w
  IfErrors marker_failed
  FileWrite $0 "TRELLIS Studio managed installation"
  IfErrors marker_write_failed
  FileClose $0
  IfErrors marker_failed
  ClearErrors
  !include "${INSTALL_FILES}"
  IfErrors payload_failed
  SetOutPath "$INSTDIR"
  IfErrors payload_failed
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  IfErrors payload_failed
  WriteRegStr HKCU "Software\TRELLIS Studio" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${ARP}" "DisplayName" "TRELLIS Studio"
  WriteRegStr HKCU "${ARP}" "DisplayVersion" "${STUDIO_VERSION}"
  WriteRegStr HKCU "${ARP}" "Publisher" "TRELLIS Studio contributors"
  WriteRegStr HKCU "${ARP}" "DisplayIcon" "$INSTDIR\installer\windows\trellis-studio.ico"
  WriteRegStr HKCU "${ARP}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${ARP}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${ARP}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${ARP}" "NoModify" 1
  WriteRegDWORD HKCU "${ARP}" "NoRepair" 1
  !insertmacro ManageShortcuts "Install" "-DesktopShortcut $CreateDesktopShortcut -ServerMode $InstallServer"
  ${If} $0 != "0"
    MessageBox MB_ICONEXCLAMATION "$(ShortcutError)" /SD IDOK
  ${EndIf}
  StrCpy $KimodoArguments ""
  ${If} $InstallKimodo == "1"
  ${AndIf} $AcceptKimodoLicenses == "1"
    StrCpy $KimodoArguments "-WithKimodo -AcceptKimodoModelLicenses"
  ${EndIf}
  ${If} $InstallServer == "1"
    IfSilent install_done
    DetailPrint "$(InstallingServer)"
    StrCpy $1 "$KimodoArguments"
    ${If} $InstallFull == "1"
      StrCpy $1 "$1 -FullStudio"
    ${EndIf}
    ClearErrors
    ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\installer\windows\Launch-Installed.ps1" -Mode ServerSetup -NoBrowser $1' $0
    IfErrors server_failed
    ${If} $0 != "0"
      Goto server_failed
    ${EndIf}
  ${ElseIf} $InstallFull == "1"
    DetailPrint "$(InstallingFull)"
    ClearErrors
    ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\installer\windows\Launch-Installed.ps1" -Mode Full -NoBrowser $KimodoArguments' $0
    IfErrors full_console_failed
    ${If} $0 != "0"
      DetailPrint "$(FullFailed)"
      MessageBox MB_ICONEXCLAMATION "$(FullFailed)" /SD IDOK
      SetErrorLevel 3
      Abort
    ${EndIf}
  ${Else}
    DetailPrint "$(InstallingWorkshop)"
    ClearErrors
    ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\installer\windows\Launch-Installed.ps1" -Mode PrepareWorkshop -NoBrowser $KimodoArguments' $0
    IfErrors workshop_failed
    ${If} $0 != "0"
      Goto workshop_failed
    ${EndIf}
  ${EndIf}
  Goto install_done
  workshop_failed:
    DetailPrint "$(WorkshopFailed)"
    MessageBox MB_ICONEXCLAMATION "$(WorkshopFailed)" /SD IDOK
    SetErrorLevel 3
    Abort
  server_failed:
    DetailPrint "$(ServerFailed)"
    MessageBox MB_ICONEXCLAMATION "$(ServerFailed)" /SD IDOK
    SetErrorLevel 3
    Abort
  full_console_failed:
    DetailPrint "$(FullConsoleFailed)"
    MessageBox MB_ICONEXCLAMATION "$(FullConsoleFailed)" /SD IDOK
    SetErrorLevel 3
    Abort
  marker_write_failed:
    FileClose $0
  marker_failed:
    DetailPrint "$(MarkerFailed)"
    MessageBox MB_ICONSTOP "$(MarkerFailed)" /SD IDOK
    SetErrorLevel 2
    Abort
  payload_failed:
    DetailPrint "$(PayloadFailed)"
    MessageBox MB_ICONSTOP "$(PayloadFailed)" /SD IDOK
    SetErrorLevel 2
    Abort
  install_done:
SectionEnd

Function un.onInit
  StrCpy $LANGUAGE ${LANG_ENGLISH}
FunctionEnd

Section "Uninstall"
  !insertmacro ReadStudioState "-Action ProbeUninstall"
  ${If} $0 == "10"
    MessageBox MB_ICONQUESTION|MB_YESNO|MB_DEFBUTTON2 "$(CloseForUninstall)" /SD IDYES IDYES close_studio
    SetErrorLevel 2
    Abort
    close_studio:
    !insertmacro ReadStudioState "-Action StopForUninstall"
  ${EndIf}
  ${If} $0 != "0"
    DetailPrint "$1"
    ${If} $0 == "11"
      MessageBox MB_ICONSTOP "$(BusyUninstall)" /SD IDOK
    ${Else}
      MessageBox MB_ICONSTOP "$(CannotCloseForUninstall)" /SD IDOK
    ${EndIf}
    SetErrorLevel 2
    Abort
  ${EndIf}
  !insertmacro ManageShortcuts "Uninstall" ""
  !include "${UNINSTALL_FILES}"
  Delete "$INSTDIR\Uninstall.exe"
  ; Keep the owner marker with the retained library for a later reinstall.
  ReadRegStr $0 HKCU "Software\TRELLIS Studio" "InstallDir"
  ${If} $0 == "$INSTDIR"
    DeleteRegKey HKCU "${ARP}"
    DeleteRegKey HKCU "Software\TRELLIS Studio"
  ${EndIf}
SectionEnd

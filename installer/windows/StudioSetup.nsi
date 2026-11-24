# -*- coding: utf-8 -*-
Unicode true
ManifestDPIAware true
RequestExecutionLevel user
!define GUIDED_MARKER ".trellis-guided-setup"
!define PREVIEW_MARKER ".trellis-setup-test"
!ifdef SETUP_PREVIEW
  !define SETUP_NAME "TRELLIS Studio Setup Test"
  !define SETUP_MARKER "${PREVIEW_MARKER}"
  !define SETUP_DESCRIPTION "TRELLIS Studio Setup Test for Windows"
!else
  !define SETUP_NAME "TRELLIS Studio"
  !define SETUP_MARKER "${GUIDED_MARKER}"
  !define SETUP_DESCRIPTION "TRELLIS Studio Windows Setup"
!endif
!define SETUP_KEY "Software\${SETUP_NAME}"
Name "${SETUP_NAME}"
OutFile "${OUTPUT_EXE}"
InstallDir "$LOCALAPPDATA\Programs\${SETUP_NAME}"
InstallDirRegKey HKCU "${SETUP_KEY}" "InstallDir"
SetCompressor /SOLID lzma
ShowInstDetails show
VIProductVersion "${STUDIO_VERSION}.0"
VIAddVersionKey "ProductName" "${SETUP_NAME}"
VIAddVersionKey "FileDescription" "${SETUP_DESCRIPTION}"
VIAddVersionKey "FileVersion" "${STUDIO_VERSION}"
VIAddVersionKey "ProductVersion" "${STUDIO_VERSION}"
VIAddVersionKey "CompanyName" "TRELLIS Studio contributors"
VIAddVersionKey "LegalCopyright" "TRELLIS Studio contributors (MIT)"

!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"
!include "nsDialogs.nsh"
; The x86 NSIS stub otherwise launches SysWOW64 PowerShell, which cannot see the
; native NVIDIA utility through System32. Keep every setup helper in the native host.
!if ${NSIS_PTR_SIZE} > 4
  !define SETUP_SYSTEM_DIR "$SYSDIR"
!else
  !define SETUP_SYSTEM_DIR "$WINDIR\Sysnative"
!endif
!define ARP "Software\Microsoft\Windows\CurrentVersion\Uninstall\${SETUP_NAME}"
!define MUI_LANGDLL_REGISTRY_ROOT "HKCU"
!define MUI_LANGDLL_REGISTRY_KEY "${SETUP_KEY}"
!define MUI_LANGDLL_REGISTRY_VALUENAME "Installer Language"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION StartStudio
!define MUI_FINISHPAGE_RUN_TEXT "$(LaunchLabel)"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!define MUI_ICON "${PAYLOAD_ROOT}\installer\windows\trellis-studio.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "${PAYLOAD_ROOT}\installer\windows\trellis-welcome.bmp"
!define MUI_UNICON "${PAYLOAD_ROOT}\installer\windows\trellis-studio.ico"

Var InstallTrellis
Var InstallPixal3D
Var InstallUniRig
Var TrellisCheckbox
Var Pixal3DCheckbox
Var UniRigCheckbox
Var GpuName
Var GpuMemory
Var VramNotice
Var GpuDriver
Var GpuCompute
Var GpuUuid
Var GpuProfile
Var GpuSupported
Var RigSupported
Var RigStatus
Var WslDistribution
Var WslReady
Var BlenderPath
Var BlenderReady
Var BlenderSummary
Var BlenderInput
Var BlenderStatusLabel
Var ComponentsArgument
Var HardwareArguments
Var PreflightRoot
Var SetupCulture
Var InstallServer
Var ServerRadio
Var CreateDesktopShortcut
Var DesktopCheckbox
Var InstallHi3d
Var Hi3dSupported
Var SkipHi3d
Var Hi3dCheckbox
Var AcceptHi3dLicenses
Var Hi3dLicenseCheckbox
Var InstallMultiviewTexture
Var MultiviewTextureSupported
Var SkipMultiviewTexture
Var MultiviewTextureCheckbox
Var AcceptMultiviewTextureLicenses
Var MultiviewTextureLicenseCheckbox
Var InstallUltraTex
Var UltraTexSupported
Var SkipUltraTex
Var UltraTexCheckbox
Var AcceptUltraTexLicenses
Var UltraTexLicenseCheckbox
Var InstallNativeWorkflows
Var InstallHighDetailGGUF
Var HighDetailGGUFSupported
Var AcceptHighDetailMeshLib
Var SkipHighDetailGGUF
Var NativeWorkflowsDefault
Var NativeWorkflowsSupported
Var SkipNativeWorkflows
Var NativeWorkflowsCheckbox
Var AcceptNativeWorkflowLicenses
Var NativeWorkflowLicenseCheckbox
Var InstallKimodo
Var KimodoCheckbox
Var AcceptKimodoLicenses
Var KimodoLicenseCheckbox
Var KimodoArguments

!ifdef SETUP_PREVIEW
  !define MUI_WELCOMEPAGE_TITLE "$(PreviewWelcome)"
!endif
!insertmacro MUI_PAGE_WELCOME
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE ValidateInstallFolder
!insertmacro MUI_PAGE_DIRECTORY
Page custom ShowInstallMode SaveInstallMode
Page custom ShowHardware SaveHardware
Page custom ShowComponentMode SaveComponentMode
Page custom ShowNativeWorkflowOptions SaveNativeWorkflowOptions
Page custom ShowHighDetailGGUFOptions SaveHighDetailGGUFOptions
Page custom ShowHi3dOptions SaveHi3dOptions
Page custom ShowMultiviewTextureOptions SaveMultiviewTextureOptions
Page custom ShowUltraTexOptions SaveUltraTexOptions
Page custom ShowKimodoOptions SaveKimodoOptions
Page custom ShowShortcutOptions SaveShortcutOptions
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "French"

LangString LaunchLabel ${LANG_ENGLISH} "Open TRELLIS from its tray icon"

LangString LaunchLabel ${LANG_FRENCH} "Ouvrir TRELLIS depuis son icône de notification"
LangString WrongPlatform ${LANG_ENGLISH} "TRELLIS Studio requires Windows x64 on an Intel or AMD processor."
LangString WrongPlatform ${LANG_FRENCH} "TRELLIS Studio requiert Windows x64 sur un processeur Intel ou AMD."
LangString DifferentInstall ${LANG_ENGLISH} "The selected folder already contains files and is not a recognized ${SETUP_NAME} installation. Choose an empty folder. Setup did not change the folder."
LangString DifferentInstall ${LANG_FRENCH} "Le dossier choisi contient déjà des fichiers et ne correspond pas à une installation de ${SETUP_NAME}. Choisissez un dossier vide."
LangString DifferentUninstall ${LANG_ENGLISH} "This folder is not a recognized ${SETUP_NAME} installation. No files were removed."
LangString DifferentUninstall ${LANG_FRENCH} "Ce dossier ne correspond pas à une installation de ${SETUP_NAME}. Aucun fichier n’a été supprimé."
LangString StudioRunning ${LANG_ENGLISH} "This copy of TRELLIS or its installer is still running. Stop Desktop / Server, then quit its tray icon before continuing. No process was stopped."
LangString StudioRunning ${LANG_FRENCH} "Arrêtez TRELLIS Studio ou TRELLIS Server, puis fermez son icône de notification avant de continuer."
LangString MarkerFailed ${LANG_ENGLISH} "Setup could not prepare the installation folder: $INSTDIR. Check that the folder is writable and run Setup again."
LangString MarkerFailed ${LANG_FRENCH} "Impossible de préparer le dossier $INSTDIR. Vérifiez les droits d’écriture, puis relancez l’installation."
LangString PayloadFailed ${LANG_ENGLISH} "Setup could not copy all application files to $INSTDIR. Close any program using those files and run Setup again."
LangString PayloadFailed ${LANG_FRENCH} "Impossible de copier tous les fichiers de l’application dans $INSTDIR. Fermez les programmes qui utilisent ces fichiers et réessayez."
LangString CloseForUninstall ${LANG_ENGLISH} "This copy of TRELLIS Studio is running in the background. Stop it and continue uninstalling? Your library will be kept."
LangString CloseForUninstall ${LANG_FRENCH} "TRELLIS Studio tourne en arrière-plan. Voulez-vous l’arrêter pour poursuivre la désinstallation ? Votre bibliothèque sera conservée."
LangString BusyUninstall ${LANG_ENGLISH} "Studio is running a generation or export. Let it finish before uninstalling."
LangString BusyUninstall ${LANG_FRENCH} "Une génération ou un export est en cours. Attendez la fin de l’opération avant de désinstaller."
LangString CannotCloseForUninstall ${LANG_ENGLISH} "Stop TRELLIS Studio or TRELLIS Server from the Start menu and close any MCP client or component installer, then try again."
LangString CannotCloseForUninstall ${LANG_FRENCH} "Arrêtez TRELLIS Studio ou TRELLIS Server depuis le menu Démarrer. Fermez les clients MCP et l’installateur de composants, puis réessayez."
LangString InstallModeTitle ${LANG_ENGLISH} "Choose how to use TRELLIS"
LangString InstallModeTitle ${LANG_FRENCH} "Choisir le mode d’utilisation"
LangString InstallModeSubtitle ${LANG_ENGLISH} "Choose the edition before selecting the components."
LangString InstallModeSubtitle ${LANG_FRENCH} "Choisissez l’édition avant de sélectionner les composants."
LangString DesktopModeChoice ${LANG_ENGLISH} "TRELLIS Desktop (single user)"
LangString DesktopModeChoice ${LANG_FRENCH} "TRELLIS Bureau (mono-utilisateur)"
LangString DesktopModeDescription ${LANG_ENGLISH} "Use your local library on this PC without creating an account."
LangString DesktopModeDescription ${LANG_FRENCH} "Utilisez votre bibliothèque locale sur ce PC sans créer de compte."
LangString ServerChoice ${LANG_ENGLISH} "TRELLIS Server (multi-user)"
LangString ServerChoice ${LANG_FRENCH} "TRELLIS Server (multi-utilisateur)"
!ifdef SETUP_PREVIEW
  LangString ServerDescription ${LANG_ENGLISH} "Set up an isolated local server and its first administrator. This test uses its own data folder and a localhost address."
  LangString ServerDescription ${LANG_FRENCH} "Configurez un serveur local isolé et son premier administrateur. Le test utilise son propre dossier et l’adresse locale."
  LangString InstallingServer ${LANG_ENGLISH} "Preparing the isolated local server. Follow the instructions in the TRELLIS PowerShell window."
  LangString InstallingServer ${LANG_FRENCH} "Préparation du serveur local isolé. Suivez les instructions dans PowerShell."
!else
  LangString ServerDescription ${LANG_ENGLISH} "Choose local access, LAN access with your certificate, or Internet access with automatic HTTPS. Configure the data folder, optional startup and first administrator."
  LangString ServerDescription ${LANG_FRENCH} "Choisissez un accès local, sur le réseau avec votre certificat ou sur Internet avec HTTPS. Configurez le dossier, le démarrage et le premier administrateur."
  LangString InstallingServer ${LANG_ENGLISH} "Preparing the server. Follow the instructions in the TRELLIS PowerShell window."
  LangString InstallingServer ${LANG_FRENCH} "Préparation du serveur. Suivez les instructions dans PowerShell."
!endif
LangString HardwareTitle ${LANG_ENGLISH} "Check this PC"
LangString HardwareTitle ${LANG_FRENCH} "Vérifier ce PC"
LangString HardwareSubtitle ${LANG_ENGLISH} "Review the detected GPU and choose the Blender executable."
LangString HardwareSubtitle ${LANG_FRENCH} "Vérifiez le GPU détecté et sélectionnez l’exécutable de Blender."
LangString ComponentModeTitle ${LANG_ENGLISH} "Choose the components"
LangString ComponentModeTitle ${LANG_FRENCH} "Choisir les composants"
LangString ComponentModeSubtitle ${LANG_ENGLISH} "Install the Workshop and select the additional engines for this PC."
LangString ComponentModeSubtitle ${LANG_FRENCH} "Installez l’Atelier et choisissez les moteurs à ajouter sur ce PC."
LangString WorkshopDescription ${LANG_ENGLISH} "Workshop includes the 3D viewer, GLB tools and standard animation files. Blender applies clips to compatible rigs."
LangString WorkshopDescription ${LANG_FRENCH} "L’Atelier inclut la visionneuse 3D, les outils GLB et les animations standard. Blender applique les clips aux squelettes compatibles."
LangString ServerFailed ${LANG_ENGLISH} "Server setup did not finish. Review the console messages and run Setup again to resume."
LangString ServerFailed ${LANG_FRENCH} "La configuration du serveur a échoué. Consultez la console et relancez l’installation."
LangString InstallingWorkshop ${LANG_ENGLISH} "Preparing the Workshop and tray application. Python dependencies are downloaded automatically."
LangString InstallingWorkshop ${LANG_FRENCH} "Préparation de l’Atelier et de l’icône de notification. Les dépendances Python sont téléchargées automatiquement."
LangString WorkshopFailed ${LANG_ENGLISH} "The application files are installed, but Workshop preparation did not finish. Review the console and run Setup again to resume."
LangString WorkshopFailed ${LANG_FRENCH} "Les fichiers de l’application sont installés. La préparation de l’Atelier a échoué. Consultez la console et relancez l’installation."
LangString ComponentsNeedAttention ${LANG_ENGLISH} "Some components need attention. See the setup logs in $INSTDIR\logs, then open Repair or resume components in the ${SETUP_NAME} Start menu folder."
LangString ComponentsNeedAttention ${LANG_FRENCH} "Certains composants demandent une intervention. Consultez $INSTDIR\logs, puis ouvrez Réparer ou reprendre les composants dans le dossier ${SETUP_NAME} du menu Démarrer."
LangString ShortcutOptionsTitle ${LANG_ENGLISH} "Shortcuts"
LangString ShortcutOptionsTitle ${LANG_FRENCH} "Raccourcis"
LangString ShortcutOptionsSubtitle ${LANG_ENGLISH} "Choose where to open TRELLIS Studio."
LangString ShortcutOptionsSubtitle ${LANG_FRENCH} "Choisissez comment ouvrir TRELLIS Studio."
LangString StartMenuDescription ${LANG_ENGLISH} "The Start menu opens a tray icon to start, stop and open TRELLIS. Quitting the icon keeps the application running."
LangString StartMenuDescription ${LANG_FRENCH} "Le menu Démarrer ouvre l’icône qui permet de démarrer, arrêter et ouvrir TRELLIS. Fermer cette icône laisse TRELLIS actif."
LangString DesktopChoice ${LANG_ENGLISH} "Create a desktop shortcut"
LangString DesktopChoice ${LANG_FRENCH} "Créer un raccourci sur le Bureau"
LangString ShortcutError ${LANG_ENGLISH} "Studio files are installed, but one or more shortcuts could not be created. You can launch Studio with $INSTDIR\installer\windows\Launch.cmd."
LangString ShortcutError ${LANG_FRENCH} "Les fichiers sont installés, mais certains raccourcis n’ont pas pu être créés. Ouvrez Studio avec $INSTDIR\installer\windows\Launch.cmd."
LangString KimodoTitle ${LANG_ENGLISH} "Optional motion generation"
LangString KimodoTitle ${LANG_FRENCH} "Génération de mouvements (facultatif)"
LangString KimodoSubtitle ${LANG_ENGLISH} "Available with either Desktop or Server."
LangString KimodoSubtitle ${LANG_FRENCH} "Disponible avec les éditions Bureau et Serveur."
LangString KimodoChoice ${LANG_ENGLISH} "Install Kimodo text-to-motion (optional)"
LangString KimodoChoice ${LANG_FRENCH} "Installer Kimodo (facultatif)"
LangString KimodoDescription ${LANG_ENGLISH} "Create reusable humanoid animations from text on the CPU. About 9.3 GB of model weights plus portable build tools. No NVIDIA GPU or CUDA required."
LangString KimodoDescription ${LANG_FRENCH} "Créez des animations humanoïdes réutilisables à partir de texte sur le CPU. Environ 9,3 Go de poids et des outils portables. GPU NVIDIA et CUDA facultatifs."
LangString KimodoRequirements ${LANG_ENGLISH} "Needs WSL2 Linux x64, Python 3.10+, an AVX2/FMA/F16C CPU and 12 GiB free in WSL. Setup guides you if WSL is missing; Windows may require a restart."
LangString KimodoRequirements ${LANG_FRENCH} "Prérequis : WSL2 Linux x64, Python 3.10+, CPU AVX2/FMA/F16C et 12 Gio dans WSL. L’installation peut demander un redémarrage."
LangString KimodoNvidiaLicense ${LANG_ENGLISH} "Read the NVIDIA Open Model License"
LangString KimodoNvidiaLicense ${LANG_FRENCH} "Lire la licence NVIDIA Open Model"
LangString KimodoLlamaLicense ${LANG_ENGLISH} "Read the Meta Llama 3 Community License (text encoder)"
LangString KimodoLlamaLicense ${LANG_FRENCH} "Lire la licence communautaire Meta Llama 3"
LangString KimodoAccept ${LANG_ENGLISH} "I have read and accept both model licenses for the optional Kimodo installation."
LangString KimodoAccept ${LANG_FRENCH} "J’ai lu et j’accepte les deux licences de modèles pour installer Kimodo."
LangString KimodoLicenseRequired ${LANG_ENGLISH} "Accept both model licenses to install Kimodo, or clear the optional Kimodo selection."
LangString KimodoLicenseRequired ${LANG_FRENCH} "Acceptez les deux licences ou décochez Kimodo."

!ifdef SETUP_PREVIEW
  LangString PreviewWelcome ${LANG_ENGLISH} "Welcome to the TRELLIS Studio Setup Test"
  LangString PreviewWelcome ${LANG_FRENCH} "Bienvenue dans le test d’installation de TRELLIS Studio"
!endif
LangString GpuMiB ${LANG_ENGLISH} "$GpuName ($GpuMemory MiB VRAM)"
LangString GpuMiB ${LANG_FRENCH} "$GpuName ($GpuMemory Mio de VRAM)"
LangString GpuCapability ${LANG_ENGLISH} "Compute capability $GpuCompute  |  Driver $GpuDriver"
LangString GpuCapability ${LANG_FRENCH} "Capacité de calcul $GpuCompute  |  Pilote $GpuDriver"
LangString GpuUnavailable ${LANG_ENGLISH} "NVIDIA GPU unavailable"
LangString GpuUnavailable ${LANG_FRENCH} "GPU NVIDIA indisponible"
LangString WorkshopAvailable ${LANG_ENGLISH} "Workshop remains available."
LangString WorkshopAvailable ${LANG_FRENCH} "L’Atelier reste disponible."
LangString GpuProfileSuffix ${LANG_ENGLISH} "$4  |  Profile $GpuProfile"
LangString GpuProfileSuffix ${LANG_FRENCH} "$4  |  Profil $GpuProfile"
LangString HardwareFallback ${LANG_ENGLISH} "Hardware check could not complete. You can continue with Workshop."
LangString HardwareFallback ${LANG_FRENCH} "Vérification matérielle incomplète. Vous pouvez continuer avec l’Atelier."
LangString WslFallback ${LANG_ENGLISH} "WSL2 could not be verified."
LangString WslFallback ${LANG_FRENCH} "Impossible de vérifier WSL2."
LangString BlenderExecutable ${LANG_ENGLISH} "Blender executable"
LangString BlenderExecutable ${LANG_FRENCH} "Exécutable de Blender"
LangString BlenderFileFilter ${LANG_ENGLISH} "Blender executable|blender.exe"
LangString BlenderFileFilter ${LANG_FRENCH} "Exécutable de Blender|blender.exe"
LangString BrowseLabel ${LANG_ENGLISH} "Browse..."
LangString BrowseLabel ${LANG_FRENCH} "Parcourir…"
LangString BlenderLaterHint ${LANG_ENGLISH} "Leave blank to configure Blender later."
LangString BlenderLaterHint ${LANG_FRENCH} "Laissez ce champ vide pour configurer Blender plus tard."
LangString BlenderPending ${LANG_ENGLISH} "The selected Blender will be checked when you continue."
LangString BlenderPending ${LANG_FRENCH} "Blender sera vérifié quand vous continuerez."
LangString BlenderLater ${LANG_ENGLISH} "Blender will be configured later."
LangString BlenderLater ${LANG_FRENCH} "Blender sera configuré plus tard."
LangString BlenderPickFile ${LANG_ENGLISH} "Choose an existing blender.exe file."
LangString BlenderPickFile ${LANG_FRENCH} "Choisissez un fichier blender.exe existant."
LangString BlenderInvalid ${LANG_ENGLISH} "Blender could not be verified. Choose another file or clear the path."
LangString BlenderInvalid ${LANG_FRENCH} "Impossible de vérifier Blender. Choisissez un autre fichier ou effacez le chemin."
LangString InstallTrellisLabel ${LANG_ENGLISH} "TRELLIS.2 image-to-3D  (about 15 GiB of models)"
LangString InstallTrellisLabel ${LANG_FRENCH} "TRELLIS.2, de l’image à la 3D (environ 15 Gio de modèles)"
LangString InstallPixalLabel ${LANG_ENGLISH} "Pixal3D compatibility generation  (about 8.25 GiB more)"
LangString InstallPixalLabel ${LANG_FRENCH} "Génération Pixal3D (environ 8,25 Gio en plus)"
LangString InstallRigLabel ${LANG_ENGLISH} "UniRig skeleton and skinning  (WSL2 and Blender)"
LangString InstallRigLabel ${LANG_FRENCH} "Squelettes et poids UniRig (WSL2 et Blender)"
LangString GpuNeedsDriver ${LANG_ENGLISH} "GPU generation needs a supported NVIDIA card and driver."
LangString GpuNeedsDriver ${LANG_FRENCH} "La génération GPU requiert une carte et un pilote NVIDIA compatibles."
LangString GpuProfileMatched ${LANG_ENGLISH} "The detected GPU matches the $GpuProfile dependency profile."
LangString GpuProfileMatched ${LANG_FRENCH} "Le GPU détecté correspond au profil $GpuProfile."
LangString RigUnsupported ${LANG_ENGLISH} "UniRig is unavailable for this GPU profile."
LangString RigUnsupported ${LANG_FRENCH} "UniRig est indisponible pour ce profil GPU."
LangString RigNeedsWsl ${LANG_ENGLISH} "UniRig can be added after a compatible WSL2 distribution is ready."
LangString RigNeedsWsl ${LANG_FRENCH} "Préparez une distribution WSL2 compatible pour installer UniRig."
LangString RigNeedsBlender ${LANG_ENGLISH} "UniRig can be added after selecting a working Blender."
LangString RigNeedsBlender ${LANG_FRENCH} "Sélectionnez une installation de Blender fonctionnelle pour ajouter UniRig."
LangString RigReadyForSetup ${LANG_ENGLISH} "The UniRig prerequisites are available. Setup will test the runtime."
LangString RigReadyForSetup ${LANG_FRENCH} "Les prérequis d’UniRig sont disponibles. L’installation vérifiera le moteur."
LangString CheckSelectedEngines ${LANG_ENGLISH} "Setup checks each selected engine before marking it ready."
LangString CheckSelectedEngines ${LANG_FRENCH} "Chaque moteur sélectionné sera vérifié avant activation."
LangString NativeTitle ${LANG_ENGLISH} "High Detail and Game Asset"
LangString NativeTitle ${LANG_FRENCH} "High Detail et Game Asset"
LangString GGUFTitle ${LANG_ENGLISH} "High Detail GGUF"
LangString GGUFTitle ${LANG_FRENCH} "High Detail GGUF"
LangString GGUFChoice ${LANG_ENGLISH} "Install High Detail GGUF with native PBR"
LangString GGUFChoice ${LANG_FRENCH} "Installer High Detail GGUF avec les matériaux PBR natifs"
LangString GGUFDescription ${LANG_ENGLISH} "Generate dense geometry and materials from one reference on the RTX 5070 Ti. Setup reuses the TRELLIS.2 foundation and verifies the geometry runtime."
LangString GGUFDescription ${LANG_FRENCH} "Générez la géométrie dense et les matériaux à partir d’une référence sur la RTX 5070 Ti. L’installation réutilise TRELLIS.2 et vérifie le moteur géométrique."
LangString GGUFConsent ${LANG_ENGLISH} "I have read and accept the MeshLib terms."
LangString GGUFConsent ${LANG_FRENCH} "J’ai lu et j’accepte les conditions de MeshLib."
LangString GGUFAcceptRequired ${LANG_ENGLISH} "Accept the MeshLib terms or clear the High Detail GGUF selection."
LangString GGUFAcceptRequired ${LANG_FRENCH} "Acceptez les conditions de MeshLib ou décochez High Detail GGUF."
LangString NativeSubtitle ${LANG_ENGLISH} "Install the native workflows with UltraTex for TRELLIS Studio."
LangString NativeSubtitle ${LANG_FRENCH} "Installez les profils natifs avec UltraTex pour TRELLIS Studio."
LangString ProbeIncomplete ${LANG_ENGLISH} "NVIDIA hardware could not be checked. You can continue with the other components."
LangString ProbeIncomplete ${LANG_FRENCH} "Impossible de vérifier le matériel NVIDIA. Les autres composants restent disponibles."
LangString NativeChoice ${LANG_ENGLISH} "Install High Detail and Game Asset (recommended)"
LangString NativeChoice ${LANG_FRENCH} "Installer High Detail et Game Asset (recommandé)"
LangString NativeDescription ${LANG_ENGLISH} "Setup downloads native geometry, mesh finishing and UltraTex. Read the non-commercial evaluation terms before continuing."
LangString NativeDescription ${LANG_FRENCH} "Installe la génération native, la finition des maillages et UltraTex. Lisez les conditions d’évaluation non commerciale."
LangString NativeBlenderSelected ${LANG_ENGLISH} "Game Asset uses the Blender selected on Check this PC."
LangString NativeBlenderSelected ${LANG_FRENCH} "Game Asset utilise le Blender sélectionné dans Vérifier ce PC."
LangString NativeBlenderPortable ${LANG_ENGLISH} "Setup can prepare a private portable Blender for Game Asset."
LangString NativeBlenderPortable ${LANG_FRENCH} "L’installation peut préparer un Blender portable dédié à Game Asset."
LangString FluxTerms ${LANG_ENGLISH} "FLUX.2 [klein] 9B terms"
LangString FluxTerms ${LANG_FRENCH} "Conditions de FLUX.2 [klein] 9B"
LangString MeshLibTerms ${LANG_ENGLISH} "MeshLib terms"
LangString MeshLibTerms ${LANG_FRENCH} "Conditions de MeshLib"
LangString NativeLicenseChoice ${LANG_ENGLISH} "I have read and accept the FLUX.2 [klein] 9B and MeshLib terms."
LangString NativeLicenseChoice ${LANG_FRENCH} "J’ai lu et j’accepte les conditions de FLUX.2 [klein] 9B et de MeshLib."
LangString NativeLicenseRequired ${LANG_ENGLISH} "Accept both the FLUX.2 [klein] 9B and MeshLib terms, or clear the native workflows selection."
LangString NativeLicenseRequired ${LANG_FRENCH} "Acceptez les deux licences ou décochez les profils natifs."
LangString Hi3dTitle ${LANG_ENGLISH} "Optional Hi3D Detail Refinement"
LangString Hi3dTitle ${LANG_FRENCH} "Affinage des détails Hi3D (facultatif)"
LangString OptionalGpuSubtitle ${LANG_ENGLISH} "Available with Desktop or Server on supported NVIDIA hardware."
LangString OptionalGpuSubtitle ${LANG_FRENCH} "Disponible en Bureau et Serveur sur un GPU NVIDIA compatible."
LangString Hi3dChoice ${LANG_ENGLISH} "Install Hi3D Detail Refinement (optional)"
LangString Hi3dChoice ${LANG_FRENCH} "Installer Hi3D (facultatif)"
LangString Hi3dDescription ${LANG_ENGLISH} "Refine native TRELLIS.2 meshes in 512 or 1024. Requires TRELLIS.2 generation and downloads about 10.7 GB of weights."
LangString Hi3dDescription ${LANG_FRENCH} "Affine les maillages en 512 ou 1024. Requiert TRELLIS.2 et télécharge environ 10,7 Go de poids."
LangString Hi3dTerms ${LANG_ENGLISH} "Hi3D license"
LangString Hi3dTerms ${LANG_FRENCH} "Licence Hi3D"
LangString DinoTerms ${LANG_ENGLISH} "DINOv2 terms"
LangString DinoTerms ${LANG_FRENCH} "Conditions de DINOv2"
LangString ClipTerms ${LANG_ENGLISH} "CLIP terms"
LangString ClipTerms ${LANG_FRENCH} "Conditions de CLIP"
LangString Hi3dLicenseChoice ${LANG_ENGLISH} "I have read and accept the Hi3D, DINOv2 and CLIP terms."
LangString Hi3dLicenseChoice ${LANG_FRENCH} "J’ai lu et j’accepte les conditions de Hi3D, DINOv2 et CLIP."
LangString Hi3dLicenseRequired ${LANG_ENGLISH} "Accept all three model terms, or clear the optional Hi3D selection."
LangString Hi3dLicenseRequired ${LANG_FRENCH} "Acceptez les trois licences ou décochez Hi3D."
LangString MultiviewTitle ${LANG_ENGLISH} "Optional multiview texture refinement"
LangString MultiviewTitle ${LANG_FRENCH} "Affinage multivue des textures (facultatif)"
LangString MultiviewChoice ${LANG_ENGLISH} "Install multiview texture refinement (optional)"
LangString MultiviewChoice ${LANG_FRENCH} "Installer MV-Adapter (facultatif)"
LangString MultiviewDescription ${LANG_ENGLISH} "Refine baked colors from six generated views. Requires TRELLIS.2 generation and downloads about 3.3 GB of model files."
LangString MultiviewDescription ${LANG_FRENCH} "Affine les couleurs à partir de six vues générées. Requiert TRELLIS.2 et télécharge environ 3,3 Go de poids."
LangString DiffusionTerms ${LANG_ENGLISH} "Stable Diffusion 2.1 terms"
LangString DiffusionTerms ${LANG_FRENCH} "Licence Stable Diffusion 2.1"
LangString AdapterTerms ${LANG_ENGLISH} "MV-Adapter terms"
LangString AdapterTerms ${LANG_FRENCH} "Licence MV-Adapter"
LangString MultiviewLicenseChoice ${LANG_ENGLISH} "I have read and accept the Open RAIL++-M and MV-Adapter terms."
LangString MultiviewLicenseChoice ${LANG_FRENCH} "J’ai lu et j’accepte les conditions Open RAIL++-M et MV-Adapter."
LangString MultiviewLicenseRequired ${LANG_ENGLISH} "Accept both model terms or clear the optional multiview texture refinement selection."
LangString MultiviewLicenseRequired ${LANG_FRENCH} "Acceptez les deux licences ou décochez MV-Adapter."
LangString UltraTexTitle ${LANG_ENGLISH} "Optional UltraTex 2K preview"
LangString UltraTexTitle ${LANG_FRENCH} "UltraTex 2K en aperçu (facultatif)"
LangString UltraTexSubtitle ${LANG_ENGLISH} "Six-view compatibility component for local evaluation."
LangString UltraTexSubtitle ${LANG_FRENCH} "Composant à six vues pour l’évaluation locale."
LangString UltraTexChoice ${LANG_ENGLISH} "Install UltraTex 2K preview (optional)"
LangString UltraTexChoice ${LANG_FRENCH} "Installer l’aperçu UltraTex 2K (facultatif)"
LangString UltraTexDescription ${LANG_ENGLISH} "Six-view compatibility component. High Detail and Game Asset install their own UltraTex runtime. This preview adds about 14 GB of model downloads."
LangString UltraTexDescription ${LANG_FRENCH} "Affine les textures sur six vues. High Detail et Game Asset ont leur propre moteur UltraTex. Environ 14 Go de modèles en plus."
LangString UltraTexTerms ${LANG_ENGLISH} "Read the FLUX.2 [klein] 9B model terms"
LangString UltraTexTerms ${LANG_FRENCH} "Lire les conditions de FLUX.2 [klein] 9B"
LangString UltraTexLicenseChoice ${LANG_ENGLISH} "I have read and accept the FLUX.2 [klein] 9B model terms."
LangString UltraTexLicenseChoice ${LANG_FRENCH} "J’ai lu et j’accepte les conditions de FLUX.2 [klein] 9B."
LangString UltraTexLicenseRequired ${LANG_ENGLISH} "Accept the FLUX.2 [klein] 9B model terms or clear the optional UltraTex selection."
LangString UltraTexLicenseRequired ${LANG_FRENCH} "Acceptez les conditions de FLUX.2 [klein] 9B ou décochez UltraTex."

Function .onInit
  ; A PowerShell 7 parent can pass modules that Windows PowerShell 5.1 cannot load.
  System::Call 'kernel32::SetEnvironmentVariableW(w "PSModulePath", p 0)'
  IfSilent language_selected
  !insertmacro MUI_LANGDLL_DISPLAY
  language_selected:
  StrCpy $SetupCulture "en"
  ${If} $LANGUAGE == ${LANG_FRENCH}
    StrCpy $SetupCulture "fr"
  ${EndIf}
  StrCpy $InstallTrellis "0"
  StrCpy $InstallPixal3D "0"
  StrCpy $InstallUniRig "0"
  StrCpy $BlenderReady "0"
  StrCpy $InstallServer "0"
  IfFileExists "$INSTDIR\config\server.json" 0 +2
  StrCpy $InstallServer "1"
  StrCpy $CreateDesktopShortcut "0"
  StrCpy $InstallHi3d "0"
  StrCpy $SkipHi3d "0"
  StrCpy $AcceptHi3dLicenses "0"
  StrCpy $InstallMultiviewTexture "0"
  StrCpy $SkipMultiviewTexture "0"
  StrCpy $AcceptMultiviewTextureLicenses "0"
  StrCpy $InstallUltraTex "0"
  StrCpy $SkipUltraTex "0"
  StrCpy $AcceptUltraTexLicenses "0"
  StrCpy $InstallNativeWorkflows "0"
  StrCpy $InstallHighDetailGGUF "0"
  StrCpy $AcceptHighDetailMeshLib "0"
  StrCpy $SkipHighDetailGGUF "0"
  StrCpy $NativeWorkflowsDefault "0"
  StrCpy $SkipNativeWorkflows "0"
  StrCpy $AcceptNativeWorkflowLicenses "0"
  StrCpy $InstallKimodo "0"
  StrCpy $AcceptKimodoLicenses "0"
  ${IfNot} ${IsNativeAMD64}
    MessageBox MB_ICONSTOP "$(WrongPlatform)" /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
FunctionEnd

Function ValidateInstallFolder
  IfFileExists "$INSTDIR\.git" foreign
  IfFileExists "$INSTDIR\.git\*.*" foreign
!ifndef SETUP_PREVIEW
  IfFileExists "$INSTDIR\${PREVIEW_MARKER}" foreign
!endif
  ClearErrors
  FileOpen $0 "$INSTDIR\${SETUP_MARKER}" r
  IfErrors check_legacy
  StrCpy $1 ""
  FileRead $0 $1
  FileClose $0
  StrCmp $1 "${SETUP_NAME}" allowed

  check_legacy:
!ifndef SETUP_PREVIEW
    ; Only migrate an existing packaged installation at the registered path.
    IfFileExists "$INSTDIR\bundled-web.json" 0 check_directory
    ClearErrors
    ReadRegStr $1 HKCU "${SETUP_KEY}" "InstallDir"
    IfErrors check_directory
    StrCmp $1 "" check_directory
    GetFullPathName $0 "$INSTDIR"
    GetFullPathName $1 "$1"
    IfErrors check_directory
    StrCmp $0 $1 allowed
!endif
  check_directory:
    ClearErrors
    FindFirst $0 $1 "$INSTDIR\*.*"
    IfErrors allowed
  next_entry:
    StrCmp $1 "." ignore_entry
    StrCmp $1 ".." ignore_entry
    StrCmp $1 "" empty
    FindClose $0
  foreign:
    MessageBox MB_ICONSTOP "$(DifferentInstall)" /SD IDOK
    SetErrorLevel 2
    Abort
  ignore_entry:
    ClearErrors
    FindNext $0 $1
    IfErrors empty next_entry
  empty:
    FindClose $0
  allowed:
    ClearErrors
    SetErrorLevel 0
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

Function RunHardwareProbe
  InitPluginsDir
  File /oname=$PLUGINSDIR\Setup-Preflight.ps1 "${PAYLOAD_ROOT}\installer\windows\Setup-Preflight.ps1"
  File /oname=$PLUGINSDIR\gpu-runtime-profiles.json "${PAYLOAD_ROOT}\installer\gpu-runtime-profiles.json"
  Delete "$PLUGINSDIR\preflight.ini"
  nsExec::ExecToStack /TIMEOUT=30000 '"${SETUP_SYSTEM_DIR}\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\Setup-Preflight.ps1" -Action Probe -Language $SetupCulture -InstallRoot "$INSTDIR" -OutputPath "$PLUGINSDIR\preflight.ini"'
  Pop $0
  Pop $1
FunctionEnd

Function ShowHardware
  Call RunHardwareProbe
  ${If} $PreflightRoot != $INSTDIR
    StrCpy $PreflightRoot "$INSTDIR"
    StrCpy $BlenderSummary ""
    ReadINIStr $InstallTrellis "$PLUGINSDIR\preflight.ini" "Plan" "Trellis"
    ReadINIStr $InstallPixal3D "$PLUGINSDIR\preflight.ini" "Plan" "Pixal3D"
    ReadINIStr $InstallUniRig "$PLUGINSDIR\preflight.ini" "Plan" "UniRig"
    ReadINIStr $InstallHi3d "$PLUGINSDIR\preflight.ini" "Plan" "Hi3D"
    ReadINIStr $AcceptHi3dLicenses "$PLUGINSDIR\preflight.ini" "Plan" "Hi3DLicenseAccepted"
    ReadINIStr $InstallMultiviewTexture "$PLUGINSDIR\preflight.ini" "Plan" "MultiviewTexture"
    ReadINIStr $AcceptMultiviewTextureLicenses "$PLUGINSDIR\preflight.ini" "Plan" "MultiviewTextureLicenseAccepted"
    ReadINIStr $InstallUltraTex "$PLUGINSDIR\preflight.ini" "Plan" "UltraTex"
    ReadINIStr $AcceptUltraTexLicenses "$PLUGINSDIR\preflight.ini" "Plan" "UltraTexLicenseAccepted"
    ReadINIStr $InstallNativeWorkflows "$PLUGINSDIR\preflight.ini" "Plan" "NativeWorkflows"
    ReadINIStr $InstallHighDetailGGUF "$PLUGINSDIR\preflight.ini" "Plan" "HighDetailGGUF"
    ReadINIStr $AcceptHighDetailMeshLib "$PLUGINSDIR\preflight.ini" "Plan" "MeshLibAccepted"
    ReadINIStr $NativeWorkflowsDefault "$PLUGINSDIR\preflight.ini" "Plan" "NativeWorkflowsDefault"
    ReadINIStr $AcceptNativeWorkflowLicenses "$PLUGINSDIR\preflight.ini" "Plan" "NativeWorkflowsLicenseAccepted"
    StrCpy $SkipNativeWorkflows "0"
    ${If} $InstallNativeWorkflows != "1"
      StrCpy $InstallNativeWorkflows "0"
    ${EndIf}
    ${If} $AcceptNativeWorkflowLicenses != "1"
      StrCpy $AcceptNativeWorkflowLicenses "0"
    ${EndIf}
    ${If} $InstallUltraTex != "1"
      StrCpy $InstallUltraTex "0"
    ${EndIf}
    ${If} $AcceptUltraTexLicenses != "1"
      StrCpy $AcceptUltraTexLicenses "0"
    ${EndIf}
    ${If} $InstallMultiviewTexture != "1"
      StrCpy $InstallMultiviewTexture "0"
    ${EndIf}
    ${If} $AcceptMultiviewTextureLicenses != "1"
      StrCpy $AcceptMultiviewTextureLicenses "0"
    ${EndIf}
    ${If} $InstallHi3d != "1"
      StrCpy $InstallHi3d "0"
    ${EndIf}
    ${If} $AcceptHi3dLicenses != "1"
      StrCpy $AcceptHi3dLicenses "0"
    ${EndIf}
    ${If} $InstallTrellis != "1"
      StrCpy $InstallTrellis "0"
    ${EndIf}
    ${If} $InstallPixal3D != "1"
      StrCpy $InstallPixal3D "0"
    ${EndIf}
    ${If} $InstallUniRig != "1"
      StrCpy $InstallUniRig "0"
    ${EndIf}
  ${EndIf}
  !insertmacro MUI_HEADER_TEXT "$(HardwareTitle)" "$(HardwareSubtitle)"
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ReadINIStr $GpuName "$PLUGINSDIR\preflight.ini" "GPU" "Name"
  ReadINIStr $GpuMemory "$PLUGINSDIR\preflight.ini" "GPU" "MemoryMiB"
  ReadINIStr $VramNotice "$PLUGINSDIR\preflight.ini" "GPU" "VramNotice"
  ReadINIStr $GpuDriver "$PLUGINSDIR\preflight.ini" "GPU" "Driver"
  ReadINIStr $GpuCompute "$PLUGINSDIR\preflight.ini" "GPU" "Compute"
  ReadINIStr $GpuUuid "$PLUGINSDIR\preflight.ini" "GPU" "Uuid"
  ReadINIStr $GpuProfile "$PLUGINSDIR\preflight.ini" "GPU" "Profile"
  ReadINIStr $GpuSupported "$PLUGINSDIR\preflight.ini" "GPU" "Supported"
  ReadINIStr $RigSupported "$PLUGINSDIR\preflight.ini" "GPU" "UniRigSupported"
  ReadINIStr $RigStatus "$PLUGINSDIR\preflight.ini" "GPU" "UniRigStatus"
  ReadINIStr $2 "$PLUGINSDIR\preflight.ini" "GPU" "Status"
  ${If} $GpuName != ""
    StrCpy $3 "$(GpuMiB)"
    StrCpy $4 "$(GpuCapability)"
  ${Else}
    StrCpy $3 "$(GpuUnavailable)"
    StrCpy $4 "$(WorkshopAvailable)"
  ${EndIf}
  ${If} $GpuProfile != ""
    StrCpy $4 "$(GpuProfileSuffix)"
  ${EndIf}
  ${If} $2 == ""
    StrCpy $2 "$(HardwareFallback)"
  ${EndIf}
  ${NSD_CreateLabel} 0 0u 100% 11u "$3"
  Pop $0
  ${NSD_CreateLabel} 0 12u 100% 11u "$4"
  Pop $0
  ${NSD_CreateLabel} 0 23u 100% 20u "$2"
  Pop $0
  ReadINIStr $WslDistribution "$PLUGINSDIR\preflight.ini" "WSL" "Distribution"
  ReadINIStr $WslReady "$PLUGINSDIR\preflight.ini" "WSL" "Ready"
  ReadINIStr $2 "$PLUGINSDIR\preflight.ini" "WSL" "Status"
  ${If} $2 == ""
    StrCpy $2 "$(WslFallback)"
  ${EndIf}
  ${NSD_CreateLabel} 0 43u 100% 20u "$2"
  Pop $0
  ReadINIStr $2 "$PLUGINSDIR\preflight.ini" "Disk" "Status"
  ${NSD_CreateLabel} 0 63u 100% 16u "$2"
  Pop $0
  ${If} $BlenderSummary == ""
    ReadINIStr $BlenderPath "$PLUGINSDIR\preflight.ini" "Blender" "Path"
    ReadINIStr $BlenderReady "$PLUGINSDIR\preflight.ini" "Blender" "Ready"
    ReadINIStr $BlenderSummary "$PLUGINSDIR\preflight.ini" "Blender" "Status"
  ${EndIf}
  ${NSD_CreateLabel} 0 80u 100% 11u "$(BlenderExecutable)"
  Pop $0
  ${NSD_CreateText} 0 92u -58u 13u "$BlenderPath"
  Pop $BlenderInput
  ${NSD_CreateBrowseButton} -53u 92u 53u 13u "$(BrowseLabel)"
  Pop $0
  ${NSD_OnClick} $0 BrowseBlender
  ${NSD_CreateLabel} 0 108u 100% 19u "$BlenderSummary"
  Pop $BlenderStatusLabel
  ${NSD_CreateLabel} 0 128u 100% 11u "$(BlenderLaterHint)"
  Pop $0
  nsDialogs::Show
FunctionEnd

Function BrowseBlender
  Pop $0
  ${NSD_GetText} $BlenderInput $1
  nsDialogs::SelectFileDialog open "$1" "$(BlenderFileFilter)"
  Pop $0
  ${If} $0 != ""
    ${NSD_SetText} $BlenderInput "$0"
    ${NSD_SetText} $BlenderStatusLabel "$(BlenderPending)"
  ${EndIf}
FunctionEnd

Function SaveHardware
  ${NSD_GetText} $BlenderInput $BlenderPath
  StrCpy $BlenderReady "0"
  ${If} $BlenderPath == ""
    StrCpy $BlenderSummary "$(BlenderLater)"
    Return
  ${EndIf}
  IfFileExists "$BlenderPath" validate_blender
    ${NSD_SetText} $BlenderStatusLabel "$(BlenderPickFile)"
    Abort
  validate_blender:
  Delete "$PLUGINSDIR\blender.ini"
  nsExec::ExecToStack /TIMEOUT=20000 '"${SETUP_SYSTEM_DIR}\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\Setup-Preflight.ps1" -Action ValidateBlender -Language $SetupCulture -BlenderPath "$BlenderPath" -OutputPath "$PLUGINSDIR\blender.ini"'
  Pop $0
  Pop $1
  ReadINIStr $BlenderReady "$PLUGINSDIR\blender.ini" "Blender" "Ready"
  ReadINIStr $BlenderSummary "$PLUGINSDIR\blender.ini" "Blender" "Status"
  ${If} $BlenderReady != "1"
    ${If} $BlenderSummary == ""
      StrCpy $BlenderSummary "$(BlenderInvalid)"
    ${EndIf}
    ${NSD_SetText} $BlenderStatusLabel "$BlenderSummary"
    Abort
  ${EndIf}
  ReadINIStr $BlenderPath "$PLUGINSDIR\blender.ini" "Blender" "Path"
FunctionEnd

Function ShowComponentMode
  !insertmacro MUI_HEADER_TEXT "$(ComponentModeTitle)" "$(ComponentModeSubtitle)"
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 1u 100% 22u "$(WorkshopDescription)"
  Pop $0
  ${NSD_CreateCheckbox} 0 27u 100% 13u "$(InstallTrellisLabel)"
  Pop $TrellisCheckbox
  ${NSD_CreateCheckbox} 0 45u 100% 13u "$(InstallPixalLabel)"
  Pop $Pixal3DCheckbox
  ${NSD_CreateCheckbox} 0 63u 100% 13u "$(InstallRigLabel)"
  Pop $UniRigCheckbox
  ${If} $GpuSupported != "1"
    StrCpy $InstallTrellis "0"
    StrCpy $InstallPixal3D "0"
    EnableWindow $TrellisCheckbox 0
    EnableWindow $Pixal3DCheckbox 0
    StrCpy $1 "$(GpuNeedsDriver)"
  ${Else}
    StrCpy $1 "$(GpuProfileMatched)"
  ${EndIf}
  ${NSD_SetState} $TrellisCheckbox $InstallTrellis
  ${NSD_SetState} $Pixal3DCheckbox $InstallPixal3D
  ${NSD_SetState} $UniRigCheckbox $InstallUniRig
  ${NSD_OnClick} $TrellisCheckbox UpdateGenerationChoices
  ${NSD_OnClick} $Pixal3DCheckbox SelectTrellisDependency
  ${If} $GpuSupported != "1"
  ${OrIf} $RigSupported != "1"
    StrCpy $2 "$(RigUnsupported)"
    ${If} $RigStatus != ""
      StrCpy $2 "$RigStatus"
    ${EndIf}
  ${ElseIf} $WslReady != "1"
    StrCpy $2 "$(RigNeedsWsl)"
  ${ElseIf} $BlenderReady != "1"
    StrCpy $2 "$(RigNeedsBlender)"
  ${Else}
    StrCpy $2 "$(RigReadyForSetup)"
    ${If} $RigStatus != ""
      StrCpy $2 "$RigStatus"
    ${EndIf}
  ${EndIf}
  ${If} $GpuSupported != "1"
  ${OrIf} $RigSupported != "1"
  ${OrIf} $WslReady != "1"
  ${OrIf} $BlenderReady != "1"
    ${NSD_Uncheck} $UniRigCheckbox
    EnableWindow $UniRigCheckbox 0
  ${EndIf}
  ${NSD_CreateLabel} 0 84u 100% 18u "$1"
  Pop $0
  ${NSD_CreateLabel} 0 104u 100% 22u "$2"
  Pop $0
  ${If} $VramNotice != ""
    ${NSD_CreateLabel} 0 126u 100% 20u "$VramNotice"
  ${Else}
    ${NSD_CreateLabel} 0 126u 100% 13u "$(CheckSelectedEngines)"
  ${EndIf}
  Pop $0
  nsDialogs::Show
FunctionEnd

Function UpdateGenerationChoices
  Pop $0
  ${NSD_GetState} $TrellisCheckbox $0
  ${If} $0 != "1"
    ${NSD_Uncheck} $Pixal3DCheckbox
  ${EndIf}
FunctionEnd

Function SelectTrellisDependency
  Pop $0
  ${NSD_GetState} $0 $1
  ${If} $1 == "1"
    ${NSD_Check} $TrellisCheckbox
  ${EndIf}
FunctionEnd

Function SaveComponentMode
  ${NSD_GetState} $TrellisCheckbox $InstallTrellis
  ${NSD_GetState} $Pixal3DCheckbox $InstallPixal3D
  ${NSD_GetState} $UniRigCheckbox $InstallUniRig
  ${If} $InstallPixal3D == "1"
    StrCpy $InstallTrellis "1"
  ${EndIf}
FunctionEnd

Function NativeWorkflowChoiceChanged
  Pop $0
  ${NSD_GetState} $NativeWorkflowsCheckbox $0
  EnableWindow $NativeWorkflowLicenseCheckbox $0
FunctionEnd

Function OpenNativeWorkflowMeshLibLicense
  Pop $0
  ReadINIStr $1 "$PLUGINSDIR\preflight.ini" "NativeWorkflows" "MeshLibLicenseUrl"
  ${If} $1 != ""
    ExecShell "open" "$1"
  ${EndIf}
FunctionEnd

Function ShowNativeWorkflowOptions
  ReadINIStr $HighDetailGGUFSupported "$PLUGINSDIR\preflight.ini" "HighDetailGGUF" "Supported"
  ${If} $HighDetailGGUFSupported == "1"
    StrCpy $NativeWorkflowsSupported "0"
    Abort
  ${EndIf}
  ${If} $InstallTrellis != "1"
    StrCpy $SkipNativeWorkflows "0"
    Abort
  ${EndIf}
  !insertmacro MUI_HEADER_TEXT "$(NativeTitle)" "$(NativeSubtitle)"
  Call ExtractUltraTexLicense
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ReadINIStr $NativeWorkflowsSupported "$PLUGINSDIR\preflight.ini" "NativeWorkflows" "Supported"
  ReadINIStr $1 "$PLUGINSDIR\preflight.ini" "NativeWorkflows" "Status"
  ${If} $1 == ""
    StrCpy $1 "$(ProbeIncomplete)"
  ${EndIf}
  ${NSD_CreateCheckbox} 0 1u 100% 15u "$(NativeChoice)"
  Pop $NativeWorkflowsCheckbox
  ${NSD_OnClick} $NativeWorkflowsCheckbox NativeWorkflowChoiceChanged
  ${NSD_CreateLabel} 13u 19u -13u 23u "$(NativeDescription)"
  Pop $0
  ${NSD_CreateLabel} 13u 43u -13u 22u "$1"
  Pop $0
  ${If} $BlenderReady == "1"
    StrCpy $2 "$(NativeBlenderSelected)"
  ${Else}
    StrCpy $2 "$(NativeBlenderPortable)"
  ${EndIf}
  ${NSD_CreateLabel} 13u 67u -13u 14u "$2"
  Pop $0
  ReadINIStr $2 "$PLUGINSDIR\preflight.ini" "NativeWorkflows" "Guidance"
  ${NSD_CreateLabel} 13u 83u -13u 14u "$2"
  Pop $0
  ${NSD_CreateLink} 13u 99u 52% 11u "$(FluxTerms)"
  Pop $0
  ${NSD_OnClick} $0 OpenUltraTexLicense
  ${NSD_CreateLink} 58% 99u 35% 11u "$(MeshLibTerms)"
  Pop $0
  ${NSD_OnClick} $0 OpenNativeWorkflowMeshLibLicense
  ${If} $NativeWorkflowsSupported != "1"
    EnableWindow $0 0
  ${EndIf}
  ${NSD_CreateCheckbox} 0 112u 100% 22u "$(NativeLicenseChoice)"
  Pop $NativeWorkflowLicenseCheckbox
  StrCpy $0 $InstallNativeWorkflows
  ${If} $NativeWorkflowsSupported != "1"
    StrCpy $0 "0"
    EnableWindow $NativeWorkflowsCheckbox 0
  ${ElseIf} $NativeWorkflowsDefault == "1"
    StrCpy $0 "1"
  ${EndIf}
  ${NSD_SetState} $NativeWorkflowsCheckbox $0
  ${NSD_SetState} $NativeWorkflowLicenseCheckbox $AcceptNativeWorkflowLicenses
  EnableWindow $NativeWorkflowLicenseCheckbox $0
  nsDialogs::Show
FunctionEnd

Function SaveNativeWorkflowOptions
  ${If} $NativeWorkflowsSupported != "1"
    Return
  ${EndIf}
  ${NSD_GetState} $NativeWorkflowsCheckbox $InstallNativeWorkflows
  ${NSD_GetState} $NativeWorkflowLicenseCheckbox $AcceptNativeWorkflowLicenses
  StrCpy $NativeWorkflowsDefault "0"
  StrCpy $SkipNativeWorkflows "0"
  ${If} $InstallNativeWorkflows == "0"
    StrCpy $SkipNativeWorkflows "1"
  ${ElseIf} $AcceptNativeWorkflowLicenses != "1"
    MessageBox MB_ICONEXCLAMATION "$(NativeLicenseRequired)" /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Function ShowHighDetailGGUFOptions
  ${If} $InstallTrellis != "1"
  ${OrIf} $HighDetailGGUFSupported != "1"
    Abort
  ${EndIf}
  !insertmacro MUI_HEADER_TEXT "$(GGUFTitle)" "$(OptionalGpuSubtitle)"
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateCheckbox} 0 3u 100% 15u "$(GGUFChoice)"
  Pop $NativeWorkflowsCheckbox
  ${NSD_OnClick} $NativeWorkflowsCheckbox NativeWorkflowChoiceChanged
  ${NSD_CreateLabel} 13u 24u -13u 39u "$(GGUFDescription)"
  Pop $0
  ${NSD_CreateLink} 13u 68u 65% 12u "$(MeshLibTerms)"
  Pop $0
  ${NSD_OnClick} $0 OpenNativeWorkflowMeshLibLicense
  ${NSD_CreateCheckbox} 0 88u 100% 22u "$(GGUFConsent)"
  Pop $NativeWorkflowLicenseCheckbox
  ${NSD_SetState} $NativeWorkflowsCheckbox $InstallHighDetailGGUF
  ${NSD_SetState} $NativeWorkflowLicenseCheckbox $AcceptHighDetailMeshLib
  EnableWindow $NativeWorkflowLicenseCheckbox $InstallHighDetailGGUF
  nsDialogs::Show
FunctionEnd

Function SaveHighDetailGGUFOptions
  ${NSD_GetState} $NativeWorkflowsCheckbox $InstallHighDetailGGUF
  ${NSD_GetState} $NativeWorkflowLicenseCheckbox $AcceptHighDetailMeshLib
  StrCpy $SkipHighDetailGGUF "0"
  ${If} $InstallHighDetailGGUF != "1"
    StrCpy $SkipHighDetailGGUF "1"
  ${ElseIf} $AcceptHighDetailMeshLib != "1"
    MessageBox MB_ICONEXCLAMATION "$(GGUFAcceptRequired)" /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Function Hi3dChoiceChanged
  ${NSD_GetState} $Hi3dCheckbox $InstallHi3d
  EnableWindow $Hi3dLicenseCheckbox $InstallHi3d
FunctionEnd

Function OpenHi3dLicense
  ExecShell "open" "https://github.com/visualbruno/ComfyUI-Hi3D/blob/03dea7e366ba951d7475f3f1c8a71596a87f913c/LICENSE"
FunctionEnd

Function OpenHi3dDinoTerms
  ExecShell "open" "https://huggingface.co/facebook/dinov2-large/tree/47b73eefe95e8d44ec3623f8890bd894b6ea2d6c"
FunctionEnd

Function OpenHi3dClipTerms
  ExecShell "open" "https://huggingface.co/openai/clip-vit-large-patch14/tree/32bd64288804d66eefd0ccbe215aa642df71cc41"
FunctionEnd

Function ShowHi3dOptions
  !insertmacro MUI_HEADER_TEXT "$(Hi3dTitle)" "$(OptionalGpuSubtitle)"
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateCheckbox} 0 3u 100% 15u "$(Hi3dChoice)"
  Pop $Hi3dCheckbox
  ${NSD_OnClick} $Hi3dCheckbox Hi3dChoiceChanged
  ${NSD_CreateLabel} 13u 20u -13u 24u "$(Hi3dDescription)"
  Pop $0
  ReadINIStr $1 "$PLUGINSDIR\preflight.ini" "Hi3D" "Status"
  ReadINIStr $2 "$PLUGINSDIR\preflight.ini" "Hi3D" "VramNotice"
  ReadINIStr $Hi3dSupported "$PLUGINSDIR\preflight.ini" "Hi3D" "Supported"
  ${If} $1 == ""
    StrCpy $1 "$(ProbeIncomplete)"
  ${EndIf}
  ${NSD_CreateLabel} 13u 44u -13u 22u "$1"
  Pop $0
  ${NSD_CreateLabel} 13u 66u -13u 25u "$2"
  Pop $0
  ${NSD_CreateLink} 13u 94u 30% 11u "$(Hi3dTerms)"
  Pop $0
  ${NSD_OnClick} $0 OpenHi3dLicense
  ${NSD_CreateLink} 34% 94u 29% 11u "$(DinoTerms)"
  Pop $0
  ${NSD_OnClick} $0 OpenHi3dDinoTerms
  ${NSD_CreateLink} 66% 94u 28% 11u "$(ClipTerms)"
  Pop $0
  ${NSD_OnClick} $0 OpenHi3dClipTerms
  ${NSD_CreateCheckbox} 0 108u 100% 20u "$(Hi3dLicenseChoice)"
  Pop $Hi3dLicenseCheckbox
  ${If} $Hi3dSupported != "1"
    StrCpy $InstallHi3d "0"
    EnableWindow $Hi3dCheckbox 0
  ${EndIf}
  ${NSD_SetState} $Hi3dCheckbox $InstallHi3d
  ${NSD_SetState} $Hi3dLicenseCheckbox $AcceptHi3dLicenses
  EnableWindow $Hi3dLicenseCheckbox $InstallHi3d
  nsDialogs::Show
FunctionEnd

Function SaveHi3dOptions
  ${NSD_GetState} $Hi3dCheckbox $InstallHi3d
  ${NSD_GetState} $Hi3dLicenseCheckbox $AcceptHi3dLicenses
  StrCpy $SkipHi3d "0"
  ${If} $Hi3dSupported == "1"
  ${AndIf} $InstallHi3d == "0"
    StrCpy $SkipHi3d "1"
  ${EndIf}
  ${If} $InstallHi3d == "1"
  ${AndIf} $AcceptHi3dLicenses != "1"
    MessageBox MB_ICONEXCLAMATION "$(Hi3dLicenseRequired)" /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Function MultiviewTextureChoiceChanged
  ${NSD_GetState} $MultiviewTextureCheckbox $InstallMultiviewTexture
  EnableWindow $MultiviewTextureLicenseCheckbox $InstallMultiviewTexture
FunctionEnd

Function OpenMultiviewTextureBaseLicense
  ExecShell "open" "$PLUGINSDIR\Stable-Diffusion-2.1-OpenRAIL++-M.txt"
FunctionEnd

Function OpenMultiviewTextureAdapterLicense
  ExecShell "open" "https://github.com/huanngzh/MV-Adapter/blob/4277e0018232bac82bb2c103caf0893cedb711be/LICENSE"
FunctionEnd

Function ShowMultiviewTextureOptions
  !insertmacro MUI_HEADER_TEXT "$(MultiviewTitle)" "$(OptionalGpuSubtitle)"
  InitPluginsDir
  File /oname=$PLUGINSDIR\Stable-Diffusion-2.1-OpenRAIL++-M.txt "${PAYLOAD_ROOT}\licenses\Stable-Diffusion-2.1-OpenRAIL++-M.txt"
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateCheckbox} 0 3u 100% 15u "$(MultiviewChoice)"
  Pop $MultiviewTextureCheckbox
  ${NSD_OnClick} $MultiviewTextureCheckbox MultiviewTextureChoiceChanged
  ${NSD_CreateLabel} 13u 20u -13u 25u "$(MultiviewDescription)"
  Pop $0
  ReadINIStr $1 "$PLUGINSDIR\preflight.ini" "MultiviewTexture" "Status"
  ReadINIStr $2 "$PLUGINSDIR\preflight.ini" "MultiviewTexture" "VramNotice"
  ReadINIStr $MultiviewTextureSupported "$PLUGINSDIR\preflight.ini" "MultiviewTexture" "Supported"
  ${If} $1 == ""
    StrCpy $1 "$(ProbeIncomplete)"
  ${EndIf}
  ${NSD_CreateLabel} 13u 47u -13u 22u "$1"
  Pop $0
  ${NSD_CreateLabel} 13u 70u -13u 25u "$2"
  Pop $0
  ${NSD_CreateLink} 13u 96u 50% 11u "$(DiffusionTerms)"
  Pop $0
  ${NSD_OnClick} $0 OpenMultiviewTextureBaseLicense
  ${NSD_CreateLink} 65% 96u 34% 11u "$(AdapterTerms)"
  Pop $0
  ${NSD_OnClick} $0 OpenMultiviewTextureAdapterLicense
  ${NSD_CreateCheckbox} 0 110u 100% 20u "$(MultiviewLicenseChoice)"
  Pop $MultiviewTextureLicenseCheckbox
  ${If} $MultiviewTextureSupported != "1"
    StrCpy $InstallMultiviewTexture "0"
    EnableWindow $MultiviewTextureCheckbox 0
  ${EndIf}
  ${NSD_SetState} $MultiviewTextureCheckbox $InstallMultiviewTexture
  ${NSD_SetState} $MultiviewTextureLicenseCheckbox $AcceptMultiviewTextureLicenses
  EnableWindow $MultiviewTextureLicenseCheckbox $InstallMultiviewTexture
  nsDialogs::Show
FunctionEnd

Function SaveMultiviewTextureOptions
  ${NSD_GetState} $MultiviewTextureCheckbox $InstallMultiviewTexture
  ${NSD_GetState} $MultiviewTextureLicenseCheckbox $AcceptMultiviewTextureLicenses
  StrCpy $SkipMultiviewTexture "0"
  ${If} $MultiviewTextureSupported == "1"
  ${AndIf} $InstallMultiviewTexture == "0"
    StrCpy $SkipMultiviewTexture "1"
  ${EndIf}
  ${If} $InstallMultiviewTexture == "1"
  ${AndIf} $AcceptMultiviewTextureLicenses != "1"
    MessageBox MB_ICONEXCLAMATION "$(MultiviewLicenseRequired)" /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Function UltraTexChoiceChanged
  Pop $0
  ${NSD_GetState} $UltraTexCheckbox $InstallUltraTex
  EnableWindow $UltraTexLicenseCheckbox $InstallUltraTex
FunctionEnd

Function OpenUltraTexLicense
  Pop $0
  ExecShell "open" "$PLUGINSDIR\FLUX.2-klein-base-9B-LICENSE.txt"
FunctionEnd

Function ExtractUltraTexLicense
  InitPluginsDir
  File /oname=$PLUGINSDIR\FLUX.2-klein-base-9B-LICENSE.txt "${PAYLOAD_ROOT}\licenses\FLUX.2-klein-base-9B-LICENSE.md"
FunctionEnd

Function ShowUltraTexOptions
  !insertmacro MUI_HEADER_TEXT "$(UltraTexTitle)" "$(UltraTexSubtitle)"
  Call ExtractUltraTexLicense
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateCheckbox} 0 3u 100% 15u "$(UltraTexChoice)"
  Pop $UltraTexCheckbox
  ${NSD_OnClick} $UltraTexCheckbox UltraTexChoiceChanged
  ${NSD_CreateLabel} 13u 20u -13u 30u "$(UltraTexDescription)"
  Pop $0
  ReadINIStr $1 "$PLUGINSDIR\preflight.ini" "UltraTex" "Status"
  ReadINIStr $2 "$PLUGINSDIR\preflight.ini" "UltraTex" "Guidance"
  ReadINIStr $UltraTexSupported "$PLUGINSDIR\preflight.ini" "UltraTex" "Supported"
  ${If} $1 == ""
    StrCpy $1 "$(ProbeIncomplete)"
  ${EndIf}
  ${NSD_CreateLabel} 13u 50u -13u 23u "$1"
  Pop $0
  ${NSD_CreateLabel} 13u 75u -13u 21u "$2"
  Pop $0
  ${NSD_CreateLink} 13u 98u 90% 11u "$(UltraTexTerms)"
  Pop $0
  ${NSD_OnClick} $0 OpenUltraTexLicense
  ${NSD_CreateCheckbox} 0 111u 100% 22u "$(UltraTexLicenseChoice)"
  Pop $UltraTexLicenseCheckbox
  ${If} $UltraTexSupported != "1"
    StrCpy $InstallUltraTex "0"
    EnableWindow $UltraTexCheckbox 0
  ${EndIf}
  ${NSD_SetState} $UltraTexCheckbox $InstallUltraTex
  ${NSD_SetState} $UltraTexLicenseCheckbox $AcceptUltraTexLicenses
  EnableWindow $UltraTexLicenseCheckbox $InstallUltraTex
  nsDialogs::Show
FunctionEnd

Function SaveUltraTexOptions
  ${NSD_GetState} $UltraTexCheckbox $InstallUltraTex
  ${NSD_GetState} $UltraTexLicenseCheckbox $AcceptUltraTexLicenses
  StrCpy $SkipUltraTex "0"
  ${If} $UltraTexSupported == "1"
  ${AndIf} $InstallUltraTex == "0"
    StrCpy $SkipUltraTex "1"
  ${EndIf}
  ${If} $InstallUltraTex == "1"
  ${AndIf} $AcceptUltraTexLicenses != "1"
    MessageBox MB_ICONEXCLAMATION "$(UltraTexLicenseRequired)" /SD IDOK
    Abort
  ${EndIf}
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
  nsExec::ExecToStack '"${SETUP_SYSTEM_DIR}\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\check-idle.ps1" -InstallRoot "$INSTDIR" ${ExtraArguments}'
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
  nsExec::ExecToStack '"${SETUP_SYSTEM_DIR}\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\Manage-Shortcuts.ps1" -InstallRoot "$INSTDIR" -Action ${Mode} -SetupLanguage $LANGUAGE ${ExtraArguments}'
  Pop $0
  Pop $1
  ${If} $1 != ""
    DetailPrint "$1"
  ${EndIf}
!macroend

!macro WriteSetupMarker Marker Label
  ClearErrors
  FileOpen $0 "$INSTDIR\${Marker}" r
  ${IfNot} ${Errors}
    StrCpy $1 ""
    FileRead $0 $1
    FileClose $0
    StrCmp $1 "${SETUP_NAME}" marker_ready_${Label}
  ${EndIf}
  ClearErrors
  StrCpy $2 "$INSTDIR\${Marker}"
  FileOpen $0 "$2" w
  IfErrors marker_failed
  FileWrite $0 "${SETUP_NAME}"
  IfErrors marker_write_failed
  FileClose $0
  IfErrors marker_close_failed
  marker_ready_${Label}:
!macroend

Section "${SETUP_NAME}"
  Call ValidateInstallFolder
  !insertmacro CheckIdle
  ClearErrors
  SetOutPath "$INSTDIR"
  IfErrors marker_failed
  !insertmacro WriteSetupMarker "${SETUP_MARKER}" owner
!ifdef SETUP_PREVIEW
  !insertmacro WriteSetupMarker "${GUIDED_MARKER}" guided
!endif
  ClearErrors
  !include "${INSTALL_FILES}"
  IfErrors payload_failed
  SetOutPath "$INSTDIR"
  IfErrors payload_failed
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  IfErrors payload_failed
  WriteRegStr HKCU "${SETUP_KEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${ARP}" "DisplayName" "${SETUP_NAME}"
  WriteRegStr HKCU "${ARP}" "DisplayVersion" "${STUDIO_VERSION}"
  WriteRegStr HKCU "${ARP}" "Publisher" "TRELLIS Studio contributors"
  WriteRegStr HKCU "${ARP}" "DisplayIcon" "$INSTDIR\installer\windows\trellis-studio.ico"
  WriteRegStr HKCU "${ARP}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${ARP}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${ARP}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${ARP}" "NoModify" 1
  WriteRegDWORD HKCU "${ARP}" "NoRepair" 1
!ifndef SETUP_PREVIEW
  IfSilent 0 prepare_shortcuts
  StrCpy $InstallServer "0"
  IfFileExists "$INSTDIR\config\server.json" 0 prepare_shortcuts
  StrCpy $InstallServer "1"
  prepare_shortcuts:
!endif
  !insertmacro ManageShortcuts "Install" "-DesktopShortcut $CreateDesktopShortcut -ServerMode $InstallServer"
  ${If} $0 != "0"
    MessageBox MB_ICONEXCLAMATION "$(ShortcutError)" /SD IDOK
  ${EndIf}
  StrCpy $KimodoArguments ""
  ${If} $InstallKimodo == "1"
  ${AndIf} $AcceptKimodoLicenses == "1"
    StrCpy $KimodoArguments "-WithKimodo -AcceptKimodoModelLicenses"
  ${EndIf}
!ifdef SETUP_PREVIEW
  IfSilent install_done
!else
  IfSilent 0 assemble_selection
  ; Silent reinstalls never open the server configuration dialog.
  StrCmp $InstallServer "1" install_done
  assemble_selection:
!endif
  StrCpy $ComponentsArgument ""
  StrCpy $HardwareArguments ""
  ${If} $InstallTrellis == "1"
    StrCpy $ComponentsArgument "trellis"
    ${If} $InstallNativeWorkflows == "1"
    ${AndIf} $NativeWorkflowsSupported == "1"
      StrCpy $ComponentsArgument "$ComponentsArgument,native-workflows"
    ${EndIf}
    ${If} $InstallHighDetailGGUF == "1"
    ${AndIf} $HighDetailGGUFSupported == "1"
      StrCpy $ComponentsArgument "$ComponentsArgument,high-detail-gguf"
    ${EndIf}
  ${EndIf}
  ${If} $InstallPixal3D == "1"
    StrCpy $ComponentsArgument "$ComponentsArgument,pixal3d"
  ${EndIf}
  ${If} $InstallUniRig == "1"
    ${If} $ComponentsArgument == ""
      StrCpy $ComponentsArgument "unirig"
    ${Else}
      StrCpy $ComponentsArgument "$ComponentsArgument,unirig"
    ${EndIf}
  ${EndIf}
  ${If} $InstallHi3d == "1"
    ${If} $ComponentsArgument == ""
      StrCpy $ComponentsArgument "hi3d"
    ${Else}
      StrCpy $ComponentsArgument "$ComponentsArgument,hi3d"
    ${EndIf}
  ${EndIf}
  ${If} $InstallMultiviewTexture == "1"
    ${If} $ComponentsArgument == ""
      StrCpy $ComponentsArgument "multiview-texture"
    ${Else}
      StrCpy $ComponentsArgument "$ComponentsArgument,multiview-texture"
    ${EndIf}
  ${EndIf}
  ${If} $InstallUltraTex == "1"
    ${If} $ComponentsArgument == ""
      StrCpy $ComponentsArgument "ultratex"
    ${Else}
      StrCpy $ComponentsArgument "$ComponentsArgument,ultratex"
    ${EndIf}
  ${EndIf}
  ${If} $ComponentsArgument != ""
    StrCpy $HardwareArguments '-Components "$ComponentsArgument"'
    ${If} $GpuUuid != ""
      StrCpy $HardwareArguments '$HardwareArguments -GpuUuid "$GpuUuid"'
    ${EndIf}
    ${If} $InstallUniRig == "1"
    ${AndIf} $WslDistribution != ""
      StrCpy $HardwareArguments '$HardwareArguments -WslDistribution "$WslDistribution"'
    ${EndIf}
  ${EndIf}
  ${If} $InstallTrellis == "1"
  ${AndIf} $InstallNativeWorkflows == "1"
  ${AndIf} $NativeWorkflowsSupported == "1"
  ${AndIf} $AcceptNativeWorkflowLicenses == "1"
    StrCpy $HardwareArguments "$HardwareArguments -AcceptNativeWorkflowModelLicenses"
  ${ElseIf} $SkipNativeWorkflows == "1"
    StrCpy $HardwareArguments "$HardwareArguments -SkipNativeWorkflows"
  ${EndIf}
  ${If} $InstallTrellis == "1"
  ${AndIf} $InstallHighDetailGGUF == "1"
  ${AndIf} $HighDetailGGUFSupported == "1"
  ${AndIf} $AcceptHighDetailMeshLib == "1"
    StrCpy $HardwareArguments "$HardwareArguments -AcceptHighDetailMeshLib"
  ${ElseIf} $SkipHighDetailGGUF == "1"
    StrCpy $HardwareArguments "$HardwareArguments -SkipHighDetailGGUF"
  ${EndIf}
  ${If} $InstallHi3d == "1"
  ${AndIf} $AcceptHi3dLicenses == "1"
    StrCpy $HardwareArguments "$HardwareArguments -AcceptHi3dModelLicenses"
  ${ElseIf} $SkipHi3d == "1"
    StrCpy $HardwareArguments "$HardwareArguments -SkipHi3d"
  ${EndIf}
  ${If} $InstallMultiviewTexture == "1"
  ${AndIf} $AcceptMultiviewTextureLicenses == "1"
    StrCpy $HardwareArguments "$HardwareArguments -AcceptMultiviewTextureModelLicenses"
  ${ElseIf} $SkipMultiviewTexture == "1"
    StrCpy $HardwareArguments "$HardwareArguments -SkipMultiviewTexture"
  ${EndIf}
  ${If} $InstallUltraTex == "1"
  ${AndIf} $AcceptUltraTexLicenses == "1"
    StrCpy $HardwareArguments "$HardwareArguments -AcceptUltraTexModelLicenses"
  ${ElseIf} $SkipUltraTex == "1"
    StrCpy $HardwareArguments "$HardwareArguments -SkipUltraTex"
  ${EndIf}
  ${If} $BlenderReady == "1"
  ${AndIf} $BlenderPath != ""
    StrCpy $HardwareArguments '$HardwareArguments -BlenderPath "$BlenderPath"'
  ${EndIf}

  ${If} $InstallServer == "1"
    DetailPrint "$(InstallingServer)"
    StrCpy $1 "ServerSetup"
  ${Else}
    DetailPrint "$(InstallingWorkshop)"
    StrCpy $1 "PrepareWorkshop"
  ${EndIf}
  ClearErrors
  ExecWait '"${SETUP_SYSTEM_DIR}\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\installer\windows\Launch-Installed.ps1" -Mode $1 -Guided -NoBrowser -SetupLanguage $LANGUAGE $HardwareArguments $KimodoArguments' $0
  IfErrors setup_failed
  ${If} $0 == "3"
    DetailPrint "$(ComponentsNeedAttention)"
    MessageBox MB_ICONEXCLAMATION "$(ComponentsNeedAttention)" /SD IDOK
    SetErrorLevel 3
  ${ElseIf} $0 != "0"
    Goto setup_failed
  ${EndIf}
  Goto install_done

  setup_failed:
    ${If} $InstallServer == "1"
      DetailPrint "$(ServerFailed)"
      MessageBox MB_ICONEXCLAMATION "$(ServerFailed)" /SD IDOK
    ${Else}
      DetailPrint "$(WorkshopFailed)"
      MessageBox MB_ICONEXCLAMATION "$(WorkshopFailed)" /SD IDOK
    ${EndIf}
    SetErrorLevel 3
    Abort
  marker_write_failed:
    FileClose $0
  marker_close_failed:
    Delete "$2"
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
  System::Call 'kernel32::SetEnvironmentVariableW(w "PSModulePath", p 0)'
  !insertmacro MUI_UNGETLANGUAGE
  IfFileExists "$INSTDIR\.git" foreign
  IfFileExists "$INSTDIR\.git\*.*" foreign
!ifndef SETUP_PREVIEW
  IfFileExists "$INSTDIR\${PREVIEW_MARKER}" foreign
!endif
  ClearErrors
  FileOpen $0 "$INSTDIR\${SETUP_MARKER}" r
  IfErrors foreign
  StrCpy $1 ""
  FileRead $0 $1
  FileClose $0
  StrCmp $1 "${SETUP_NAME}" allowed
  foreign:
    MessageBox MB_ICONSTOP "$(DifferentUninstall)" /SD IDOK
    SetErrorLevel 2
    Abort
  allowed:
    ClearErrors
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
  ReadRegStr $0 HKCU "${SETUP_KEY}" "InstallDir"
  ${If} $0 == "$INSTDIR"
    DeleteRegKey HKCU "${ARP}"
    DeleteRegKey HKCU "${SETUP_KEY}"
  ${EndIf}
SectionEnd

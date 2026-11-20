; Inno Setup-skript for Akasha Protokoll (installationsfil per anvandare, utan administratorsratt).
;   ISCC.exe /DVersion=0.2.0.1 /DKalla="dist\Akasha Protokoll" /DIkon="build\app\ikon.ico" /DUt=dist paketering\akasha-protokoll.iss
; /D-vardena satts av paketering/bygg_installation.py. Standardvardena nedan ar relativa till den har filen.
; Filen sparas som UTF-8 med BOM, sa att Inno Setup laser a-ring, a-prickar och o-prickar ratt.
#ifndef Version
  #define Version "0.2.0.0"
#endif
#ifndef Kalla
  #define Kalla "..\dist\Akasha Protokoll"
#endif
#ifndef Ikon
  #define Ikon "..\build\app\ikon.ico"
#endif
#ifndef Ut
  #define Ut "..\dist"
#endif
#define Namn "Akasha Protokoll"
#define Exe "Akasha Protokoll.exe"
; Swedish.isl foljer med Inno Setup bara om den installationen har den (den ar en inofficiell oversattning). Annars
; anvands det inbyggda (engelska) och texterna nedan i [Messages] och [Tasks] ar anda pa svenska.
#if FileExists(CompilerPath + "Languages\Swedish.isl")
  #define SprakFil "compiler:Languages\Swedish.isl"
#else
  #define SprakFil "compiler:Default.isl"
#endif

[Setup]
AppId={{9E5B73C9-B94B-4979-B5DF-00C834E09C1E}
AppName={#Namn}
AppVersion={#Version}
AppCopyright=© 2026 Dennis Fredin. Apache-2.0.
VersionInfoVersion={#Version}
VersionInfoDescription={#Namn}
VersionInfoCopyright=© 2026 Dennis Fredin. Apache-2.0.
; Per anvandare: ingen administratorsratt, ingen UAC-ruta. Programmappen ligger under %LOCALAPPDATA%\Programs.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#Namn}
DisableProgramGroupPage=yes
; Alltid %LOCALAPPDATA%\Programs\Akasha Protokoll: ingen katalogsida, sa att ingen valjer en katalog med annat i.
; /DIR= pa kommandoraden galler anda (kontrollen i Actions anvander det).
DisableDirPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
LicenseFile=..\LICENSE
SetupIconFile={#Ikon}
UninstallDisplayIcon={app}\{#Exe}
UninstallDisplayName={#Namn}
OutputDir={#Ut}
OutputBaseFilename=Akasha-Protokoll-installation
Compression=lzma2
SolidCompression=yes
; Programmets mutex (app/windows_app.py: MUTEX) heter Local\AkashaProtokoll. Inno Setup oppnar namnet som det star med
; OpenMutex, och ett namn med Local\ ar sessionens egen namnrymd, samma som programmet skapade. Installationsfilen
; och avinstallationen ber anvandaren avsluta programmet om mutexen finns; de stanger det inte sjalva (en inspelning
; kan pagia), darfor CloseApplications=no.
AppMutex=Local\AkashaProtokoll
CloseApplications=no

[Languages]
Name: "sv"; MessagesFile: "{#SprakFil}"

[Messages]
LicenseLabel=Läs licensen nedan innan du fortsätter. Andra delar av programmet har egna licenser.

[Tasks]
Name: "desktopicon"; Description: "Skapa en genväg på skrivbordet"; Flags: unchecked

[Files]
Source: "{#Kalla}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#Namn}"; Filename: "{app}\{#Exe}"
Name: "{autodesktop}\{#Namn}"; Filename: "{app}\{#Exe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#Exe}"; Description: "Starta Akasha Protokoll"; Flags: nowait postinstall skipifsilent

; Inno Setup tar bort sina egna filer och tomma kataloger. Hit hor bara det som PyInstaller kan ha skapat efter
; installationen (__pycache__ i _internal). {app} i sig tas aldrig bort med allt innehall: en katalog med andras filer
; (eller anvandarens data) ska klara en avinstallation. Inspelningarna (AkashaProtokoll i hemkatalogen) och modellerna och
; installningarna (%LOCALAPPDATA%\Akasha Protokoll) ligger i andra kataloger och rors aldrig.
[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    SuppressibleMsgBox('Dina inspelningar ligger kvar i mappen AkashaProtokoll i din hemkatalog, och modellerna i %LOCALAPPDATA%\Akasha Protokoll. Ta bort dem själv om du inte vill ha dem.', mbInformation, MB_OK, IDOK);
end;

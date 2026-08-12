; packaging/windows/setup.iss
; Script para Inno Setup

[Setup]
AppId={{F4B6E64A-2E7C-4B7E-8A2A-6A2D2B8C0F1A}
AppName=IPTV Player
AppVersion=1.0.0
AppPublisher=IPTV Player Project
DefaultDirName={autopf}\IPTV Player
DefaultGroupName=IPTV Player
OutputBaseFilename=IPTV-Player-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
SetupIconFile=..\..\resources\icon.ico
UninstallDisplayIcon={app}\resources\icon.ico
ChangesAssociations=yes

; Diretório de saída para o instalador compilado
OutputDir=..\..\dist

[Languages]
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 1. Empacota a versão embutida do Python (deve ser descarregada e colocada aqui)
Source: "python-embed\*"; DestDir: "{app}\python"; Flags: recursesubdirs

; 2. Empacota o código fonte da aplicação
Source: "..\..\src\*"; DestDir: "{app}\src"; Flags: recursesubdirs
Source: "..\..\main.py"; DestDir: "{app}"
Source: "..\..\requirements.txt"; DestDir: "{app}"
Source: "..\..\resources\*"; DestDir: "{app}\resources"; Flags: recursesubdirs

; 3. Script que será executado para configurar o ambiente
Source: "setup_venv.bat"; DestDir: "{app}"

[Icons]
Name: "{group}\IPTV Player"; Filename: "{app}\IPTV Player.exe"
Name: "{group}\{cm:UninstallProgram,IPTV Player}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\IPTV Player"; Filename: "{app}\IPTV Player.exe"; Tasks: desktopicon

[Run]
; Executa o script para criar o venv e instalar dependências após a cópia dos ficheiros
Filename: "{app}\setup_venv.bat"; Parameters: """{app}"""; StatusMsg: "A configurar o ambiente da aplicação..."; Flags: runhidden waituntilterminated

; Cria um executável 'wrapper' para não mostrar a consola
Filename: "{app}\python\python.exe"; Parameters: "-m PySide6.scripts.pyside6-windows-resource-compiler -o ""{app}\IPTV Player.exe"" ""{app}\resources\win_wrapper.rc"""; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}"

[Code]
function IsVlcInstalled: boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\VideoLAN\VLC') or
            RegKeyExists(HKCU, 'SOFTWARE\VideoLAN\VLC') or
            RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\VideoLAN\VLC');
end;

function InitializeSetup(): Boolean;
begin
  if not IsVlcInstalled then
  begin
    MsgBox('O VLC Media Player não foi encontrado. É necessário para a reprodução de vídeo.'#13#10#13'Por favor, instale o VLC a partir de www.videolan.org e execute a instalação novamente.', mbError, MB_OK);
    Result := False;
  end
  else
    Result := True;
end;
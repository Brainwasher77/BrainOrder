; Instalador de BrainOrder para Windows (Inno Setup 6). Lo arma GitHub Actions:
;   iscc /DVER=2.17.0 /DSRC=..\..\dist\win /DOUT=..\..\dist empaquetar\windows\BrainOrder.iss
; Trae su propio Python con todo lo necesario (no hace falta instalar nada más) y, durante la instalación,
; pregunta tus carpetas y te guía con la app de Spotify. Lo que elijas queda en %APPDATA%\BrainOrder\preconfig.json
; y BrainOrder lo usa al abrirse por primera vez.

#ifndef VER
  #define VER "0.0.0"
#endif
#ifndef SRC
  #define SRC "..\..\dist\win"
#endif
#ifndef OUT
  #define OUT "..\..\dist"
#endif

[Setup]
AppId={{6F0B7C1E-3B7A-4C55-9E3B-B0A1D0E2F0C7}
AppName=BrainOrder
AppVersion={#VER}
AppVerName=BrainOrder {#VER}
AppPublisher=Brainwasher77
AppPublisherURL=https://github.com/Brainwasher77/BrainOrder
DefaultDirName={localappdata}\Programs\BrainOrder
DefaultGroupName=BrainOrder
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir={#OUT}
OutputBaseFilename=BrainOrder-{#VER}-Windows
SetupIconFile={#SRC}\app\icon.ico
UninstallDisplayIcon={app}\app\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "{#SRC}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SRC}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; el código viejo del programa se reemplaza entero
Type: filesandordirs; Name: "{app}\app"

[Icons]
Name: "{userprograms}\BrainOrder"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\arranque.py"" --seed"; WorkingDir: "{app}"; IconFilename: "{app}\app\icon.ico"; Comment: "BrainOrder: tus playlists, tu música y tus programas de DJ"
Name: "{userdesktop}\BrainOrder"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\arranque.py"" --seed"; WorkingDir: "{app}"; IconFilename: "{app}\app\icon.ico"; Comment: "BrainOrder: tus playlists, tu música y tus programas de DJ"

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\arranque.py"" --seed"; WorkingDir: "{app}"; Description: "Abrir BrainOrder"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
const
  REDIRECT = 'http://127.0.0.1:8888/callback';
  DASHBOARD = 'https://developer.spotify.com/dashboard';
  WEBVIEW2 = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';

var
  FolderPage: TInputDirWizardPage;
  SpotifyPage: TWizardPage;
  CidEdit: TNewEdit;
  CidMsg: TNewStaticText;
  AlreadySetUp: Boolean;

function SupportDir(): String;
begin
  Result := ExpandConstant('{userappdata}\BrainOrder');
  if (not DirExists(Result)) and DirExists(ExpandConstant('{userappdata}\SpotiSync')) then
    Result := ExpandConstant('{userappdata}\SpotiSync');
end;

{ ¿Ya estaba configurado? (instalación anterior): entonces no se pregunta nada y se mantiene todo }
function IsSetUp(): Boolean;
var
  S: AnsiString;
begin
  Result := False;
  if LoadStringFromFile(SupportDir() + '\config.json', S) then
    Result := (Pos('"setup_done": true', S) > 0);
end;

function HasWebView2(): Boolean;
var
  V: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V) and (V <> '') and (V <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V) and (V <> '') and (V <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V) and (V <> '') and (V <> '0.0.0.0'));
end;

procedure OpenUrl(Url: String);
var
  Code: Integer;
begin
  ShellExec('open', Url, '', '', SW_SHOWNORMAL, ewNoWait, Code);
end;

procedure DashboardClick(Sender: TObject);
begin
  OpenUrl(DASHBOARD);
end;

function IsHex(S: String): Boolean;
var
  I: Integer;
  C: Char;
begin
  Result := Length(S) = 32;
  if Result then
    for I := 1 to Length(S) do
    begin
      C := S[I];
      if not (((C >= '0') and (C <= '9')) or ((C >= 'a') and (C <= 'f')) or ((C >= 'A') and (C <= 'F'))) then
      begin
        Result := False;
        Exit;
      end;
    end;
end;

procedure CidChange(Sender: TObject);
var
  S: String;
begin
  S := Trim(CidEdit.Text);
  if S = '' then
    CidMsg.Caption := 'Si lo dejas vacío, lo pones después en BrainOrder (te guía al abrirlo).'
  else if IsHex(S) then
    CidMsg.Caption := '✓ Se ve bien. Al abrir BrainOrder autorizas tu cuenta en el navegador.'
  else
    CidMsg.Caption := 'El Client ID son 32 letras y números: revisa que lo copiaste completo.';
end;

function AddLabel(Parent: TWizardPage; Top: Integer; Text: String; Bold: Boolean): TNewStaticText;
begin
  Result := TNewStaticText.Create(Parent);
  Result.Parent := Parent.Surface;
  Result.Top := Top;
  Result.Left := 0;
  Result.Width := Parent.SurfaceWidth;
  Result.AutoSize := False;
  Result.WordWrap := True;
  Result.Caption := Text;
  if Bold then Result.Font.Style := [fsBold];
  Result.Height := ScaleY(30);
  Result.AdjustHeight();
end;

procedure InitializeWizard();
var
  T: Integer;
  L: TNewStaticText;
  B: TNewButton;
  Uri: TNewEdit;
begin
  AlreadySetUp := IsSetUp();

  { --- Carpetas --- }
  FolderPage := CreateInputDirPage(wpWelcome, 'Tus carpetas de música',
    '¿Dónde organizo tu música y dónde caen tus descargas?',
    'BrainOrder ordena tus canciones en una subcarpeta por playlist y revisa la carpeta de descargas para ' +
    'ubicar lo nuevo. Si no existen, se crean. Nunca borra música: lo repetido se aparta en «_duplicados».',
    False, 'BrainOrder');
  FolderPage.Add('Música organizada (una subcarpeta por playlist):');
  FolderPage.Add('Descargas nuevas (donde guardas lo que bajas):');
  FolderPage.Values[0] := ExpandConstant('{%USERPROFILE}\Music\Playlists BrainOrder');
  FolderPage.Values[1] := ExpandConstant('{%USERPROFILE}\Music\Descargas BrainOrder');

  { --- Spotify --- }
  SpotifyPage := CreateCustomPage(FolderPage.ID, 'Conectar Spotify',
    'Spotify pide que cada persona use su propia «app» de desarrollador (gratis, una sola vez).');
  T := 0;
  L := AddLabel(SpotifyPage, T, '1. Abre el panel de desarrolladores de Spotify e inicia sesión con tu cuenta:', False);
  T := L.Top + L.Height + ScaleY(4);
  B := TNewButton.Create(SpotifyPage);
  B.Parent := SpotifyPage.Surface;
  B.Top := T; B.Left := ScaleX(14); B.Width := ScaleX(200); B.Height := ScaleY(24);
  B.Caption := 'Abrir developer.spotify.com';
  B.OnClick := @DashboardClick;
  T := B.Top + B.Height + ScaleY(8);
  L := AddLabel(SpotifyPage, T, '2. Toca «Create app» (nombre y descripción: lo que quieras, p. ej. BrainOrder).', False);
  T := L.Top + L.Height + ScaleY(6);
  L := AddLabel(SpotifyPage, T, '3. En «Redirect URIs» pega esto y toca «Add» (selecciónalo y Ctrl+C):', False);
  T := L.Top + L.Height + ScaleY(4);
  Uri := TNewEdit.Create(SpotifyPage);
  Uri.Parent := SpotifyPage.Surface;
  Uri.Top := T; Uri.Left := ScaleX(14); Uri.Width := ScaleX(260);
  Uri.Text := REDIRECT;
  Uri.ReadOnly := True;
  T := Uri.Top + Uri.Height + ScaleY(8);
  L := AddLabel(SpotifyPage, T, '4. Marca «Web API», acepta los términos y toca «Save».', False);
  T := L.Top + L.Height + ScaleY(6);
  L := AddLabel(SpotifyPage, T, '5. Entra a «Settings» de tu app, copia el «Client ID» y pégalo aquí:', False);
  T := L.Top + L.Height + ScaleY(4);
  CidEdit := TNewEdit.Create(SpotifyPage);
  CidEdit.Parent := SpotifyPage.Surface;
  CidEdit.Top := T; CidEdit.Left := ScaleX(14); CidEdit.Width := SpotifyPage.SurfaceWidth - ScaleX(14);
  CidEdit.OnChange := @CidChange;
  T := CidEdit.Top + CidEdit.Height + ScaleY(4);
  CidMsg := AddLabel(SpotifyPage, T, '', False);
  CidMsg.Height := ScaleY(28);
  CidChange(nil);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not HasWebView2() then
  begin
    if MsgBox('BrainOrder usa Microsoft Edge WebView2 para su ventana y no lo encontré en este computador.' + #13#10#13#10 +
              '¿Abro la página de Microsoft para instalarlo? (Es gratis; instálalo y luego abre BrainOrder.)',
              mbConfirmation, MB_YESNO) = IDYES then
      OpenUrl(WEBVIEW2);
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := AlreadySetUp and ((PageID = FolderPage.ID) or (PageID = SpotifyPage.ID));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  A, B: String;
begin
  Result := True;
  if CurPageID = FolderPage.ID then
  begin
    A := Trim(FolderPage.Values[0]);
    B := Trim(FolderPage.Values[1]);
    if (A = '') or (B = '') then
    begin
      MsgBox('Elige las dos carpetas.', mbError, MB_OK);
      Result := False;
    end
    else if (CompareText(AddBackslash(A), AddBackslash(B)) = 0) or
            (Pos(Lowercase(AddBackslash(A)), Lowercase(AddBackslash(B))) = 1) or
            (Pos(Lowercase(AddBackslash(B)), Lowercase(AddBackslash(A))) = 1) then
    begin
      MsgBox('La carpeta de música organizada y la de descargas no pueden ser la misma ni estar una dentro de la otra.', mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = SpotifyPage.ID then
  begin
    A := Trim(CidEdit.Text);
    if (A <> '') and not IsHex(A) then
    begin
      MsgBox('El Client ID son 32 letras y números. Revisa que lo copiaste completo, o déjalo vacío para ponerlo después.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function JsonStr(S: String): String;
begin
  StringChangeEx(S, '\', '\\', True);
  StringChangeEx(S, '"', '\"', True);
  Result := '"' + S + '"';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Lines: TArrayOfString;
  Cid: String;
begin
  if (CurStep = ssPostInstall) and not AlreadySetUp then
  begin
    ForceDirectories(SupportDir());
    ForceDirectories(Trim(FolderPage.Values[0]));
    ForceDirectories(Trim(FolderPage.Values[1]));
    Cid := Trim(CidEdit.Text);
    if not IsHex(Cid) then Cid := '';
    SetArrayLength(Lines, 1);
    Lines[0] := '{"dest_root": ' + JsonStr(Trim(FolderPage.Values[0])) + ', "inbox": ' + JsonStr(Trim(FolderPage.Values[1])) +
                ', "client_id": ' + JsonStr(Cid) + ', "from": "instalador"}';
    SaveStringsToUTF8File(SupportDir() + '\preconfig.json', Lines, False);
  end;
end;

@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Instalar SpotiSync
cd /d "%~dp0"
set "SRC=%~dp0"
if "%SRC:~-1%"=="\" set "SRC=%SRC:~0,-1%"
set "SUP=%APPDATA%\SpotiSync"

echo == SpotiSync: instalacion ==
echo.

rem --- Buscar Python 3.9 o superior ---
set "PY="
where py >nul 2>nul && (py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul && set "PY=py -3")
if not defined PY (
  where python >nul 2>nul && (python -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul && set "PY=python")
)
if not defined PY (
  echo No encontre Python 3.9 o superior.
  echo Instalalo desde https://www.python.org/downloads/  ^(marca "Add python.exe to PATH"^)
  echo o en una terminal:  winget install Python.Python.3.12
  echo y vuelve a abrir este instalador.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('%PY% --version') do echo Usando %%v

rem --- 1. Copiar el codigo a la carpeta de datos (la app ya no depende de esta carpeta) ---
if not exist "%SUP%" mkdir "%SUP%"
if exist "%SUP%\app.new" rmdir /s /q "%SUP%\app.new"
robocopy "%SRC%" "%SUP%\app.new" /E /XD .git __pycache__ /XF *.pyc .DS_Store /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (echo No pude copiar los archivos. & pause & exit /b 1)
if exist "%SUP%\app.prev" rmdir /s /q "%SUP%\app.prev"
if exist "%SUP%\app" move "%SUP%\app" "%SUP%\app.prev" >nul
move "%SUP%\app.new" "%SUP%\app" >nul
copy /y "%SUP%\app\arranque.py" "%SUP%\arranque.py" >nul
copy /y "%SUP%\app\windows\abrir.cmd" "%SUP%\abrir.cmd" >nul
copy /y "%SUP%\app\windows\abrir.vbs" "%SUP%\abrir.vbs" >nul
if exist "%SUP%\update" rmdir /s /q "%SUP%\update"
echo Codigo instalado en: %SUP%\app

rem --- 2. Entorno de Python (se rehace si esta roto) ---
"%SUP%\venv\Scripts\python.exe" -c "import sys" >nul 2>nul
if errorlevel 1 (
  if exist "%SUP%\venv" rmdir /s /q "%SUP%\venv"
  %PY% -m venv "%SUP%\venv" || (echo No pude crear el entorno de Python. & pause & exit /b 1)
)
"%SUP%\venv\Scripts\python.exe" -m pip install --upgrade pip -q
"%SUP%\venv\Scripts\python.exe" -m pip install --upgrade -q -r "%SUP%\app\requirements.txt"
if errorlevel 1 (
  echo.
  echo Fallo la instalacion de componentes. Revisa tu conexion e intentalo de nuevo.
  pause
  exit /b 1
)
echo Componentes listos.

rem --- 3. Accesos directos (Escritorio y Menu Inicio) ---
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$sup = Join-Path $env:APPDATA 'SpotiSync';" ^
  "$targets = @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'));" ^
  "foreach ($d in $targets) {" ^
  "  $l = $ws.CreateShortcut((Join-Path $d 'SpotiSync.lnk'));" ^
  "  $l.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe';" ^
  "  $l.Arguments = '\"' + (Join-Path $sup 'abrir.vbs') + '\"';" ^
  "  $l.WorkingDirectory = $sup;" ^
  "  $l.IconLocation = (Join-Path $sup 'app\icon.ico');" ^
  "  $l.Description = 'SpotiSync: Spotify, tu musica y Rekordbox';" ^
  "  $l.Save() }"

echo.
echo Listo. SpotiSync quedo en el Escritorio y en el Menu Inicio.
echo Se actualiza sola desde GitHub y, si Python cambia, se repara sola al abrirla.
echo Ya puedes borrar esta carpeta descargada si quieres.
echo Si Windows pregunta por permisos de red la primera vez (para conectar con Spotify), acepta "Redes privadas".
wscript "%SUP%\abrir.vbs"
pause

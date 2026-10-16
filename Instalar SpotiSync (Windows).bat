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

if not exist "%SUP%" mkdir "%SUP%"
if not exist "%SUP%\venv\Scripts\python.exe" (
  %PY% -m venv "%SUP%\venv" || (echo No pude crear el entorno de Python. & pause & exit /b 1)
)
"%SUP%\venv\Scripts\python.exe" -m pip install --upgrade pip -q
"%SUP%\venv\Scripts\python.exe" -m pip install --upgrade -q pywebview "pyrekordbox>=0.4" mutagen openpyxl
if errorlevel 1 (
  echo.
  echo Fallo la instalacion de componentes. Revisa tu conexion e intentalo de nuevo.
  pause
  exit /b 1
)
echo Dependencias listas.

rem --- Accesos directos (Escritorio y Menu Inicio) ---
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$targets = @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'));" ^
  "foreach ($d in $targets) {" ^
  "  $l = $ws.CreateShortcut((Join-Path $d 'SpotiSync.lnk'));" ^
  "  $l.TargetPath = Join-Path $env:APPDATA 'SpotiSync\venv\Scripts\pythonw.exe';" ^
  "  $l.Arguments = '\"' + '%SRC%\app.py' + '\"';" ^
  "  $l.WorkingDirectory = '%SRC%';" ^
  "  $l.IconLocation = '%SRC%\icon.ico';" ^
  "  $l.Description = 'SpotiSync: Spotify, tu musica y Rekordbox';" ^
  "  $l.Save() }"

echo.
echo Listo. SpotiSync quedo en el Escritorio y en el Menu Inicio.
echo Si Windows pregunta por permisos de red la primera vez (para conectar con Spotify), acepta "Redes privadas".
start "" "%SUP%\venv\Scripts\pythonw.exe" "%SRC%\app.py"
pause

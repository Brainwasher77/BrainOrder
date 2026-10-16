@echo off
rem Lanzador de SpotiSync: repara el entorno de Python si se dañó y abre la app.
setlocal
set "SUP=%APPDATA%\SpotiSync"
set "LOG=%SUP%\spotisync.log"
"%SUP%\venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul
if errorlevel 1 call :reparar
if not exist "%SUP%\venv\Scripts\pythonw.exe" exit /b 1
start "" "%SUP%\venv\Scripts\pythonw.exe" "%SUP%\arranque.py"
exit /b 0

:reparar
echo [%date% %time%] lanzador: entorno de Python roto o ausente; reparando>> "%LOG%"
if exist "%SUP%\venv" rmdir /s /q "%SUP%\venv"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv "%SUP%\venv" >> "%LOG%" 2>&1
  if exist "%SUP%\venv\Scripts\python.exe" goto :pip
)
python -m venv "%SUP%\venv" >> "%LOG%" 2>&1
if not exist "%SUP%\venv\Scripts\python.exe" (
  mshta "javascript:alert('SpotiSync: no encontre Python 3.9 o superior. Instalalo desde python.org y vuelve a abrir SpotiSync.');close();"
  exit /b 1
)
:pip
"%SUP%\venv\Scripts\python.exe" -m pip install -q --upgrade pip >> "%LOG%" 2>&1
echo [%date% %time%] lanzador: entorno recreado>> "%LOG%"
exit /b 0

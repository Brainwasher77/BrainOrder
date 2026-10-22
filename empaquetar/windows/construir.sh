#!/bin/bash
# Arma el instalador .exe de Windows (lo corre GitHub Actions en Windows, con Git Bash e Inno Setup).
source "$(cd "$(dirname "$0")/.." && pwd)/comun.sh"
WORK="$ROOT/dist/win"
rm -rf "$WORK"; mkdir -p "$WORK"
bajar_python x86_64-pc-windows-msvc "$WORK/python"
PY="$WORK/python/python.exe"
find "$WORK/python" -name EXTERNALLY-MANAGED -delete || true
"$PY" -m pip --version >/dev/null 2>&1 || "$PY" -m ensurepip
"$PY" -m pip install --disable-pip-version-check --no-warn-script-location -q --upgrade pip
"$PY" -m pip install --disable-pip-version-check --no-warn-script-location -q -r "$ROOT/requirements.txt"
"$PY" -c "import webview, pyrekordbox, sqlcipher3, mutagen, openpyxl, clr; print('componentes OK')"
rm -rf "$WORK/python/Lib/test" "$WORK/python/Lib/idlelib" "$WORK/python/Lib/tkinter" "$WORK/python/Lib/turtledemo" "$WORK/python/tcl"
find "$WORK/python" -name __pycache__ -type d -prune -exec rm -rf {} +
copiar_codigo "$WORK/app"
ISCC="${ISCC:-/c/Program Files (x86)/Inno Setup 6/ISCC.exe}"
# MSYS_NO_PATHCONV: que Git Bash no convierta «/DVER=…» en una ruta
MSYS_NO_PATHCONV=1 "$ISCC" "/DAPPVER=$VER" "/DBOSRC=$(cygpath -w "$WORK")" "/DBOOUT=$(cygpath -w "$ROOT/dist")" "$(cygpath -w "$ROOT/empaquetar/windows/BrainOrder.iss")"
echo "Listo: $ROOT/dist/BrainOrder-$VER-Windows.exe"

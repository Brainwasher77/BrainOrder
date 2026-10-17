#!/bin/bash
# Lanzador de BrainOrder.app: repara el entorno de Python si se dañó y abre la app.
BASE="$HOME/Library/Application Support"
SUP="$BASE/BrainOrder"
# instalaciones de cuando la app se llamaba SpotiSync
if [ ! -f "$SUP/arranque.py" ] && [ -f "$BASE/SpotiSync/arranque.py" ]; then SUP="$BASE/SpotiSync"; fi
PY="$SUP/venv/bin/python"
LOG="$SUP/brainorder.log"
export BRAINORDER_BUNDLE="$(cd "$(dirname "$0")/../.." && pwd)"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] lanzador: $*" >> "$LOG"; }
ok_py() { [ -x "$1" ] && "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; }

mkdir -p "$SUP"
if [ ! -f "$SUP/arranque.py" ]; then
  osascript -e 'display alert "BrainOrder" message "No encuentro la instalación. Vuelve a correr «Instalar BrainOrder.command»."'
  exit 1
fi

# Si Python se actualizó o se borró (p. ej. brew upgrade), el entorno queda roto: se rehace solo.
if ! ok_py "$PY"; then
  log "entorno de Python roto o ausente; reparando"
  osascript -e 'display notification "Reparando BrainOrder: Python cambió en tu Mac. La primera vez tarda un par de minutos." with title "BrainOrder"' >/dev/null 2>&1
  NEWPY=""
  for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
           "$HOME/.pyenv/shims/python3" /usr/bin/python3; do
    if ok_py "$p"; then NEWPY="$p"; break; fi
  done
  if [ -z "$NEWPY" ]; then
    log "no encontré Python 3.9+"
    osascript -e 'display alert "BrainOrder" message "No encontré Python 3.9 o superior en tu Mac. Instálalo (brew install python) y vuelve a abrir BrainOrder."'
    exit 1
  fi
  rm -rf "$SUP/venv"
  "$NEWPY" -m venv "$SUP/venv" >> "$LOG" 2>&1 || { log "no pude crear el entorno"; exit 1; }
  "$SUP/venv/bin/python" -m pip install -q --upgrade pip >> "$LOG" 2>&1
  log "entorno recreado con $NEWPY"
fi

# arranque.py instala actualizaciones pendientes y componentes que falten, y abre la ventana
exec "$PY" "$SUP/arranque.py" >> "$LOG" 2>&1

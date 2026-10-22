#!/bin/bash
# Lanzador de BrainOrder.app: repara el entorno de Python si se dañó y abre la app.
BASE="$HOME/Library/Application Support"
SUP="$BASE/BrainOrder"
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

# Python «desde dentro» de BrainOrder.app: así macOS muestra BrainOrder (no «Python») junto a la manzana,
# en el Dock y en ⌘-Tab. Se copia el intérprete de Python.app al bundle y se arranca como lo hace el propio
# Python (variable __PYVENV_LAUNCHER__ = Python del entorno). Si algo no funciona, se usa el Python normal.
bundle_python() {
  [ -d "$BRAINORDER_BUNDLE/Contents/MacOS" ] || return 1
  local real dst stamp sig
  real=$("$PY" -c 'import os,sys;b=os.path.realpath(getattr(sys,"_base_executable",sys.executable));d=os.path.dirname;p=os.path.join(d(d(b)),"Resources","Python.app","Contents","MacOS","Python");print(p if os.path.isfile(p) else "")' 2>/dev/null)
  [ -n "$real" ] || return 1
  dst="$BRAINORDER_BUNDLE/Contents/MacOS/BrainOrder-python"
  stamp="$SUP/.bundle-python"
  sig="$real|$(stat -f '%m %z' "$real" 2>/dev/null)|$PY"
  if [ -x "$dst" ] && [ "$(cat "$stamp" 2>/dev/null)" = "ok|$sig" ]; then echo "$dst"; return 0; fi
  [ "$(cat "$stamp" 2>/dev/null)" = "no|$sig" ] && return 1
  cp -p "$real" "$dst.tmp" 2>/dev/null && mv -f "$dst.tmp" "$dst" || { rm -f "$dst.tmp"; return 1; }
  if __PYVENV_LAUNCHER__="$PY" "$dst" -c 'import os,sys;sys.exit(0 if os.path.realpath(sys.prefix)==os.path.realpath(sys.argv[1]) else 3)' "$SUP/venv" >/dev/null 2>&1; then
    echo "ok|$sig" > "$stamp"; log "Python dentro de BrainOrder.app listo"; echo "$dst"; return 0
  fi
  rm -f "$dst"; echo "no|$sig" > "$stamp"; log "Python dentro de BrainOrder.app no funcionó; uso el normal"
  return 1
}

# arranque.py instala actualizaciones pendientes y componentes que falten, y abre la ventana
if BPY=$(bundle_python); then
  export __PYVENV_LAUNCHER__="$PY"
  exec "$BPY" "$SUP/arranque.py" >> "$LOG" 2>&1
fi
exec "$PY" "$SUP/arranque.py" >> "$LOG" 2>&1

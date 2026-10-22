#!/bin/bash
# Lanzador de BrainOrder.app (instalador .dmg): trae su propio Python y el código de la app.
# La primera vez (o si este programa trae una versión más nueva) el código se copia a la carpeta de datos
# y desde ahí corre, así las actualizaciones automáticas siguen funcionando igual que siempre.
CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
RES="$CONTENTS/Resources"
BASE="$HOME/Library/Application Support"
SUP="$BASE/BrainOrder"
mkdir -p "$SUP"
export BRAINORDER_BUNDLE="$(cd "$CONTENTS/.." && pwd)"
export BRAINORDER_PACKAGED=1
export PYTHONPYCACHEPREFIX="$SUP/pycache"   # nada se escribe dentro de BrainOrder.app
export PYTHONNOUSERSITE=1
unset PYTHONHOME PYTHONPATH
INNER="$CONTENTS/MacOS/BrainOrder-python"
if [ -x "$INNER" ] && PYTHONHOME="$RES/python" "$INNER" -c "import json" >/dev/null 2>&1; then
  export PYTHONHOME="$RES/python"
  exec "$INNER" "$RES/app/arranque.py" --seed >> "$SUP/brainorder.log" 2>&1
fi
exec "$RES/python/bin/python3" "$RES/app/arranque.py" --seed >> "$SUP/brainorder.log" 2>&1

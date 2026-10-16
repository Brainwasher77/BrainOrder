#!/bin/bash
# Instalador de SpotiSync para macOS.
# Copia la app a tu carpeta de datos, prepara Python y crea SpotiSync.app.
# Después de instalar puedes borrar la carpeta descargada: la app se actualiza sola.
set -e
cd "$(dirname "$0")"
SRC="$(pwd)"
SUP="$HOME/Library/Application Support/SpotiSync"

echo "== SpotiSync: instalación =="

ok_py() { [ -x "$1" ] && "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; }
PY=""
for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
         "$HOME/.pyenv/shims/python3" "$(command -v python3 || true)"; do
  if ok_py "$p"; then PY="$p"; break; fi
done
if [ -z "$PY" ]; then
  echo "No encontré Python 3.9 o superior. Instálalo con:  brew install python   y vuelve a abrir este instalador."
  read -n 1 -s -r -p "Presiona una tecla para cerrar…"; exit 1
fi
echo "Usando $PY ($("$PY" --version))"

# 1. Copiar el código a la carpeta de datos (la app ya no depende de esta carpeta)
mkdir -p "$SUP"
rm -rf "$SUP/app.new"
mkdir -p "$SUP/app.new"
( cd "$SRC" && tar --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' -cf - . ) | ( cd "$SUP/app.new" && tar -xf - )
rm -rf "$SUP/app.prev"
[ -d "$SUP/app" ] && mv "$SUP/app" "$SUP/app.prev"
mv "$SUP/app.new" "$SUP/app"
cp "$SUP/app/arranque.py" "$SUP/arranque.py"
rm -rf "$SUP/update"
echo "Código instalado en: $SUP/app"

# 2. Entorno de Python (se rehace si está roto)
if ! ok_py "$SUP/venv/bin/python"; then
  rm -rf "$SUP/venv"
  "$PY" -m venv "$SUP/venv"
fi
"$SUP/venv/bin/python" -m pip install --upgrade pip -q
"$SUP/venv/bin/python" -m pip install --upgrade -q -r "$SUP/app/requirements.txt"
echo "Componentes listos."

# 3. SpotiSync.app (en /Applications si se puede, si no en ~/Applications)
if [ -w /Applications ]; then DEST="/Applications"; else DEST="$HOME/Applications"; mkdir -p "$DEST"; fi
APP="$DEST/SpotiSync.app"
for old in "$HOME/Applications/SpotiSync.app" "/Applications/SpotiSync.app"; do
  [ -d "$old" ] && [ "$old" != "$APP" ] && rm -rf "$old" && echo "Quité la versión anterior de $old"
done
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
VER=$("$SUP/venv/bin/python" -c "import json;print(json.load(open('$SUP/app/version.json'))['version'])" 2>/dev/null || echo 1.0)
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>SpotiSync</string>
  <key>CFBundleDisplayName</key><string>SpotiSync</string>
  <key>CFBundleIdentifier</key><string>com.brainwasher.spotisync</string>
  <key>CFBundleVersion</key><string>$VER</string>
  <key>CFBundleShortVersionString</key><string>$VER</string>
  <key>CFBundleExecutable</key><string>SpotiSync</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
cp "$SUP/app/mac/lanzador.sh" "$APP/Contents/MacOS/SpotiSync"
chmod +x "$APP/Contents/MacOS/SpotiSync"
if [ -f "$SUP/app/icon.png" ]; then
  IS="$(mktemp -d)/icon.iconset"; mkdir -p "$IS"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$SUP/app/icon.png" --out "$IS/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$SUP/app/icon.png" --out "$IS/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$IS" -o "$APP/Contents/Resources/icon.icns" || true
fi
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
touch "$APP"

echo ""
echo "✅ Listo. SpotiSync $VER quedó en $DEST (búscalo con Spotlight: ⌘ + espacio → SpotiSync)."
echo "   Se actualiza sola desde GitHub y, si Python cambia en tu Mac, se repara sola al abrirla."
echo "   Ya puedes borrar esta carpeta descargada si quieres."
open "$APP"
read -n 1 -s -r -p "Presiona una tecla para cerrar esta ventana…"

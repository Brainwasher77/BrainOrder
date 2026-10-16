#!/bin/bash
# Instalador de SpotiSync: crea un entorno Python propio y la app en ~/Applications.
set -e
cd "$(dirname "$0")"
SRC="$(pwd)"
SUP="$HOME/Library/Application Support/SpotiSync"
APP="$HOME/Applications/SpotiSync.app"

echo "== SpotiSync: instalación =="

PY=""
for p in /opt/homebrew/bin/python3 "$HOME/.homebrew/bin/python3" /usr/local/bin/python3 "$(command -v python3 || true)"; do
  if [ -n "$p" ] && [ -x "$p" ] && "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
    PY="$p"; break
  fi
done
if [ -z "$PY" ]; then
  echo "No encontré Python 3.9 o superior. Instálalo con:  brew install python   y vuelve a abrir este instalador."
  read -n 1 -s -r -p "Presiona una tecla para cerrar…"; exit 1
fi
echo "Usando $PY ($("$PY" --version))"

mkdir -p "$SUP"
if [ ! -x "$SUP/venv/bin/python" ]; then
  "$PY" -m venv "$SUP/venv"
fi
"$SUP/venv/bin/python" -m pip install --upgrade pip -q
"$SUP/venv/bin/python" -m pip install --upgrade -q pywebview "pyrekordbox>=0.4" mutagen openpyxl
echo "Dependencias listas."

# Construir el .app
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>SpotiSync</string>
  <key>CFBundleDisplayName</key><string>SpotiSync</string>
  <key>CFBundleIdentifier</key><string>com.brainwasher.spotisync</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleExecutable</key><string>SpotiSync</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
cat > "$APP/Contents/MacOS/SpotiSync" <<LAUNCH
#!/bin/bash
exec "$SUP/venv/bin/python" "$SRC/app.py" >> "$SUP/spotisync.log" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/SpotiSync"
if [ -f "$SRC/icon.png" ]; then
  IS="$(mktemp -d)/icon.iconset"; mkdir -p "$IS"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$SRC/icon.png" --out "$IS/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$SRC/icon.png" --out "$IS/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$IS" -o "$APP/Contents/Resources/icon.icns" || true
fi
touch "$APP"

echo ""
echo "✅ Listo. SpotiSync quedó en ~/Applications (búscalo con Spotlight: ⌘ + espacio → SpotiSync)."
echo "   Si macOS pide permiso para acceder a Música o a otras carpetas, acéptalo."
open "$APP"
read -n 1 -s -r -p "Presiona una tecla para cerrar esta ventana…"

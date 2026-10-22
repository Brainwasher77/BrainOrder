#!/bin/bash
# Arma BrainOrder.app (con su propio Python y todo lo que necesita) y el .dmg para instalarla.
# Uso: empaquetar/mac/construir_dmg.sh   (en un Mac; lo corre GitHub Actions)
source "$(cd "$(dirname "$0")/.." && pwd)/comun.sh"
export PYTHONDONTWRITEBYTECODE=1   # nada de cachés dentro de la app (rompería la firma)
case "$(uname -m)" in
  arm64) TRIPLE=aarch64-apple-darwin; LABEL=AppleSilicon ;;
  x86_64) TRIPLE=x86_64-apple-darwin; LABEL=Intel ;;
  *) echo "arquitectura desconocida"; exit 1 ;;
esac
WORK="$ROOT/dist/mac-$LABEL"
APP="$WORK/BrainOrder.app"
rm -rf "$WORK"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

bajar_python "$TRIPLE" "$APP/Contents/Resources/python"
PY="$APP/Contents/Resources/python/bin/python3"
find "$APP/Contents/Resources/python/lib" -name EXTERNALLY-MANAGED -delete || true
"$PY" -m pip --version >/dev/null 2>&1 || "$PY" -m ensurepip
"$PY" -m pip install --disable-pip-version-check --no-warn-script-location -q --upgrade pip
"$PY" -m pip install --disable-pip-version-check --no-warn-script-location -q -r "$ROOT/requirements.txt"
"$PY" -c "import webview, pyrekordbox, mutagen, openpyxl, objc, WebKit; print('componentes OK')"
# lo que no se usa (pruebas de Python, IDLE, tkinter) fuera: el instalador pesa menos
PYLIB=$(echo "$APP"/Contents/Resources/python/lib/python3.*)
rm -rf "$PYLIB/test" "$PYLIB/idlelib" "$PYLIB/tkinter" "$PYLIB/turtledemo" "$PYLIB/lib2to3/tests"
# la app guarda su caché de Python en la carpeta de datos (PYTHONPYCACHEPREFIX): estas no se usan
find "$APP/Contents/Resources/python" -name __pycache__ -type d -prune -exec rm -rf {} +

copiar_codigo "$APP/Contents/Resources/app"
cp "$ROOT/empaquetar/mac/lanzador.sh" "$APP/Contents/MacOS/BrainOrder"
chmod +x "$APP/Contents/MacOS/BrainOrder"
# Python «desde dentro» de BrainOrder.app: así el Dock, ⌘-Tab y la barra de menú dicen BrainOrder (no «Python»)
cp "$(cd "$(dirname "$PY")" && pwd -P)/$(readlink "$PY" || basename "$PY")" "$APP/Contents/MacOS/BrainOrder-python"
INNER="$APP/Contents/MacOS/BrainOrder-python"
LIBREF=$(otool -L "$INNER" | awk '/libpython/{print $1}' | head -1)
if [ -n "$LIBREF" ]; then
  install_name_tool -change "$LIBREF" "@executable_path/../Resources/python/lib/$(basename "$LIBREF")" "$INNER"
fi
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>BrainOrder</string>
  <key>CFBundleDisplayName</key><string>BrainOrder</string>
  <key>CFBundleIdentifier</key><string>com.brainwasher.brainorder</string>
  <key>CFBundleVersion</key><string>$VER</string>
  <key>CFBundleShortVersionString</key><string>$VER</string>
  <key>CFBundleExecutable</key><string>BrainOrder</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
IS="$WORK/icon.iconset"; mkdir -p "$IS"
for s in 16 32 128 256 512; do
  sips -z $s $s "$ROOT/icon.png" --out "$IS/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$ROOT/icon.png" --out "$IS/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$IS" -o "$APP/Contents/Resources/icon.icns"

# firma «ad hoc» (sin cuenta de Apple): en Mac con chip Apple todo binario tiene que estar firmado
find "$APP/Contents/Resources/python" -type f \( -name "*.so" -o -name "*.dylib" -o -perm -u+x \) -print0 \
  | while IFS= read -r -d '' f; do file -b "$f" | grep -q "Mach-O" && codesign --force --sign - "$f" 2>/dev/null || true; done
[ -f "$INNER" ] && codesign --force --sign - "$INNER"
codesign --force --sign - "$APP"
codesign --verify --verbose=1 "$APP" || true

# prueba: el Python del programa arranca y encuentra los componentes (los dos, el normal y el de dentro)
"$PY" -c "import webview, pyrekordbox, sqlcipher3; print('arranque OK')"
if ! PYTHONHOME="$APP/Contents/Resources/python" "$INNER" -c "import sys, webview, pyrekordbox, sqlcipher3; print('arranque desde dentro OK', sys.prefix)"; then
  echo "El Python de dentro no arrancó: la app usará el normal"
  rm -f "$INNER"; codesign --force --sign - "$APP"
fi

STAGE="$WORK/dmg"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Aplicaciones"
cat > "$STAGE/Si macOS no la abre.txt" <<'TXT'
BrainOrder no está firmada con una cuenta de desarrollador de Apple, así que la primera vez macOS la frena.

1. Arrastra BrainOrder a la carpeta Aplicaciones.
2. Ábrela con doble clic. Si dice que no se puede verificar: toca «Listo».
3. Ve a Configuración del Sistema → Privacidad y seguridad, baja hasta «BrainOrder se bloqueó…»
   y toca «Abrir igualmente». Confirma con tu contraseña o Touch ID.
   (En macOS 14 o anterior también sirve: clic derecho sobre BrainOrder → Abrir → Abrir.)

Eso es solo la primera vez. Después se abre normal y se actualiza sola.
Al abrirla te guía en la instalación: tus carpetas, tus programas de DJ y la conexión con Spotify.
TXT
mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/BrainOrder-$VER-Mac-$LABEL.dmg"
rm -f "$OUT"
# hdiutil a veces falla con «Resource busy» en los Mac de GitHub: se reintenta
for i in 1 2 3 4 5 6; do
  if hdiutil create -volname "BrainOrder $VER" -srcfolder "$STAGE" -ov -format UDZO "$OUT"; then break; fi
  [ "$i" = 6 ] && { echo "hdiutil no pudo crear el .dmg"; exit 1; }
  echo "hdiutil ocupado, reintento $i…"; sleep $((i * 10))
done
echo "Listo: $OUT"

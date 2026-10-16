# SpotiSync

App de escritorio para **macOS y Windows** que mantiene sincronizadas tus playlists de Spotify con tu música descargada y con Rekordbox.

- Compara tus playlists de Spotify (y tus Me gusta) con los archivos de tu computador y te dice qué te falta y a qué carpeta va.
- **Organizar** mueve las descargas a la carpeta de su playlist, sin duplicar archivos, y replica las playlists en Rekordbox con el mismo orden de Spotify.
- **Unificar repetidos** limpia la carpeta: junta carpetas repetidas, aparta canciones repetidas en `_duplicados` y corrige las rutas en Rekordbox.
- Links de **Spotify y Deezer** para cada canción que falta. Botones para copiarlos todos de una, por playlist.
- Informes en **Excel** por playlist o de todo lo que falta, `.txt` de faltantes dentro de cada carpeta y estadísticas.

---

## Instalación

Necesitas **Python 3.9 o superior**.

### macOS
1. Si no tienes Python: `brew install python` (o descárgalo de python.org).
2. Doble clic en **`Instalar SpotiSync.command`**. Si macOS lo bloquea: clic derecho → Abrir.
3. Queda **SpotiSync** en Aplicaciones. Ábrelo con Spotlight (⌘ + espacio) y, si quieres, déjalo fijo en el Dock.

### Windows 10 / 11
1. Si no tienes Python: instálalo desde [python.org](https://www.python.org/downloads/) marcando **"Add python.exe to PATH"**, o en una terminal: `winget install Python.Python.3.12`.
2. Doble clic en **`Instalar SpotiSync (Windows).bat`**. Si aparece "Windows protegió tu PC": Más información → Ejecutar de todas formas.
3. Queda un acceso directo **SpotiSync** en el Escritorio y en el Menú Inicio.

El instalador copia la app a tu carpeta de datos y crea un entorno de Python propio (no toca tu Python del sistema). **Después de instalar puedes borrar la carpeta descargada.**

## Actualizaciones automáticas
- Cada vez que abres SpotiSync revisa si hay una versión nueva en este repositorio (`version.json`). Si la hay, la descarga en segundo plano y te ofrece **Reiniciar ahora**; si dices "Después", se instala sola la próxima vez que la abras.
- Si Python cambia en tu computador (por ejemplo después de `brew upgrade`), el lanzador rehace el entorno solo al abrir la app. La primera vez después de eso tarda un par de minutos.
- Solo hace falta volver a correr el instalador si cambias de computador.

Para publicar una versión nueva: sube los cambios a `main` y aumenta `build` en `version.json`.

## Conectar Spotify (una vez)
1. Entra a <https://developer.spotify.com/dashboard> con tu cuenta (Spotify exige que el dueño de la app sea **Premium**).
2. **Create app** → API: **Web API** → Redirect URI: `http://127.0.0.1:8888/callback` (exacto).
3. Copia el **Client ID** (no hace falta el Client Secret) y pégalo en SpotiSync → **Ajustes**.
4. **Conectar Spotify** y autoriza en el navegador.

## Uso
| Botón | Qué hace |
|---|---|
| **⟳ (Tus playlists)** | Trae solo la lista de tus playlists, sin canciones (rápido). Las que cambiaron en Spotify desde que las analizaste se marcan con ●. |
| **🔄 Analizar** (en cada playlist) | Lee de Spotify solo esa playlist y la cruza con tus archivos. |
| **Analizar todo** | Lee todas tus playlists de una vez. Verde = la tienes, naranja = está en descargas, rojo = falta. |
| **Organizar** (general o en cada playlist) | Muestra cuántos archivos hay en descargas y se ilumina en cuanto llega uno. Lo que no coincide con ninguna playlist analizada lo puedes mover por subcarpeta (como carpeta de playlist) o a la carpeta que elijas. Mueve las descargas a su carpeta (una sola copia por canción), aparta las repetidas en `_duplicados` y actualiza Rekordbox. **Rekordbox debe estar cerrado.** |
| **📂 Reorganizar** (en cada playlist) | Muestra las canciones que ya tienes en otras carpetas, agrupadas por carpeta, y eliges para cada una: dejarla donde está, moverla a su carpeta o a la de esta playlist. Lo que dejas queda recordado. Si el archivo está en Rekordbox, se corrige su ruta (con respaldo). |
| **📋 Spotify / 📋 Deezer** | Copia al portapapeles los links de lo que falta (en cada playlist o en "Faltan por descargar"), uno por línea. |
| **📊 Informe Excel** | Informe de una playlist: estado de cada canción, dónde está y links. |
| **Exportar a Excel** | Todas las canciones que faltan, con links de Spotify y Deezer. |
| **Unificar repetidos** | Revisa (sin mover nada) y luego unifica carpetas y canciones repetidas. |

Carpetas por defecto (se cambian en Ajustes con el selector de carpetas):
- Música por playlist: `Música/Spotify playlists/<playlist>`
- Descargas por organizar: `Música/descargas para organizar`

## Seguridad de tus archivos
- Nunca se borra música: lo repetido se aparta en carpetas `_duplicados` para que lo revises tú.
- Antes de escribir en Rekordbox se respalda `master.db` (se guardan los últimos 5 respaldos `master.backup.spotisync-…db`).
- Si Unificar falla a mitad de camino, se deshacen los movimientos.

Para restaurar Rekordbox: ciérralo y reemplaza `master.db` por uno de los respaldos.
- macOS: `~/Library/Pioneer/rekordbox/`
- Windows: `%APPDATA%\Pioneer\rekordbox\`

## Dónde guarda sus datos
Ajustes, sesión de Spotify, cachés y el log (`spotisync.log`):
- macOS: `~/Library/Application Support/SpotiSync/`
- Windows: `%APPDATA%\SpotiSync\`

Tu Client ID y tu sesión de Spotify viven solo ahí, nunca en el repositorio.

## Limitaciones
- Spotify no deja que apps personales lean canciones de playlists de otras personas. SpotiSync te pregunta si quieres integrarlas; para hacerlo, cópialas en Spotify a una playlist tuya (Seleccionar todo → Añadir a playlist → Nueva playlist).
- Las pistas nuevas entran a Rekordbox sin analizar: al abrirlo, selecciónalas y analízalas (BPM, waveform).

## Estructura
| Archivo | Para qué |
|---|---|
| `arranque.py` | Instala actualizaciones pendientes y componentes que falten, y abre la app |
| `actualizador.py` | Revisa y descarga versiones nuevas desde GitHub |
| `mac/lanzador.sh`, `windows/abrir.*` | Lanzadores que reparan el entorno de Python si se daña |
| `app.py` | Ventana (pywebview) y puente con la interfaz |
| `ui.html` | Interfaz |
| `spotify_api.py` | Login PKCE y lectura de playlists |
| `biblioteca.py` | Escaneo de archivos y cruce con Spotify (título, versión y duración) |
| `organizador.py` | Mover descargas a su carpeta |
| `rekordbox_sync.py` | Playlists de Rekordbox |
| `unificar.py` | Carpetas y canciones repetidas |
| `deezer.py` | Links de Deezer (ISRC o búsqueda) |
| `reportes.py`, `excel.py` | `.txt` por carpeta e informes Excel |
| `plataforma.py` | Diferencias entre macOS y Windows |

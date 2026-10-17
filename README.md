# BrainOrder

App de escritorio para **macOS y Windows** que mantiene sincronizadas tus playlists (Spotify, Deezer, Apple Music, SoundCloud, Tidal…) con tu música descargada y con tus programas de DJ (Rekordbox, Traktor, Serato, Engine DJ y cualquiera que lea M3U).

- Compara tus playlists de Spotify (y tus Me gusta) con los archivos de tu computador y te dice qué te falta y a qué carpeta va.
- **Organizar** mueve las descargas a la carpeta de su playlist, sin duplicar archivos, y replica las playlists en Rekordbox con el mismo orden de Spotify.
- **Unificar repetidos** limpia la carpeta: junta carpetas repetidas, aparta canciones repetidas en `_duplicados` y corrige las rutas en Rekordbox.
- Links de **Spotify y Deezer** para cada canción que falta. Botones para copiarlos todos de una, por playlist.
- Informes en **Excel** por playlist o de todo lo que falta, `.txt` de faltantes dentro de cada carpeta y estadísticas.

---

> **Antes se llamaba SpotiSync.** Si ya la tenías instalada no tienes que hacer nada: se actualiza sola, se renombra a BrainOrder y conserva tu configuración e historial.

## Instalación

Necesitas **Python 3.9 o superior**.

### macOS
1. Si no tienes Python: `brew install python` (o descárgalo de python.org).
2. Doble clic en **`Instalar BrainOrder.command`**. Si macOS lo bloquea: clic derecho → Abrir.
3. Queda **BrainOrder** en Aplicaciones. Ábrelo con Spotlight (⌘ + espacio) y, si quieres, déjalo fijo en el Dock.

### Windows 10 / 11
1. Si no tienes Python: instálalo desde [python.org](https://www.python.org/downloads/) marcando **"Add python.exe to PATH"**, o en una terminal: `winget install Python.Python.3.12`.
2. Doble clic en **`Instalar BrainOrder (Windows).bat`**. Si aparece "Windows protegió tu PC": Más información → Ejecutar de todas formas.
3. Queda un acceso directo **BrainOrder** en el Escritorio y en el Menú Inicio.

El instalador copia la app a tu carpeta de datos y crea un entorno de Python propio (no toca tu Python del sistema). **Después de instalar puedes borrar la carpeta descargada.**

## Actualizaciones automáticas
- Cada vez que abres BrainOrder revisa si hay una versión nueva en este repositorio (`version.json`). Si la hay, la descarga en segundo plano y te ofrece **Reiniciar ahora**; si dices "Después", se instala sola la próxima vez que la abras.
- Si Python cambia en tu computador (por ejemplo después de `brew upgrade`), el lanzador rehace el entorno solo al abrir la app. La primera vez después de eso tarda un par de minutos.
- Solo hace falta volver a correr el instalador si cambias de computador.

Para publicar una versión nueva: sube los cambios a `main` y aumenta `build` en `version.json`.

## Conectar Spotify (una vez)
1. Entra a <https://developer.spotify.com/dashboard> con tu cuenta (Spotify exige que el dueño de la app sea **Premium**).
2. **Create app** → API: **Web API** → Redirect URI: `http://127.0.0.1:8888/callback` (exacto).
3. Copia el **Client ID** (no hace falta el Client Secret) y pégalo en BrainOrder → **Ajustes**.
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

## Conexiones: fuentes y programas de DJ
En la barra lateral, **Conexiones**:
- **Fuentes de playlists** (se pueden usar varias a la vez; la misma canción en dos fuentes se une por ISRC):
  - **Spotify**: tus playlists y Me gusta (Client ID de tu app de desarrollador).
  - **Deezer**: playlists públicas de tu perfil y links sueltos, sin login.
  - **Archivos exportados**: una carpeta donde cada `.m3u`, `.csv` o `.txt` es una playlist. Sirve para Apple Music (Archivo → Biblioteca → Exportar playlist), SoundCloud, Tidal o YouTube Music (exporta con TuneMyMusic o Soundiiz) y Exportify.
- **Programas de DJ** (se actualizan al Organizar; cada uno con respaldo y cerrado):
  - **Rekordbox** (master.db), **Traktor Pro** (collection.nml), **Serato DJ** (crates en `_Serato_/Subcrates`) y **Engine DJ** (`Engine Library/Database2/m.db`). Al Reorganizar o Unificar también se corrigen sus rutas.
  - **Playlists M3U** para VirtualDJ, djay, Mixxx o cualquier otro.

## Primer uso
La primera vez se abre un **asistente** de 4 pasos: programas de DJ (detecta los instalados), de dónde vienen tus playlists, tus carpetas (sugiere las que tienen música) y listo. Se puede volver a abrir desde **Ajustes → Asistente de configuración**.

## Historial y Deshacer
Todo lo que BrainOrder mueve (Organizar, Reorganizar, Unificar) queda en **Historial**. **Deshacer** devuelve cada archivo a donde estaba y corrige las rutas en Rekordbox, Traktor, Serato y Engine DJ (con respaldo). Nunca pisa un archivo: si algo cambió desde entonces, ese archivo se salta y te lo dice.

## Key y energía (Mixed In Key)
Cada playlist muestra **Key** (Camelot), **Energía** (1–10) y **BPM** de tus archivos, leídos de las etiquetas que deja **Mixed In Key 10 u 11** (los datos de **Mixed In Key siempre tienen prioridad**; solo si una canción no tiene nada de MIK se usa la key de otros programas —«Am», «C#m», Open Key «1m»…—, marcada con *). Se ordena por cualquiera de esas columnas, el filtro **Sin Mixed In Key** muestra lo que falta analizar y escribir **8A** en el buscador deja solo esa key. BrainOrder solo lee: nunca cambia las etiquetas.

## Reglas (a tu gusto)
En la barra lateral, **Reglas**:
- **Exclusiones**: carpetas y patrones (`Samples`, `*stem*`, `*.wav`, `*/Sets grabados/*`) que BrainOrder nunca lee, mueve ni cuenta. También puedes ignorar audios muy cortos (one-shots). El botón **Probar** muestra qué quedaría fuera antes de guardar.
- **Prioridad de playlists**: si una canción está en varias playlists, su archivo vive en la carpeta de la primera de la lista. Arrastra para ordenar. Cada playlist puede **Organizar** o **Ignorar**.
- **Comparación**: tolerancia de duración para decidir si es la misma grabación, y qué formato se queda cuando hay repetidos.

## Seguridad de tus archivos
- Nunca se borra música: lo repetido se aparta en carpetas `_duplicados` para que lo revises tú.
- Antes de escribir en Rekordbox se respalda `master.db` (se guardan los últimos 5 respaldos `master.backup.spotisync-…db`).
- Si Unificar falla a mitad de camino, se deshacen los movimientos.

Para restaurar Rekordbox: ciérralo y reemplaza `master.db` por uno de los respaldos.
- macOS: `~/Library/Pioneer/rekordbox/`
- Windows: `%APPDATA%\Pioneer\rekordbox\`

## Dónde guarda sus datos
Ajustes, sesión de Spotify, cachés y el log (`spotisync.log`):
- macOS: `~/Library/Application Support/BrainOrder/`
- Windows: `%APPDATA%\BrainOrder\`

Tu Client ID y tu sesión de Spotify viven solo ahí, nunca en el repositorio.

## Limitaciones
- Spotify no deja que apps personales lean canciones de playlists de otras personas. BrainOrder te pregunta si quieres integrarlas; para hacerlo, cópialas en Spotify a una playlist tuya (Seleccionar todo → Añadir a playlist → Nueva playlist).
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

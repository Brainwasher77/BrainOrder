# BrainOrder

App de escritorio para **macOS y Windows** que mantiene sincronizadas tus playlists (Spotify, Deezer, Apple Music, SoundCloud, Tidal…) con tu música descargada y con tus programas de DJ (Rekordbox, Traktor, Serato, Engine DJ y cualquiera que lea M3U).

- Compara tus playlists de Spotify (y tus Me gusta) con los archivos de tu computador y te dice qué te falta y a qué carpeta va.
- **Organizar** mueve las descargas a la carpeta de su playlist, sin duplicar archivos, y replica las playlists en Rekordbox con el mismo orden de Spotify.
- **Unificar repetidos** limpia la carpeta: junta carpetas repetidas, aparta canciones repetidas en `_duplicados` y corrige las rutas en Rekordbox.
- Links de **Spotify y Deezer** para cada canción que falta. Botones para copiarlos todos de una, por playlist.
- Informes en **Excel** por playlist o de todo lo que falta, `.txt` de faltantes dentro de cada carpeta y estadísticas.

📘 **[Manual de usuario y novedades por versión](docs/BrainOrder%20-%20Manual%20de%20usuario.docx)** (Word): todas las funciones explicadas paso a paso.

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
- Si una versión nueva no llegara a arrancar, BrainOrder vuelve sola a la anterior y no reintenta esa versión.
- Si una versión nueva necesita componentes nuevos, se instalan solos al abrirla.
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
| **📂 Reorganizar** (en cada playlist) | Muestra las canciones que ya tienes en otras carpetas, agrupadas por carpeta, y eliges para cada una: dejarla donde está, moverla a su carpeta o a la de esta playlist. Te las propone siempre (recordar lo que dejas es opcional). Si el archivo está en Rekordbox, se corrige su ruta (con respaldo). |
| **📋 Spotify / 📋 Deezer** | Copia al portapapeles los links de lo que falta (en cada playlist o en "Faltan por descargar"), uno por línea. |
| **📊 Informe Excel** | Informe de una playlist: estado de cada canción, dónde está y links. |
| **Exportar a Excel** | Todas las canciones que faltan, con links de Spotify y Deezer. |
| **Unificar repetidos** | Revisa (sin mover nada) y luego unifica carpetas y canciones repetidas. |

Carpetas por defecto en instalaciones nuevas (se cambian en el asistente o en Ajustes):
- Música por playlist: `Música/Playlists BrainOrder/<playlist>`
- Descargas por organizar: `Música/Descargas BrainOrder`

## Descargas en otra versión
Una descarga se reconoce solo si es la misma grabación que la de la playlist. Los links de Deezer buscan esa misma versión (título y duración); si Deezer no la tiene, el link dice «Deezer (otra versión)». Si bajas otra versión (remix, Dream Version, corte largo…), al organizar aparece en «Parecen de tus playlists» con ▶ y **Usar esta versión** para que cuente como esa canción.

## Vista previa
Cada canción tiene **▶** (playlists, faltantes, Comparar y clic derecho → Escuchar). Si tienes el archivo suena tu archivo (desde el 25 %, sin la intro); si te falta, 30 s de Deezer. Reproductor abajo con pausa (barra espaciadora), adelantar, −15/+15 s y ½ (ir a la mitad). Tus archivos se sirven solo dentro del computador (127.0.0.1, con clave de sesión) y solo los de tus carpetas de música.

## Ordenar playlists, clic derecho y Reorganizar
- Debajo de «Tus playlists» eliges el orden: de Spotify, más o menos faltantes primero, completas o menos completas primero, con descargas por organizar, por nombre o por cantidad de canciones. Se recuerda.
- **Clic derecho en una canción**: moverla a su carpeta, a la de esta playlist, a la de otra playlist que también la tenga o a cualquier carpeta de tu biblioteca; fijarla donde está; mostrarla en Finder; abrirla en Spotify/Deezer o copiar su nombre. Cada movimiento corrige Rekordbox y demás programas y se puede deshacer en Historial.
- **Reorganizar** te propone las canciones siempre. Solo si marcas «No volver a proponer las que dejo» se dejan de mostrar las que dejas donde están (esa elección se recuerda, y las fijadas se pueden soltar cuando quieras).

**Clic derecho en una playlist** (lista de la izquierda): **⚖️ Comparar con…** (canciones en común, solo en cada una, % de parecido, artistas compartidos, fechas, BPM/keys; las playlists para elegir se ordenan por nombre, fecha de creación, canciones agregadas hace poco, cantidad o más en común; con pestañas, buscador, Copiar y atajo para fusionar; no cambia nada), **Renombrar**, **Fusionar con otra** o **Eliminar**, en todas partes: BrainOrder, su carpeta, Spotify, Rekordbox, Traktor, Serato, Engine DJ y M3U (los programas deben estar cerrados; se respaldan antes). Renombrar pasa sus archivos a la carpeta con el nombre nuevo. Fusionar agrega las canciones que falten a la otra playlist (también en Spotify), pasa sus archivos a esa carpeta (las repetidas a `_duplicados`) y elimina la primera. Eliminar la quita en todas partes y ordena sus archivos (los que están en otras playlists van a la carpeta de esas; el resto a `_Playlists eliminadas/<nombre>`) o los deja donde están: la música nunca se borra y todo se puede deshacer en Historial. La carpeta vieja no queda rezagada: lo que choca por nombre va a `_duplicados` y la basura del sistema se limpia; si algo no se puede mover, te avisa y esa carpeta no se toma como «playlist nueva». Si Spotify está en pausa, allá queda en la cola. Deezer y los archivos exportados no dejan cambiarse desde una app: el cambio queda en BrainOrder y tus programas.

## Playlists nuevas (carpetas y programas de DJ)
BrainOrder te pregunta si quieres importar como playlist:
- **Una carpeta nueva** que creas en tu carpeta de playlists o en cualquiera de tus carpetas de música (Ajustes), aunque esté vacía. Espera a que termines de copiar.
- **Una playlist nueva** que creas en Rekordbox, Engine DJ o Serato (al momento) o en Traktor (cuando lo cierras, que es cuando Traktor guarda), en cuanto tiene canciones.

Al importar eliges la plataforma:
- **Spotify**: crea la playlist buscando cada canción (por ISRC o artista + título) y te dice cuáles no encontró.
- **Deezer, Apple Music, Tidal, SoundCloud u otra**: esas plataformas no dejan que una app personal cree playlists; BrainOrder deja un `… (para importar).csv` en `_Informes` para subirlo en TuneMyMusic o Soundiiz.
- **Ninguna**: solo en BrainOrder. Una carpeta importada así se llena sola con lo que pongas en ella; una playlist de un programa de DJ se relee de ese programa.

**Borrar un archivo repetido no vacía la playlist**: si borras o mueves un archivo de una carpeta-playlist porque esa canción ya está en otra, la canción sigue en la playlist usando la otra copia (como en Rekordbox); Spotify nunca se toca por borrar archivos. Solo sale si borras la única copia, o con clic derecho → *Quitar de esta playlist*.

También te pregunta si **pasa sus archivos a tu carpeta de playlists** (`<carpeta de playlists>/<nombre>`): se mueven con rutas corregidas en Rekordbox y tus otros programas, queda en Historial para deshacer y, si era una carpeta, la vieja se elimina si queda vacía. Lo importado sale de «Playlists nuevas» y la carpeta que crea BrainOrder al mover no se toma como nueva. **En Spotify nunca se duplica**: si ya tienes una playlist con ese nombre se usa esa (solo se agregan las canciones que falten), y si después agregas canciones a una carpeta importada a Spotify, te pregunta si las agrega a esa misma playlist. Opcionalmente la pasa enseguida a tus otros programas de DJ. Una playlist que nació en un programa no se vuelve a copiar a ese mismo programa. «Ahora no» vuelve a preguntar la próxima vez que abras BrainOrder; «No preguntar por esta» no. Lo que ya existía cuando instalaste esta función no genera preguntas, pero aparece en **Playlists nuevas** para importarlo cuando quieras.

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

## Mixed In Key → tus programas de DJ (automático)
Lo que analizó Mixed In Key pasa a **Rekordbox, Traktor, Serato y Engine DJ** (los que tengas activos en Conexiones):
- **Key** en la columna Key de cada programa (MIK siempre gana sobre la que tuviera).
- **Energía** en el comentario («8A - Energy 6»), solo si el comentario está vacío o ya era de MIK.
- **Hot cues de MIK** (A, B, C… con su energía), **solo en canciones que todavía no tienen hot cues** en ese programa: los tuyos nunca se pisan. En Rekordbox también FLAC (se calcula la posición como lo hace Rekordbox); las MP3 VBR se saltan. En Engine DJ, cuando la pista ya está analizada. **Serato** lee los cues del propio archivo: los ve si MIK tiene activada su opción de escribir cue points para Serato (BrainOrder avisa cuántas canciones no los tienen).
Pasa al **Organizar** y **cada 5 minutos** en cada programa que esté cerrado (con respaldo de su librería). En Conexiones → Mixed In Key hay **Ver qué falta** y **Actualizar ahora**. No toca BPM, grid ni memory cues.

## Nombre de la carpeta de BrainOrder en tus programas
Se cambia en Conexiones. Al cambiarlo, BrainOrder **renombra la carpeta** en Rekordbox, Traktor, Serato, Engine DJ y M3U: son las mismas playlists, no se duplican, no aparecen en «Playlists nuevas» ni como borradas en «Cambios en Rekordbox». Un programa abierto se renombra al cerrarlo (Organizar no le crea otra carpeta mientras tanto). Si la renombras dentro de Rekordbox, BrainOrder usa ese nombre y lo pasa a los demás; si la cambiaste en una versión anterior, encuentra la carpeta vieja por sus playlists y la arregla.

## Cancelar
Lo que está **en cola** (esperando a que termine otra tarea) se cancela con su ✕ en la barra de tareas o con clic derecho. Una tarea que ya empezó no se corta a mitad, para no dejar archivos ni programas a medio cambiar. Los pendientes para Spotify se cancelan igual (✕ o clic derecho) desde «· N pendientes» arriba o desde «Playlists nuevas».

## Cambios en Rekordbox → Spotify
Si dentro de la carpeta de BrainOrder en Rekordbox **creas, borras o renombras una playlist, o le agregas o quitas canciones**, BrainOrder lo detecta (aunque Rekordbox siga abierto) y pregunta qué hacer con cada cambio:
- **Hacer lo mismo en Spotify** (busca cada canción por tus playlists, por ISRC o por artista + título con la misma duración; lo que no encuentre te lo dice).
- **Solo en Rekordbox**: esa playlist pasa a mandar en Rekordbox y BrainOrder no la vuelve a sobrescribir (se puede volver atrás).
- **Deshacer en Rekordbox**: la deja como está en su plataforma.
Mientras no decidas, Organizar no toca esas playlists. Para escribir en Spotify hay que **reconectar Spotify** una vez (permiso de editar playlists). Deezer y los archivos exportados solo se pueden leer.

## Duplicados
Busca archivos repetidos en **toda** tu música: copias idénticas (aunque tengan otro nombre) y la misma canción en otro formato o calidad. Sugiere cuál conservar (cues o playlists en Rekordbox, Mixed In Key, uso en tus playlists, calidad) y tú eliges. Lo apartado va a `_duplicados`, se corrigen las rutas en tus programas de DJ y se puede deshacer en Historial.

## Reglas (a tu gusto)
En la barra lateral, **Reglas**:
- **Exclusiones**: carpetas y patrones (`Samples`, `*stem*`, `*.wav`, `*/Sets grabados/*`) que BrainOrder nunca lee, mueve ni cuenta. También puedes ignorar audios muy cortos (one-shots). El botón **Probar** muestra qué quedaría fuera antes de guardar.
- **Prioridad de playlists**: si una canción está en varias playlists, su archivo vive en la carpeta de la primera de la lista. Arrastra para ordenar. Cada playlist puede **Organizar** o **Ignorar**.
- **Comparación**: tolerancia de duración para decidir si es la misma grabación, y qué formato se queda cuando hay repetidos.

## Seguridad de tus archivos
- Nunca se borra música: lo repetido se aparta en carpetas `_duplicados` para que lo revises tú.
- Mover entre discos es a prueba de cortes: se copia a un temporal oculto, se verifica y recién entonces se borra el original. Si se llena el disco o se desconecta, el original queda intacto y no queda ninguna copia a medias.
- Antes de escribir en Rekordbox se respalda `master.db` en un solo archivo consistente (incluye lo que Rekordbox aún tenía en su diario `-wal`); se guardan los últimos 5 `master.backup.brainorder-…db`. Si no hay espacio para el respaldo, no se escribe nada. El paso automático de Mixed In Key hace como mucho un respaldo por hora.
- Para revisar cambios en Rekordbox se lee la librería en modo solo lectura, sin copiarla (antes se copiaban ~200 MB en cada revisión).
- Si Unificar, Reorganizar o Deshacer fallan a mitad de camino, se deshacen los movimientos.
- Los ajustes se guardan de forma atómica con copia anterior (`config.json.bak`): si el archivo se daña, se recupera solo.

Para restaurar Rekordbox: ciérralo y reemplaza `master.db` por uno de los respaldos.
- macOS: `~/Library/Pioneer/rekordbox/`
- Windows: `%APPDATA%\Pioneer\rekordbox\`

## Dónde guarda sus datos
Ajustes, sesión de Spotify, cachés y el log (`brainorder.log`, se rota al pasar de 5 MB):
- macOS: `~/Library/Application Support/BrainOrder/`
- Windows: `%APPDATA%\BrainOrder\`

Tu Client ID y tu sesión de Spotify viven solo ahí, nunca en el repositorio.

## Límite de consultas de Spotify
Las apps personales de Spotify tienen un límite de consultas. Si se excede, Spotify pone a la app en pausa (a veces varias horas).
- BrainOrder recuerda la pausa (aunque cierres la app) y no le pregunta nada a Spotify hasta que termine: cada consulta extra puede alargarla. Arriba se ve «Spotify en pausa hasta las HH:MM».
- Mientras tanto usa lo último que leyó de Spotify; Deezer, archivos, organizar, Rekordbox y lo demás siguen funcionando.
- Puedes importar a Spotify igual durante la pausa: la playlist queda lista en BrainOrder y tus programas de DJ y entra a una **cola**; BrainOrder la crea en Spotify sola en cuanto Spotify lo permite (revisa cada minuto). Lo mismo con las canciones nuevas de una carpeta vinculada. Los pendientes se ven (y se pueden cancelar o «Pasar ya») en «Playlists nuevas», y arriba dice cuántos hay.
- Para no llegar al límite: «Analizar todo» solo vuelve a leer las playlists que cambiaron en Spotify (y Me gusta solo si cambió), y las consultas van espaciadas.

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

# BrainOrder

**BrainOrder by @BRAINWASHERDJ** · © 2026 @BRAINWASHERDJ. Todos los derechos reservados ([LICENSE](LICENSE)).

App de escritorio para **macOS y Windows** que mantiene sincronizadas tus playlists (Spotify, Deezer, Apple Music, SoundCloud, Tidal…) con tu música descargada y con tus programas de DJ (Rekordbox, Traktor, Serato, Engine DJ y cualquiera que lea M3U).

- Compara tus playlists de Spotify (y tus Me gusta) con los archivos de tu computador y te dice qué te falta y a qué carpeta va.
- **Organizar** mueve las descargas a la carpeta de su playlist, sin duplicar archivos, y replica las playlists en Rekordbox con el mismo orden de Spotify.
- **Unificar repetidos** limpia la carpeta: junta carpetas repetidas, aparta canciones repetidas en `_duplicados` y corrige las rutas en Rekordbox.
- Links de **Spotify y Deezer** para cada canción que falta. Botones para copiarlos todos de una, por playlist.
- Informes en **Excel** por playlist o de todo lo que falta, `.txt` de faltantes dentro de cada carpeta y estadísticas.

📘 **[Manual de usuario y novedades por versión](docs/BrainOrder%20-%20Manual%20de%20usuario.docx)** (Word): todas las funciones explicadas paso a paso.

---

## Instalación

### Con el instalador (recomendado, no necesitas Python)
Descarga el instalador de la última versión en **[Releases](https://github.com/Brainwasher77/BrainOrder/releases/latest)**:

| Tu computador | Archivo |
|---|---|
| Mac con chip Apple (M1, M2, M3, M4…) | `BrainOrder-<versión>-Mac-AppleSilicon.dmg` |
| Mac con Intel | `BrainOrder-<versión>-Mac-Intel.dmg` |
| Windows 10 / 11 | `BrainOrder-<versión>-Windows.exe` |

Traen su propio Python y todos los componentes. Durante la instalación te pregunta **tus carpetas** (música organizada y descargas) y te guía paso a paso para crear la **app de Spotify** y pegar el **Client ID**; al final abre Spotify en el navegador para autorizar y queda todo listo.

- **Mac:** abre el `.dmg` y arrastra **BrainOrder** a **Aplicaciones**. La primera vez macOS dice que no puede verificarla (no está firmada con una cuenta de Apple de pago): toca **Listo**, ve a **Configuración del Sistema → Privacidad y seguridad** y toca **Abrir igualmente** (en macOS 14 o anterior también sirve clic derecho → Abrir). Al abrirse, el asistente de instalación te lleva por carpetas → programas de DJ → fuentes → Spotify (con botón **Conectar y probar**).
- **Windows:** abre el `.exe`. Si aparece «Windows protegió tu PC»: **Más información → Ejecutar de todas formas**. El instalador pregunta tus carpetas y el Client ID de Spotify (con botón para abrir el panel de Spotify y el Redirect URI listo para copiar). Al abrir BrainOrder ya está todo puesto: solo revisas y autorizas Spotify. Se instala solo para tu usuario (no pide administrador) con accesos en el Escritorio y el Menú Inicio.
- Si ya tenías BrainOrder instalada con el script, el instalador conserva tu configuración, historial y cachés.
- Los instaladores los arma GitHub Actions solo (`.github/workflows/instaladores.yml`, scripts en `empaquetar/`) cada vez que cambia `version.json` en `main`, y quedan en Releases.

### Con el script (si ya tienes Python 3.9+)
- **macOS:** `brew install python` si no lo tienes, y doble clic en **`Instalar BrainOrder.command`** (si macOS lo bloquea: clic derecho → Abrir).
- **Windows:** instala Python desde [python.org](https://www.python.org/downloads/) marcando **"Add python.exe to PATH"** (o `winget install Python.Python.3.12`) y doble clic en **`Instalar BrainOrder (Windows).bat`**.

El script copia la app a tu carpeta de datos y crea un entorno de Python propio (no toca tu Python del sistema). Después de instalar puedes borrar la carpeta descargada.

## Actualizaciones automáticas
- Cada vez que abres BrainOrder revisa si hay una versión nueva en este repositorio (`version.json`). Si la hay, la descarga en segundo plano y te ofrece **Reiniciar ahora**; si dices "Después", se instala sola la próxima vez que la abras.
- Para revisar en cualquier momento: **Ajustes → 🔄 Buscar actualizaciones**. Te dice si ya tienes la última o te ofrece reiniciar con la nueva.
- Si Python cambia en tu computador (por ejemplo después de `brew upgrade`), el lanzador rehace el entorno solo al abrir la app (solo en la instalación con script: la del instalador trae su propio Python).
- Si una versión nueva no llegara a arrancar, BrainOrder vuelve sola a la anterior y no reintenta esa versión.
- Si una versión nueva necesita componentes nuevos, se instalan solos al abrirla (con el instalador quedan en `componentes/` de la carpeta de datos). Si instalas un `.dmg`/`.exe` más nuevo que tu versión, su código reemplaza al anterior; si es más viejo, se sigue usando el actualizado.
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

## Descargas reconocidas aunque el nombre cambie
Lo que bajas con los links de BrainOrder (Deezer) a veces trae el nombre escrito distinto que en Spotify («Can’t» / «Can't», «Alexis & Fido» / «Alexis y Fido», «Part 1» / «Pt. I», «Altın» / «Altin»…). BrainOrder empareja cada archivo por su **ISRC**, el código de la grabación que traen dentro las descargas, y compara los nombres con tolerancia a esas diferencias. También reconoce así canciones que ya tenías con otro nombre. La primera vez el análisis tarda unos segundos más porque lee esos códigos; después quedan guardados.

## Descargas que ya usas en Rekordbox
Si pones descargas en una playlist que armas en Rekordbox (u otro programa), al organizar aparecen en «Ya están en tus playlists de tu programa de DJ» con esa playlist y el botón **Importarla…**. Organizar corrige la ruta en Rekordbox (y Traktor, Serato, Engine) de toda descarga que ya esté en tu librería, para que nada quede perdido.

## Descargas en otra versión
Una descarga se reconoce solo si es la misma grabación que la de la playlist. Los links de Deezer buscan esa misma versión (título y duración); si Deezer no la tiene, el link dice «Deezer (otra versión)». Si bajas otra versión (remix, Dream Version, corte largo…), al organizar aparece en «Parecen de tus playlists» con ▶ y **Usar esta versión** para que cuente como esa canción.

## Vista previa
Cada canción tiene **▶** (playlists, faltantes, Comparar y clic derecho → Escuchar). Si tienes el archivo suena tu archivo (desde el 25 %, sin la intro); si te falta, 30 s de Deezer. Reproductor abajo con pausa (barra espaciadora), adelantar, −15/+15 s y ½ (ir a la mitad). Tus archivos se sirven solo dentro del computador (127.0.0.1, con clave de sesión) y solo los de tus carpetas de música.

## Ordenar playlists, clic derecho y Reorganizar
- Debajo de «Tus playlists» eliges el orden: de Spotify, más o menos faltantes primero, completas o menos completas primero, con descargas por organizar, por nombre o por cantidad de canciones. Se recuerda.
- **Clic derecho en una canción**: moverla a su carpeta, a la de esta playlist, a la de otra playlist que también la tenga o a cualquier carpeta de tu biblioteca; fijarla donde está; mostrarla en Finder; abrirla en Spotify/Deezer o copiar su nombre. Cada movimiento corrige Rekordbox y demás programas y se puede deshacer en Historial.
- **Reorganizar** te propone las canciones siempre. Solo si marcas «No volver a proponer las que dejo» se dejan de mostrar las que dejas donde están (esa elección se recuerda, y las fijadas se pueden soltar cuando quieras).

**Clic derecho en una playlist** (lista de la izquierda): **⚖️ Comparar con…** (canciones en común, solo en cada una, % de parecido, artistas compartidos, fechas, BPM/keys; las playlists para elegir se ordenan por nombre, fecha de creación, canciones agregadas hace poco, cantidad o más en común; con pestañas, buscador, Copiar y atajo para fusionar; no cambia nada), **Renombrar**, **Fusionar con otra**, **🙈 Ocultar de mis estadísticas** (no cuenta en tus números ni en faltantes, pero se sigue organizando; se vuelve a mostrar igual o desde Estadísticas) o **Eliminar**, en todas partes: BrainOrder, su carpeta, Spotify, Rekordbox, Traktor, Serato, Engine DJ y M3U (los programas deben estar cerrados; se respaldan antes). Renombrar pasa sus archivos a la carpeta con el nombre nuevo. Fusionar agrega las canciones que falten a la otra playlist (también en Spotify), pasa sus archivos a esa carpeta (las repetidas a `_duplicados`) y elimina la primera. Eliminar la quita en todas partes y ordena sus archivos (los que están en otras playlists van a la carpeta de esas; el resto a `_Playlists eliminadas/<nombre>`) o los deja donde están: la música nunca se borra y todo se puede deshacer en Historial. La carpeta vieja no queda rezagada: lo que choca por nombre va a `_duplicados` y la basura del sistema se limpia; si algo no se puede mover, te avisa y esa carpeta no se toma como «playlist nueva». Si Spotify está en pausa, allá queda en la cola; al fusionar, mientras tanto las canciones ya se ven en la otra playlist con sus archivos (no parece que se hubieran borrado), y varias fusiones hacia la misma playlist se suman en la cola en vez de reemplazarse. Deezer y los archivos exportados no dejan cambiarse desde una app: el cambio queda en BrainOrder y tus programas.

## Playlists nuevas (carpetas y programas de DJ)
BrainOrder te pregunta si quieres importar como playlist:
- **Una carpeta nueva** que creas en tu carpeta de playlists o en cualquiera de tus carpetas de música (Ajustes), aunque esté vacía. Espera a que termines de copiar.
- **Una playlist nueva** que creas en Rekordbox, Engine DJ o Serato (al momento) o en Traktor (cuando lo cierras, que es cuando Traktor guarda), en cuanto tiene canciones.

**Antes de preguntarte, revisa qué es nuevo de verdad** (en playlists de Rekordbox y tus otros programas): canción por canción mira si el archivo ya es de una de tus playlists de BrainOrder, si es una **copia exacta** de uno que ya tienes o si es **la misma canción** (artista + título + versión + duración). Solo te pregunta cuando hay **música nueva**, y te dice cuántas son nuevas y cuántas ya tienes. Lo que ya tienes **no se copia otra vez**: la playlist usa tu archivo de siempre (y la copia no se borra ni se mueve; si quieres limpiarla, usa *Duplicados*). Si ya existe una playlist de BrainOrder con **el mismo nombre** (aunque cambien tildes, emojis o mayúsculas), **no se crea otra**: el botón dice **Sumar lo nuevo** y solo agrega las canciones nuevas a esa playlist (también en Spotify si es de Spotify).

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
La primera vez se abre el **asistente de instalación**: tus carpetas (sugiere las que tienen música), programas de DJ (detecta los instalados), de dónde vienen tus playlists, **Conectar Spotify** (guía paso a paso para crear tu app de desarrollador, Redirect URI para copiar, revisa que el Client ID esté completo y botón **Conectar y probar**) y listo. Al terminar trae tus playlists solo. Si instalaste con el `.exe`, las carpetas y el Client ID ya vienen puestos. Se puede volver a abrir desde **Ajustes → Asistente de configuración**.

## Historial y Deshacer
Todo lo que BrainOrder mueve (Organizar, Reorganizar, Unificar) queda en **Historial**. **Deshacer** devuelve cada archivo a donde estaba y corrige las rutas en Rekordbox, Traktor, Serato y Engine DJ (con respaldo). Nunca pisa un archivo: si algo cambió desde entonces, ese archivo se salta y te lo dice.

## Key y energía (Mixed In Key)
Cada playlist muestra **Key** (Camelot), **Energía** (1–10) y **BPM** de tus archivos, leídos de las etiquetas que deja **Mixed In Key 10 u 11** (los datos de **Mixed In Key siempre tienen prioridad**; solo si una canción no tiene nada de MIK se usa la key de otros programas —«Am», «C#m», Open Key «1m»…—, marcada con *). Se ordena por cualquiera de esas columnas, el filtro **Sin Mixed In Key** muestra lo que falta analizar y escribir **8A** en el buscador deja solo esa key. BrainOrder solo lee: nunca cambia las etiquetas.

## Sin Mixed In Key
Sección del menú con las canciones que tienes y que Mixed In Key todavía no analizó (una por archivo, con sus playlists). Marca y dale **Mandar a Mixed In Key**: se abren en tu Mixed In Key; cuando las analiza, BrainOrder lo nota y salen de la lista. También con clic derecho en una canción. Sin Mixed In Key instalado, te abre las carpetas en Finder para arrastrarlas. En Windows lo busca en los programas instalados, sus carpetas y el Menú Inicio; si no lo encuentra, **Buscar Mixed In Key…** te deja elegir su programa.

**Canciones que en Mixed In Key salen analizadas pero aquí no:** BrainOrder sabe que una canción está analizada porque Mixed In Key escribe la key y la energía dentro del archivo. Si Mixed In Key ya tenía esa canción en su colección (otra copia), la muestra como analizada pero no vuelve a escribir en el archivo nuevo. Cuando la copia analizada quedó en `_duplicados`, el botón **Recuperar** la pone en el lugar de la otra (mismo nombre y carpeta; se puede deshacer). Para las demás, quítalas de la colección de Mixed In Key y vuelve a mandarlas. **Unificar repetidos** y **Duplicados** conservan siempre la copia analizada con Mixed In Key (salvo que otra tenga cues en Rekordbox). Si tienes varias copias de una canción, BrainOrder usa la analizada con Mixed In Key.

**Ocultar:** marca canciones que no quieres analizar y dale **🙈 Ocultar**: salen de la lista y del contador (no se toca ningún archivo). **Ver ocultas** las muestra y **Mostrar otra vez** las devuelve.

BrainOrder no cuenta los accesos directos rotos (alias que apuntan a un archivo que ya no existe): esas canciones salen en «Faltan por descargar», no como si las tuvieras. Los WAV y AIFF con un bloque interno raro (por ejemplo un LIST vacío) se leen igual, así no salen como sin analizar si Mixed In Key ya los analizó.

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

## Sin playlist
Sección del menú con las canciones que no son de ninguna playlist: descargas que no coinciden con nada y las de tu carpeta `_Sin Playlist`. Elige a qué playlist va cada una (sale ★ sugerida la playlist donde más tienes de ese artista; también puedes marcar varias y ponerles la misma). **Llevar a su playlist** mueve el archivo a la carpeta de la playlist y agrega la canción a la playlist: en Spotify al momento o, si Spotify está en pausa, queda en los pendientes y mientras tanto ya la ves en BrainOrder con su archivo. En las playlists de carpeta queda como suya. Se corrigen tus programas de DJ y se puede deshacer en Historial. Desde **Organizar** también llegas con «Elegir a qué playlist va cada una».

**De qué carpeta lee:** arriba en «Sin playlist» ves de qué carpeta saca las canciones sin playlist (sola encuentra la carpeta sin playlist dentro de tus carpetas de música). Cuando la elige BrainOrder (no elegiste ninguna) se llama **`_Sin Playlist`**: si la tuya se llama distinto (por ejemplo `_SIn Playlist`) se renombra, corrigiendo las rutas en tus programas de DJ (tienen que estar cerrados; queda en el Historial), y si no tienes ninguna se crea en tu carpeta de playlists. Con «📁 Cambiar carpeta…» eliges otra, con «➕ Agregar otra carpeta» lees de varias a la vez (también sus subcarpetas, sin `_duplicados`) y con ✕ quitas una; «Que la detecte sola» vuelve a lo automático. Tus descargas se revisan siempre. No se puede elegir una carpeta de música entera, la de descargas, `_duplicados` ni la carpeta de una playlist.

**Playlist nueva:** si ninguna te sirve, elige «➕ Crear playlist nueva…» en la lista de la canción (o el botón «➕ Playlist nueva» para las marcadas). Le pones nombre, eliges **la carpeta donde van a quedar sus canciones** (por defecto `<tu carpeta de playlists>/<nombre>`; con «📁 Elegir otra…» puedes poner cualquier otra, por ejemplo dentro de `DJ Library`) y si se crea también en Spotify. La playlist se crea al darle a Llevar: si Spotify está en pausa se crea en BrainOrder ya y pasa a Spotify sola después; si Spotify no encuentra ninguna de sus canciones queda solo en BrainOrder y te avisa. Si ya tienes una playlist con ese nombre, las canciones van a esa (nunca dos con el mismo nombre). No se puede usar como carpeta tu carpeta de playlists entera, la de descargas, `_Sin Playlist`, `_duplicados` ni la carpeta de otra playlist.

## Sugerencias
Sección del menú con ideas de playlists para ordenar tu música **según tus criterios**: por **género** (la etiqueta «género» de cada archivo), por **energía** (la de Mixed In Key, 1 a 10), por **BPM** o combinados (**Género + energía**, **Género + BPM**). Eliges si mira toda tu música o solo las canciones sin playlist y el mínimo de canciones por playlist. Cada sugerencia muestra cuántas canciones tiene, sus artistas, energía y BPM; puedes ver sus canciones, cambiarle el nombre y crearla (también en Spotify si quieres). Si ya tienes una playlist con ese nombre, se le suman las que le faltan.

Crear una playlist sugerida **no mueve ningún archivo**: cada canción se queda en su carpeta y la playlist la usa desde ahí (como en Rekordbox). Las nuevas quedan al final de tu prioridad (Reglas), así ninguna canción cambia de carpeta; solo las que no tienen otra playlist se ordenan ahí al Organizar.

**✏️ Mis criterios** (se guardan para cada usuario, en su computadora):
- **Grupos de géneros:** cada grupo es una playlist con las palabras que lo reconocen en la etiqueta género (sin importar mayúsculas ni tildes): «Reggaetón» ← reggaeton, reguetón, urbano, dembow… Si un género coincide con varios grupos gana la palabra más específica («tech house» le gana a «house»); si empatan, el grupo de más arriba. Abajo ves los géneros que tienen tus canciones, cuántas tiene cada uno y a qué grupo van; cambias el grupo de un género con un clic. Los que no entran en ningún grupo pueden ir cada uno a su playlist, todos juntos o no sugerirse.
- **Rangos de energía y de BPM** con el nombre que quieras («Calentando 1–4», «Pico 7–8»…).
- **Nombres** de las combinadas con `{genero}`, `{energia}` y `{bpm}` («{genero} · {energia}») y prefijo opcional.
- «Volver a los de fábrica» deja los criterios como venían.

## Datos incompletos
Sección del menú que encuentra las canciones con **artista desconocido** («Desconocido», «Unknown Artist»…), **sin título**, **sin género** o con un **nombre de archivo que no es «Artista - Título»** (así BrainOrder no las reconoce bien). Para cada una propone los datos: de la canción de Spotify con la que ya se cruzó, del título (muchas descargas traen «Artista - Título» en el título con artista «Desconocido») o del nombre del archivo, limpiando basura típica («(WWW.ELGENERO.COM)», «on iTunes», «- from YouTube», «(1)»). Puedes corregir cada dato, ponerle género a varias a la vez o buscar en Spotify 🔎 cómo se llama de verdad (con la duración para comparar). **Arreglar** escribe artista, título y género en el archivo (sin tocar cues, key ni energía de Mixed In Key; ID3 2.3 se mantiene) y, si lo marcas, renombra el archivo a «Artista - Título», corrigiendo las rutas en tus programas de DJ (Rekordbox cerrado). Todo queda en el Historial: Deshacer devuelve nombres y etiquetas. En Rekordbox, los datos nuevos se ven con clic derecho → «Volver a cargar etiqueta».

## Pendientes de Spotify primero
Lo que quedó pendiente para Spotify (fusiones, canciones agregadas, playlists importadas, nombres) se hace **antes** de volver a leer tus playlists: Analizar todo, Analizar una playlist y Cargar playlists primero pasan los pendientes y, si Spotify se vuelve a pausar a mitad, no gastan más consultas leyendo. Lo barato va primero (renombrar, eliminar), después agregar y crear. Lo que ya se buscó en Spotify queda guardado (en el pendiente y entre sesiones), así que si se corta a la mitad no se vuelve a buscar, y una pausa nunca se toma como «canción no encontrada». Las playlists a las que se agregan canciones no se vuelven a leer enteras. En la lista de pendientes (arriba, «N pendientes») ves por qué no avanzan si algo lo impide (pausa, Spotify desconectado o sin permiso de editar) y puedes darle «Hacerlos ya».

## Perdidas en Rekordbox
Canciones de tu colección de Rekordbox cuyo archivo ya no está donde Rekordbox lo busca, y las que apuntan a una carpeta `_duplicados` (se pierden en cuanto la vacías). Para cada una BrainOrder busca **dónde está ahora**: primero lo que movió BrainOrder (Historial, el archivo exacto), después otra entrada de tu colección (copia exacta, mismo ISRC o mismo título y artista con la misma duración ±4 s) y por último cualquier archivo de tus carpetas que no esté en la colección. Y las repara **dentro de Rekordbox** (no se mueve ningún archivo):
- 🔗 **Reconectar**: la pista pasa a apuntar al archivo encontrado. Conserva cues, playlists, historial y análisis (lo mismo que «Reubicar» de Rekordbox, pero automático).
- 🔀 **Unir con la copia**: la copia que ya está en tu colección toma su lugar en cada playlist (misma posición), se queda con sus cues si no tenía, y la perdida sale de la colección (con todo lo que cuelga de ella, sin dejar restos).
- **Otra versión** (otra duración) no se toca sola. Las **sin copia** en ninguna parte se pueden sacar de la colección marcando la casilla.

Rekordbox tiene que estar cerrado; antes se respalda la librería y todo se puede deshacer en Historial (vuelve exactamente como estaba: rutas, cues, playlists y su orden). Las canciones de un disco externo desconectado no cuentan como perdidas.

**Descargas en otra carpeta:** «Faltan por descargar» muestra en qué carpeta reviso tus descargas. Si bajaste canciones en otra, **🔎 Buscar en otras carpetas** revisa Descargas, Escritorio y las carpetas de tu Música que no están en Ajustes, te muestra las que te faltan y las mueve a la carpeta de su playlist; si casi todas están en una misma carpeta, te ofrece usarla como carpeta de descargas.

**Buscar en la papelera** (en Perdidas en Rekordbox y en Faltan por descargar): revisa la papelera (Mac: la tuya y la de cada disco externo; Windows: la Papelera de reciclaje de cada disco) y te muestra las canciones que están ahí y que son perdidas de Rekordbox o te faltan en tus playlists. **Recuperar** las saca de la papelera: las perdidas vuelven a su ruta (Rekordbox las encuentra con sus cues y playlists) y las que faltan van a la carpeta de su playlist. Queda en el Historial. En el Mac, macOS solo deja leer la papelera si BrainOrder tiene **Acceso total al disco** (Ajustes del Sistema → Privacidad y seguridad); si no, BrainOrder te lo dice.

**Canciones que solo están en `_duplicados`:** si una canción no tiene otra copia en tu música, el aviso de arriba lo dice y **Recuperar** la devuelve a su lugar: donde la espera un acceso directo roto (así vuelve a funcionar), donde estaba antes (Historial), la carpeta de su playlist o `_Recuperadas`. Se corrige Rekordbox y se puede deshacer.

## Duplicados
Busca archivos repetidos en **toda** tu música: copias idénticas (aunque tengan otro nombre) y la misma canción en otro formato o calidad. Sugiere cuál conservar (cues o playlists en Rekordbox, Mixed In Key, uso en tus playlists, calidad) y tú eliges. Lo apartado va a `_duplicados`, se corrigen las rutas en tus programas de DJ y se puede deshacer en Historial.

## Reglas (a tu gusto)
En la barra lateral, **Reglas**:
- **Exclusiones**: carpetas y patrones (`Samples`, `*stem*`, `*.wav`, `*/Sets grabados/*`) que BrainOrder nunca lee, mueve ni cuenta. También puedes ignorar audios muy cortos (one-shots). El botón **Probar** muestra qué quedaría fuera antes de guardar.
- **Prioridad de playlists**: si una canción está en varias playlists, su archivo vive en la carpeta de la primera de la lista. Arrastra para ordenar. Cada playlist puede **Organizar** o **Ignorar**.
- **Comparación**: tolerancia de duración para decidir si es la misma grabación, y qué formato se queda cuando hay repetidos.

## Seguridad de tus archivos
- Nunca se borra música: lo repetido se aparta en carpetas `_duplicados` para que lo revises tú.
- Solo se aparta algo a `_duplicados` si **de verdad** hay otra copia: que exista ahora, que no esté en `_duplicados` y que no sea el mismo archivo visto por otro camino (acceso directo, mayúsculas o tildes distintas). Si al juntar carpetas hay dos archivos con el mismo nombre pero distinto contenido, se conservan los dos («Canción (2).mp3»).
- Al apartar una repetida, su pista de Rekordbox se **une** a la que se conserva (no queda apuntando a `_duplicados`), y las pistas que apuntan a un acceso directo se corrigen cuando su archivo se mueve.
- Se guardan los 5 respaldos más recientes de Rekordbox y además el primero de cada uno de los últimos 7 días.
- Mover entre discos es a prueba de cortes: se copia a un temporal oculto, se verifica y recién entonces se borra el original. Si se llena el disco o se desconecta, el original queda intacto y no queda ninguna copia a medias.
- Antes de escribir en Rekordbox se respalda `master.db` en un solo archivo consistente (incluye lo que Rekordbox aún tenía en su diario `-wal`); se guardan los últimos 5 `master.backup.brainorder-…db`. Si no hay espacio para el respaldo, no se escribe nada. El paso automático de Mixed In Key hace como mucho un respaldo por hora.
- Para revisar cambios en Rekordbox se lee la librería en modo solo lectura, sin copiarla (antes se copiaban ~200 MB en cada revisión).
- Si Unificar, Reorganizar o Deshacer fallan a mitad de camino, se deshacen los movimientos.
- Los ajustes se guardan de forma atómica con copia anterior (`config.json.bak`): si el archivo se daña, se recupera solo.
- Rekordbox a veces guarda rutas con barras de más (`//Users/...`). BrainOrder las trata como la misma ruta: al mover un archivo corrige su ruta en Rekordbox (antes esas pistas quedaban perdidas) y al sincronizar no la agrega dos veces. En Windows las rutas se comparan sin distinguir mayúsculas.
- Los accesos directos (alias / symlinks) se mueven como accesos directos y siguen apuntando al mismo archivo; los rotos no cuentan como canciones que tienes, y un acceso directo a un archivo que ya está en tu biblioteca no cuenta como otra copia.

Para restaurar Rekordbox: ciérralo y reemplaza `master.db` por uno de los respaldos.
- macOS: `~/Library/Pioneer/rekordbox/`
- Windows: `%APPDATA%\Pioneer\rekordbox\`

## Dónde guarda sus datos
Ajustes, sesión de Spotify, cachés y el log (`brainorder.log`, se rota al pasar de 5 MB):
- macOS: `~/Library/Application Support/BrainOrder/`
- Windows: `%APPDATA%\BrainOrder\`

Tu Client ID y tu sesión de Spotify viven solo ahí, nunca en el repositorio.

## Límite de consultas de Spotify
**Conexiones → 🩺 Probar Spotify** hace una sola consulta y te dice exactamente qué pasa: funciona, **cuota agotada** (desde 2026 las apps en modo desarrollo tienen una cuota de consultas por cuenta de desarrollador; se recupera sola con el tiempo), pausa por exceso de consultas, falta **Premium** en la cuenta dueña de la app, tu cuenta no está en **User Management** de la app, o la sesión venció. Con **Reintentar ahora** vuelve a preguntar sin esperar la pausa.

Mientras Spotify no responda, BrainOrder sigue con lo último que leyó. Para no depender de la cuota: exporta tus playlists a CSV con Exportify o TuneMyMusic y ponlas en **Conexiones → Archivos exportados**. BrainOrder ya no intenta leer las canciones de playlists de otros (Spotify dejó de darlas en febrero de 2026), así gasta menos consultas.

Las apps personales de Spotify tienen un límite de consultas. Si se excede, Spotify pone a la app en pausa (a veces varias horas).
- BrainOrder recuerda la pausa (aunque cierres la app) y no le pregunta nada a Spotify hasta que termine: cada consulta extra puede alargarla. Arriba se ve «Spotify en pausa hasta las HH:MM».
- Mientras tanto usa lo último que leyó de Spotify; Deezer, archivos, organizar, Rekordbox y lo demás siguen funcionando.
- Puedes importar a Spotify igual durante la pausa: la playlist queda lista en BrainOrder y tus programas de DJ y entra a una **cola**; BrainOrder la crea en Spotify sola en cuanto Spotify lo permite (revisa cada minuto). Lo mismo con las canciones nuevas de una carpeta vinculada. Los pendientes se ven (y se pueden cancelar o «Pasar ya») en «Playlists nuevas», y arriba dice cuántos hay.
- Para no llegar al límite: «Analizar todo» solo vuelve a leer las playlists que cambiaron en Spotify (y Me gusta solo si cambió), y las consultas van espaciadas.

## Limitaciones
- Spotify no deja que apps personales lean canciones de playlists de otras personas. Quedan en la sección **Playlists de otros** (BrainOrder ya no te las pregunta en una ventana al abrir): ahí eliges si las integras; para hacerlo, cópialas en Spotify a una playlist tuya (Seleccionar todo → Añadir a playlist → Nueva playlist).
- Las pistas nuevas entran a Rekordbox sin analizar: al abrirlo, selecciónalas y analízalas (BPM, waveform).

## Estructura
| Archivo | Para qué |
|---|---|
| `arranque.py` | Instala actualizaciones pendientes y componentes que falten, y abre la app |
| `actualizador.py` | Revisa y descarga versiones nuevas desde GitHub |
| `mac/lanzador.sh`, `windows/abrir.*` | Lanzadores (instalación con script) que reparan el entorno de Python si se daña |
| `empaquetar/` | Arma los instaladores `.dmg` y `.exe` con su propio Python (lo corre GitHub Actions) |
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
| `rb_perdidas.py` | Canciones perdidas en Rekordbox: dónde está cada una ahora |
| `rb_coleccion.py` | Reconectar, unir y sacar pistas de la colección de Rekordbox, con Deshacer |
| `rescate.py` | Canciones que solo quedaron en `_duplicados` |
| `papelera.py` | Buscar en la papelera las canciones perdidas o que faltan |
| `novedades.py` | Qué es nuevo en una playlist de tu programa de DJ (sin duplicar archivos ni playlists) |

---

## Autor y derechos
**BrainOrder es de @BRAINWASHERDJ.** © 2026 @BRAINWASHERDJ. Todos los derechos reservados: ver [LICENSE](LICENSE). La firma *BrainOrder by @BRAINWASHERDJ* aparece en la app, en los informes (Excel y `.txt`), en las listas M3U, en la descripción de las playlists que BrainOrder crea en Spotify y en los instaladores. BrainOrder nunca escribe nada dentro de tus archivos de música.

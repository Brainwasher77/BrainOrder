"""Links de Deezer: se comprueba que lleven a la canción (ISRC repetido, caché viejo, id reutilizado)."""
import os, sys, json, tempfile, pathlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
tmp = pathlib.Path(tempfile.mkdtemp())
import deezer
deezer.CACHE = tmp / "deezer_cache.json"

TRACKS = {
    "111": {"id": 111, "title": "La Rebelión", "duration": 300, "artist": {"name": "Joe Arroyo"}, "link": "https://www.deezer.com/track/111"},
    "222": {"id": 222, "title": "Otra Cosa", "duration": 200, "artist": {"name": "Otro Artista"}, "link": "https://www.deezer.com/track/222"},
    "333": {"id": 333, "title": "La Bicicleta", "duration": 230, "artist": {"name": "Carlos Vives"},
            "contributors": [{"name": "Carlos Vives"}, {"name": "Shakira"}], "link": "https://www.deezer.com/track/333"},
}
CALLS = []
def fake_get(url, tries=4, lang=None):
    CALLS.append(url)
    if "/track/isrc:" in url:
        return TRACKS["222"]  # ISRC reutilizado: Deezer devuelve otra canción
    if "/track/" in url:
        return TRACKS.get(url.rsplit("/", 1)[-1], {"error": {"code": 800}})
    if "/search?" in url:
        q = url.lower()
        return {"data": [t for t in TRACKS.values() if t["title"].split()[-1].lower()[:4] in q]}
    return {}
deezer._get = fake_get

rows = [
    {"id": "a", "name": "La Rebelión", "artists": ["Joe Arroyo"], "duration_ms": 301000, "isrc": "XX123", "status": "missing"},
    {"id": "b", "name": "La Bicicleta", "artists": ["Shakira"], "duration_ms": 230000, "status": "missing"},
]
# caché viejo: a con link de otra canción (marcado exact), b con su link bueno
deezer._MEM.clear(); deezer._LOADED[0] = True
deezer._MEM.update({"a": {"url": "https://www.deezer.com/track/222", "exact": True},
                    "b": {"url": "https://www.deezer.com/track/333", "exact": False, "v": 2}})

# sin conexión, lo no comprobado no se muestra como encontrado
an = [{"tracks": [dict(r) for r in rows]}]
deezer.add_links(an, offline=True)
assert all(not r["deezer"]["found"] for r in an[0]["tracks"]), an

an = [{"tracks": [dict(r) for r in rows]}]
deezer.add_links(an)
a, b = an[0]["tracks"]
assert a["deezer"]["url"].endswith("/111") and a["deezer"]["found"], a  # ISRC falso descartado → búsqueda
assert b["deezer"]["url"].endswith("/333") and b["deezer"]["found"], b  # el viejo estaba bien (colaborador)
assert deezer.check_link(rows[0], "https://www.deezer.com/co/track/111")
assert not deezer.check_link(rows[0], "https://www.deezer.com/track/222")
assert deezer.track_id("https://www.deezer.com/es/track/42") == "42"

# id reutilizado por otra canción: se vuelve a comprobar
n = len(CALLS)
an = [{"tracks": [{**rows[0], "name": "Otra Cosa", "artists": ["Otro Artista"], "isrc": ""}]}]
deezer.add_links(an)
assert an[0]["tracks"][0]["deezer"]["url"].endswith("/222") and len(CALLS) > n
print("ok")

"""Si lo que baja el link de Deezer ya está en tu música (otra versión / otra duración que la de Spotify),
la canción cuenta como tenida: no se vuelve a dar el link (antes la bajabas y Organizar la mandaba a _duplicados)."""
import os, sys, tempfile, pathlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
TMP = pathlib.Path(tempfile.mkdtemp())
config.SUPPORT_DIR = TMP
import biblioteca, deezer
deezer.CACHE = TMP / "deezer_cache.json"

dest, inbox = TMP / "BRAIN LIBRARY", TMP / "Nuevas descargas"
(dest / "Techno").mkdir(parents=True); (inbox).mkdir()
(dest / "Techno" / "Acti - Vicker (T78 2018 Rework) (Extended Mix).mp3").write_bytes(b"x")
(dest / "Techno" / "Otro - Tema.mp3").write_bytes(b"x")
(inbox / "Acti - Vicker (T78 2018 Rework) (Extended Mix).mp3").write_bytes(b"y")  # la bajó otra vez
cfg = {"dest_root": str(dest), "inbox": str(inbox), "rules": {"min_seconds": 0}}
row = {"id": "sp1", "name": "Vicker - T78 2018 Rework", "artists": ["Acti", "T78"], "duration_ms": 0}
pls = [{"id": "fav", "name": "Favoritas", "tracks": [row]}]

# sin saber qué baja el link: falta
a = biblioteca.analyze(pls, cfg)
assert a[0]["tracks"][0]["status"] == "missing", a

# el link de Deezer baja «Vicker (T78 2018 Rework) (Extended Mix)»: ya lo tienes
deezer._MEM.clear(); deezer._LOADED[0] = True
deezer._MEM["sp1"] = {"url": "https://www.deezer.com/track/506614762", "exact": True, "v": deezer.V,
                      "for": "Acti - Vicker - T78 2018 Rework",
                      "to": {"a": "Acti", "t": "Vicker (T78 2018 Rework) (Extended Mix)", "d": 400}}
a = biblioteca.analyze(pls, cfg, alt=deezer.targets())
r = a[0]["tracks"][0]
assert r["status"] == "elsewhere" and r["source"].endswith("Techno/Acti - Vicker (T78 2018 Rework) (Extended Mix).mp3"), r
assert r["via_deezer"] and r["inbox_dups"] == [str(inbox / "Acti - Vicker (T78 2018 Rework) (Extended Mix).mp3")], r
deezer.add_links(a, offline=True)
assert "deezer" not in r  # ya no sale el link

# el link guardado es de otra canción (el id cambió): no se usa
deezer._MEM["sp1"]["for"] = "Otro - Tema"
a = biblioteca.analyze(pls, cfg, alt=deezer.targets())
assert a[0]["tracks"][0]["status"] == "missing"

# links viejos sin «to»: se averigua qué bajan solo donde puede que ya tengas el archivo
CALLS = []
def fake_get(url, tries=4, lang=None):
    CALLS.append(url)
    return {"id": 506614762, "title": "Vicker (T78 2018 Rework) (Extended Mix)", "duration": 400,
            "artist": {"name": "Acti"}, "link": "https://www.deezer.com/track/506614762"}
deezer._get = fake_get
deezer._MEM.clear()
deezer._MEM["sp1"] = {"url": "https://www.deezer.com/track/506614762", "exact": True, "v": deezer.V,
                      "for": "Acti - Vicker - T78 2018 Rework"}
deezer._MEM["sp2"] = {"url": "https://www.deezer.com/track/1", "exact": True, "v": deezer.V, "for": "Nadie - Nada"}
row2 = {"id": "sp2", "name": "Nada", "artists": ["Nadie"], "duration_ms": 0}
pls2 = [{"id": "fav", "name": "Favoritas", "tracks": [row, row2]}]
a = biblioteca.analyze(pls2, cfg, alt=deezer.targets())
deezer.add_links(a, maybe_have=biblioteca.maybe_have)
assert len(CALLS) == 1 and CALLS[0].endswith("/track/506614762"), CALLS  # «Nada» no se consulta
assert deezer._MEM["sp1"]["to"]["t"].endswith("(Extended Mix)")
a = biblioteca.analyze(pls2, cfg, alt=deezer.targets())
assert a[0]["tracks"][0]["status"] == "elsewhere" and a[0]["tracks"][1]["status"] == "missing"
print("ok")

"""2.32.0: un solo orden (Rekordbox o plataforma), lista .m3u8 por carpeta, Spotify reordenado, accesos directos."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TMP = Path(tempfile.mkdtemp())
config.SUPPORT_DIR = TMP / "sup"
config.SUPPORT_DIR.mkdir()
config.save = lambda c: None
import accesos  # noqa: E402
import app  # noqa: E402
import orden  # noqa: E402

# ------------------------------------------------ el análisis sigue el orden de Rekordbox
rows = [{"pos": i, "id": f"{c}" * 22, "name": c, "artists": ["X"], "status": "ok", "source": f"/m/{c}.mp3",
         "duration_ms": 60000} for i, c in enumerate("abcd")]
rows.append({"pos": 4, "id": "e" * 22, "name": "e", "artists": [], "status": "missing", "source": None})
res = [{"id": "sp1", "name": "Techno", "tracks": list(rows)}, {"id": "sp2", "name": "Otra", "tracks": list(rows)}]
orden.apply(res, orden.order_map({"9": {"pid": "sp1", "paths": ["/m/c.mp3", "/m/a.mp3", "/m/d.mp3", "/m/b.mp3"]}}))
assert [r["name"] for r in res[0]["tracks"]] == ["c", "a", "d", "b", "e"] and res[0]["order"] == "rekordbox"
assert [r["pos"] for r in res[0]["tracks"]] == [2, 0, 3, 1, 4]  # «pos» sigue siendo la de la plataforma
assert [r["name"] for r in res[1]["tracks"]] == list("abcde") and "order" not in res[1]
print("orden ok")

# ------------------------------------------------ Spotify: nunca agrega ni quita, solo ordena
assert orden.merge_order(["a", "b", "c", "b", "z"], ["c", "b", "a", "q"]) == ["c", "b", "a", "b", "z"]
assert orden.merge_order(["a"], []) == ["a"]
assert orden.wanted_ids(res[0]) == ["c" * 22, "a" * 22, "d" * 22, "b" * 22, "e" * 22]
print("spotify ok")

# ------------------------------------------------ lista .m3u8 en la carpeta
folder = TMP / "BRAIN LIBRARY" / "Techno" / "Hard"
folder.mkdir(parents=True)
for c in "abcd":
    (folder / f"{c}.mp3").write_bytes(b"x")
pl = {"id": "sp1", "name": "Hard: Techno", "folder": str(folder), "order": "rekordbox",
      "tracks": [{**r, "source": str(folder / Path(r["source"]).name) if r["source"] else None} for r in res[0]["tracks"]]}
pl["tracks"][1]["source"] = str(TMP / "BRAIN LIBRARY" / "Otra" / "a.mp3")  # vive en otra carpeta
assert orden.write_lists([pl]) == 1
lst = folder / orden.list_name("Hard: Techno")
txt = lst.read_text("utf-8").splitlines()
assert txt[0] == "#EXTM3U" and orden.MARK in txt[2] and "orden: Rekordbox" in txt[2]
assert [x for x in txt if not x.startswith("#")] == ["c.mp3", "../../Otra/a.mp3", "d.mp3", "b.mp3"], txt
assert orden.write_lists([pl]) == 0  # sin cambios no se reescribe
pl2 = {**pl, "name": "Hard Techno"}
orden.write_lists([pl2])
assert not lst.exists() and (folder / "_Hard Techno.m3u8").exists()  # la vieja de BrainOrder se quita
mine = folder / "_mia.m3u8"
mine.write_text("#EXTM3U\nc.mp3\n")
orden.write_lists([pl2])
assert mine.exists()  # una lista tuya no se toca
# no impide quitar una carpeta vacía
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "_remove_if_empty")][0]
empty = TMP / "vacia"
empty.mkdir()
(empty / "_Vieja.m3u8").write_text(f"#EXTM3U\n#PLAYLIST:x\n{orden.MARK} x\n")
A._remove_if_empty(empty)
assert not empty.exists()
print("lista m3u8 ok")

# ------------------------------------------------ trabajo «reorder» en la cola de Spotify


class FakeSp:
    def __init__(self):
        self.calls = []

    def replace_items(self, pid, uris):
        self.calls.append((pid, uris))
        return "snap2"

    def playlist_tracks(self, pid):
        raise AssertionError("debía usar la caché")


o = A.__new__(A)
cache = {"playlists": [{"id": "sp1", "snapshot": "s1", "analyzed_snapshot": "s1",
                        "tracks": [{"id": i * 22} for i in "abcd"]}]}
o._load_sp = lambda: cache
o._update_sp = lambda f: f(cache)
sp = FakeSp()
out = o._sp_reorder({"pid": "sp1", "ids": [i * 22 for i in "cadb"]}, sp)
assert out["reordered"] == 4 and sp.calls[0][1] == ["spotify:track:" + i * 22 for i in "cadb"]
assert [t["id"][0] for t in cache["playlists"][0]["tracks"]] == list("cadb") and cache["playlists"][0]["snapshot"] == "snap2"
assert o._sp_reorder({"pid": "sp1", "ids": [i * 22 for i in "cadb"]}, sp)["reordered"] == 0 and len(sp.calls) == 1
cache["playlists"][0]["tracks"].append({"id": "local:spotify:local:x"})
assert o._sp_reorder({"pid": "sp1", "ids": [i * 22 for i in "abcd"]}, sp)["skipped"]  # archivos locales: no se toca
print("reorder ok")

# ------------------------------------------------ accesos directos
lib = TMP / "BRAIN LIBRARY" / "Otra"
lib.mkdir(parents=True, exist_ok=True)
(lib / "a.mp3").write_bytes(b"x")
(lib / "uno.mp3").write_bytes(b"x")
sc = TMP / "Playlists rekordbox" / "Crossover" / "MGNO" / "Funk"
sc.mkdir(parents=True)
os.symlink(lib / "a.mp3", sc / "a.mp3")
os.symlink(TMP / "no existe.mp3", sc / "rota.mp3")
(sc / "uno.mp3 alias").write_bytes(accesos.ALIAS_MAGIC + b"\x00" * 40)
(sc.parent / "real.mp3").write_bytes(b"x" * 10)
r = accesos.scan(TMP / "Playlists rekordbox", [str(TMP / "BRAIN LIBRARY")])
assert r["links"] == {str(sc / "a.mp3"): str((lib / "a.mp3").resolve()), str(sc / "uno.mp3 alias"): str(lib / "uno.mp3")}, r
assert r["broken"] == [str(sc / "rota.mp3")] and r["audio"] == [str(sc.parent / "real.mp3")]
assert accesos.looks_like_shortcuts(TMP / "Playlists rekordbox", [str(TMP / "BRAIN LIBRARY")])
assert accesos.looks_like_shortcuts(TMP / "BRAIN LIBRARY") is None
print("accesos ok")
print("OK")

"""2.49.0: grupos de playlists como carpetas (en Rekordbox y en el disco)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

TMP = Path(tempfile.mkdtemp())
config.SUPPORT_DIR = TMP
config.save = lambda c: None
import app  # noqa: E402
import grupos as G  # noqa: E402
import rb_cambios  # noqa: E402
import rekordbox_sync as RS  # noqa: E402

rb_cambios.BASELINE = TMP / "rb_baseline.json"

# ------------------------------------------------ cálculo
assert G.to_trail("Crossover /  MGNO ") == ["Crossover", "MGNO"] and G.to_trail("") == []
assert G.to_group(["Crossover", "MGNO"]) == "Crossover / MGNO" and G.same("techno", "Techno")
t = G.effective_tree({"a": ["X"]}, {"b": "Techno / Hard", "c": "Salsa"}, {"c": []}, True)
assert t == {"a": ["X"], "b": ["Techno", "Hard"]}, t  # «c»: le quitaste el grupo -> carpeta principal
assert G.effective_tree({"a": ["X"]}, {"b": "Techno"}, {}, False) == {"a": ["X"]}
assert G.effective_tree({"a": ["X"]}, {"b": "Techno"}, {}, True, mirror_on=False) == {"b": ["Techno"]}

groups = {"p1": "Techno", "p2": "Latino", "p3": "House", "p5": "Bodas"}
tree = {"p2": ["Crossover", "MGNO"], "p3": ["house"], "p4": ["Brainwasher"]}
present = {"p1", "p2", "p3", "p4"}  # p5 no está en Rekordbox
pl = G.activation_plan(groups, tree, present, "rekordbox")
assert pl["groups"] == {"p1": "Techno", "p2": "Crossover / MGNO", "p3": "House", "p4": "Brainwasher", "p5": "Bodas"}, pl
assert pl["moves"] == {"p1": ["Techno"]}, pl["moves"]  # p1 suelta -> a su carpeta; p5 no está allá
assert pl["from_rb"] == ["p4"] and [c["pid"] for c in pl["conflicts"]] == ["p2"]
pl = G.activation_plan(groups, tree, present, "group")
assert pl["groups"]["p2"] == "Latino" and pl["moves"] == {"p1": ["Techno"], "p2": ["Latino"]}, pl
print("cálculo ok")

# Rekordbox manda en lo que muevas allá; lo pendiente no se pisa y se da por hecho cuando coincide
g, pend, ch = G.follow_rekordbox({"p1": "Techno", "p2": "Latino", "p3": "Salsa"},
                                 {"p1": ["Techno", "Hard"], "p2": ["Latino"]}, {"p1", "p2", "p3"}, {"p2": ["latino"]})
assert g == {"p1": "Techno / Hard", "p2": "Latino"} and pend == {} and ch == ["p1", "p3"], (g, pend, ch)
g, pend, ch = G.follow_rekordbox({"p1": "Techno"}, {}, {"p1"}, {"p1": ["Techno"]})
assert g == {"p1": "Techno"} and pend == {"p1": ["Techno"]} and ch == [], (g, pend, ch)
print("seguir a Rekordbox ok")


# ------------------------------------------------ Rekordbox (base falsa)
class Content:
    def __init__(self, i, path):
        self.ID, self.FolderPath = i, path


class Song:
    def __init__(self, c, n):
        self.Content, self.ContentID, self.TrackNo = c, c.ID, n


class PL:
    def __init__(self, i, name, parent, attr=0):
        self.ID, self.Name, self.ParentID, self.Attribute, self.Songs = i, name, parent, attr, []


class Q(list):
    def first(self):
        return self[0] if self else None


ST = {}


class FakeDB:
    def __init__(self, *a, **k):
        self.pls = ST["pls"]

    def get_playlist(self, ID=None, ParentID=None, Name=None):
        if ID is not None:
            return next((p for p in self.pls if str(p.ID) == str(ID)), None)
        if ParentID is None and Name is None:
            return Q(self.pls)
        return Q([p for p in self.pls if p.ParentID == ParentID and (Name is None or p.Name == Name)])

    def create_playlist_folder(self, name, parent=None):
        ST["n"] += 1
        p = PL(f"F{ST['n']}", name, parent.ID if parent is not None else "root", 1)
        self.pls.append(p)
        return p

    def create_playlist(self, name, parent=None):
        ST["n"] += 1
        p = PL(str(ST["n"]), name, parent.ID)
        self.pls.append(p)
        return p

    def move_playlist(self, pl, parent=None):
        pl.ParentID = parent.ID

    def delete_playlist(self, pl):
        self.pls.remove(pl)

    def get_artist(self, Name=None):
        return Q([])

    def add_artist(self, name):
        return type("A", (), {"ID": 1})()

    def add_content(self, path, **k):
        return Content(path, path)

    def add_to_playlist(self, pl, c):
        pl.Songs.append(Song(c, len(pl.Songs) + 1))

    def remove_from_playlist(self, pl, s):
        pl.Songs.remove(s)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


import pyrekordbox  # noqa: E402
pyrekordbox.MasterDatabase = FakeDB
RS.backup = lambda: Path("/tmp/x.db")
RUNNING = [False]
RS.rekordbox_running = lambda: RUNNING[0]
RS.content_by_path = lambda db, p: Content(p, p)

root = PL("1", "BrainOrder", "root", 1)
old = PL("2", "Viejo", "1", 1)          # subcarpeta que se queda vacía
tech = PL("3", "techno", "1", 1)        # ya existe con otra mayúscula: se usa esa
mine = PL("4", "Mías", "1", 1)          # tiene otra cosa adentro: no se toca
ST.update(n=100, pls=[root, old, tech, mine, PL("10", "Acid", "2"), PL("11", "Salsa", "1"),
                      PL("12", "Hard", "3"), PL("13", "Otra", "4"), PL("14", "Fuera", "root")])
cfg = {"rekordbox_folder": "BrainOrder"}
r = RS.place(cfg, [{"ref": "10", "trail": ["Techno"]}, {"ref": "11", "trail": ["Latino", "Salsa"]},
                   {"ref": "12", "trail": []}, {"ref": "14", "trail": ["X"]}, {"ref": "99", "trail": ["X"]}])
by = {p.ID: p for p in ST["pls"]}
assert by["10"].ParentID == "3" and by["12"].ParentID == "1", [(p.ID, p.Name, p.ParentID) for p in ST["pls"]]
lat = next(p for p in ST["pls"] if p.Name == "Latino" and p.ParentID == "1" and p.Attribute == 1)
sal = next(p for p in ST["pls"] if p.Name == "Salsa" and p.Attribute == 1)
assert sal.ParentID == lat.ID and by["11"].ParentID == sal.ID
assert "2" not in by and "4" in by and by["14"].ParentID == "root"  # vacía fuera; la tuya se queda; la de afuera no se toca
assert (r["moved"], r["folders_removed"], r["missing"]) == (3, 1, 2) and len(r["done"]) == 5, r
RUNNING[0] = True
try:
    RS.place(cfg, [{"ref": "10", "trail": []}])
    raise SystemExit("debía pedir cerrar Rekordbox")
except RS.RekordboxError:
    pass
RUNNING[0] = False
print("Rekordbox: mover a carpetas ok")

# Organizar: la nueva nace en la carpeta de su grupo y una pendiente se muda
ST.update(n=200, pls=[PL("1", "BrainOrder", "root", 1), PL("20", "House", "1")])
an = [{"id": "spN", "name": "Nueva", "tracks": [{"status": "ok", "source": "/m/a.mp3", "name": "a", "artists": []}]},
      {"id": "spH", "name": "House", "tracks": []}]
st = RS.sync(an, {"rekordbox_folder": "BrainOrder", "rb_master": True, "_rb_base": {"20": {"pid": "spH", "paths": []}},
                  "_rb_place": {"spN": ["Bodas"], "spH": ["Deep"]}})
nueva = next(p for p in ST["pls"] if p.Name == "Nueva")
bodas = next(p for p in ST["pls"] if p.Name == "Bodas")
deep = next(p for p in ST["pls"] if p.Name == "Deep")
assert nueva.ParentID == bodas.ID and bodas.ParentID == "1" and ST["pls"][1].ParentID == deep.ID, \
    [(p.ID, p.Name, p.ParentID) for p in ST["pls"]]
assert st.get("placed") == 1, st
print("Organizar en la carpeta del grupo ok")

# ------------------------------------------------ BrainOrder: cambiar grupos deja pendiente la mudanza
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, "set_pl_group")][0]
o = A.__new__(A)
o._cfg = {"pl_groups": {"p1": "Techno"}, "rb_tree": {"p9": ["Brainwasher"]}}
assert o.set_pl_group(["p2"], "techno")["moved"] == 0 and "grp_moves" not in o._cfg  # solo visual: nada pendiente
o._cfg["groups_folders"] = True
r = o.set_pl_group(["p3"], "House / Deep")
assert r["folders"] and r["moved"] == 1 and o._cfg["grp_moves"] == {"p3": ["House", "Deep"]}, o._cfg
r = o.rename_pl_group("Techno", "Hard Techno")
assert r["moved"] == 2 and o._cfg["grp_moves"]["p1"] == ["Hard Techno"] and o._cfg["grp_moves"]["p2"] == ["Hard Techno"]
o.set_pl_group(["p3"], "")
assert o._cfg["grp_moves"]["p3"] == []
tr = o._tree()
assert tr == {"p9": ["Brainwasher"], "p1": ["Hard Techno"], "p2": ["Hard Techno"]}, tr
# lo que Organizar debe ubicar: las pendientes y las que aún no están en Rekordbox
rb_cambios.save_baseline({"7": {"pid": "p1", "name": "x", "paths": []}})
pm = o._rb_place_map()
assert pm == {"p1": ["Hard Techno"], "p2": ["Hard Techno"], "p3": []}, pm
print("pendientes ok")

# ------------------------------------------------ disco: la playlist se muda a <carpeta>/<grupo>/<playlist>
music = TMP / "Music" / "Spotify playlists"
(music / "Acid").mkdir(parents=True)
(music / "Acid" / "uno.mp3").write_bytes(b"x")
o2 = A.__new__(A)
o2._cfg = {"dest_root": str(music), "groups_folders": True, "pl_groups": {"spA": "Techno"}, "rb_mirror": True}
analysis = [{"id": "spA", "name": "Acid", "folder": str(music / "Acid"), "tracks": [
    {"source": str(music / "Acid" / "uno.mp3"), "dest_dir": str(music / "Techno" / "Acid"), "status": "elsewhere"}]}]
loaded = o2._mirror_folders([{"id": "spA", "name": "Acid"}])
assert loaded[0]["folder"] == str(music / "Techno" / "Acid"), loaded
moves, _ = o2._mirror_plan([{**analysis[0], "folder": str(music / "Techno" / "Acid")}])
assert len(moves) == 1 and moves[0]["to"] == str(music / "Techno" / "Acid") and moves[0]["files"] == [str(music / "Acid" / "uno.mp3")], moves
o2._cfg["groups_folders"] = False
o2._cfg["rb_mirror"] = False
assert o2._mirror_folders([{"id": "spA", "name": "Acid"}]) == [{"id": "spA", "name": "Acid"}]  # solo visual: no se muda
print("disco ok")
print("OK")

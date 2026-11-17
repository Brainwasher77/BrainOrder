"""La cola de Spotify suma (no reemplaza) varias quitadas o agregadas a la misma playlist mientras espera."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
import cola_spotify as Q
Q.FILE = Path(tempfile.mkdtemp()) / "cola.json"
Q.add({"kind": "remove", "pid": "p", "name": "X", "uris": ["a", "b"]})
Q.add({"kind": "remove", "pid": "p", "name": "X", "uris": ["b", "c"], "local": [{"uri": "l", "nth": 0}]})
Q.add({"kind": "remove", "pid": "q", "name": "X", "uris": ["z"]})
j = [x for x in Q.load() if x["pid"] == "p"]
assert len(j) == 1 and j[0]["uris"] == ["a", "b", "c"] and j[0]["local"] == [{"uri": "l", "nth": 0}], Q.load()
assert len(Q.load()) == 2
Q.add({"kind": "add", "pid": "p", "name": "X", "path": "/c", "files": ["1"]})
Q.add({"kind": "add", "pid": "p", "name": "X", "path": "/c", "files": ["2"]})
assert [x["files"] for x in Q.load() if x["kind"] == "add"] == [["1", "2"]]
Q.add({"kind": "reorder", "pid": "p", "name": "X", "ids": [1]})
Q.add({"kind": "reorder", "pid": "p", "name": "X", "ids": [2]})
Q.add({"kind": "reorder", "pid": "q", "name": "X", "ids": [3]})  # mismo nombre, otra playlist: no se pisa
assert sorted(x["ids"][0] for x in Q.load() if x["kind"] == "reorder") == [2, 3]
assert {x["kind"]: x["count"] for x in Q.summary()}["remove"] in (4, 1)
print("OK")

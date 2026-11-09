import sys, os, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app, config, plataforma
from pathlib import Path
config.save = lambda c: None
A = [v for v in vars(app).values() if isinstance(v, type) and hasattr(v, 'playlist_common')][0]
root = Path(tempfile.mkdtemp())
fa, fb = root/'A', root/'B'; fa.mkdir(); fb.mkdir()
def mk(p, data=b'x'*1000): p.write_bytes(data); return str(p)
s1 = mk(fa/'uno.mp3')                 # solo en carpeta A -> va a B
s2 = mk(fa/'dos.mp3', b'y'*1000)      # B tiene copia idéntica -> _duplicados
k2 = mk(fb/'dos.mp3.copy.mp3', b'y'*1000)
s3 = mk(fb/'tres.mp3', b'z'*1000)     # ya en B (mismo archivo) -> no se mueve
SP = lambda c: c*22
LA = {"id":"pa","name":"A","folder":str(fa),"tracks":[
  {"pos":1,"id":SP('a'),"name":"uno","source":s1},{"pos":2,"id":SP('b'),"name":"dos","source":s2},
  {"pos":3,"id":SP('c'),"name":"tres","source":s3},{"pos":4,"id":SP('d'),"name":"solo A","source":None}]}
LB = {"id":"pb","name":"B","folder":str(fb),"tracks":[
  {"pos":1,"id":SP('a'),"name":"uno","source":s1},{"pos":2,"id":SP('b'),"name":"dos","source":k2},{"pos":3,"id":SP('c'),"name":"tres","source":s3}]}
o = A.__new__(A); o._cfg = {"dest_root": str(root)}
o._analysis = lambda: [LA, LB]
o._pl_ctx = lambda pid, an=None: ((LA,'spotify',None,None) if pid=='pa' else (LB,'spotify',None,None))
o._is_foreign = lambda pid: False
o._spotify_ready = o._dj_closed = lambda *a: None
o._set_stage = lambda *a: None
o._task = lambda fn, k, l, files=False: fn()
o._update_sp = lambda f: None
o._build_analysis = lambda light=True: [LA, LB]
jobs = []
o._spotify_do = lambda j: (jobs.append(j), {"state":"ok"})[1]
got = {}
def reloc(ops, label, extra=None):
    ch = {a: str(Path(d)/Path(a).name) for a, d in ops}
    got.update(ops=ops, extra=extra(ch) if extra else None); return {"moved": len(ops), "changes": ch}
o._relocate_ops = reloc
r = o.playlist_common('pb', 'pa', [[1,1],[2,2],[3,3]])
print(r['result'])
for a, d in got['ops']: print(Path(a).name, '->', Path(d).relative_to(root))
print('dup_of:', {Path(k).name: Path(v).name for k, v in got['extra']['dup_of'].items()})
print('spotify:', jobs[0]['kind'], len(jobs[0]['uris']))
assert len(jobs[0]['uris'])==3 and len(got['ops'])==2
shutil.rmtree(root)
print("OK")

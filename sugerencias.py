"""Sugerencias para organizar tu biblioteca en playlists: por género, por energía, por BPM o combinados.

Todo se ajusta por usuario (cfg["suggest_rules"]):
- Grupos de géneros: nombre de la playlist + palabras que lo reconocen en la etiqueta «género» del archivo
  («Reggaetón» ← reggaeton, reguetón, urbano, dembow…). Gana la palabra más específica (la más larga): «tech house»
  le gana a «house»; si empatan, el grupo que está más arriba. Los géneros que no entran en ningún grupo pueden ir cada uno a su
  propia playlist o a «Otros».
- Rangos de energía (la de Mixed In Key, 1 a 10) y de BPM, con el nombre que quieras para cada rango.
- Cómo se llaman las playlists combinadas: «{genero} · {energia}», con prefijo opcional.
- Mínimo de canciones para sugerir una playlist.
"""
import copy
import re
import unicodedata
from collections import Counter, defaultdict

MODES = {
    "genero": "Género",
    "energia": "Energía",
    "bpm": "BPM",
    "genero_energia": "Género + energía",
    "genero_bpm": "Género + BPM",
}

DEFAULT_GENRES = [
    {"name": "Tech House", "match": ["tech house"]},
    {"name": "Afro House", "match": ["afro house", "amapiano"]},
    {"name": "Deep House", "match": ["deep house"]},
    {"name": "Techno", "match": ["techno"]},
    {"name": "Trance", "match": ["trance", "psytrance"]},
    {"name": "Guaracha", "match": ["guaracha", "aleteo", "zapateo"]},
    {"name": "Electrónica", "match": ["electro", "electronic", "electronica", "house", "edm", "dance", "dancefloor", "techno"]},
    {"name": "Reggaetón", "match": ["reggaeton", "regueton", "reguetón", "reggaetón", "urbano", "dembow", "perreo", "trap latino",
                                    "latin urban", "moombahton"]},
    {"name": "Salsa Choque", "match": ["choque", "choke"]},
    {"name": "Salsa", "match": ["salsa", "son cubano", "timba"]},
    {"name": "Vallenato", "match": ["vallenato"]},
    {"name": "Champeta", "match": ["champeta"]},
    {"name": "Cumbia", "match": ["cumbia"]},
    {"name": "Merengue", "match": ["merengue"]},
    {"name": "Bachata", "match": ["bachata"]},
    {"name": "Tropipop", "match": ["tropipop"]},
    {"name": "Tropical", "match": ["tropical", "colombiana", "colombia", "porro", "papayera"]},
    {"name": "Decembrinas", "match": ["decembrina", "navidad", "christmas"]},
    {"name": "Regional mexicano", "match": ["ranchera", "norteña", "norteno", "corrido", "banda", "mariachi", "mexicana",
                                            "regional mexican", "grupera", "sierreño", "sierreno"]},
    {"name": "Reggae y Dancehall", "match": ["reggae", "dancehall", "dance hall"]},
    {"name": "Hip Hop y Rap", "match": ["rap", "hip hop", "hip-hop", "trap"]},
    {"name": "R&B y Soul", "match": ["r&b", "rnb", "soul", "funk"]},
    {"name": "Rock", "match": ["rock", "alternativo", "alternative", "metal", "punk", "indie", "grunge"]},
    {"name": "Pop latino", "match": ["pop latino", "latin pop", "pop en español"]},
    {"name": "Pop", "match": ["pop", "ballad", "balada"]},
    {"name": "Latino", "match": ["latino", "latin"]},
    {"name": "Disco", "match": ["disco"]},
    {"name": "Jazz y Blues", "match": ["jazz", "blues", "swing"]},
    {"name": "Clásica", "match": ["clasica", "clásica", "classical"]},
    {"name": "Bandas sonoras", "match": ["peliculas", "películas", "soundtrack", "juegos", "banda sonora"]},
]

DEFAULTS = {
    "mode": "genero",
    "scope": "todo",              # «todo» o «sin_playlist»
    "min_songs": 15,
    "genres": DEFAULT_GENRES,
    "others": "propia",           # géneros sin grupo: «propia» (cada uno su playlist), «otros» o «nada»
    "others_name": "Otros géneros",
    "energy": [
        {"name": "Calentando", "min": 1, "max": 4},
        {"name": "Arriba", "min": 5, "max": 6},
        {"name": "Pico", "min": 7, "max": 8},
        {"name": "Al máximo", "min": 9, "max": 10},
    ],
    "bpm": [
        {"name": "Lentas", "min": 0, "max": 95},
        {"name": "Medias", "min": 96, "max": 115},
        {"name": "Bailables", "min": 116, "max": 125},
        {"name": "Rápidas", "min": 126, "max": 300},
    ],
    "name_tpl": "{genero} · {energia}",
    "name_tpl_bpm": "{genero} · {bpm}",
    "prefix": "",
}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def get(cfg):
    r = copy.deepcopy(DEFAULTS)
    saved = cfg.get("suggest_rules") or {}
    r.update({k: v for k, v in saved.items() if k in DEFAULTS})
    return r


def clean(rules):
    """Valida lo que llega de la pantalla. -> (reglas, errores)"""
    r, errs = copy.deepcopy(DEFAULTS), []
    rules = rules or {}
    if rules.get("mode") in MODES:
        r["mode"] = rules["mode"]
    if rules.get("scope") in ("todo", "sin_playlist"):
        r["scope"] = rules["scope"]
    if rules.get("others") in ("propia", "otros", "nada"):
        r["others"] = rules["others"]
    try:
        r["min_songs"] = max(1, min(1000, int(rules.get("min_songs", r["min_songs"]))))
    except (TypeError, ValueError):
        errs.append("El mínimo de canciones no es un número.")
    r["others_name"] = (str(rules.get("others_name") or r["others_name"]).strip() or DEFAULTS["others_name"])[:80]
    if "genres" in rules:
        gs, seen = [], set()
        for g in rules.get("genres") or []:
            name = re.sub(r"\s+", " ", str(g.get("name") or "")).strip()[:80]
            words = [w for w in (re.sub(r"\s+", " ", str(x)).strip().lower() for x in (g.get("match") or [])) if w]
            nots = [w for w in (re.sub(r"\s+", " ", str(x)).strip().lower() for x in (g.get("not") or [])) if w]
            if not name and not words:
                continue
            if not name:
                errs.append("Hay un grupo de géneros sin nombre.")
                continue
            if not words:
                errs.append(f"El grupo «{name}» no tiene palabras para reconocerlo.")
                continue
            if name.lower() in seen:
                errs.append(f"Hay dos grupos que se llaman «{name}».")
                continue
            seen.add(name.lower())
            gs.append({"name": name, "match": list(dict.fromkeys(words)), **({"not": nots} if nots else {})})
        r["genres"] = gs
    for key, lo, hi in (("energy", 1, 10), ("bpm", 0, 300)):
        if key not in rules:
            continue
        rs = []
        for x in rules.get(key) or []:
            name = re.sub(r"\s+", " ", str(x.get("name") or "")).strip()[:60]
            try:
                a, b = float(x.get("min")), float(x.get("max"))
            except (TypeError, ValueError):
                errs.append(f"«{name or '?'}»: el rango no es un número.")
                continue
            if not name:
                errs.append("Hay un rango sin nombre.")
                continue
            a, b = max(lo, min(hi, a)), max(lo, min(hi, b))
            if a > b:
                a, b = b, a
            rs.append({"name": name, "min": a, "max": b})
        rs.sort(key=lambda x: x["min"])
        for i in range(1, len(rs)):
            if rs[i]["min"] <= rs[i - 1]["max"]:
                errs.append(f"Los rangos «{rs[i - 1]['name']}» y «{rs[i]['name']}» se cruzan.")
        r[key] = rs
    for k in ("name_tpl", "name_tpl_bpm"):
        if k in rules:
            t = re.sub(r"\s+", " ", str(rules.get(k) or "")).strip()[:120]
            r[k] = t or DEFAULTS[k]
    r["prefix"] = str(rules.get("prefix") or "")[:30]
    return r, errs


# ---------------------------------------------------------------- clasificar
def _has(text, word):
    w = norm(word)
    if not w:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text) is not None


def genre_group(genre, rules):
    """Etiqueta de género del archivo -> nombre del grupo (o None)."""
    g = norm(genre)
    if not g:
        return None
    # gana la palabra más larga que coincide (la más específica: «tech house» le gana a «house»); si empatan,
    # el grupo que está más arriba
    best, best_len = None, 0
    for grp in rules["genres"]:
        if any(_has(g, w) for w in grp.get("not") or []):
            continue
        for w in grp["match"]:
            n = len(norm(w))
            if n > best_len and _has(g, w):
                best, best_len = grp["name"], n
    if best:
        return best
    if rules["others"] == "propia":
        return " ".join(w[:1].upper() + w[1:] for w in str(genre).strip().split())[:80]
    if rules["others"] == "otros":
        return rules["others_name"]
    return None


def _bucket(v, ranges):
    if v is None:
        return None
    for r in ranges:
        if r["min"] <= v <= r["max"]:
            return r["name"]
    return None


def classify(song, rules, mode=None):
    """song: {path, genre, energy, bpm} -> nombre de la playlist sugerida (o None)."""
    mode = mode or rules["mode"]
    g = genre_group(song.get("genre"), rules) if "genero" in mode else None
    e = _bucket(song.get("energy"), rules["energy"]) if "energia" in mode else None
    b = _bucket(song.get("bpm"), rules["bpm"]) if "bpm" in mode else None
    if mode == "genero":
        name = g
    elif mode == "energia":
        name = e
    elif mode == "bpm":
        name = b
    elif mode == "genero_energia":
        name = rules["name_tpl"].replace("{genero}", g).replace("{energia}", e).replace("{bpm}", b or "") if g and e else None
    else:
        name = rules["name_tpl_bpm"].replace("{genero}", g).replace("{bpm}", b).replace("{energia}", e or "") if g and b else None
    if not name:
        return None
    name = re.sub(r"\s+", " ", (rules.get("prefix") or "") + name).strip()
    return name[:100]


def suggest(songs, rules, playlists=()):
    """songs: [{path, artist, title, genre, energy, bpm}]. playlists: [{id, name, paths:set}] que ya tienes.
    -> {suggestions: [...], stats: {...}, genres: [{genre, count, group}]}"""
    groups = defaultdict(list)
    no_data = 0
    for s in songs:
        name = classify(s, rules)
        if name:
            groups[name].append(s)
        else:
            no_data += 1
    by_name = {norm(p["name"]): p for p in playlists}
    out = []
    for name, items in groups.items():
        if len(items) < rules["min_songs"]:
            continue
        paths = [x["path"] for x in items]
        have = by_name.get(norm(name))
        missing = [p for p in paths if not have or p not in have["paths"]]
        if have and not missing:
            continue  # ya la tienes completa
        arts = Counter(a for x in items for a in [x.get("artist") or ""] if a)
        en = [x["energy"] for x in items if x.get("energy")]
        bp = [x["bpm"] for x in items if x.get("bpm")]
        out.append({
            "name": name, "count": len(items), "paths": paths, "missing": missing,
            "exists": {"id": have["id"], "name": have["name"]} if have else None,
            "artists": [a for a, _ in arts.most_common(4)],
            "energy": round(sum(en) / len(en), 1) if en else None,
            "bpm": [round(min(bp)), round(max(bp))] if bp else None,
            "songs": [{"path": x["path"], "artist": x.get("artist") or "", "title": x.get("title") or "",
                       "energy": x.get("energy"), "bpm": x.get("bpm"), "genre": x.get("genre") or ""} for x in items],
        })
    out.sort(key=lambda x: (-x["count"], x["name"].lower()))
    gc = Counter(s.get("genre") or "" for s in songs)
    genres = [{"genre": g, "count": n, "group": genre_group(g, rules)} for g, n in gc.most_common() if g]
    stats = {
        "songs": len(songs),
        "genre": sum(1 for s in songs if s.get("genre")),
        "energy": sum(1 for s in songs if s.get("energy")),
        "bpm": sum(1 for s in songs if s.get("bpm")),
        "unclassified": no_data,
        "small": sum(1 for n, it in groups.items() if len(it) < rules["min_songs"]),
    }
    return {"suggestions": out, "stats": stats, "genres": genres}

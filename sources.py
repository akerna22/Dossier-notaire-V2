"""Accès aux API publiques de l'État (BAN, API Carto IGN, GPU, Géorisques, geo.api, DVF)."""
import csv, io, json, math, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import requests

UA = {"User-Agent": "dossier-parcellaire/1.0 (outil interne d'etude)"}
TIMEOUT = 30
BAN = "https://api-adresse.data.gouv.fr/search/"
GEO = "https://geo.api.gouv.fr/communes/"
CARTO = "https://apicarto.ign.fr/api/"
GEORISQUES = "https://georisques.gouv.fr/api/v1/"
DVF = "https://files.data.gouv.fr/geo-dvf/latest/csv/{year}/communes/{dep}/{insee}.csv"
NATURE = ["natura-habitat", "natura-oiseaux", "znieff1", "znieff2", "pnr", "pn", "rnn", "rnr"]


def _get(url, **params):
    r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def suggest(q, limit=6):
    """Recherche / normalisation d'adresse via la Base Adresse Nationale."""
    feats = _get(BAN, q=q, limit=limit).json().get("features", [])
    out = []
    for f in feats:
        p, (lon, lat) = f["properties"], f["geometry"]["coordinates"]
        out.append(dict(label=p.get("label"), lon=lon, lat=lat, citycode=p.get("citycode"),
                        postcode=p.get("postcode"), city=p.get("city"), context=p.get("context"),
                        type=p.get("type")))
    return out


def point(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


def square(lon, lat, half_m):
    dy = half_m / 111320
    dx = half_m / (111320 * math.cos(math.radians(lat)))
    return {"type": "Polygon", "coordinates": [[[lon-dx, lat-dy], [lon+dx, lat-dy], [lon+dx, lat+dy],
                                                [lon-dx, lat+dy], [lon-dx, lat-dy]]]}


def carto(path, geom):
    r = _get(CARTO + path, geom=json.dumps(geom), _limit=200)
    return r.json().get("features", [])


def gr(path, **params):
    j = _get(GEORISQUES + path, **params).json()
    return j.get("data", j) if isinstance(j, dict) else j


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371000 * 2 * math.asin(math.sqrt(a))


import re, statistics, functools

WFS = "https://data.geopf.fr/wfs/ows"
KEEP = ("id_mutation", "date_mutation", "nature_mutation", "valeur_fonciere", "adresse_numero", "adresse_nom_voie",
        "id_parcelle", "type_local", "surface_reelle_bati", "nombre_pieces_principales", "nature_culture",
        "surface_terrain", "longitude", "latitude")


def _rings(g):
    if not g:
        return
    if g["type"] == "Polygon":
        yield g["coordinates"][0]
    elif g["type"] == "MultiPolygon":
        for p in g["coordinates"]:
            yield p[0]


def _simplify(r, n=24):
    s = r[:-1][::max(1, len(r) // n)]
    return s + [s[0]]


def sel_geom(sel):
    polys = [[_simplify(r)] for f in sel for r in _rings(f["geometry"])]
    if len(polys) == 1:
        return {"type": "Polygon", "coordinates": polys[0]}
    return {"type": "MultiPolygon", "coordinates": polys}


def sel_center(sel):
    pts = [c[:2] for f in sel for r in _rings(f["geometry"]) for c in r]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    lon, lat = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    half = max(haversine(lat, min(xs), lat, max(xs)), haversine(min(ys), lon, max(ys), lon)) / 2
    return lon, lat, half


def _first(a):
    return _first(a[0]) if isinstance(a[0], list) else a


def _lines(g):
    t, c = g["type"], g["coordinates"]
    return [c] if t == "LineString" else c if t in ("MultiLineString", "Polygon") else \
        [r for p in c for r in p] if t == "MultiPolygon" else []


def coast_distance(lon, lat, rad=3000):
    """Distance à la limite terre-mer (IGN BD TOPO, WFS Géoplateforme). Ordre des axes testé dans les 2 sens."""
    kx, ky, ok = math.cos(math.radians(lat)) * 111320, 111320, False
    for sw in (0, 1):
        pt = f"POINT({lat} {lon})" if sw else f"POINT({lon} {lat})"
        try:
            j = _get(WFS, SERVICE="WFS", VERSION="2.0.0", REQUEST="GetFeature", TYPENAMES="BDTOPO_V3:limite_terre_mer",
                     OUTPUTFORMAT="application/json", SRSNAME="EPSG:4326", COUNT=60,
                     CQL_FILTER=f"DWITHIN(geometrie,{pt},{rad},meters)").json()
        except Exception:
            continue
        ok, F = True, j.get("features", [])
        if not F:
            continue
        c = _first(F[0]["geometry"]["coordinates"])
        swap = abs(c[0] - lat) + abs(c[1] - lon) < abs(c[0] - lon) + abs(c[1] - lat)
        best = 1e12
        for f in F:
            for ln in _lines(f["geometry"]):
                P = [((p[1], p[0]) if swap else (p[0], p[1])) for p in ln]
                for (x1, y1), (x2, y2) in zip(P, P[1:]):
                    ax, ay, bx, by = (x1 - lon) * kx, (y1 - lat) * ky, (x2 - lon) * kx, (y2 - lat) * ky
                    dx, dy = bx - ax, by - ay
                    t = max(0, min(1, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) or 1)))
                    best = min(best, math.hypot(ax + t * dx, ay + t * dy))
        return {"dist": round(best), "n": len(F)}
    if not ok:
        raise RuntimeError("Service IGN (limite terre-mer) indisponible")
    return {"dist": None, "n": 0}


@functools.lru_cache(maxsize=4)
def dvf_rows(insee, year):
    dep = insee[:3] if insee.startswith("97") else insee[:2]
    try:
        txt = _get(DVF.format(year=year, dep=dep, insee=insee)).content.decode("utf-8")
    except requests.HTTPError:
        return ()
    return tuple({k: row.get(k, "") or "" for k in KEEP} for row in csv.DictReader(io.StringIO(txt)))


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def estimate(insee, lon, lat, typ="Maison", surface=0, radius=500, months=24, adj=None):
    """Prix au m² à partir des ventes DVF du même type de bien sur `months` mois, dans `radius` mètres."""
    today = dt.date.today()
    since = (today - dt.timedelta(days=round(months * 30.44))).isoformat()
    muts = {}
    for y in range(int(since[:4]), today.year + 1):
        for r in dvf_rows(insee, y):
            if r["date_mutation"] >= since and r["nature_mutation"] == "Vente":
                muts.setdefault(r["id_mutation"], []).append(r)
    comps = []
    for rows in muts.values():
        val = _f(rows[0]["valeur_fonciere"])
        if val <= 0:
            continue
        locs = [r for r in rows if r["type_local"] not in ("", "Dépendance")]
        if typ == "Terrain":
            s = sum(_f(r["surface_terrain"]) for r in rows)
            if locs or s < 50 or not any("terrain" in r["nature_culture"].lower() for r in rows):
                continue
            r0 = rows[0]
        else:
            if len(locs) != 1 or locs[0]["type_local"] != typ:
                continue
            r0 = locs[0]
            s = _f(r0["surface_reelle_bati"])
            if s < 9:
                continue
        if not r0["longitude"] or not r0["latitude"]:
            continue
        d = haversine(lat, lon, float(r0["latitude"]), float(r0["longitude"]))
        pm2 = val / s
        if d > radius or (typ != "Terrain" and not 300 <= pm2 <= 30000):
            continue
        comps.append(dict(date=r0["date_mutation"], adresse=" ".join(x for x in (r0["adresse_numero"], r0["adresse_nom_voie"]) if x),
                          surface=round(s), valeur=round(val), pm2=round(pm2), dist=round(d), pieces=r0["nombre_pieces_principales"]))
    n_raw = len(comps)
    if len(comps) >= 4:  # écarte les valeurs aberrantes (règle 1,5 x écart interquartile)
        q1, _, q3 = statistics.quantiles([c["pm2"] for c in comps], n=4)
        comps = [c for c in comps if q1 - 1.5 * (q3 - q1) <= c["pm2"] <= q3 + 1.5 * (q3 - q1)]
    pm = [c["pm2"] for c in comps]
    adj = {k: _f(v) for k, v in (adj or {}).items()}
    out = dict(type=typ, radius=radius, months=months, n_raw=n_raw, n=len(pm), surface=surface, adj=adj)
    if pm:
        q = statistics.quantiles(pm, n=4) if len(pm) >= 4 else [min(pm), statistics.median(pm), max(pm)]
        out.update(median=round(statistics.median(pm)), mean=round(statistics.mean(pm)), q1=round(q[0]), q3=round(q[2]))
        if surface:
            k = 1 + sum(adj.values()) / 100
            out.update(coef=k, base=round(out["median"] * surface), estimate=round(out["median"] * surface * k),
                       low=round(q[0] * surface * k), high=round(q[2] * surface * k))
    out["comps"] = sorted(comps, key=lambda c: c["dist"])[:60]
    return out


def _safe(fn):
    try:
        return {"data": fn(), "error": None}
    except Exception as ex:  # une source en panne ne doit pas bloquer le dossier
        return {"data": None, "error": f"{type(ex).__name__}: {str(ex)[:200]}"}


def collect(place, sel=None, sections=None, est=None):
    """sel : parcelles (features GeoJSON) choisies sur la carte ; sections : None = tout, sinon ensemble de thèmes."""
    need = lambda *ss: sections is None or any(x in sections for x in ss)
    lon, lat, insee, half = place["lon"], place["lat"], place["citycode"], 0
    geom = None
    if sel:
        lon, lat, half = sel_center(sel)
        geom = sel_geom(sel)
    ll, pt, box = f"{lon},{lat}", point(lon, lat), square(lon, lat, 25)
    sg, lg = geom or pt, geom or box
    T = {"commune": lambda: _get(GEO + insee, fields="nom,code,codesPostaux,population,surface,departement,region,epci").json()}
    if need("cadastre", "urbanisme"):
        if not sel:
            T["parcelle"] = lambda: carto("cadastre/parcelle", pt)
        T["voisines"] = lambda: carto("cadastre/parcelle", square(lon, lat, max(70, half + 40)))
        T["zone_urba"] = lambda: carto("gpu/zone-urba", sg)
    if need("urbanisme"):
        T["document"] = lambda: carto("gpu/document", sg)
        for k in ("prescription-surf", "prescription-lin", "prescription-pct", "info-surf", "info-lin", "info-pct"):
            T["gpu:" + k] = lambda k=k: carto("gpu/" + k, sg if k.endswith("surf") else lg)
    if need("urbanisme", "littoral"):
        for k in ("assiette-sup-s", "assiette-sup-l", "assiette-sup-p"):
            T["sup:" + k] = lambda k=k: carto("gpu/" + k, sg if k.endswith("-s") else lg)
    if need("environnement", "littoral"):
        for k in NATURE:
            T["nat:" + k] = lambda k=k: carto("nature/" + k, sg)
    if need("littoral"):
        T["litt"] = lambda: coast_distance(lon, lat)
    if need("risques"):
        GR = {
            "rga": ("rga", {"latlon": ll}), "radon": ("radon", {"code_insee": insee}),
            "sismique": ("zonage_sismique", {"code_insee": insee}), "risques": ("gaspar/risques", {"code_insee": insee}),
            "azi": ("gaspar/azi", {"code_insee": insee}), "pprn": ("gaspar/pprn", {"code_insee": insee}),
            "catnat": ("gaspar/catnat", {"code_insee": insee, "page_size": 100}),
            "mvt": ("mvt", {"latlon": ll, "rayon": 500}), "cavites": ("cavites", {"latlon": ll, "rayon": 500}),
            "casias": ("ssp/casias", {"latlon": ll, "rayon": 500}), "sis": ("ssp/sis", {"latlon": ll, "rayon": 500}),
            "icpe": ("installations_classees", {"latlon": ll, "rayon": 1000}),
        }
        for k, (path, prm) in GR.items():
            T["gr:" + k] = lambda path=path, prm=prm: gr(path, **prm)
    if est and need("marche"):
        T["est"] = lambda: estimate(insee, lon, lat, est.get("type", "Maison"), _f(est.get("surface")),
                                    int(_f(est.get("radius")) or 500), 24, est.get("adj"))
    with ThreadPoolExecutor(8) as ex:
        futs = {k: ex.submit(_safe, fn) for k, fn in T.items()}
        D = {k: f.result() for k, f in futs.items()}
    if sel:
        D["parcelle"] = {"data": sel, "error": None}
    D["_center"], D["_half"] = (lon, lat), half
    D["_date"] = dt.datetime.now().strftime("%d/%m/%Y %H:%M")
    return D

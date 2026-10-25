"""Cartes : fond IGN (Géoplateforme WMS-R) + tracés vectoriels (parcelles, zonage PLU)."""
import io, math
import requests
from PIL import Image, ImageDraw, ImageFont

WMS = "https://data.geopf.fr/wms-r/wms"
ORTHO, PLAN = "ORTHOIMAGERY.ORTHOPHOTOS", "GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2"
R = 6378137.0


def merc(lon, lat):
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def font(sz):
    for n in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(n, sz)
        except OSError:
            pass
    return ImageFont.load_default(sz)


def base(layer, bbox, w, h):
    try:
        r = requests.get(WMS, params=dict(SERVICE="WMS", VERSION="1.3.0", REQUEST="GetMap", LAYERS=layer,
                                          STYLES="", CRS="EPSG:3857", BBOX=",".join(map(str, bbox)),
                                          WIDTH=w, HEIGHT=h, FORMAT="image/jpeg"), timeout=30)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB"), True
    except Exception:
        return Image.new("RGB", (w, h), (235, 235, 235)), False


def rings(g):
    if not g:
        return
    if g["type"] == "Polygon":
        yield g["coordinates"][0]
    elif g["type"] == "MultiPolygon":
        for p in g["coordinates"]:
            yield p[0]


def render(lon, lat, half_m, layer, parcels=(), target=None, zones=(), size=1000):  # target : ensemble d'IDU
    cx, cy = merc(lon, lat)
    hm = half_m / math.cos(math.radians(lat))
    bbox = (cx - hm, cy - hm, cx + hm, cy + hm)
    im, ok = base(layer, bbox, size, size)
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d, f = ImageDraw.Draw(ov), font(22)

    def px(lo, la):
        x, y = merc(lo, la)
        return (x - bbox[0]) / (2 * hm) * size, (bbox[3] - y) / (2 * hm) * size

    def label(pts, txt, col=(255, 255, 255, 255)):
        cx_, cy_ = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        d.text((cx_, cy_), txt, font=f, fill=col, anchor="mm", stroke_width=3, stroke_fill=(0, 0, 0, 255))

    for z in zones:
        for r in rings(z.get("geometry")):
            pts = [px(*c[:2]) for c in r]
            d.polygon(pts, fill=(0, 160, 230, 50))
            d.line(pts + [pts[0]], fill=(0, 210, 255, 255), width=3)
            label(pts, str(z["properties"].get("libelle") or z["properties"].get("typezone") or ""), (120, 230, 255, 255))
    for p in parcels:
        tgt = p["properties"].get("idu") in (target or ())
        for r in rings(p.get("geometry")):
            pts = [px(*c[:2]) for c in r]
            if tgt:
                d.polygon(pts, fill=(255, 0, 0, 80))
            d.line(pts + [pts[0]], fill=(255, 40, 40, 255) if tgt else (255, 225, 0, 255), width=4 if tgt else 2)
            label(pts, str(p["properties"].get("numero", "")).lstrip("0"))
    x, y = px(lon, lat)
    d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(255, 0, 255, 255), outline=(255, 255, 255, 255), width=3)
    # échelle
    L = min((10, 20, 50, 100, 200, 500, 1000), key=lambda v: abs(v - half_m * 0.4))
    bw = L / (2 * half_m) * size
    d.rectangle([20, size - 60, 40 + bw + 120, size - 15], fill=(255, 255, 255, 220))
    d.rectangle([30, size - 42, 30 + bw, size - 34], fill=(0, 0, 0, 255))
    d.text((40 + bw, size - 38), f"{L} m", font=font(20), fill=(0, 0, 0, 255), anchor="lm")
    return Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB"), ok


def make_all(place, D):
    lon, lat = D.get("_center") or (place["lon"], place["lat"])
    half = D.get("_half") or 0
    g = lambda k: (D.get(k) or {}).get("data") or []
    tgt = {p["properties"].get("idu") for p in g("parcelle")}
    only_t = [p for p in g("voisines") + g("parcelle") if p["properties"].get("idu") in tgt]
    return {
        "cadastre": render(lon, lat, max(70, half + 30), ORTHO, g("voisines") or g("parcelle"), tgt),
        "zonage": render(lon, lat, max(250, half * 2 + 60), ORTHO, only_t, tgt, g("zone_urba")),
        "situation": render(lon, lat, 1500, PLAN),
    }

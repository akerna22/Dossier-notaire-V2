import hmac, io, os, re
from flask import Flask, Response, jsonify, render_template, request, send_file
import maps, report, sources

app = Flask(__name__)
SECTIONS = {"cadastre", "urbanisme", "risques", "environnement", "littoral", "marche"}


@app.before_request
def protect():
    """Si APP_PASSWORD est défini (hébergement Render), demande un mot de passe (identifiant libre)."""
    pw = os.environ.get("APP_PASSWORD")
    if not pw:
        return None
    a = request.authorization
    if not a or not hmac.compare_digest(a.password or "", pw):
        return Response("Authentification requise", 401, {"WWW-Authenticate": 'Basic realm="Dossier parcellaire"'})


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/suggest")
def api_suggest():
    q = request.args.get("q", "").strip()
    try:
        return jsonify(sources.suggest(q) if len(q) >= 3 else [])
    except Exception as ex:
        return jsonify(error=str(ex)), 502


@app.post("/api/estimation")
def api_estimation():
    b = request.get_json(force=True)
    place, est = b["place"], b.get("est") or {}
    sel = b.get("features") or None
    lon, lat = (sources.sel_center(sel)[:2] if sel else (place["lon"], place["lat"]))
    try:
        return jsonify(sources.estimate(place["citycode"], lon, lat, est.get("type", "Maison"), sources._f(est.get("surface")),
                                        int(sources._f(est.get("radius")) or 500), 24, est.get("adj")))
    except Exception as ex:
        return jsonify(error=f"{type(ex).__name__}: {ex}"), 502


@app.post("/api/pdf")
def api_pdf():
    b = request.get_json(force=True)
    place, sec = b.get("place"), b.get("section", "global")
    if not place or not place.get("lon"):
        return jsonify(error="Choisissez d'abord une adresse."), 400
    if sec != "global" and sec not in SECTIONS:
        return jsonify(error="Section inconnue."), 400
    sections = None if sec == "global" else {sec}
    D = sources.collect(place, b.get("features") or None, sections, b.get("est"))
    imgs = maps.make_all(place, D) if sections is None or sections & {"cadastre", "urbanisme"} else {}
    pdf = report.build(place, D, imgs, sections)
    name = re.sub(r"[^A-Za-z0-9]+", "_", place["label"]).strip("_")
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=True, download_name=f"{sec}_{name}.pdf")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)

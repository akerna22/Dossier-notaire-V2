"""Usage en ligne de commande / GitHub Actions : ADRESSE="12 rue ... Lannion" python generate.py"""
import os, re, sys
import maps, report, sources

q = (os.environ.get("ADRESSE") or " ".join(sys.argv[1:])).strip()
if not q:
    sys.exit("Aucune adresse fournie.")
found = sources.suggest(q, 1)
if not found:
    sys.exit(f"Adresse introuvable : {q}")
place = found[0]
print("Adresse retenue :", place["label"])
D = sources.collect(place)
for k, v in D.items():
    if isinstance(v, dict) and v.get("error"):
        print("Source en erreur :", k, "->", v["error"])
pdf = report.build(place, D, maps.make_all(place, D))
os.makedirs("out", exist_ok=True)
path = "out/dossier_" + re.sub(r"[^A-Za-z0-9]+", "_", place["label"]).strip("_") + ".pdf"
open(path, "wb").write(pdf)
print("PDF généré :", path)

"""Génération du PDF (reportlab)."""
import io, json, re
from collections import Counter
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor("#1f3a5f")
ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Heading1"], textColor=NAVY, fontSize=15, spaceBefore=10, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY, fontSize=11, spaceBefore=8, spaceAfter=3)
B = ParagraphStyle("b", parent=ss["Normal"], fontSize=9.5, leading=13)
SM = ParagraphStyle("sm", parent=B, fontSize=8, textColor=colors.grey)
CELL = ParagraphStyle("c", parent=B, fontSize=8.5, leading=11)
CELLH = ParagraphStyle("ch", parent=CELL, textColor=colors.white, fontName="Helvetica-Bold")
WARN = ParagraphStyle("w", parent=B, textColor=colors.HexColor("#9a3412"), fontSize=8.5)
NAMES = ["nom_site", "nom", "libelle", "libelle_risque_long", "libelle_risque_jo", "nom_etablissement",
         "raison_sociale", "nom_usuel", "identifiant", "type", "code"]


def P(t, st=B):
    return Paragraph(escape(str(t)), st)


def tbl(rows, widths, head=True):
    data = [[c if isinstance(c, Paragraph) else Paragraph(escape(str(c if c is not None else "")),
             CELLH if head and i == 0 else CELL) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[w * cm for w in widths], repeatRows=1 if head else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b7c3")), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if head:
        st.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    else:
        st.append(("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f7")))
    t.setStyle(TableStyle(st))
    return t


def desc(d):
    if not isinstance(d, dict):
        return str(d)
    parts = [str(d[k]) for k in NAMES if d.get(k)][:3]
    for k in ("date_debut_evt", "date_maj", "date_approbation", "distance"):
        if d.get(k):
            parts.append(f"{k}: {d[k]}")
    return " — ".join(parts) or json.dumps(d, ensure_ascii=False)[:160]


def val(d, *keys):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return ""


def img(pair, cm_=12.5):
    if pair is None:
        return []
    im, ok = pair
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    buf.seek(0)
    items = [Image(buf, cm_ * cm, cm_ * cm)]
    if not ok:
        items.append(P("Fond de carte IGN indisponible : seuls les tracés vectoriels sont affichés.", WARN))
    return items


def build(place, D, imgs, sections=None):
    g = lambda k: (D.get(k) or {}).get("data")
    err = lambda k: (D.get(k) or {}).get("error")
    lst = lambda k: g(k) if isinstance(g(k), list) else ([g(k)] if g(k) else [])
    ch, synth = {}, []
    S = ch.setdefault("cover", [])

    def unavailable(*keys):
        e = [f"{k}: {err(k)}" for k in keys if err(k)]
        if e:
            S.append(P("Source(s) indisponible(s) lors de la génération — à vérifier manuellement. " + " | ".join(e), WARN))
        return bool(e)

    # --- couverture
    sub = "" if sections is None else "Extrait : " + ", ".join(sorted(sections))
    parc = g("parcelle") or []
    pp = parc[0]["properties"] if parc else {}
    refs = ", ".join(f"{p['properties'].get('section')} {p['properties'].get('numero')}" for p in parc[:10]) + (" …" if len(parc) > 10 else "")
    tot = sum(float(p["properties"].get("contenance") or 0) for p in parc)
    zones = g("zone_urba") or []
    zl = ", ".join(sorted({str(z["properties"].get("libelle", "")) for z in zones})) or "Non trouvé"
    S += [Spacer(1, 3 * cm), P("DOSSIER PARCELLAIRE ET URBANISTIQUE", ParagraphStyle("t", parent=H1, fontSize=22, leading=26)),
          P(sub, H2), Spacer(1, .5 * cm), P(place["label"], ParagraphStyle("a", parent=H1, fontSize=15)), Spacer(1, 1 * cm),
          tbl([["Référence(s) cadastrale(s)", refs or "Non trouvée"],
               ["Surface cadastrale (total)", f"{tot:.0f} m²" if tot else "Non disponible"],
               ["Zonage PLU / carte communale", zl], ["Édité le", D["_date"]]], [6, 10], head=False),
          Spacer(1, 1 * cm),
          P("Document de synthèse établi à partir de données publiques ouvertes (sources en dernière page). "
            "Il ne se substitue ni au certificat d'urbanisme, ni à l'état des risques et pollutions, ni à l'extrait "
            "cadastral officiel. Les données sont à vérifier avant tout usage juridique.", SM), PageBreak()]

    S = ch.setdefault("cadastre", [])
    # --- 1 identification
    c = g("commune") or {}
    S.append(P("1. Identification", H1))
    unavailable("commune")
    S.append(tbl([["Adresse normalisée (BAN)", place["label"]],
                  ["Coordonnées WGS84", f"{place['lat']:.6f} N ; {place['lon']:.6f} E"],
                  ["Commune / code INSEE", f"{c.get('nom', place.get('city'))} / {place['citycode']}"],
                  ["Code postal", place.get("postcode")],
                  ["Département / Région", f"{(c.get('departement') or {}).get('nom', '')} / {(c.get('region') or {}).get('nom', '')}"],
                  ["EPCI", (c.get("epci") or {}).get("nom", "")],
                  ["Population communale", c.get("population", "")],
                  ["Superficie communale", f"{c['surface'] / 100:.1f} km²" if c.get("surface") else ""]], [5.5, 11.5], head=False))

    # --- 2 cadastre
    S.append(P("2. Cadastre", H1))
    unavailable("parcelle", "voisines")
    if parc:
        S.append(tbl([["IDU", "Section", "N°", "Commune", "Contenance (m²)"]] + [[p["properties"].get("idu"), p["properties"].get("section"), p["properties"].get("numero"), p["properties"].get("nom_com"), p["properties"].get("contenance")] for p in parc[:40]] + [["Total", "", "", "", f"{tot:.0f}"]], [5.5, 2, 2, 4.5, 3]))
    elif not err("parcelle"):
        S.append(P("Aucune parcelle trouvée au point d'adresse (voie, adresse en limite ?). Parcelles voisines ci-dessous."))
    S += img(imgs.get("cadastre"))
    S.append(P("Rouge : parcelle de l'adresse — jaune : parcelles voisines — point violet : point d'adresse BAN.", SM))
    sel_ids = {p["properties"].get("idu") for p in parc}
    vs = [p["properties"] for p in (g("voisines") or []) if p["properties"].get("idu") not in sel_ids]
    if vs:
        S.append(P("Parcelles voisines", H2))
        S.append(tbl([["IDU", "Section", "N°", "Contenance (m²)"]] +
                     [[v.get("idu"), v.get("section"), v.get("numero"), v.get("contenance")] for v in vs[:30]], [6, 3, 3, 5]))
    synth.append(("Cadastre", f"{len(parc)} parcelle(s) : {refs} — {tot:.0f} m²" if parc else "Parcelle non identifiée", "OK" if pp else "À vérifier"))

    # --- 3 cartes
    S += [PageBreak(), P("3. Photographies et cartes", H1), P("Orthophotographie IGN, zonage d'urbanisme (cyan) et parcelle (rouge) — rayon 250 m", H2)]
    S += img(imgs.get("zonage"))
    S += [P("Carte de situation (Plan IGN) — rayon 1,5 km", H2)] + img(imgs.get("situation"))

    S = ch.setdefault("urbanisme", [])
    # --- 4 urbanisme
    S += [PageBreak(), P("4. Urbanisme (Géoportail de l'urbanisme)", H1)]
    unavailable("zone_urba", "document")
    docs = [d["properties"] for d in (g("document") or [])]
    for d in docs:
        S.append(tbl([["Document applicable", val(d, "name", "grid_title", "title")], ["Type", val(d, "du_type", "type")],
                      ["Statut / date", f"{val(d, 'status', 'etat')} {val(d, 'approval_date', 'datappro')}"],
                      ["Référence GPU", val(d, "id", "partition")]], [5.5, 11.5], head=False))
    if zones:
        S.append(P("Zonage de la parcelle", H2))
        S.append(tbl([["Zone", "Type", "Libellé long", "Document / règlement écrit", "Approbation"]] +
                     [[z["properties"].get("libelle"), z["properties"].get("typezone"), z["properties"].get("libelong"),
                       val(z["properties"], "urlfic") or val(z["properties"], "nomfic"), val(z["properties"], "datappro", "datvalid")]
                      for z in zones], [1.8, 1.6, 5, 6, 2.6]))
    elif not err("zone_urba"):
        S.append(P("Aucune zone d'urbanisme numérisée au GPU à cet endroit (RNU, carte communale non numérisée ou document absent). "
                   "À confirmer auprès de la mairie."))
    for k, t in (("prescription", "Prescriptions"), ("info", "Informations d'urbanisme")):
        rows = []
        for sfx in ("surf", "lin", "pct"):
            for f in g(f"gpu:{k}-{sfx}") or []:
                p = f["properties"]
                rows.append([val(p, "libelle"), val(p, "typepsc", "typeinf"), str(val(p, "txt"))[:300]])
        unavailable(*[f"gpu:{k}-{s}" for s in ("surf", "lin", "pct")])
        if rows:
            S.append(P(t, H2))
            S.append(tbl([["Libellé", "Type", "Texte"]] + rows, [6, 2.5, 8.5]))
    S.append(P("Le règlement écrit complet, les OAP et les pièces graphiques sont à télécharger sur geoportail-urbanisme.gouv.fr.", SM))
    synth.append(("Zonage d'urbanisme", zl, "À vérifier" if not zones else "OK"))

    # --- 5 servitudes
    S.append(P("5. Servitudes d'utilité publique", H1))
    unavailable("sup:assiette-sup-s", "sup:assiette-sup-l", "sup:assiette-sup-p")
    rows = [[val(f["properties"], "nomsuplitt", "nomass", "libelle", "nom"), val(f["properties"], "categorie", "typeass", "suptype"),
             val(f["properties"], "nomass", "idass")] for s in ("s", "l", "p") for f in g(f"sup:assiette-sup-{s}") or []]
    S.append(tbl([["Servitude", "Catégorie", "Assiette"]] + rows, [8, 3, 6]) if rows else P("Aucune servitude publiée au GPU à proximité immédiate."))
    synth.append(("Servitudes d'utilité publique", f"{len(rows)} trouvée(s)" if rows else "Aucune publiée", "À vérifier" if rows else "Néant"))

    S = ch.setdefault("risques", [])
    # --- 6 géorisques
    S += [PageBreak(), P("6. Risques (Géorisques)", H1)]
    risk_rows = []
    rga = lst("gr:rga")
    expo = val(rga[0], "exposition", "alea", "codeExposition") if rga and isinstance(rga[0], dict) else ""
    risk_rows.append(["Retrait-gonflement des argiles", expo or ("Non communiqué" if not err("gr:rga") else "Indisponible")])
    rad = lst("gr:radon")
    risk_rows.append(["Radon (classe de potentiel)", val(rad[0], "classe_potentiel") if rad and isinstance(rad[0], dict) else "Non communiqué"])
    sis = lst("gr:sismique")
    risk_rows.append(["Zone de sismicité", val(sis[0], "zone_sismicite", "libelle_zone", "code_zone") if sis and isinstance(sis[0], dict) else "Non communiqué"])
    gasp = lst("gr:risques")
    rl = sorted({r.get("libelle_risque_long", "") for it in gasp if isinstance(it, dict) for r in it.get("risques_detail", [])})
    risk_rows.append(["Risques recensés sur la commune (GASPAR)", "; ".join(rl) or "Aucun / non communiqué"])
    for k, t in (("azi", "Atlas des zones inondables"), ("pprn", "Plans de prévention des risques naturels")):
        risk_rows.append([t + " (commune)", "; ".join(sorted({desc(x) for x in lst("gr:" + k)})[:6]) or "Aucun / non communiqué"])
    S.append(tbl([["Thème", "Constat"]] + risk_rows, [6, 11]))
    unavailable(*[f"gr:{k}" for k in ("rga", "radon", "sismique", "risques", "azi", "pprn")])
    S.append(P("Éléments localisés à proximité (rayon indiqué) — présence à proximité ≠ risque sur la parcelle", H2))
    prox = [("mvt", "Mouvements de terrain (500 m)"), ("cavites", "Cavités souterraines (500 m)"),
            ("casias", "Anciens sites industriels CASIAS (500 m)"), ("sis", "Secteurs d'information sur les sols (500 m)"),
            ("icpe", "Installations classées ICPE (1 km)")]
    rows = []
    for k, t in prox:
        L = lst("gr:" + k)
        rows.append([t, f"{len(L)} — " + " | ".join(desc(x) for x in L[:3]) if L else ("Indisponible" if err("gr:" + k) else "0")])
    S.append(tbl([["Thème", "Résultat"]] + rows, [6, 11]))
    cat = lst("gr:catnat")
    if cat:
        cnt = Counter(c_.get("libelle_risque_jo", "?") for c_ in cat if isinstance(c_, dict))
        S.append(P("Arrêtés de catastrophe naturelle (commune)", H2))
        S.append(tbl([["Risque", "Nombre"]] + [[k, v] for k, v in cnt.most_common(8)], [12, 5]))
    S.append(P("Pour une vente : l'état des risques et pollutions (ERP) officiel se génère sur georisques.gouv.fr.", SM))
    flagged = [r[0] for r in risk_rows[:3] if r[1] and "Non" not in str(r[1]) and "Indispo" not in str(r[1])]
    synth.append(("Risques naturels (commune/parcelle)", "; ".join(flagged + rl[:4]) or "Voir chapitre 6", "À vérifier"))
    near = sum(len(lst("gr:" + k)) for k, _ in prox)
    synth.append(("Sites / aléas à proximité", f"{near} élément(s) recensé(s)", "À vérifier" if near else "Néant"))

    S = ch.setdefault("environnement", [])
    # --- 7 environnement
    S.append(P("7. Environnement et protections", H1))
    labels = {"natura-habitat": "Natura 2000 Habitats", "natura-oiseaux": "Natura 2000 Oiseaux", "znieff1": "ZNIEFF type I",
              "znieff2": "ZNIEFF type II", "pnr": "Parc naturel régional", "pn": "Parc national",
              "rnn": "Réserve naturelle nationale", "rnr": "Réserve naturelle régionale"}
    rows, hits = [], 0
    for k, t in labels.items():
        L = g("nat:" + k) or []
        hits += len(L)
        rows.append([t, "; ".join(val(f["properties"], "sitename", "nom", "nom_site", "sitecode", "id_mnhn") .__str__() for f in L) if L
                     else ("Indisponible" if err("nat:" + k) else "Non concernée")])
    S.append(tbl([["Zonage", "Résultat au point d'adresse"]] + rows, [5, 12]))
    synth.append(("Environnement protégé", f"{hits} zonage(s)" if hits else "Aucun zonage", "À vérifier" if hits else "Néant"))

    # --- 8 littoral, patrimoine, mérule
    S = ch.setdefault("littoral", [])
    S.append(P("8. Littoral, sites remarquables et mérule", H1))
    unavailable("litt")
    lt = g("litt")
    if lt is not None:
        d_ = lt.get("dist")
        if d_ is None:
            txt, lvl = "Aucune limite terre-mer à moins de 3 km (IGN BD TOPO).", "Néant"
        else:
            txt = f"Distance à la limite terre-mer (IGN BD TOPO) : {d_} m. " + (
                "Dans la bande des 100 m depuis le rivage (loi Littoral) : à confirmer au PLU." if d_ <= 100 else
                "Proche du rivage (moins de 1 km) : vérifier les espaces proches du rivage au PLU." if d_ <= 1000 else
                "À plus de 1 km du rivage.")
            lvl = "À vérifier" if d_ <= 1000 else "Info"
        S.append(P(txt))
        synth.append(("Littoral", txt, lvl))
    S.append(P("Patrimoine et sites remarquables", H2))
    pat = [[val(f["properties"], "nomsuplitt", "nomass", "libelle", "nom"), re.search(r"\bAC[124]\b", json.dumps(f["properties"]), re.I).group(0).upper()]
           for s_ in ("s", "l", "p") for f in g(f"sup:assiette-sup-{s_}") or []
           if re.search(r"\bAC[124]\b", json.dumps(f["properties"]), re.I)]
    S.append(tbl([["Servitude patrimoniale", "Code"]] + pat, [14, 3]) if pat else P("Aucune servitude AC1 (monuments historiques), AC2 (sites inscrits/classés) ou AC4 (sites patrimoniaux remarquables) publiée au GPU à cet endroit. Les zonages Natura 2000, ZNIEFF, parcs et réserves figurent au chapitre 7."))
    S.append(P("La vue mer n'est pas une donnée publique : elle se saisit à la main dans l'estimation (chapitre 9).", SM))
    synth.append(("Sites remarquables (AC1/AC2/AC4)", f"{len(pat)} servitude(s)" if pat else "Aucune publiée", "À vérifier" if pat else "Néant"))
    dep_ = place["citycode"][:2] if not place["citycode"].startswith("97") else place["citycode"][:3]
    S.append(P("Risque mérule", H2))
    S.append(P("Le risque mérule relève d'arrêtés préfectoraux départementaux (loi ALUR) : il n'existe pas de source nationale unique interrogeable. "
               "L'absence d'arrêté ne garantit pas l'absence de mérule. Département : " + dep_ + ". "
               + ("Carte de la DDTM des Côtes-d'Armor : https://geobretagne.fr/mviewer/?config=/pub/ddtm-22/apps/merule/merule.xml" if dep_ == "22" else
                  "Consulter l'arrêté du département (préfecture, mairie) ou rechercher « mérule » sur data.gouv.fr.")))
    synth.append(("Mérule", "Arrêté préfectoral à vérifier (pas d'API nationale)", "À vérifier"))

    # --- 9 estimation DVF
    S = ch.setdefault("marche", [])
    S.append(P("9. Estimation du prix au m² (ventes DVF)", H1))
    unavailable("est")
    e = g("est")
    if e and e.get("n"):
        S.append(tbl([["Type de bien", e["type"]], ["Zone", f"rayon {e['radius']} m autour de la sélection"],
                      ["Période", f"{e['months']} derniers mois (ventes uniquement)"],
                      ["Ventes retenues", f"{e['n']} (sur {e['n_raw']} avant exclusion des valeurs aberrantes)"],
                      ["Prix médian au m²", f"{e['median']} €/m²"], ["Prix moyen au m²", f"{e['mean']} €/m²"],
                      ["Intervalle central (25-75 %)", f"{e['q1']} – {e['q3']} €/m²"]], [6, 11], head=False))
        if e["n"] < 5:
            S.append(P("Échantillon faible (moins de 5 ventes) : élargir le rayon avant toute conclusion.", WARN))
        if e.get("estimate"):
            a_ = e["adj"]
            S.append(P("Estimation indicative", H2))
            S.append(tbl([["Surface du bien", f"{e['surface']:.0f} m²"], ["Valeur de base (médiane x surface)", f"{e['base']:,} €".replace(",", " ")],
                          ["Ajustements saisis", f"vue mer {a_.get('vue_mer', 0):+.0f} % ; proximité mer {a_.get('proximite_mer', 0):+.0f} % ; autre {a_.get('autre', 0):+.0f} %"],
                          ["Estimation ajustée", f"{e['estimate']:,} €".replace(",", " ")],
                          ["Fourchette (25-75 %)", f"{e['low']:,} – {e['high']:,} €".replace(",", " ")]], [6, 11], head=False))
            synth.append(("Estimation DVF", f"{e['estimate']:,} € ({e['median']} €/m² médian)".replace(",", " "), "Info"))
        S.append(P("Ventes retenues (les plus proches)", H2))
        S.append(tbl([["Date", "Adresse", "Surface m²", "Prix €", "€/m²", "Distance m"]] +
                     [[c["date"], c["adresse"], c["surface"], c["valeur"], c["pm2"], c["dist"]] for c in e["comps"][:25]],
                     [2.2, 6, 2.2, 2.6, 1.8, 2.2]))
    elif e is not None:
        S.append(P("Aucune vente comparable trouvée : élargir le rayon ou changer le type de bien."))
    elif not err("est"):
        S.append(P("Estimation non demandée : renseigner le type de bien dans l'outil."))
    S.append(P("Source : Demandes de valeurs foncières (DGFiP, open data). Ventes simples d'un seul local du type choisi ; données récentes parfois non publiées. "
               "Les ajustements (vue mer, proximité de la mer, site remarquable) sont saisis par l'utilisateur : ils ne proviennent d'aucune source publique. "
               "Estimation indicative, ne remplaçant pas une expertise.", SM))

    S = ch.setdefault("synthese", [])
    # --- 9 synthèse
    S += [PageBreak(), P("9. Synthèse", H1), tbl([["Thème", "Constat", "Statut"]] + [list(r) for r in synth], [4.5, 9.5, 3])]
    S += [P("Pièces et démarches complémentaires à prévoir pour un dossier", H2),
          P("• Extrait cadastral officiel et plan sur cadastre.gouv.fr — • Certificat d'urbanisme (CUa/CUb) et note de renseignements "
            "d'urbanisme auprès de la mairie — • État des risques et pollutions (ERP) sur georisques.gouv.fr — • Vérification du droit de "
            "préemption urbain (DPU) auprès de la commune — • Assainissement (raccordement ou SPANC) et réseaux auprès de la mairie / "
            "intercommunalité — • Diagnostics techniques obligatoires (DPE, etc.) selon la nature du bien.")]

    S = ch.setdefault("sources", [])
    # --- 10 sources
    S += [P("10. Sources et réserves", H1), tbl([["Source", "Données utilisées", "Adresse"],
          ["Base Adresse Nationale", "Normalisation et géocodage", "adresse.data.gouv.fr"],
          ["API Carto IGN – Cadastre", "Parcelles, contenance", "apicarto.ign.fr"],
          ["Géoportail de l'urbanisme (via API Carto)", "Zonage, prescriptions, informations, servitudes", "geoportail-urbanisme.gouv.fr"],
          ["API Carto IGN – Nature (INPN)", "Natura 2000, ZNIEFF, parcs, réserves", "apicarto.ign.fr / inpn.mnhn.fr"],
          ["Géorisques", "Risques naturels et technologiques, sols pollués", "georisques.gouv.fr"],
          ["Géoplateforme IGN", "Orthophotographie, Plan IGN", "geoservices.ign.fr"],
          ["DVF (DGFiP / Etalab)", "Valeurs foncières", "data.gouv.fr"],
          ["geo.api.gouv.fr", "Commune, EPCI, population", "geo.api.gouv.fr"]], [5.5, 6.5, 5]),
          Spacer(1, .3 * cm), P(f"Données interrogées le {D['_date']}. Les données publiques peuvent être incomplètes, non à jour ou non "
                               "numérisées : ce document est une aide à l'instruction et n'a aucune valeur juridique en lui-même.", SM)]

    ORDER = ["cadastre", "urbanisme", "risques", "environnement", "littoral", "marche", "synthese"]
    story = list(ch["cover"])
    for k in ORDER:
        if (sections is not None and k not in sections) or not ch.get(k):
            continue
        part = list(ch[k])
        while part and isinstance(part[0], PageBreak):
            part.pop(0)
        story += part + [PageBreak()]
    story += [x for x in ch["sources"] if not isinstance(x, PageBreak)]
    buf = io.BytesIO()

    def footer(cv, doc):
        cv.saveState(); cv.setFont("Helvetica", 7.5); cv.setFillColor(colors.grey)
        cv.drawString(2 * cm, 1.1 * cm, f"Dossier parcellaire — {place['label']}")
        cv.drawRightString(A4[0] - 2 * cm, 1.1 * cm, f"Page {doc.page} — {D['_date']}")
        cv.restoreState()

    SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                      title=f"Dossier parcellaire - {place['label']}").build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()

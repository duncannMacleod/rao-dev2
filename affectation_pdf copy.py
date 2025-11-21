# generate_pdf_from_marches.py
import json
import pandas as pd
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm

# ------------------ Paramètres généraux ------------------
DOSSIER_JSON = "marches_json"
KM_MARCHES_FILE = "km_marches.json"

# Paramètres métiers
m_st_chrls = "MSC"
navette_time = 0.083
tampon = 0.333
tampon_15m = 0.25
temps_minimal = 0.20
seuil_atelier = 1.25

# Parc de rames
parc = {
    "C":    {"modele": "Corail",   "numero": 22201, "quantite": 3,  "utilise": 0, "places": 704},
    "BGC":  {"modele": "BGC",      "numero": 81501, "quantite": 27, "utilise": 0, "places": 200},
    "REG":  {"modele": "Regiolis", "numero": 84501, "quantite": 15, "utilise": 0, "places": 220},
    "2NPG": {"modele": "2NPG",     "numero": 23501, "quantite": 30, "utilise": 0, "places": 210},
}

# ------------------ Fonctions d'affectation ------------------
def get_rame_id(nom_ligne: str):
    """Retourne un ID de rame en fonction du fichier de marches."""
    if nom_ligne == "marches_intervilles-marseille-lyon.json":
        key = "C"
    elif nom_ligne == "marches_marseille-toulon-hyeres-les-arcs-draguignan.json":
        key = "2NPG"
    elif nom_ligne == "marches_marseille-avignon.json":
        key = "2NPG"
    else:
        key = "BGC" if parc["BGC"]["utilise"] < parc["BGC"]["quantite"] else "REG"

    if parc[key]["utilise"] >= parc[key]["quantite"]:
        raise RuntimeError(f"Plus de rames disponibles pour {parc[key]['modele']}")

    rame_id = parc[key]["numero"] + parc[key]["utilise"]
    parc[key]["utilise"] += 1
    return rame_id


def navette_mat(rame_id, gare_dep, depart, tampon, navette_time):
    navette_dict = {
        "MSC": {"gare_depart": "MBC", "gare_arrivee": "MSC"},
        "AVV": {"gare_depart": "AVG", "gare_arrivee": "AVV"},
        "AVI": {"gare_depart": "AVG", "gare_arrivee": "AVI"},
        "LPR": {"gare_depart": "LYG", "gare_arrivee": "LPR"},
        "LYD": {"gare_depart": "LYG", "gare_arrivee": "LYD"},
        "MAS": {"gare_depart": "MAG", "gare_arrivee": "MAS"},
        "HYE": {"gare_depart": "HYG", "gare_arrivee": "HYE"},
        "TLN": {"gare_depart": "TLG", "gare_arrivee": "TLN"},
        "LAC": {"gare_depart": "LAG", "gare_arrivee": "LAC"},
        "AXP": {"gare_depart": "AXG", "gare_arrivee": "AXP"},
        "GAP": {"gare_depart": "GAG", "gare_arrivee": "GAP"},
        "SIS": {"gare_depart": "SIG", "gare_arrivee": "SIS"},
        "BRI": {"gare_depart": "BRG", "gare_arrivee": "BRI"},
    }
    if gare_dep not in navette_dict:
        return None

    info = navette_dict[gare_dep]
    return {
        "rame": rame_id,
        "marche": f"navette_mat_{rame_id}",
        "gare_depart": info["gare_depart"],
        "depart": depart - tampon - navette_time,
        "gare_arrivee": info["gare_arrivee"],
        "arrivee": depart - tampon,
        "vide_voyageur": True,
    }


def navette_soir(rame_id, gare_dep, dispo):
    mapping = {
        "MSC": "MBC",
        "AVV": "AVG",
        "AVI": "AVG",
        "LPR": "LYG",
        "LYD": "LYG",
        "MAS": "MAG",
        "HYE": "HYG",
        "TLN": "TLG",
        "LAC": "LAG",
        "AXP": "AXG",
        "GAP": "GAG",
        "SIS": "SIG",
        "BRI": "BRG",
    }
    if gare_dep not in mapping:
        return None
    return {
        "rame": rame_id,
        "marche": f"navette_soir_{rame_id}",
        "gare_depart": gare_dep,
        "depart": dispo + tampon_15m,
        "gare_arrivee": mapping[gare_dep],
        "arrivee": dispo + tampon_15m + navette_time,
        "vide_voyageur": True,
    }


def gestion_evo(rame_id, gare_dep, depart, state, assignments):
    mapping_navette = {
        "MSC": "MBC",
        "AVV": "AVG",
        "AVI": "AVG",
        "LPR": "LYG",
        "LYD": "LYG",
        "MAS": "MAG",
        "HYE": "HYG",
        "TLN": "TLG",
        "LAC": "LAG",
        "AXP": "AXG",
        "GAP": "GAG",
        "SIS": "SIG",
        "BRI": "BRG",
    }

    if gare_dep not in mapping_navette:
        return

    gare_navette = mapping_navette[gare_dep]

    assignments.append(
        {
            "rame": rame_id,
            "marche": f"evo_in_{rame_id}",
            "gare_depart": gare_dep,
            "depart": state["dispo"] + tampon_15m,
            "gare_arrivee": gare_navette,
            "arrivee": state["dispo"] + navette_time + tampon_15m,
            "vide_voyageur": True,
        }
    )

    assignments.append(
        {
            "rame": rame_id,
            "marche": f"evo_out_{rame_id}",
            "gare_depart": gare_navette,
            "depart": depart - navette_time - tampon_15m,
            "gare_arrivee": gare_dep,
            "arrivee": depart - tampon_15m,
            "vide_voyageur": True,
        }
    )

    state["gare"] = gare_dep
    state["dispo"] = depart


# ------------------ Calcul PPHPD ------------------
def calcul_pphpd_par_direction(df_assign, parc):
    resultats = []

    if df_assign.empty:
        return pd.DataFrame(resultats)

    hmin = int(df_assign["depart"].min())
    hmax = int(df_assign["arrivee"].max()) + 1

    for h in range(hmin, hmax):
        tranche = df_assign[
            (df_assign["depart"] >= h)
            & (df_assign["depart"] < h + 1)
            & (~df_assign["vide_voyageur"])
        ]

        for direction in ["Paris", "Province"]:
            capacite_totale = 0
            for _, row in tranche.iterrows():
                try:
                    num = int(row["marche"])
                except Exception:
                    continue

                if (num % 2 == 0 and direction == "Paris") or (
                    num % 2 == 1 and direction == "Province"
                ):
                    rame = row["rame"]
                    for key, info in parc.items():
                        if (
                            info["numero"] <= rame < info["numero"] + info["quantite"]
                        ) and not row["vide_voyageur"]:
                            capacite_totale += info["places"]
                            break

            resultats.append(
                {"heure": h, "direction": direction, "pphpd": capacite_totale}
            )

    return pd.DataFrame(resultats)


# ------------------ Layout PDF ------------------
PAGE_WIDTH, PAGE_HEIGHT = A4  # portrait

LEFT_MARGIN = 15 * mm
RIGHT_MARGIN = 15 * mm
TOP_MARGIN = 12 * mm
BOTTOM_MARGIN = 12 * mm

MAX_RAMES_PER_PAGE = 12
ESPACEMENT_RAME = 10  # espace vertical entre cadres

HAUTEUR_DISPO = PAGE_HEIGHT - TOP_MARGIN - BOTTOM_MARGIN
RAME_HEIGHT = (HAUTEUR_DISPO - (MAX_RAMES_PER_PAGE - 1) * ESPACEMENT_RAME) / MAX_RAMES_PER_PAGE

HEURE_MIN = 4
HEURE_MAX = 23
ECHELLE_HEURE = (PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN) / (HEURE_MAX - HEURE_MIN)

# Fenêtre de référence pour la performance (en heure décimale)
WINDOW_START = 5.5   # 5h30
WINDOW_END   = 22.5  # 22h30
WINDOW_DURATION = WINDOW_END - WINDOW_START  # 17h


# Décalage horizontal (en points) pour la première gare de départ de la rame
FIRST_LABEL_OFFSET = 15
LAST_LABEL_OFFSET = 15

def x_from_time(horaire):
    """Convertit une heure décimale en coordonnée X du PDF."""
    return LEFT_MARGIN + (horaire - HEURE_MIN) * ECHELLE_HEURE


def draw_train_bar(c, x1, x2, y, height=5, color=colors.black):
    """Barre horizontale pour une marche (voyageurs ou HLP)."""
    c.setFillColor(color)
    c.rect(x1, y - height / 2, x2 - x1, height, stroke=0, fill=1)


def format_time_hm(h):
    """Retourne uniquement les minutes (MM) pour une heure décimale."""
    try:
        h = float(h)
        h_int = int(h)
        m = int(round((h - h_int) * 60))
        if m == 60:
            m = 0
        return f"{m:02d}"
    except Exception:
        return str(h)


def draw_station_label(c, x, y_base, gare, heure, align="left"):
    """Affiche gare + heure sur deux lignes."""
    c.setFont("Helvetica", 5)
    if align == "left":
        c.drawString(x, y_base, gare)
        c.drawString(x, y_base - 5, heure)
    elif align == "right":
        c.drawRightString(x, y_base, gare)
        c.drawRightString(x, y_base - 5, heure)
    else:
        c.drawCentredString(x, y_base, gare)
        c.drawCentredString(x, y_base - 5, heure)


def draw_time_only(c, x, y_base, heure, align="center"):
    """Affiche uniquement l'heure sur une ligne."""
    c.setFont("Helvetica", 5)
    if align == "left":
        c.drawString(x, y_base, heure)
    elif align == "right":
        c.drawRightString(x, y_base, heure)
    else:
        c.drawCentredString(x, y_base, heure)


# ------------------ Chargement distances ------------------
km_dict = {}
if os.path.exists(KM_MARCHES_FILE):
    with open(KM_MARCHES_FILE, "r", encoding="utf-8") as f:
        try:
            km_data = json.load(f)
            for d in km_data:
                km_dict[(d["origine"], d["destination"])] = d["distance"]
                km_dict[(d["destination"], d["origine"])] = d["distance"]
        except Exception as e:
            print(f"⚠️ Erreur lecture {KM_MARCHES_FILE}: {e}")
else:
    print(f"⚠️ {KM_MARCHES_FILE} introuvable — les distances seront à 0.")


def get_distance_safe(row):
    if row.get("vide_voyageur", False):
        return 0
    try:
        return km_dict[(row["gare_depart"], row["gare_arrivee"])]
    except KeyError:
        print(f"⚠️ Distance inconnue pour {row['gare_depart']} → {row['gare_arrivee']}")
        return 0
    except Exception as e:
        print(
            f"❌ Erreur inattendue pour {row['gare_depart']} → {row['gare_arrivee']}: {e}"
        )
        return 0


# ------------------ Génération PDF à partir des assignments ------------------
def draw_pdf_for_assignments(df_assign, json_file):
    """
    Génére un PDF pour un fichier de marches :
    - un cadre par rame
    - affichage de la ligne de roulement (hier -> aujourd'hui -> demain)
      basée sur l'index de la rame dans rame_list (1..N).
    """
    rame_list = sorted(df_assign["rame"].unique())
    nom_pdf = os.path.splitext(os.path.basename(json_file))[0] + ".pdf"
    c = canvas.Canvas(nom_pdf, pagesize=A4)

    # ------- Titre du document PDF -------
    titre = os.path.splitext(os.path.basename(json_file))[0]   # nom fichier sans .json
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.black)
    c.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 20, titre)
    # -------------------------------------


    # km par rame
    df_km_par_rame = (
        df_assign[~df_assign["vide_voyageur"]]
        .groupby("rame")["distance_km"]
        .sum()
        .reset_index()
    )
    
    # --- Performance : temps en marche voyageur dans la fenêtre [5h30, 22h30] ---
    df_voy = df_assign[~df_assign["vide_voyageur"]].copy()

    if not df_voy.empty:
        # on "clipse" départ / arrivée dans la fenêtre
        df_voy["depart_clip"] = df_voy["depart"].clip(lower=WINDOW_START, upper=WINDOW_END)
        df_voy["arrivee_clip"] = df_voy["arrivee"].clip(lower=WINDOW_START, upper=WINDOW_END)

        # durée effective dans la fenêtre
        df_voy["duree_fenetre"] = (df_voy["arrivee_clip"] - df_voy["depart_clip"]).clip(lower=0)

        df_perf_par_rame = (
            df_voy.groupby("rame")["duree_fenetre"]
            .sum()
            .reset_index()
        )
        df_perf_par_rame["taux_utilisation"] = (
            df_perf_par_rame["duree_fenetre"] / WINDOW_DURATION * 100.0
        )
    else:
        # aucun voyageur → DF vide
        df_perf_par_rame = pd.DataFrame(columns=["rame", "duree_fenetre", "taux_utilisation"])

    y_start = PAGE_HEIGHT - TOP_MARGIN
    rame_counter = 0
    nb_rames = len(rame_list)

    for rame_index, rame in enumerate(rame_list):

        if rame_counter >= MAX_RAMES_PER_PAGE:
            c.showPage()
            y_start = PAGE_HEIGHT - TOP_MARGIN
            rame_counter = 0

        sous_df = df_assign[df_assign["rame"] == rame].sort_values("depart")

        cadre_top = y_start
        cadre_bottom = y_start - RAME_HEIGHT

        # ---- Numéro de ligne de roulement (hier / aujourd'hui / demain) ----
        ligne_auj = (rame_index % nb_rames) + 1
        ligne_hier = ((rame_index - 1) % nb_rames) + 1
        ligne_demain = ((rame_index + 1) % nb_rames) + 1
        texte_roulement = f"{ligne_hier} ➜ {ligne_auj} ➜ {ligne_demain}"
        # --------------------------------------------------------------------

        # Cadre
        c.setStrokeColor(colors.HexColor("#3A7ECB"))
        c.setLineWidth(1.0)
        c.rect(
            LEFT_MARGIN,
            cadre_bottom,
            PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN,
            RAME_HEIGHT,
            stroke=1,
            fill=0,
        )

        # Titre rame
        c.setFont("Helvetica-Bold", 5)
        c.setFillColor(colors.magenta)
        c.drawString(LEFT_MARGIN + 6, cadre_top - 12, texte_roulement)

        # Km total
        total_rame_km = df_km_par_rame.loc[
            df_km_par_rame["rame"] == rame, "distance_km"
        ]
        if not total_rame_km.empty:
            total_rame_km = int(total_rame_km.values[0])
            c.setFont("Helvetica-Bold", 5)
            c.setFillColor(colors.blue)
            c.drawString(LEFT_MARGIN + 6, cadre_bottom + 4, f"{total_rame_km} km")
            c.setFillColor(colors.black)

        # Indicateur de performance (taux d'utilisation dans la fenêtre)
        perf_row = df_perf_par_rame.loc[df_perf_par_rame["rame"] == rame, "taux_utilisation"]
        if not perf_row.empty:
            perf_val = perf_row.values[0]
            # on arrondit à l'entier, tu peux mettre :.1f si tu veux une décimale
            txt_perf = f"Perf : {perf_val:.0f}%"
            c.setFont("Helvetica-Bold", 5)
            c.setFillColor(colors.green)
            # en bas à droite du cadre
            c.drawRightString(PAGE_WIDTH - RIGHT_MARGIN - 6, cadre_bottom + 4, txt_perf)
            c.setFillColor(colors.black)

        # Ligne centrale
        y_line = cadre_bottom + (RAME_HEIGHT / 2)
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.6)
        c.line(LEFT_MARGIN, y_line, PAGE_WIDTH - RIGHT_MARGIN, y_line)

        # Traits horaires (toutes les heures)
        c.setFont("Helvetica", 4)
        for h in range(HEURE_MIN, HEURE_MAX + 1):
            xh = x_from_time(h)

            # ligne verticale pointillée
            c.setStrokeColor(colors.lightgrey)
            c.setDash(1, 2)   # 1 point, 2 espaces
            c.line(xh, cadre_bottom, xh, cadre_top)
            c.setDash()       # reset style

            # Heure en tout petit
            c.setFillColor(colors.black)
            c.drawString(xh - 5, cadre_top - 6, f"{h}h")

        # Marches avec gestion des nœuds de gare
        prev_node = None  # {"gare", "x", "heure"}
        prev_arrivee = None
        premiere_marche = True  # pour l'offset de la 1re marche

        for _, row in sous_df.iterrows():
            x1 = x_from_time(row["depart"])
            x2 = x_from_time(row["arrivee"])

            if x2 < LEFT_MARGIN:
                continue
            if x1 > PAGE_WIDTH - RIGHT_MARGIN:
                continue
            x1 = max(x1, LEFT_MARGIN + 2)
            x2 = min(x2, PAGE_WIDTH - RIGHT_MARGIN - 2)

            # Couleur différentes HLP / voyageurs
            if row.get("vide_voyageur", False):
                bar_color = colors.lightgrey  # HLP
            else:
                bar_color = colors.black      # voyageurs

            draw_train_bar(c, x1, x2, y_line, height=5, color=bar_color)

            # Infos de la marche
            gare_dep = str(row["gare_depart"])
            gare_arr = str(row["gare_arrivee"])
            heure_dep = format_time_hm(row["depart"])
            heure_arr = format_time_hm(row["arrivee"])

            # 1) Traiter d'abord l'arrivée précédente si elle existe
            depart_label_deja_fait = False
            c.setFillColor(colors.black)

            if prev_node is not None:
                if prev_node["gare"] == gare_dep:
                    # même gare arrivée précédente -> départ courant
                    xm = (prev_node["x"] + x1) / 2.0
                    y_base = y_line - 7

                    c.setFont("Helvetica", 5)
                    c.drawCentredString(xm, y_base, prev_node["gare"])

                    draw_time_only(
                        c, prev_node["x"], y_base - 5, prev_node["heure"], align="center"
                    )
                    draw_time_only(
                        c, x1, y_base - 10, heure_dep, align="center"
                    )

                    depart_label_deja_fait = True
                else:
                    # arrivée précédente "classique"
                    draw_station_label(
                        c,
                        prev_node["x"] - 1,
                        y_line - 7,
                        prev_node["gare"],
                        prev_node["heure"],
                        align="right",
                    )

            # 2) Départ courant (si pas déjà géré)
            if not depart_label_deja_fait:
                base_x = x1 + 1
                if premiere_marche:
                    x_depart = base_x - FIRST_LABEL_OFFSET
                else:
                    x_depart = base_x

                draw_station_label(
                    c, x_depart, y_line - 7, gare_dep, heure_dep, align="left"
                )

            # 3) Numéro de marche
            c.setFont("Helvetica", 5)
            c.setFillColor(colors.darkgray)
            marche_text = str(row["marche"])

            # HLP : numéro un peu plus haut que les trains voyageurs
            if row.get("vide_voyageur", False):
                y_num = y_line + 12   # offset Y plus grand pour les HLP
            else:
                y_num = y_line + 7    # position actuelle pour les voyageurs

            c.drawCentredString((x1 + x2) / 2, y_num, marche_text)


            # 4) Avertissement écart < 20 min
            if prev_arrivee is not None:
                ecart = row["depart"] - prev_arrivee
                if ecart < 0.333:
                    minutes = int(round(ecart * 60))
                    milieu = (row["depart"] + prev_arrivee) / 2
                    xm = x_from_time(milieu)
                    c.setFont("Helvetica-Bold", 4)
                    c.setFillColor(colors.red)
                    c.drawCentredString(xm, y_line, f"{minutes}")
                    c.setFillColor(colors.black)

            prev_arrivee = row["arrivee"]

            # 5) Préparer le nœud d'arrivée pour la prochaine marche
            prev_node = {
                "gare": gare_arr,
                "x": x2,
                "heure": heure_arr,
            }

            premiere_marche = False

        # 6) Après la dernière marche : dessiner l'arrivée finale avec offset vers la droite
        if prev_node is not None:
            x_last = prev_node["x"] + LAST_LABEL_OFFSET  # on pousse vers la droite
            draw_station_label(
                c,
                x_last,
                y_line - 7,
                prev_node["gare"],
                prev_node["heure"],
                align="right",
            )


        y_start -= (RAME_HEIGHT + ESPACEMENT_RAME)
        rame_counter += 1
        
    # ➜ Ajout de la page récap des paramètres
    draw_params_page(c, json_file)
    
    c.save()
    print(f"PDF généré : {nom_pdf}")

def draw_params_page(c, json_file):
    """Ajoute une page récap avec les paramètres de l'algo d'attribution."""
    c.showPage()

    # Titre de la page
    titre = f"Paramètres de l'attribution – {os.path.splitext(os.path.basename(json_file))[0]}"
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.black)
    c.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 40, titre)

    y = PAGE_HEIGHT - 70
    line_height = 12

    # --- Paramètres généraux ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(LEFT_MARGIN, y, "Paramètres généraux :")
    y -= line_height

    c.setFont("Helvetica", 9)
    c.drawString(LEFT_MARGIN, y, f"• Temps minimal entre deux marches : {temps_minimal:.3f} h (~{int(temps_minimal*60)} min)")
    y -= line_height
    c.drawString(LEFT_MARGIN, y, f"• Seuil atelier (évolution) : {seuil_atelier:.3f} h (~{int(seuil_atelier*60)} min)")
    y -= line_height
    c.drawString(LEFT_MARGIN, y, f"• Tampon général : {tampon:.3f} h (~{int(tampon*60)} min)")
    y -= line_height
    c.drawString(LEFT_MARGIN, y, f"• Tampon 15 min : {tampon_15m:.3f} h (~{int(tampon_15m*60)} min)")
    y -= line_height
    c.drawString(LEFT_MARGIN, y, f"• Durée navette (HLP dépôt↔gare) : {navette_time:.3f} h (~{int(navette_time*60)} min)")
    y -= line_height

    # --- Paramètres d'affichage ---
    y -= line_height // 2
    c.setFont("Helvetica-Bold", 10)
    c.drawString(LEFT_MARGIN, y, "Paramètres d'affichage :")
    y -= line_height

    c.setFont("Helvetica", 9)
    c.drawString(LEFT_MARGIN, y, f"• Plage horaire affichée : {HEURE_MIN}h → {HEURE_MAX}h")
    y -= line_height
    c.drawString(LEFT_MARGIN, y, f"• Offset premier label gare : {FIRST_LABEL_OFFSET} pts")
    y -= line_height
    c.drawString(LEFT_MARGIN, y, "• Affichage minutes uniquement pour les heures de départ / arrivée")
    y -= line_height

    # --- Indicateur de performance ---
    y -= line_height // 2
    c.setFont("Helvetica-Bold", 10)
    c.drawString(LEFT_MARGIN, y, "Indicateur de performance :")
    y -= line_height

    c.setFont("Helvetica", 9)
    # fenêtre temporelle de référence
    c.drawString(
        LEFT_MARGIN,
        y,
        f"• Fenêtre de référence : {WINDOW_START:.2f}h → {WINDOW_END:.2f}h (≈ 5h30–22h30)"
    )
    y -= line_height
    c.drawString(
        LEFT_MARGIN,
        y,
        f"• Durée de la fenêtre : {WINDOW_DURATION:.1f} h"
    )
    y -= line_height
    # principe de calcul
    c.drawString(
        LEFT_MARGIN,
        y,
        "• Pour chaque rame : somme des durées en marche voyageurs dans cette fenêtre"
    )
    y -= line_height
    c.drawString(
        LEFT_MARGIN,
        y,
        "  divisée par la durée de la fenêtre, affichée en pourcentage (Perf : XX%)."
    )
    y -= line_height

    # --- Parc de rames ---
    y -= line_height // 2
    c.setFont("Helvetica-Bold", 10)
    c.drawString(LEFT_MARGIN, y, "Parc de rames utilisé :")
    y -= line_height

    c.setFont("Helvetica", 9)
    for code, info in parc.items():
        txt = (f"• {code} – {info['modele']}: "
               f"{info['quantite']} rames (numéros {info['numero']} à {info['numero'] + info['quantite'] - 1}), "
               f"{info['places']} places par rame")
        c.drawString(LEFT_MARGIN, y, txt)
        y -= line_height
        if y < BOTTOM_MARGIN + 40:
            # nouvelle page si on descend trop bas
            c.showPage()
            y = PAGE_HEIGHT - TOP_MARGIN


# ------------------ Boucle principale ------------------
def process_and_generate():
    # reset parc
    for k in parc:
        parc[k]["utilise"] = 0

    if not os.path.exists(DOSSIER_JSON):
        print(f"⚠️ Dossier {DOSSIER_JSON} introuvable.")
        return

    for fichier_json in sorted(os.listdir(DOSSIER_JSON)):
        if not fichier_json.endswith(".json"):
            continue

        chemin_json = os.path.join(DOSSIER_JSON, fichier_json)
        with open(chemin_json, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception as e:
                print(f"❌ Impossible de lire {chemin_json}: {e}")
                continue

        df = pd.DataFrame(data).sort_values("depart").reset_index(drop=True)
        rame_state = {}
        assignments = []

        # Affectation automatique
        for _, train in df.iterrows():
            gare_dep = train["gare_depart"]
            depart = train["depart"]
            candidate = None

            for rame_id, state in rame_state.items():
                if state["gare"] == gare_dep and state["dispo"] + temps_minimal <= depart:
                    if depart - state["dispo"] > seuil_atelier:
                        gestion_evo(rame_id, state["gare"], depart, state, assignments)
                    candidate = rame_id
                    break

            if candidate is None:
                candidate = get_rame_id(fichier_json)
                marche_navette = navette_mat(
                    candidate, gare_dep, depart, tampon_15m, navette_time
                )
                if marche_navette:
                    assignments.append(marche_navette)
                rame_state[candidate] = {"gare": gare_dep, "dispo": 0}

            assignments.append(
                {
                    "rame": candidate,
                    "marche": train["marche"],
                    "gare_depart": gare_dep,
                    "depart": train["depart"],
                    "gare_arrivee": train["gare_arrivee"],
                    "arrivee": train["arrivee"],
                    "vide_voyageur": train.get("vide_voyageur", False),
                }
            )
            rame_state[candidate]["gare"] = train["gare_arrivee"]
            rame_state[candidate]["dispo"] = train["arrivee"]

        # Navette soir
        for rame_id, state in rame_state.items():
            soir = navette_soir(rame_id, state["gare"], state["dispo"])
            if soir:
                assignments.append(soir)

        df_assign = pd.DataFrame(assignments)
        if df_assign.empty:
            print(f"{fichier_json} -> aucun assignment généré.")
            continue

        df_assign["vide_voyageur"] = df_assign["vide_voyageur"].fillna(False)

        # distances
        df_assign["distance_km"] = df_assign.apply(get_distance_safe, axis=1)

        # équilibre flux (console)
        premiers_depart = (
            df_assign.sort_values("depart").groupby("rame").first()
        )
        dernieres_arrivee = (
            df_assign.sort_values("arrivee").groupby("rame").last()
        )
        depart_counts = (
            premiers_depart["gare_depart"].value_counts().rename("Departs")
        )
        arrivee_counts = (
            dernieres_arrivee["gare_arrivee"].value_counts().rename("Arrivees")
        )
        flux_balance = (
            pd.concat([depart_counts, arrivee_counts], axis=1)
            .fillna(0)
            .astype(int)
        )
        flux_balance["Diff (Arr - Dep)"] = (
            flux_balance["Arrivees"] - flux_balance["Departs"]
        )

        print(f"{fichier_json}")
        print("--- Vérification équilibre par gare (Arrivées - Départs) ---")
        print(flux_balance)
        print("\n")

        # PPHPD (console)
        df_pphpd = calcul_pphpd_par_direction(df_assign, parc)
        print("--- PPHPD par heure et direction ---")
        if not df_pphpd.empty:
            print(
                df_pphpd.pivot(
                    index="heure", columns="direction", values="pphpd"
                ).fillna(0)
            )
        print("\n")

        # Génération PDF
        draw_pdf_for_assignments(df_assign, fichier_json)


if __name__ == "__main__":
    process_and_generate()

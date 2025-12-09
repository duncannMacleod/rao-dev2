# generate_pdf_from_marches.py
import json
import pandas as pd
import os
import matplotlib.pyplot as plt
import tempfile
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
temps_minimal = 0.21
seuil_atelier = 1.25

# Parc de rames
parc = {
    "R2N":    {"modele": "Regio2n",   "numero": 22201, "quantite": 10,  "utilise": 0, "places": 505},
    "BGC":    {"modele": "BGC",       "numero": 81501, "quantite": 22,  "utilise": 0, "places": 200},
    "REG":    {"modele": "Regiolis",  "numero": 84501, "quantite": 15,  "utilise": 0, "places": 220},
    "2NPG":   {"modele": "2NPG",      "numero": 23501, "quantite": 30,  "utilise": 0, "places": 210},
}

# Gare où les rames sont affectés en dépôt
DEPOT_AFFECTATION = {
    "R2N": "AVG",
    "BGC": "AVG",
    "REG": "MBC",
    "2NPG": "MBC",
}


# Stockage de l’équilibre des flux par axe (pour affichage dans les PDF matériels)
# FLUX_PAR_AXE[axe_label] = {"fichier": ..., "flux": df, "materiels": [codes]}
FLUX_PAR_AXE = {}


# ------------------ Fonctions d'affectation ------------------
def get_rame_id(nom_ligne: str):
    """Retourne un ID de rame en fonction du fichier de marches."""
    if nom_ligne == "marches_intervilles-marseille-lyon.json":
        key = "R2N"
    elif nom_ligne == "marches_marseille-toulon-hyeres-les-arcs-draguignan.json":
        key = "2NPG"
    elif nom_ligne == "marches_marseille-avignon.json":
        key = "2NPG"
    elif nom_ligne == "marches_vallee-du-rhone.json":
        key = "R2N"
    elif nom_ligne == "marches_marseille-miramas-via-cote-bleue.json":
        key = "REG"
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
        "marche": f"EVM{depart}{gare_dep}",
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
        "marche": f"EVS{dispo}",
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
            "marche": f"EVI{rame_id}",
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
            "marche": f"EVO{rame_id}",
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
    """
    PPHPD avec règle :
      - avant 12h = basé sur l'heure d'arrivée
      - après 12h = basé sur l'heure de départ
    """
    resultats = []

    if df_assign.empty:
        return pd.DataFrame(resultats)

    # heure de référence PPHPD
    df_assign = df_assign.copy()
    df_assign["heure_pphpd"] = df_assign.apply(
        lambda r: r["arrivee"] if r["arrivee"] < 12 else r["depart"],
        axis=1
    )

    hmin = int(df_assign["heure_pphpd"].min())
    hmax = int(df_assign["heure_pphpd"].max()) + 1

    for h in range(hmin, hmax):
        tranche = df_assign[
            (df_assign["heure_pphpd"] >= h)
            & (df_assign["heure_pphpd"] < h + 1)
            & (~df_assign["vide_voyageur"])
        ]

        for direction in ["Paris", "Province"]:
            capacite_totale = 0

            for _, row in tranche.iterrows():
                try:
                    num = int(row["marche"])
                except Exception:
                    continue

                # Direction via numéro pair/impair
                if (num % 2 == 0 and direction == "Paris") or (
                    num % 2 == 1 and direction == "Province"
                ):

                    rame = row["rame"]
                    for key, info in parc.items():
                        if info["numero"] <= rame < info["numero"] + info["quantite"]:
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

HEURE_MIN = 0
HEURE_MAX = 24
ECHELLE_HEURE = (PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN) / (HEURE_MAX - HEURE_MIN)

# Fenêtre de référence pour la performance (en heure décimale)
WINDOW_START = 5.5   # 5h30
WINDOW_END   = 22.5  # 22h30
WINDOW_DURATION = WINDOW_END - WINDOW_START  # 17h

# Décalage horizontal (en points) pour la première / dernière gare
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


def get_materiel_code_from_rame(rame_id):
    """Retourne le code matériel (R2N / BGC / REG / 2NPG) à partir d'un numéro de rame."""
    for code, info in parc.items():
        if info["numero"] <= rame_id < info["numero"] + info["quantite"]:
            return code
    return None


# ------------------ Page paramètres ------------------
def draw_params_page(c, materiel_code, titre_suffix):
    """Ajoute une page récap avec les paramètres de l'algo d'attribution + flux pour ce matériel."""
    global FLUX_PAR_AXE

    c.showPage()

    # Titre de la page
    titre = f"Paramètres de l'attribution – {titre_suffix}"
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
        txt_line = (f"• {code} – {info['modele']}: "
                    f"{info['quantite']} rames (numéros {info['numero']} à {info['numero'] + info['quantite'] - 1}), "
                    f"{info['places']} places par rame")
        c.drawString(LEFT_MARGIN, y, txt_line)
        y -= line_height
        if y < BOTTOM_MARGIN + 80:
            c.showPage()
            y = PAGE_HEIGHT - TOP_MARGIN

    # --- Équilibre des flux par axe (tableaux) POUR CE MATERIEL ---
    y -= line_height // 2
    if y < BOTTOM_MARGIN + 80:
        c.showPage()
        y = PAGE_HEIGHT - TOP_MARGIN

    c.setFont("Helvetica-Bold", 10)
    c.drawString(LEFT_MARGIN, y, "Équilibre des flux par axe (Arrivées - Départs)")
    y -= line_height

    col_gare_x = LEFT_MARGIN
    col_dep_x = LEFT_MARGIN + 80
    col_arr_x = LEFT_MARGIN + 150
    col_diff_x = LEFT_MARGIN + 230
    row_h = 12

    for axe_label, info in FLUX_PAR_AXE.items():
        flux_df = info.get("flux")
        fichier = info.get("fichier", "")
        materiels = info.get("materiels", [])

        # Ne montrer que les axes où ce matériel est engagé
        if materiel_code not in materiels:
            continue

        if flux_df is None or flux_df.empty:
            continue

        if y < BOTTOM_MARGIN + 60:
            c.showPage()
            y = PAGE_HEIGHT - TOP_MARGIN
            c.setFont("Helvetica-Bold", 10)
            c.drawString(LEFT_MARGIN, y, "Équilibre des flux par axe (Arrivées - Départs)")
            y -= line_height

        # Titre de l'axe
        c.setFont("Helvetica-Bold", 9)
        titre_axe = f"{fichier} (axe : {axe_label})"
        c.drawString(LEFT_MARGIN, y, titre_axe)
        y -= row_h

        # En-têtes du tableau
        c.setFont("Helvetica-Bold", 8)
        c.drawString(col_gare_x, y, "Gare")
        c.drawString(col_dep_x,  y, "Départs")
        c.drawString(col_arr_x,  y, "Arrivées")
        c.drawString(col_diff_x, y, "Diff (Arr-Dep)")
        y -= row_h

        # Contenu du tableau
        c.setFont("Helvetica", 8)
        for _, row in flux_df.iterrows():
            if y < BOTTOM_MARGIN + 40:
                c.showPage()
                y = PAGE_HEIGHT - TOP_MARGIN
                c.setFont("Helvetica-Bold", 8)
                c.drawString(col_gare_x, y, "Gare")
                c.drawString(col_dep_x,  y, "Départs")
                c.drawString(col_arr_x,  y, "Arrivées")
                c.drawString(col_diff_x, y, "Diff (Arr-Dep)")
                y -= row_h
                c.setFont("Helvetica", 8)

            # la gare est dans la première colonne après reset_index()
            gare = str(row.iloc[0])

            dep = int(row.get("Departs", 0))
            arr = int(row.get("Arrivees", 0))
            diff = int(row.get("Diff (Arr - Dep)", 0))

            c.drawString(col_gare_x, y, gare)
            c.drawRightString(col_dep_x + 30,  y, str(dep))
            c.drawRightString(col_arr_x + 30,  y, str(arr))
            c.drawRightString(col_diff_x + 40, y, str(diff))
            y -= row_h

        y -= row_h  # espace entre axes


# ------------------ PDF par matériel ------------------
def draw_pdf_for_material(df_assign_mat, materiel_code):
    """
    Génère un PDF pour un type de matériel donné (R2N, BGC, REG, 2NPG).
    """
    if df_assign_mat.empty:
        return

    # --- Liste complète des rames du matériel (utilisées + inutilisées) ---
    info = parc[materiel_code]
    premier = info["numero"]
    dernier = info["numero"] + info["quantite"] - 1
    all_rames = list(range(premier, dernier + 1))

    rames_utilisees = sorted(df_assign_mat["rame"].unique())
    rames_inutilisees = [r for r in all_rames if r not in rames_utilisees]

    # Ajouter des lignes pour rames inutilisées
    lignes_vides = []
    for rame in rames_inutilisees:
        gare_dodo = DEPOT_AFFECTATION.get(materiel_code, "MBC")
        lignes_vides.append({
            "rame": rame,
            "marche": None,
            "gare_depart": gare_dodo,
            "depart": None,
            "gare_arrivee": gare_dodo,
            "arrivee": None,
            "vide_voyageur": False,
            "distance_km": 0,
            "axe": "Non utilisée",
            "gare_dortoir": gare_dodo
        })

    if lignes_vides:
        df_vides = pd.DataFrame(lignes_vides)
        df_vides = df_vides.loc[:, ~(df_vides.isna().all())]  # évite warning pandas
        df_assign_mat = pd.concat([df_assign_mat, df_vides], ignore_index=True)

    # Rame list complète
    rame_list = sorted(df_assign_mat["rame"].unique())

    nom_pdf = f"roulements_{materiel_code}.pdf"
    c = canvas.Canvas(nom_pdf, pagesize=A4)

    # ------- Titre PDF -------
    titre = f"Roulements – {materiel_code}"
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(PAGE_WIDTH / 2, PAGE_HEIGHT - 20, titre)

    # Km par rame
    df_km_par_rame = (
        df_assign_mat[~df_assign_mat["vide_voyageur"]]
        .groupby("rame")["distance_km"]
        .sum()
        .reset_index()
    )

    # Début / fin de journée
    df_sorted_dep = df_assign_mat.sort_values("depart")
    firsts = df_sorted_dep.groupby("rame").first()
    df_sorted_arr = df_assign_mat.sort_values("arrivee")
    lasts = df_sorted_arr.groupby("rame").last()

    start_station = firsts["gare_depart"].to_dict()
    end_station = lasts["gare_arrivee"].to_dict()

    # Numérotation lignes
    nb_rames = len(rame_list)
    rame_to_line = {rame: i + 1 for i, rame in enumerate(rame_list)}

    # Compatibilités roulées
    compatible = {i + 1: [] for i in range(nb_rames)}

    for i, rame_i in enumerate(rame_list):
        li = i + 1
        end_i = end_station.get(rame_i)

        for j, rame_j in enumerate(rame_list):
            lj = j + 1
            if end_i is not None and start_station.get(rame_j) == end_i and li != lj:
                compatible[li].append(lj)

        if not compatible[li]:
            compatible[li].append(li)

    next_line = {}
    matchR = {}

    def dfs_match(i, seen):
        for j in compatible[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in matchR or dfs_match(matchR[j], seen):
                matchR[j] = i
                return True
        return False

    for i in range(1, nb_rames + 1):
        dfs_match(i, set())

    for j, i in matchR.items():
        next_line[i] = j

    for i in range(1, nb_rames + 1):
        if i not in next_line:
            next_line[i] = (i % nb_rames) + 1

    prev_line = {i: i for i in range(1, nb_rames + 1)}
    for i, j in next_line.items():
        prev_line[j] = i

    # Performance
    df_voy = df_assign_mat[~df_assign_mat["vide_voyageur"]].copy()
    if not df_voy.empty:
        df_voy["depart_clip"] = df_voy["depart"].clip(lower=WINDOW_START, upper=WINDOW_END)
        df_voy["arrivee_clip"] = df_voy["arrivee"].clip(lower=WINDOW_START, upper=WINDOW_END)
        df_voy["duree_fenetre"] = (df_voy["arrivee_clip"] - df_voy["depart_clip"]).clip(lower=0)
        df_perf_par_rame = (
            df_voy.groupby("rame")["duree_fenetre"].sum().reset_index()
        )
        df_perf_par_rame["taux_utilisation"] = (
            df_perf_par_rame["duree_fenetre"] / WINDOW_DURATION * 100.0
        )
    else:
        df_perf_par_rame = pd.DataFrame(columns=["rame", "duree_fenetre", "taux_utilisation"])

    # Dessin des rames
    y_start = PAGE_HEIGHT - TOP_MARGIN
    rame_counter = 0
    # ===== Détection des unités multiples (UM) =====
    um_by_marche = (
        df_assign_mat.groupby("marche")["rame"]
        .apply(list)
        .to_dict()
    )
    # ===============================================

    for rame in rame_list:

        if rame_counter >= MAX_RAMES_PER_PAGE:
            c.showPage()
            y_start = PAGE_HEIGHT - TOP_MARGIN
            rame_counter = 0

        sous_df = df_assign_mat[df_assign_mat["rame"] == rame].sort_values("depart")

        cadre_top = y_start
        cadre_bottom = y_start - RAME_HEIGHT
        y_line = cadre_bottom + (RAME_HEIGHT / 2)

        # ---- Roulement ----
        ligne_auj = rame_to_line[rame]
        ligne_demain = next_line[ligne_auj]
        ligne_hier = prev_line[ligne_auj]

        axe_label = " / ".join(sous_df["axe"].dropna().unique()) or "axe inconnu"
        texte_roulement = f"{ligne_hier} ➜ {ligne_auj} ➜ {ligne_demain}"

        # Cadre
        c.setStrokeColor(colors.HexColor("#3A7ECB"))
        c.rect(LEFT_MARGIN, cadre_bottom,
               PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN,
               RAME_HEIGHT)

        # Titre rame + axe
        c.setFont("Helvetica-Bold", 5)
        c.setFillColor(colors.magenta)
        c.drawString(LEFT_MARGIN + 6, cadre_top - 12, texte_roulement)
        c.setFillColor(colors.green)
        c.drawString(LEFT_MARGIN + 30, cadre_bottom + 4, axe_label)

        # Performance
        perf_row = df_perf_par_rame.loc[df_perf_par_rame["rame"] == rame]
        if not perf_row.empty:
            perf_val = perf_row["taux_utilisation"].values[0]
            c.setFont("Helvetica-Bold", 5)
            c.setFillColor(colors.green)
            c.drawRightString(PAGE_WIDTH - RIGHT_MARGIN - 6,
                              cadre_bottom + 4,
                              f"Perf : {perf_val:.0f}%")
            c.setFillColor(colors.black)

        # Km total
        km_row = df_km_par_rame.loc[df_km_par_rame["rame"] == rame]
        if not km_row.empty:
            km_val = int(km_row["distance_km"].values[0])
            c.setFont("Helvetica-Bold", 5)
            c.setFillColor(colors.blue)
            c.drawString(LEFT_MARGIN + 6, cadre_bottom + 4, f"{km_val} km")
            c.setFillColor(colors.black)

        # === RAME INUTILISÉE ===
        if sous_df["marche"].isna().all():
            gare_dodo = sous_df.iloc[0]["gare_dortoir"]
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(colors.darkgray)
            c.drawCentredString(
                (LEFT_MARGIN + PAGE_WIDTH - RIGHT_MARGIN) / 2,
                y_line + 5,
                f"Rame garée à : {gare_dodo}"
            )
            y_start -= (RAME_HEIGHT + ESPACEMENT_RAME)
            rame_counter += 1
            continue
        # =======================

        # Ligne centrale
        c.setStrokeColor(colors.black)
        #c.line(LEFT_MARGIN, y_line, PAGE_WIDTH - RIGHT_MARGIN, y_line)

        # Traits horaires
        c.setFont("Helvetica", 4)
        for h in range(HEURE_MIN, HEURE_MAX + 1):
            xh = x_from_time(h)
            c.setLineWidth(.8) 
            c.setStrokeColor(colors.lightgrey)
            c.setDash(1, 2)
            c.line(xh, cadre_bottom, xh, cadre_top,)
            c.setDash()
            c.setFillColor(colors.black)
            c.drawString(xh - 5, cadre_top - 6, f"{h}h")
            c.setLineWidth(1) 


        # === Marches classiques ===
        prev_node = None
        prev_arrivee = None
        premiere_marche = True

        for _, row in sous_df.iterrows():
            # ===== Détection UM pour cette marche =====
            marche = row["marche"]
            um_list = um_by_marche.get(marche, [])
            is_um = len(um_list) >= 2
            is_current_lead = (is_um and rame == um_list[0])
            # ==========================================

            x1 = x_from_time(row["depart"])
            x2 = x_from_time(row["arrivee"])

            if x2 < LEFT_MARGIN:
                continue
            if x1 > PAGE_WIDTH - RIGHT_MARGIN:
                continue

            x1 = max(x1, LEFT_MARGIN + 2)
            x2 = min(x2, PAGE_WIDTH - RIGHT_MARGIN - 2)

            if row.get("vide_voyageur", True):
                bar_color = colors.lightgrey
            else:
                bar_color = colors.black
            # ===== Choix épaisseur selon UM =====
            if is_um:
                if is_current_lead:
                    draw_train_bar(c, x1, x2, y_line+ 1.5, height=3, color=bar_color)
                    draw_train_bar(c, x1, x2, y_line- 2, height=0.75, color=bar_color)
                else:
                    draw_train_bar(c, x1, x2, y_line+ 2, height=0.75, color=bar_color)
                    draw_train_bar(c, x1, x2, y_line- 1.5, height=3, color=bar_color)
            else:
                    draw_train_bar(c, x1, x2, y_line, height=5, color=bar_color) # Cas normal

            # if row.get("vide_voyageur", False):
            #     # === HLP → ligne ondulée ===
            #     draw_wave_bar(c, x1, x2, y_line, amplitude=2, wavelength=8, color=colors.lightgrey)
            # else:
            #     # === Marche voyageurs → barre normale ===
            #     draw_train_bar(c, x1, x2, y_line, height=5, color=colors.black)

            # ====================================

            gare_dep = str(row["gare_depart"])
            gare_arr = str(row["gare_arrivee"])
            heure_dep = format_time_hm(row["depart"])
            heure_arr = format_time_hm(row["arrivee"])

            depart_label_deja_fait = False
            c.setFillColor(colors.black)

            # --- Affichage de la gare de départ ---
            if prev_node is not None:
                if prev_node["gare"] == gare_dep:
                    # Gares identiques → on affiche au milieu
                    xm = (prev_node["x"] + x1) / 2.0
                    y_base = y_line - 7

                    c.setFont("Helvetica", 5)
                    c.drawCentredString(xm, y_base, gare_dep)

                    draw_time_only(c, prev_node["x"], y_base - 5, prev_node["heure"], "center")
                    draw_time_only(c, x1, y_base - 10, heure_dep, "center")

                    depart_label_deja_fait = True
                else:
                    # On affiche la gare précédente à droite
                    draw_station_label(
                        c,
                        prev_node["x"] - 1,
                        y_line - 7,
                        prev_node["gare"],
                        prev_node["heure"],
                        align="right",
                    )

            if not depart_label_deja_fait:
                base_x = x1 + 1
                if premiere_marche:
                    x_depart = base_x - FIRST_LABEL_OFFSET
                else:
                    x_depart = base_x

                draw_station_label(
                    c, x_depart, y_line - 7, gare_dep, heure_dep, align="left"
                )

            # --- Numéro de marche ---
            c.setFont("Helvetica", 5)
            c.setFillColor(colors.darkgray)
            marche=str(row["marche"])
            if "EVM" in marche or "EVO" in marche or "EVI" in marche or "EVS" in marche:
                marche_text = "HLP"
            else:
                marche_text = str(row["marche"])
            y_num = y_line + (12 if row.get("vide_voyageur", False) else 7)
            c.drawCentredString((x1 + x2) / 2, y_num, marche_text)

            # --- Affichage des écarts trop courts ---
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
            prev_node = {"gare": gare_arr, "x": x2, "heure": heure_arr}
            premiere_marche = False


        # === AFFICHAGE DE LA DERNIÈRE GARE ===
        if prev_node is not None:
            x_last = prev_node["x"] + LAST_LABEL_OFFSET
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

    # Dernière page : paramètres
    draw_params_page(c, materiel_code, f"Matériel {materiel_code}")
    c.save()
    print(f"PDF généré : {nom_pdf}")

# ------------------ Boucle principale ------------------
def process_and_generate():
    global FLUX_PAR_AXE
    FLUX_PAR_AXE = {}

    # Load maintenance JSON
    with open("gestion_maintenance.json", "r", encoding="utf-8") as f:
        maintenance_data = json.load(f)

    # reset parc usage counters
    for k in parc:
        parc[k]["utilise"] = 0

    if not os.path.exists(DOSSIER_JSON):
        print(f"⚠️ Dossier {DOSSIER_JSON} introuvable.")
        return

    all_assignments = []
    pphpd_par_axe = {}

    # ------------------------ 1) AFFECTATION DES MARCHES ------------------------
    for fichier_json in sorted(os.listdir(DOSSIER_JSON)):

        if not fichier_json.endswith(".json"):
            continue

        chemin_json = os.path.join(DOSSIER_JSON, fichier_json)
        with open(chemin_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        base = os.path.splitext(fichier_json)[0]
        if base.startswith("marches_"):
            base = base[len("marches_"):]
        axe_label = base.replace("-", " – ")

        df = pd.DataFrame(data).sort_values("depart").reset_index(drop=True)
        rame_state = {}
        assignments = []

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
                marche_navette = navette_mat(candidate, gare_dep, depart, tampon_15m, navette_time)
                if marche_navette:
                    assignments.append(marche_navette)
                rame_state[candidate] = {"gare": gare_dep, "dispo": 0}

            assignments.append({
                "rame": candidate,
                "marche": train["marche"],
                "gare_depart": train["gare_depart"],
                "depart": train["depart"],
                "gare_arrivee": train["gare_arrivee"],
                "arrivee": train["arrivee"],
                "vide_voyageur": train.get("vide_voyageur", False)
            })

            rame_state[candidate]["gare"] = train["gare_arrivee"]
            rame_state[candidate]["dispo"] = train["arrivee"]

        # Ajouter navettes du soir
        for rame_id, state in rame_state.items():
            soir = navette_soir(rame_id, state["gare"], state["dispo"])
            if soir:
                assignments.append(soir)

        # Marquer axe ferroviaire
        for a in assignments:
            a["axe"] = axe_label

        all_assignments.extend(assignments)

        # stats par axe
        df_assign_file = pd.DataFrame(assignments)
        df_assign_file["vide_voyageur"] = df_assign_file["vide_voyageur"].astype("boolean").fillna(False)
        df_assign_file["distance_km"] = df_assign_file.apply(get_distance_safe, axis=1)
        df_assign_file["materiel"] = df_assign_file["rame"].apply(get_materiel_code_from_rame)

        premiers_depart = df_assign_file.sort_values("depart").groupby("rame").first()
        dernieres_arrivee = df_assign_file.sort_values("arrivee").groupby("rame").last()
        depart_counts = premiers_depart["gare_depart"].value_counts().rename("Departs")
        arrivee_counts = dernieres_arrivee["gare_arrivee"].value_counts().rename("Arrivees")
        flux_balance = pd.concat([depart_counts, arrivee_counts], axis=1).fillna(0).astype(int)
        flux_balance["Diff (Arr - Dep)"] = flux_balance["Arrivees"] - flux_balance["Departs"]

        FLUX_PAR_AXE[axe_label] = {
            "fichier": fichier_json,
            "flux": flux_balance.reset_index(),
            "materiels": sorted(df_assign_file["materiel"].dropna().unique().tolist()),
        }

        pphpd_par_axe[axe_label] = calcul_pphpd_par_direction(df_assign_file, parc)

    # Si aucune marche
    if not all_assignments:
        print("Aucun assignment global généré.")
        return


    # ------------------------ 2) INJECTION MAINTENANCE ------------------------
    df_assign_global = pd.DataFrame(all_assignments)
    df_assign_global["vide_voyageur"] = df_assign_global["vide_voyageur"].astype("boolean").fillna(False)
    df_assign_global["distance_km"] = df_assign_global.apply(get_distance_safe, axis=1)
    df_assign_global["materiel"] = df_assign_global["rame"].apply(get_materiel_code_from_rame)

    # ------------------ 2) AFFECTATION DES MAINTENANCES (mimique des trains) ------------------

    maintenance_rows = []

    for code in parc.keys():

        df_mat = df_assign_global[df_assign_global["materiel"] == code].copy()
        if df_mat.empty:
            continue

        if code not in maintenance_data:
            continue

        slots = maintenance_data[code]["slots"]

        # état dynamique des rames comme pour les trains
        rame_state = {}

        # initialisation état rame + leurs marches existantes
        rame_timetable = {}
        for rame, grp in df_mat.groupby("rame"):
            grp = grp.sort_values("depart")
            rame_timetable[rame] = grp[["depart", "arrivee", "gare_arrivee"]].to_dict("records")
            rame_state[rame] = {
                "gare": grp.iloc[-1]["gare_arrivee"],
                "dispo": grp.iloc[-1]["arrivee"]
            }

        # tri des slots du plus long au plus court
        slots = sorted(slots, key=lambda s: -s["duration_minutes"])

        for slot in slots:
            duration = slot["duration_minutes"] / 60.0
            win_start, win_end = slot["window"]
            location = slot["location"]

            placed = False

            # Essayer chaque rame disponible
            for rame_id in sorted(rame_state.keys()):
                timetable = rame_timetable[rame_id]

                # Filtrer uniquement les événements dans la fenêtre
                events = [(win_start, win_start, location)]  # borne début
                for ev in timetable:
                    if ev["depart"] <= win_end and ev["arrivee"] >= win_start:
                        events.append((ev["depart"], ev["arrivee"], ev["gare_arrivee"]))
                events.append((win_end, win_end, location))  # borne fin
                events = sorted(events)

                # Essayer de trouver un trou
                for i in range(len(events) - 1):
                    end_prev = events[i][1] + 1   # tampon 1h après
                    start_next = events[i+1][0] - 1 # tampon 1h avant

                    free_start = max(end_prev, win_start)
                    free_end   = min(start_next, win_end)

                    if free_end - free_start >= duration:

                        # vérifier que la rame est dans la bonne gare dans ce trou
                        # gare = arrivée du dernier évènement valable
                        last_gare = events[i][2]
                        if last_gare != location:
                            continue

                        maintenance_rows.append({
                            "rame": rame_id,
                            "marche": f"MAINT-{code}-{round(free_start,2)}",
                            "gare_depart": location,
                            "depart": free_start,
                            "gare_arrivee": location,
                            "arrivee": free_start + duration,
                            "vide_voyageur": True,
                            "materiel": code,
                            "axe": "MAINTENANCE"
                        })

                        # mise à jour des états
                        rame_state[rame_id]["dispo"] = free_start + duration
                        rame_state[rame_id]["gare"] = location

                        # ajouter au planning
                        rame_timetable[rame_id].append({
                            "depart": free_start,
                            "arrivee": free_start + duration,
                            "gare_arrivee": location
                        })

                        print(f"🛠 Maintenance placée: {code} → rame {rame_id} ({duration}h entre {round(free_start,2)}h et {round(free_start+duration,2)}h)")
                        placed = True
                        break

                if placed:
                    break

            if not placed:
                print(f"⚠️ IMPOSSIBLE : {code} maintenance ({duration}h) dans fenêtre {win_start}-{win_end}")

    # merge
    if maintenance_rows:
        df_assign_global = pd.concat([df_assign_global, pd.DataFrame(maintenance_rows)], ignore_index=True)
        df_assign_global = df_assign_global.sort_values("depart")


    # ------------------------ 3) EXPORT PDF ------------------------
    generate_pphpd_global(pphpd_par_axe)

    for code in parc.keys():
        df_mat = df_assign_global[df_assign_global["materiel"] == code].copy()
        if df_mat.empty:
            continue

        print(f"\n=== Maintenances appliquées pour {code} ===")
        print(df_mat[df_mat["marche"].astype(str).str.startswith("MAINT")][["rame","marche","gare_depart","depart","gare_arrivee","arrivee"]])

        draw_pdf_for_material(df_mat, code)

    print("\n✅ Process terminé avec maintenance + tampon EVO intégrés.")

def generate_pphpd_global(pphpd_par_axe):
    from reportlab.lib.utils import ImageReader

    PAGE_WIDTH, PAGE_HEIGHT = A4
    nom_pdf = "PPHPD_global.pdf"

    c = canvas.Canvas(nom_pdf, pagesize=A4)
    # ========= PAGE 1 : TITRE + TEXTE TECHNIQUE =========
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(PAGE_WIDTH/2, PAGE_HEIGHT - 40, "PPHPD – Global")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, PAGE_HEIGHT - 90, "Méthode de calcul du PPHPD")

    c.setFont("Helvetica", 10)
    text = [
        "Le PPHPD (Place Par Heure et par Direction) permet d’estimer la",
        "capacité théorique maximale offerte par l’exploitation, heure par heure.",
        "",
        "Règles appliquées :",
        " • Avant 12h : le PPHPD est calculé à partir de l’heure d’arrivée des trains.",
        " • Après 12h : le PPHPD est calculé à partir de l’heure de départ.",
        " • Les marches vides voyageurs (HLP, navettes, évolutions) sont exclues.",
        " • La direction est déterminée par le numéro de marche :",
        "      - Numéro pair   → direction Paris",
        "      - Numéro impair → direction Province",
    ]

    y = PAGE_HEIGHT - 120
    for line in text:
        c.drawString(40, y, line)
        y -= 14

    c.showPage()
    # ========= FIN PAGE INTRO =========

    # Mise en page : 2 graphiques par page
    graphs_per_page = 0
    current_y = PAGE_HEIGHT - 80
    graph_height = 200
    left_margin = 40
    right_margin = 40

    for axe, df in pphpd_par_axe.items():
        if df.empty:
            continue

        dfp = df.pivot(index="heure", columns="direction", values="pphpd").fillna(0)

        # Génération du graphe
        plt.figure(figsize=(8, 3))
        for col in dfp.columns:
            plt.plot(dfp.index, dfp[col], marker="o", label=col)
        plt.title(f"PPHPD – {axe}")
        plt.grid(True)
        plt.legend()

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
        plt.savefig(tmp.name, dpi=150, bbox_inches='tight')
        plt.close()

        # Nouvelle page si on a déjà 2 graphiques sur la page
        if graphs_per_page >= 2:
            c.showPage()
            graphs_per_page = 0
            current_y = PAGE_HEIGHT - 80

        img = ImageReader(tmp.name)

        # Titre de l'axe
        c.setFont("Helvetica-Bold", 14)
        c.drawString(left_margin, current_y, f"Axe : {axe}")

        # Positionnement de l'image juste en dessous
        img_top = current_y - 20
        img_width = PAGE_WIDTH - left_margin - right_margin
        img_height = graph_height
        c.drawImage(
            img,
            left_margin,
            img_top - img_height,
            width=img_width,
            height=img_height,
            preserveAspectRatio=True,
        )

        graphs_per_page += 1
        current_y = img_top - img_height - 40  # espace avant le prochain graphe

        try:
            os.unlink(tmp.name)
        except PermissionError:
            pass

    c.save()
    print(f"PDF global PPHPD généré : {nom_pdf}")


if __name__ == "__main__":
    process_and_generate()

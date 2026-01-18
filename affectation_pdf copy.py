import json
import pandas as pd
import os
import matplotlib.pyplot as plt
import tempfile
import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm
import unicodedata
import re




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
    "R2N":    {"modele": "Regio2n",   "numero": 22201, "quantite": 4,  "utilise": 0, "places": 505},
    "BGC":    {"modele": "BGC",       "numero": 81501, "quantite": 27,  "utilise": 0, "places": 200},
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

AXES_OUEST = {
    "marseille-avignon",
    "marseille-avignon-via-rognac",
    "marseille-miramas-via-cote-bleue",
    "vallee-du-rhone",
    "avignon-tgv-carpentras",
    "marseille-aix-en-provence"
}

AXES_EST = {
    
    "marseille-aubagne",
    "marseille-toulon-hyeres-les-arcs-draguignan",
    "marseille-briancon",
    "intervilles-marseille-lyon",
}


# Stockage de l’équilibre des flux par axe (pour affichage dans les PDF matériels)
# FLUX_PAR_AXE[axe_label] = {"fichier": ..., "flux": df, "materiels": [codes]}
FLUX_PAR_AXE = {}




def normalize_axe_name(name: str) -> str:
    """
    Normalise un nom d'axe pour comparaison :
    - minuscules
    - suppression accents
    - tirets uniformes
    - pas d'espaces parasites
    """
    name = name.lower()
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.replace("–", "-").replace("—", "-")
    name = re.sub(r"\s*-\s*", "-", name)
    name = re.sub(r"\s+", "-", name)
    return name.strip("-")


def map_direction_pphpd(direction, axe):
    direction = direction.lower()
    axe_norm = normalize_axe_name(axe)

    if axe_norm in AXES_OUEST:
        return {
            "province": "Marseille",
            "paris": "Banlieue",
        }.get(direction, direction.capitalize())

    if axe_norm in AXES_EST:
        return {
            "province": "Banlieue",
            "paris": "Marseille",
        }.get(direction, direction.capitalize())

    # Axe inconnu → fallback sûr
    return direction.capitalize()


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
        key = "R2N" if parc["R2N"]["utilise"] < parc["R2N"]["quantite"] else "REG"
    
    elif nom_ligne == "marches_marseille-briancon.json":
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

# ------------------ Layout PDF ------------------

# ------------------ PDF par matériel ------------------

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
        "Le PPHPD (Personnes Par Heure et par Direction) permet d’estimer la",
        "capacité théorique maximale offerte sur un axe.",
        "",
        "Règles appliquées :",
        " • Avant 12h : le PPHPD est calculé à partir de l’heure d’arrivée des trains.",
        " • Après 12h : le PPHPD est calculé à partir de l’heure de départ.",
        " • Les marches vides voyageurs sont exclues.",
        " • La direction est déterminée par le numéro de marche et l'axe de la ligne:",
        "      - Numéro pair   → sens ouest",
        "      - Numéro impair → sens est",
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

        # ======================
        # Génération du graphe
        # ======================
        plt.figure(figsize=(8, 3))

        x = np.arange(len(dfp.index))          # positions numériques des heures
        width = 0.35                           # largeur des barres
        n_cols = len(dfp.columns)

        for i, col in enumerate(dfp.columns):
            plt.bar(
                x + (i - n_cols / 2) * width + width / 2,
                dfp[col].values,
                width=width,
                label=col
            )

        plt.title(f"PPHPD – {axe}")
        plt.xlabel("Heure")
        plt.ylabel("PPHPD")
        plt.xticks(x, dfp.index)               # une barre par heure
        plt.grid(axis="y", linestyle="--", alpha=0.5)
        plt.legend()

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        plt.savefig(tmp.name, dpi=150, bbox_inches="tight")
        plt.close()

        # ======================
        # Gestion du PDF
        # ======================
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
        current_y = img_top - img_height - 40

        try:
            os.unlink(tmp.name)
        except PermissionError:
            pass


    c.save()
    print(f"PDF global PPHPD généré : {nom_pdf}")


if __name__ == "__main__":
    AXES_OUEST = {
        normalize_axe_name(a) for a in AXES_OUEST
    }

    AXES_EST = {
        normalize_axe_name(a) for a in AXES_EST
    }
    process_and_generate()
    

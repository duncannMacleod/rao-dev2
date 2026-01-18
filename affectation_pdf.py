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
from collections import defaultdict

import unicodedata
import re




# ------------------ Paramètres généraux ------------------
DOSSIER_JSON = "marches_json"
KM_MARCHES_FILE = "km_marches.json"

# Paramètres 
navette_time = 0.083
tampon = 0.333
tampon_15m = 0.25
temps_minimal = 0.21
seuil_atelier = 1.25

# Parc de rames
parc = {
    #"R2N_OP": {"modele": "Regio2n_omneo_premium",   "numero": 59001, "quantite": 2,  "utilise": 0, "places": 505},
    "R2N": {"modele": "Regio2n",                    "numero": 57001, "quantite": 40,  "utilise": 0, "places": 505},
    "BGC":    {"modele": "BGC",                     "numero": 81501, "quantite": 27,  "utilise": 0, "places": 200},
    "REG":    {"modele": "Regiolis",                "numero": 84501, "quantite": 15,  "utilise": 0, "places": 220},
    "2NPG":   {"modele": "2NPG",                    "numero": 23501, "quantite": 30,  "utilise": 0, "places": 210},
    "XTER":   {"modele": "XTER",                    "numero": 72501, "quantite": 2,  "utilise": 0, "places": 300},

}

# Gare où les rames sont affectés en dépôt
DEPOT_AFFECTATION = {
    "R2N": ["AVG", "MBC"],
    "BGC": ["AVG"],
    "REG": ["MBC", "AVG"],
    "2NPG": ["MBC"],
    "XTER": ["MBC"]
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

MAINT_TYPE_COLORS = {
    "terre_plein": "#1f77b4",   # bleu
    "toiture":     "#ff7f0e",   # orange
    "fosse":       "#2ca02c",   # vert
    "verin_fosse": "#d62728"    # rouge
}

MAINT_TYPE_ORDER = {
    "terre_plein": 0,
    "toiture": 1,
    "fosse": 2,
    "verin_fosse": 3
}


# Stockage de l’équilibre des flux par axe (pour affichage dans les PDF matériels)
# FLUX_PAR_AXE[axe_label] = {"fichier": ..., "flux": df, "materiels": [codes]}
FLUX_PAR_AXE = {}

def plot_repartition_flotte_par_ligne(df_assign_mat):
    """
    Répartition de la flotte par ligne avec total par matériel en légende.
    """

    import matplotlib.pyplot as plt

    # ─────────────────────────────────────────────
    # 1) Nettoyage
    # ─────────────────────────────────────────────
    df = df_assign_mat.copy()
    df = df[~df["axe"].astype(str).str.upper().str.contains("MAINT")]

    df["axe_norm"] = df["axe"].apply(normalize_axe_name)

    # ─────────────────────────────────────────────
    # 2) Une rame = un axe
    # ─────────────────────────────────────────────
    rame_axe = (
        df.sort_values("depart")
        .groupby("rame")
        .first()[["axe_norm", "materiel"]]
        .reset_index()
    )

    # ─────────────────────────────────────────────
    # 3) Comptage par axe / matériel
    # ─────────────────────────────────────────────
    table = (
        rame_axe
        .groupby(["axe_norm", "materiel"])
        .size()
        .unstack(fill_value=0)
    )

    # Totaux par matériel (pour la légende)
    total_par_materiel = (
        rame_axe
        .groupby("materiel")["rame"]
        .nunique()
        .to_dict()
    )

    # ─────────────────────────────────────────────
    # 4) Ordre des axes
    # ─────────────────────────────────────────────
    axes_ouest = [a for a in table.index if a in AXES_OUEST]
    axes_est   = [a for a in table.index if a in AXES_EST]

    table = table.loc[axes_ouest + axes_est]

    labels = [a.replace("-", " ").title() for a in table.index]

    # ─────────────────────────────────────────────
    # 5) Plot
    # ─────────────────────────────────────────────
    colors = {
        "R2N": "#2C5876",
        "BGC": "#E07A3F",
        "2NPG": "#2E6B2D",
        "REG": "#4FA3D1",
        "XTER": "#8E44AD",
    }

    fig, ax = plt.subplots(figsize=(13, 6))

    left = [0] * len(table)

    for mat in table.columns:
        values = table[mat].values
        ax.barh(
            labels,
            values,
            left=left,
            label=f"{mat} ({total_par_materiel.get(mat, 0)})",
            color=colors.get(mat, "#7f7f7f")
        )
        left = [l + v for l, v in zip(left, values)]

    # Séparateur Ouest / Est
    if axes_ouest:
        ax.axhline(len(axes_ouest) - 0.5, color="black", linewidth=1)

    # ─────────────────────────────────────────────
    # 6) Mise en forme
    # ─────────────────────────────────────────────
    ax.set_title("Répartition de la flotte par ligne")
    ax.set_xlabel("Nombre de rames")
    ax.invert_yaxis()
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    ax.legend(title="Matériel (total utilisé)")

    plt.tight_layout()
    plt.show()


def split_used_and_unused_rames(df_assign_mat, materiel_code, parc):
    """
    Sépare les rames :
    - utilisées : au moins une vraie marche (hors MAINT et hors None)
    - inutilisées : présentes au parc mais sans marche réelle

    Retourne :
    - rame_list_used : liste triée des rames utilisées
    - rames_inutilisees : liste triée des rames inutilisées
    """

    # Rames avec au moins une vraie marche
    df_real = df_assign_mat[
        df_assign_mat["marche"].notna()
        & ~df_assign_mat["marche"].astype(str).str.startswith("MAINT")
    ]

    rame_list_used = sorted(df_real["rame"].unique())

    # Toutes les rames du parc pour ce matériel
    info = parc[materiel_code]
    all_rames = list(
        range(info["numero"], info["numero"] + info["quantite"])
    )

    rames_inutilisees = sorted(
        r for r in all_rames if r not in rame_list_used
    )

    return rame_list_used, rames_inutilisees

def compute_maintenance_occupation(df_assign_global):
    """
    Prépare les données d’occupation des voies sous forme Gantt.
    L’affectation temporelle des voies est conservée.
    Les infrastructures par voie sont réduites au strict nécessaire (logique métier).
    """

    df_maint = df_assign_global[
        (df_assign_global["axe"] == "MAINTENANCE")
        | (df_assign_global.get("type") == "MAINT")
    ].copy()

    if df_maint.empty:
        return {}

    def reduce_infra(types):
        """
        Réduction métier des besoins d'infrastructure :
        - verin_fosse domine fosse
        - toiture domine terre_plein
        - fosse domine terre_plein
        """
        t = set(types)

        if "verin_fosse" in t:
            t.discard("fosse")

        if "toiture" in t:
            t.discard("terre_plein")

        if "fosse" in t:
            t.discard("terre_plein")

        return list(t)

    occupation_by_site = {}

    for site, grp in df_maint.groupby("gare_depart"):
        grp = grp.sort_values("depart")

        voies_fin = []      # heure de libération par voie
        voies_infra = {}    # voie -> set d'infra
        rows = []

        for _, r in grp.iterrows():
            start = r["depart"]
            end = r["arrivee"]
            rame = r["rame"]
            types = set(r.get("types", []))

            # 1) affectation temporelle STRICTEMENT IDENTIQUE à ton algo initial
            voie = None
            for i, free_at in enumerate(voies_fin):
                if free_at <= start:
                    voie = i + 1
                    voies_fin[i] = end
                    break

            if voie is None:
                voies_fin.append(end)
                voie = len(voies_fin)

            # 2) accumulation brute des infra
            if voie not in voies_infra:
                voies_infra[voie] = set()
            voies_infra[voie].update(types)

            rows.append({
                "rame": rame,
                "start": start,
                "end": end,
                "voie": voie,
                "types": list(types)  # types instantanés (pour le graphe)
            })

        df_site = pd.DataFrame(rows)

        # 3) réduction métier FINALE des infra par voie
        df_site["infra_reduite"] = None

        for voie, infra in voies_infra.items():
            reduced = reduce_infra(infra)
            df_site.loc[df_site["voie"] == voie, "infra_reduite"] = df_site.loc[
                df_site["voie"] == voie
            ].apply(lambda _: reduced, axis=1)


        occupation_by_site[site] = df_site

    return occupation_by_site

def plot_maintenance_occupation(occupation_by_site):
    """
    Diagramme Gantt + synthèse infra par voie (PDF)
    """

    if not occupation_by_site:
        print("⚠️ Aucun événement de maintenance.")
        return

    from matplotlib.patches import Patch
    from reportlab.lib import colors

    nom_pdf = "occupation_voies_maintenance.pdf"
    c = canvas.Canvas(nom_pdf, pagesize=A4)

    PAGE_WIDTH, PAGE_HEIGHT = A4
    left = 50
    right = 50

    for site, df in occupation_by_site.items():
        if df.empty:
            continue

        # =========================
        # 1) PRÉPARATION DES DONNÉES
        # =========================
        df = df.copy()

        df["main_type"] = df["types"].apply(
            lambda t: t[0] if isinstance(t, list) and t else "terre_plein"
        )

        df["type_order"] = df["main_type"].map(
            lambda t: MAINT_TYPE_ORDER.get(t, 99)
        )

        # ⚠️ TRI VISUEL UNIQUEMENT (NE CHANGE PAS LES VOIES)
        df = df.sort_values(
            by=["type_order", "start", "voie"]
        )

        max_voie = df["voie"].max()

        # =========================
        # 2) GRAPHE MATPLOTLIB
        # =========================
        plt.figure(figsize=(8, 4))
        plt.tight_layout(rect=[0, 0, 1, 0.90])

        for _, r in df.iterrows():
            types = r["types"]
            main_type = r["main_type"]
            color = MAINT_TYPE_COLORS.get(main_type, "#7f7f7f")

            plt.barh(
                y=r["voie"],
                width=r["end"] - r["start"],
                left=r["start"],
                height=0.8,
                color=color,
                edgecolor="black"
            )

            # ---- label sur UNE ligne ----
            label = f"{r['rame']} – " + " + ".join(
                t.replace("_", " ") for t in types
            )

            plt.text(
                (r["start"] + r["end"]) / 2,
                r["voie"],
                label,
                ha="center",
                va="center",
                fontsize=7,
                color="white",
                zorder=4,
                clip_on=False,  # 🔑 autorise à dépasser la barre
                bbox=dict(
                    facecolor="black",
                    alpha=0.25,
                    boxstyle="round,pad=0.2"
                )
            )

        plt.yticks(range(1, max_voie + 1))
        plt.xlabel("Heure")
        plt.ylabel("Voie")
        plt.xlim(0, 24)
        plt.xticks(range(0, 25, 1))
        

        plt.suptitle(
            f"Occupation des voies journée type – site de {site}",
            fontsize=13,
            y=0.97
        )
        ax = plt.gca()
        ax.set_axisbelow(True)   # ⬅️ clé du problème
        ax.grid(axis="x", linestyle="--", alpha=0.4)

        legend_elements = [
            Patch(
                facecolor=color,
                edgecolor="black",
                label=label.replace("_", " ").title()
            )
            for label, color in MAINT_TYPE_COLORS.items()
        ]

        plt.legend(
            handles=legend_elements,
            title="Type de maintenance",
            loc="upper right"
        )

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        plt.savefig(tmp.name, dpi=300)
        plt.close()

        # =========================
        # 3) PDF – TITRE & TEXTE
        # =========================
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(
            PAGE_WIDTH / 2,
            PAGE_HEIGHT - 40,
            f"Occupation des voies – {site}"
        )

        y = PAGE_HEIGHT - 80
        c.setFont("Helvetica", 11)
        for line in [
            "Chaque barre horizontale représente une rame immobilisée sur une voie.",
            "La longueur de la barre correspond à la durée d’occupation.",
            "La couleur indique le type de maintenance effectué."
        ]:
            c.drawString(left, y, line)
            y -= 14

        # =========================
        # 4) IMAGE
        # =========================
        img_width = PAGE_WIDTH - left - right
        img_height = 300

        c.drawImage(
            tmp.name,
            left,
            PAGE_HEIGHT - 120 - img_height,
            width=img_width,
            height=img_height,
            preserveAspectRatio=True
        )

        # =========================
        # 5) INFOS GLOBALES
        # =========================
        y_info = PAGE_HEIGHT - 430
        c.setFont("Helvetica", 11)
        c.drawString(
            left,
            y_info,
            f"Nombre maximal de voies occupées simultanément : {max_voie}"
        )

        # =========================
        # 6) TABLEAU INFRA PAR VOIE
        # =========================
        
        # =========================
        # Construction infra par voie
        # =========================
        infra_by_voie = {}

        for _, r in df.iterrows():
            voie = r["voie"]
            types = set(r.get("types", []))

            if voie not in infra_by_voie:
                infra_by_voie[voie] = set()

            infra_by_voie[voie].update(types)

        types_all = ["terre_plein", "toiture", "fosse", "verin_fosse"]

        col_voie_w = 40
        col_type_w = 70
        row_h = 14

        n_rows = max_voie + 1  # en-tête + voies
        table_width = col_voie_w + len(types_all) * col_type_w

        # Titre du tableau
        table_y_start = y_info - 30
        c.setFont("Helvetica-Bold", 12)
        c.drawString(
            left,
            table_y_start,
            "Récapitulatif des infrastructures nécessaires par voie"
        )

        # Géométrie du tableau
        table_top = table_y_start - 15
        table_bottom = table_top - n_rows * row_h

        # =========================
        # Grille
        # =========================
        c.setStrokeColor(colors.lightgrey)
        c.setLineWidth(0.5)

        # lignes horizontales
        for i in range(n_rows + 1):
            y_line = table_top - i * row_h
            c.line(left, y_line, left + table_width, y_line)

        # lignes verticales
        x = left
        c.line(x, table_top, x, table_bottom)

        x += col_voie_w
        c.line(x, table_top, x, table_bottom)

        for _ in types_all:
            x += col_type_w
            c.line(x, table_top, x, table_bottom)

        # =========================
        # En-têtes
        # =========================
        c.setFont("Helvetica-Bold", 9)
        y_header = table_top - row_h + 4

        c.drawCentredString(
            left + col_voie_w / 2,
            y_header,
            "Voie"
        )

        for i, t in enumerate(types_all):
            c.drawCentredString(
                left + col_voie_w + i * col_type_w + col_type_w / 2,
                y_header,
                t.replace("_", " ").title()
            )

        # =========================
        # Contenu du tableau
        # =========================
        c.setFont("Helvetica", 9)

        for voie in range(1, max_voie + 1):
            y = table_top - (voie + 1) * row_h + 4

            # numéro de voie
            c.drawCentredString(
                left + col_voie_w / 2,
                y,
                str(voie)
            )

            # infrastructures
            for i, t in enumerate(types_all):
                mark = "✓" if t in infra_by_voie.get(voie, set()) else ""
                c.drawCentredString(
                    left + col_voie_w + i * col_type_w + col_type_w / 2,
                    y,
                    mark
                )

        c.showPage()

        try:
            os.unlink(tmp.name)
        except PermissionError:
            pass

    c.save()
    print(f"📊 PDF occupation maintenance généré : {nom_pdf}")



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
        key = "2NPG"

    elif nom_ligne == "marches_marseille-avignon.json":
        key = "2NPG"
    
    elif nom_ligne == "marches_marseille-avignon-via-rognac.json":
        key = "2NPG"
    
    elif nom_ligne == "marches_vallee-du-rhone.json":
        key = "2NPG"
        
    elif nom_ligne == "marches_marseille-briancon.json":
        key = "BGC"
        
    elif nom_ligne == "marches_marseille-aubagne.json":
        key= "REG"
        
    elif nom_ligne == "marches_marseille-aix-en-provence.json":
        key = "BGC" if parc["BGC"]["utilise"] < parc["BGC"]["quantite"] else "REG"

    elif nom_ligne == "marches_marseille-miramas-via-cote-bleue.json":
        key = "BGC" if parc["BGC"]["utilise"] < parc["BGC"]["quantite"] else "REG"
        
    elif nom_ligne == "marches_avignon-tgv-capentras.json":
        key = "BGC" if parc["BGC"]["utilise"] < parc["BGC"]["quantite"] else "REG"

    elif nom_ligne == "marches_marseille-toulon-hyeres-les-arcs-draguignan.json":
            key = "REG" if parc["REG"]["utilise"] < parc["REG"]["quantite"] else "R2N" 

    else:
        # 🔹 Choisir n'importe quel type de rame disponible
        key = None
        for k, v in parc.items():
            if v["utilise"] < v["quantite"]:
                key = k
                break

        if key is None:
            raise RuntimeError("Plus de rames disponibles dans le parc")

    if parc[key]["utilise"] >= parc[key]["quantite"]:
        raise RuntimeError(f"Plus de rames disponibles pour {parc[key]['modele']}")

    rame_id = parc[key]["numero"] + parc[key]["utilise"]
    parc[key]["utilise"] += 1
    return rame_id


def compute_maintenance_stats(df_assign_mat):
    """
    Calcule le total des heures de maintenance et le détail par site.
    """
    df_maint = df_assign_mat[
        (df_assign_mat["axe"] == "MAINTENANCE") |
        (df_assign_mat.get("type") == "MAINT")
    ].copy()

    if df_maint.empty:
        return 0.0, {}

    df_maint["duree_h"] = df_maint["arrivee"] - df_maint["depart"]

    total_hours = df_maint["duree_h"].sum()

    by_site = (
        df_maint.groupby("gare_depart")["duree_h"]
        .sum()
        .to_dict()
    )

    return total_hours, by_site

def draw_roulement_graph(
    c,
    cycles,
    line_to_rame,
    start_station,
    end_station,
    PAGE_WIDTH,
    PAGE_HEIGHT,
):
    """
    Dessine les cycles / chaînes de roulement sous forme de graphes lisibles.
    - Cycle fermé → cercle
    - Chaîne ouverte → demi-cercle
    """

    import numpy as np
    from reportlab.lib import colors

    c.showPage()
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(
        PAGE_WIDTH / 2,
        PAGE_HEIGHT - 40,
        "Graphe des roulements",
    )

    

    for idx, cycle in enumerate(cycles):

        # ===== Nettoyage du cycle (pas de doublon final) =====
        new_cycle = cycle
        if len(cycle) > 1 and cycle[0] == cycle[-1]:
            new_cycle = cycle[:-1]

        n = len(new_cycle)
        if n == 0:
            continue
        
        center_x = PAGE_WIDTH / 2
        if n>15:
            start_y = PAGE_HEIGHT - 300
        else:
            start_y = PAGE_HEIGHT - 150
        gap_y = 300
        
        # ===== Détection cycle fermé =====
        is_closed_cycle = (
            len(cycle) > 1 and cycle[0] == cycle[-1]
        )

        # ===== Position verticale =====
        radius = max(60, 7 * n)
        y = start_y - idx * gap_y

        if y < 100:
            c.showPage()
            start_y = PAGE_HEIGHT - 150
            y = start_y

        # ===== Placement des sommets =====
        points = []

        for i, line_id in enumerate(new_cycle):
            if is_closed_cycle:
                angle = 2 * np.pi * i / n
            else:
                angle = np.pi * i / (n - 1 if n > 1 else 1)

            x = center_x + radius * np.cos(angle)
            yy = y + radius * np.sin(angle)
            points.append((x, yy, line_id))

        # ===== Arêtes =====
        c.setStrokeColor(colors.darkblue)
        c.setFont("Helvetica", 7)

        # liaisons normales
        for i in range(n - 1):
            x1, y1, li = points[i]
            x2, y2, lj = points[i + 1]
            c.line(x1, y1, x2, y2)

            rame_i = line_to_rame.get(li)
            gare = end_station.get(rame_i, "")
            gare = str(gare)

            mx = (x1 + x2) / 2
            my = (y1 + y2) / 2 + 6
            c.drawCentredString(mx, my, gare)

        # fermeture du cycle si nécessaire
        if is_closed_cycle and n > 2:
            x1, y1, li = points[-1]
            x2, y2, lj = points[0]
            c.line(x1, y1, x2, y2)

            rame_i = line_to_rame.get(li)
            gare = str(end_station.get(rame_i, ""))

            mx = (x1 + x2) / 2
            my = (y1 + y2) / 2 + 6
            c.drawCentredString(mx, my, gare)

        # ===== Sommets =====
        for x, yy, line_id in points:
            c.setFillColor(colors.lightblue)
            c.circle(x, yy, 12, fill=1)
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(x, yy - 3, str(line_id))

        # ===== Label =====
        label_cycle = (
            new_cycle + [new_cycle[0]]
            if is_closed_cycle
            else new_cycle
        )

        c.setFont("Helvetica", 9)
        c.drawCentredString(
            center_x,
            y - radius - 25,
            f"Roulement {idx + 1}"
        )

def generate_kpi_pdf_from_df(df_assign_global, output_pdf="KPI_exploitation.pdf"):
    PAGE_WIDTH, PAGE_HEIGHT = A4
    LEFT = 40
    RIGHT = PAGE_WIDTH - 40

    c = canvas.Canvas(output_pdf, pagesize=A4)

    # ===================== PRÉPARATION =====================
    df = df_assign_global.copy()

    is_maint = df["axe"].astype(str).str.upper().str.contains("MAINT")
    is_hlp = df["vide_voyageur"] == True

    df_clean = df[~is_maint]

    # ----------------- KM -----------------
    total_km = df_clean["distance_km"].sum()
    km_hlp = df_clean.loc[is_hlp, "distance_km"].sum()
    taux_hlp = 100 * km_hlp / total_km if total_km > 0 else 0
    taux_vv = 100 - taux_hlp

    km_par_axe = (
        df_clean.groupby("axe")["distance_km"]
        .sum()
        .sort_values(ascending=False)
    )

    km_par_materiel = (
        df_clean.groupby("materiel")["distance_km"]
        .sum()
        .sort_values(ascending=False)
    )

    km_par_rame = df_clean.groupby("rame")["distance_km"].sum()
    km_moyen_rame = km_par_rame.mean()
    km_std_rame = km_par_rame.std()
    top_rames = km_par_rame.sort_values(ascending=False).head(6)

    # ----------------- MARCHES -----------------
    nb_marches_move = (df["type"] == "MOVE").sum()

    # ----------------- MAINTENANCE -----------------
    maint_by_type = defaultdict(float)

    df_maint = df[df["type"] == "MAINT"].copy()
    if not df_maint.empty:
        df_maint["duree_h"] = df_maint["arrivee"] - df_maint["depart"]

        for _, row in df_maint.iterrows():
            types = row.get("types", [])
            if not types:
                maint_by_type["non_specifie"] += row["duree_h"]
            else:
                for t in types:
                    maint_by_type[t] += row["duree_h"]

    total_maint_hours = sum(maint_by_type.values())

    # ----------------- TAUX D’UTILISATION -----------------
    WINDOW_START = 5.5
    WINDOW_END = 22.5
    WINDOW_DURATION = WINDOW_END - WINDOW_START

    df_voy = df[
        (~df["vide_voyageur"]) &
        (~df["axe"].astype(str).str.upper().str.contains("MAINT"))
    ].copy()

    df_voy["depart_clip"] = df_voy["depart"].clip(WINDOW_START, WINDOW_END)
    df_voy["arrivee_clip"] = df_voy["arrivee"].clip(WINDOW_START, WINDOW_END)
    df_voy["duree_fenetre"] = (
        df_voy["arrivee_clip"] - df_voy["depart_clip"]
    ).clip(lower=0)

    df_util_rame = (
        df_voy.groupby("rame")["duree_fenetre"]
        .sum()
        .reset_index()
    )

    df_util_rame["taux_utilisation"] = (
        df_util_rame["duree_fenetre"] / WINDOW_DURATION * 100
    )

    # rattachement matériel
    rame_to_mat = df[["rame", "materiel"]].drop_duplicates()
    df_util_rame = df_util_rame.merge(rame_to_mat, on="rame", how="left")

    taux_util_global = df_util_rame["taux_utilisation"].mean()

    taux_util_par_mat = (
        df_util_rame.groupby("materiel")["taux_utilisation"]
        .mean()
        .sort_values(ascending=False)
    )

    # ===================== TITRE =====================
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(
        PAGE_WIDTH / 2, PAGE_HEIGHT - 30,
        "KPI d’exploitation – Synthèse journalière"
    )

    y = PAGE_HEIGHT - 65

    # ===================== KPI GLOBAUX =====================
    c.setFont("Helvetica-Bold", 12)
    c.drawString(LEFT, y, "Indicateurs globaux")
    y -= 16

    c.setFont("Helvetica", 10)
    global_kpi = [
        f"• Kilomètres parcourus : {int(total_km):,} km",
        f"   - Part avec voyageurs : {taux_vv:.1f} %",
        f"   - Part en VV : {taux_hlp:.1f} %",
        f"• Nombre de marches : {nb_marches_move}",
        f"• Taux moyen d’utilisation (global) : {taux_util_global:.1f} % (part du temps un train est en service comercial de 5h30 à 22h30)",
        f"• Kilomètres moyens par rame : {int(km_moyen_rame):,} km",
        f"• Dispersion km par rame (σ) : {int(km_std_rame):,} km",
    ]

    for l in global_kpi:
        c.drawString(LEFT + 10, y, l)
        y -= 13

    y -= 6

    # ===================== UTILISATION PAR MATÉRIEL =====================
    c.setFont("Helvetica-Bold", 12)
    c.drawString(LEFT, y, "Taux moyen d’utilisation par matériel")
    y -= 14

    c.setFont("Helvetica", 9)
    for mat, taux in taux_util_par_mat.items():
        c.drawString(LEFT + 10, y, mat)
        c.drawRightString(RIGHT, y, f"{taux:.1f} %")
        y -= 11

    y -= 6

    # ===================== MAINTENANCE =====================
    c.setFont("Helvetica-Bold", 12)
    c.drawString(LEFT, y, "Maintenance – heures cumulées")
    y -= 14

    c.setFont("Helvetica", 9)
    c.drawString(LEFT + 10, y, f"Total maintenance : {total_maint_hours:.1f} h")
    y -= 12

    for t, h in sorted(maint_by_type.items()):
        c.drawString(
            LEFT + 20, y,
            f"- {t.replace('_', ' ').title()} : {h:.1f} h"
        )
        y -= 11

    y -= 6

    # ===================== KM PAR AXE =====================
    c.setFont("Helvetica-Bold", 12)
    c.drawString(LEFT, y, "Kilomètres parcourus par axe")
    y -= 14

    c.setFont("Helvetica", 9)
    for axe, km in km_par_axe.items():
        if y < 140:
            break
        c.drawString(LEFT + 10, y, axe)
        c.drawRightString(RIGHT, y, f"{int(km):,} km")
        y -= 11

    y -= 6

    # ===================== KM PAR MATÉRIEL =====================
    c.setFont("Helvetica-Bold", 12)
    c.drawString(LEFT, y, "Kilomètres parcourus par matériel")
    y -= 14

    c.setFont("Helvetica", 9)
    for mat, km in km_par_materiel.items():
        c.drawString(LEFT + 10, y, mat)
        c.drawRightString(RIGHT, y, f"{int(km):,} km")
        y -= 11

    y -= 6

    # ===================== TOP RAMES =====================
    c.setFont("Helvetica-Bold", 12)
    c.drawString(LEFT, y, "Rames les plus sollicitées")
    y -= 14

    c.setFont("Helvetica", 9)
    for rame, km in top_rames.items():
        c.drawString(LEFT + 10, y, f"Rame {rame}")
        c.drawRightString(RIGHT, y, f"{int(km):,} km")
        y -= 11

    # ===================== FIN =====================
    c.save()
    print(f"📄 PDF KPI (1 page avec taux d’utilisation) généré : {output_pdf}")
    
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
        "type": "MOVE"
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
        "type":"MOVE"
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
            "type": "MOVE"
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
            "type": "MOVE"
        }
    )

    state["gare"] = gare_dep
    state["dispo"] = depart


# ------------------ Calcul PPHPD ------------------
def calcul_pphpd_par_direction(df_assign, parc, axe):
    """
    PPHPD avec règle :
      - avant 12h = basé sur l'heure d'arrivée
      - après 12h = basé sur l'heure de départ

    Directions finales :
      - Marseille / Banlieue (selon l'axe)
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

                # Direction ferroviaire pair / impair
                if (num % 2 == 0 and direction == "Paris") or (
                    num % 2 == 1 and direction == "Province"
                ):
                    rame = row["rame"]
                    for info in parc.values():
                        if info["numero"] <= rame < info["numero"] + info["quantite"]:
                            capacite_totale += info["places"]
                            break

            # 🔁 Mapping final Paris/Province → Marseille/Banlieue
            direction_finale = map_direction_pphpd(direction, axe)

            resultats.append(
                {
                    "heure": h,
                    "direction": direction_finale,
                    "pphpd": capacite_totale,
                }
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

# Fenêtre de référence pour le taux d'utilisation (en heure décimale)
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
def draw_params_page(c, materiel_code, titre_suffix, total_maint_hours, maint_by_site):
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
    c.drawString(LEFT_MARGIN, y, "• Affichage minutes uniquement pour les heures de départ / arrivée")
    y -= line_height

    # --- Indicateur d'utilisation ---
    y -= line_height // 2
    c.setFont("Helvetica-Bold", 10)
    c.drawString(LEFT_MARGIN, y, "Indicateur d'utilisation :")
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
    # --- Maintenance ---
    y -= line_height
    if y < BOTTOM_MARGIN + 60:
        c.showPage()
        y = PAGE_HEIGHT - TOP_MARGIN

    c.setFont("Helvetica-Bold", 10)
    c.drawString(LEFT_MARGIN, y, "Maintenance programmée")
    y -= line_height

    c.setFont("Helvetica", 9)
    c.drawString(
        LEFT_MARGIN,
        y,
        f"• Total maintenance : {total_maint_hours:.1f} h"
    )
    y -= line_height

    if maint_by_site:
        for site, h in maint_by_site.items():
            c.drawString(
                LEFT_MARGIN + 10,
                y,
                f"- {site} : {h:.1f} h"
            )
            y -= line_height



# ------------------ PDF par matériel ------------------
def draw_pdf_for_material(df_assign_mat, materiel_code):
    """
    Génère un PDF pour un type de matériel donné (R2N, BGC, REG, 2NPG).
    """
    
    # ================== SÉPARATION RAMES UTILISÉES / INUTILISÉES ==================
    rame_list_used, rames_inutilisees = split_used_and_unused_rames(
        df_assign_mat, materiel_code, parc
    )

    # --- Liste complète des rames du matériel (utilisées + inutilisées) ---
    info = parc[materiel_code]
    premier = info["numero"]
    dernier = info["numero"] + info["quantite"] - 1
    all_rames = list(range(premier, dernier + 1))


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
    rame_list = sorted(
        set(rame_list_used) | set(rames_inutilisees)
    )


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
            if li != lj and end_i is not None and start_station.get(rame_j) == end_i:
                compatible[li].append(lj)

    # ================== MATCHING MAXIMUM ==================
    def strongly_connected_components(graph):
        index = 0
        stack = []
        indices = {}
        lowlink = {}
        onstack = set()
        result = []

        def visit(v):
            nonlocal index
            indices[v] = index
            lowlink[v] = index
            index += 1
            stack.append(v)
            onstack.add(v)

            for w in graph.get(v, []):
                if w not in indices:
                    visit(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif w in onstack:
                    lowlink[v] = min(lowlink[v], indices[w])

            if lowlink[v] == indices[v]:
                comp = []
                while True:
                    w = stack.pop()
                    onstack.remove(w)
                    comp.append(w)
                    if w == v:
                        break
                result.append(comp)

        for v in graph:
            if v not in indices:
                visit(v)
        return result


    sccs = strongly_connected_components(compatible)

    # chaque SCC = un roulement
    roulements = [sorted(comp) for comp in sccs]


    # ================== gestion cycle ==================
    cycles = []

    for r in roulements:
            cycles.append(r + [r[0]])  # cycle fermé

            
    next_line = {}
    prev_line = {}

    for cycle in cycles:
        if len(cycle) < 2:
            continue

        # cycle fermé : [1,2,3,1]
        if cycle[0] == cycle[-1]:
            nodes = cycle[:-1]
            for i in range(len(nodes)):
                a = nodes[i]
                b = nodes[(i + 1) % len(nodes)]
                next_line[a] = b
                prev_line[b] = a

        # chaîne ouverte : [1,2,3]
        else:
            for i in range(len(cycle) - 1):
                a = cycle[i]
                b = cycle[i + 1]
                next_line[a] = b
                prev_line[b] = a

    # utlisation
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
    # ================== AJOUT VISUEL DES RAMES INUTILISÉES ==================
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
        df_assign_mat = pd.concat(
            [df_assign_mat, pd.DataFrame(lignes_vides)],
            ignore_index=True
        )

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
        ligne_demain = next_line.get(ligne_auj)

        ligne_hier = prev_line.get(ligne_auj)

        texte_roulement = f"{ligne_hier} ➜ {ligne_auj} ➜ {ligne_demain}"

        # Cadre
        c.setStrokeColor(colors.HexColor("#3A7ECB"))
        c.rect(LEFT_MARGIN, cadre_bottom,
               PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN,
               RAME_HEIGHT)


        axe_label = " / ".join(
            sous_df.loc[
                ~sous_df["axe"].fillna("").str.contains("maintenance", case=False),
                "axe"
            ].unique()
        ) or "axe inconnu"
        
        # Titre rame + axe
        c.setFont("Helvetica-Bold", 5)
        c.setFillColor(colors.magenta)
        c.drawString(LEFT_MARGIN + 6, cadre_top - 12, texte_roulement)
        c.setFillColor(colors.green)
        c.drawString(LEFT_MARGIN + 30, cadre_bottom + 4, axe_label)

        # utilisation
        perf_row = df_perf_par_rame.loc[df_perf_par_rame["rame"] == rame]
        if not perf_row.empty:
            perf_val = perf_row["taux_utilisation"].values[0]
            c.setFont("Helvetica-Bold", 5)
            c.setFillColor(colors.green)
            c.drawRightString(PAGE_WIDTH - RIGHT_MARGIN - 6,
                              cadre_bottom + 4,
                              f"Utilisation : {perf_val:.0f}%")
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

            # Fond gris léger
            c.setFillColor(colors.whitesmoke)
            c.rect(
                LEFT_MARGIN + 1,
                cadre_bottom + 1,
                PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN - 2,
                RAME_HEIGHT - 2,
                stroke=0,
                fill=1
            )

            # Texte principal
            c.setFont("Helvetica-Bold", 11)
            c.setFillColor(colors.red)
            c.drawCentredString(
                (LEFT_MARGIN + PAGE_WIDTH - RIGHT_MARGIN) / 2,
                y_line + 6,
                f"{materiel_code} garé - Réserve"
            )

            # Texte secondaire
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.darkgray)
            c.drawCentredString(
                (LEFT_MARGIN + PAGE_WIDTH - RIGHT_MARGIN) / 2,
                y_line - 6,
                f"Garage : {gare_dodo} "
            )

            c.setFillColor(colors.black)

            y_start -= (RAME_HEIGHT + ESPACEMENT_RAME)
            rame_counter += 1
            continue

        # =======================

        c.setStrokeColor(colors.black)

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

        for _, marche in sous_df.iterrows():
            # ===== Détection UM pour cette marche =====
            nb_marche = marche["marche"]
            um_list = um_by_marche.get(nb_marche, [])
            um_len = len(um_list)
            is_us = um_len == 1
            is_um2 = um_len == 2
            is_um3 = um_len >= 3
            
            if len(um_list) >= 2 and rame in um_list:
                position_um = um_list.index(rame)   # 0, 1, 2, ...
            else:
                position_um = None                  # US
            # ==========================================

            x1 = x_from_time(marche["depart"])
            x2 = x_from_time(marche["arrivee"])
            gare_dep = str(marche["gare_depart"])
            gare_arr = str(marche["gare_arrivee"])
            heure_dep = format_time_hm(marche["depart"])
            heure_arr = format_time_hm(marche["arrivee"])

            if x2 < LEFT_MARGIN:
                continue
            if x1 > PAGE_WIDTH - RIGHT_MARGIN:
                continue
            
            
            x1 = max(x1, LEFT_MARGIN + 2)
            x2 = min(x2, PAGE_WIDTH - RIGHT_MARGIN - 2)

            if marche.get("vide_voyageur", True):
                bar_color = colors.lightgrey
            else:
                bar_color = colors.black
            # ===== Choix épaisseur selon UM =====
            if is_us:
                draw_train_bar(c, x1, x2, y_line, height=5, color=bar_color) # Cas normal
            elif is_um2:
                if position_um == 0:
                    draw_train_bar(c, x1, x2, y_line+ 1.5, height=3, color=bar_color)
                    draw_train_bar(c, x1, x2, y_line- 2, height=0.75, color=bar_color)
                elif position_um ==1:
                    draw_train_bar(c, x1, x2, y_line+ 2, height=0.75, color=bar_color)
                    draw_train_bar(c, x1, x2, y_line- 1.5, height=3, color=bar_color)
            elif is_um3:
                if position_um == 0:
                    draw_train_bar(c, x1, x2, y_line + 2.25, height=3, color=bar_color)
                    draw_train_bar(c, x1, x2, y_line -0.5,     height=0.75, color=bar_color)
                    draw_train_bar(c, x1, x2, y_line - 2, height=0.75, color=bar_color)
                elif position_um == 1:
                    draw_train_bar(c, x1, x2, y_line + 3, height=0.75, color=bar_color)
                    draw_train_bar(c, x1, x2, y_line,     height=3, color=bar_color)
                    draw_train_bar(c, x1, x2, y_line - 3, height=0.75, color=bar_color)
                elif position_um == 2:
                    draw_train_bar(c, x1, x2, y_line + 2, height=0.75, color=bar_color)
                    draw_train_bar(c, x1, x2, y_line +0.5,     height=0.75, color=bar_color)
                    draw_train_bar(c, x1, x2, y_line - 2.25, height=3, color=bar_color)


            gare_dep = str(marche["gare_depart"])
            gare_arr = str(marche["gare_arrivee"])
            heure_dep = format_time_hm(marche["depart"])
            heure_arr = format_time_hm(marche["arrivee"])

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
            
            if str(nb_marche).startswith("MAINT"):
                types = marche.get("types", [])
                if types:
                    types_txt = " / ".join(t.replace("_", " ") for t in types)
                    marche_text = f"{nb_marche}\n{types_txt}"
                else:
                    marche_text = str(nb_marche)

            elif str(nb_marche).startswith(("EVM", "EVO", "EVI", "EVS")):
                marche_text = "HLP"
            else:
                marche_text = str(nb_marche)

            y_num = y_line + (12 if marche.get("vide_voyageur", False) else 7)
            c.drawCentredString((x1 + x2) / 2, y_num, marche_text)

            # --- Affichage des écarts trop courts ---
            if prev_arrivee is not None:
                ecart = marche["depart"] - prev_arrivee
                if ecart < 0.333:
                    minutes = int(round(ecart * 60))
                    milieu = (marche["depart"] + prev_arrivee) / 2
                    xm = x_from_time(milieu)
                    c.setFont("Helvetica-Bold", 4)
                    c.setFillColor(colors.red)
                    c.drawCentredString(xm, y_line, f"{minutes}")
                    c.setFillColor(colors.black)

            prev_arrivee = marche["arrivee"]
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
    line_to_rame = {v: k for k, v in rame_to_line.items()}

    draw_roulement_graph(
    c,
    cycles,
    line_to_rame,
    start_station,
    end_station,
    PAGE_WIDTH,
    PAGE_HEIGHT,
    )
    total_maint_hours, maint_by_site = compute_maintenance_stats(df_assign_mat)

    # Dernière page : paramètres
    draw_params_page(
        c,
        materiel_code,
        f"Matériel {materiel_code}",
        total_maint_hours,
        maint_by_site
    )
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
                "vide_voyageur": train.get("vide_voyageur", False),
                "type": "MOVE"
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

        pphpd_par_axe[axe_label] = calcul_pphpd_par_direction(df_assign_file, parc,axe_label)

    # Si aucune marche
    if not all_assignments:
        print("Aucun assignment global généré.")
        return


    # ------------------------ 2) INJECTION MAINTENANCE ------------------------
    df_assign_global = pd.DataFrame(all_assignments)
    df_assign_global["vide_voyageur"] = df_assign_global["vide_voyageur"].astype("boolean").fillna(False)
    df_assign_global["distance_km"] = df_assign_global.apply(get_distance_safe, axis=1)
    df_assign_global["materiel"] = df_assign_global["rame"].apply(get_materiel_code_from_rame)
    
    # ================== TOTAL KM PAR AXE ==================

    print("\n🚆 Total des kilomètres effectués par axe (hors HLP / maintenance)")

    df_km_par_axe = (
        df_assign_global[
            (~df_assign_global["vide_voyageur"]) &
            (df_assign_global["axe"] != "MAINTENANCE")
        ]
        .groupby("axe")["distance_km"]
        .sum()
        .sort_values(ascending=False)
    )

    for axe, km in df_km_par_axe.items():
        print(f"• {axe} : {int(km)} km")

    print("──────────────────────────────────────────")
    print(f"TOTAL RÉSEAU : {int(df_km_par_axe.sum())} km\n")

    df_assign_global.to_csv("df_assign_global.csv", index=False, encoding="utf-8")



    # ------------------ 2) AFFECTATION DES MAINTENANCES (mimique des trains) ------------------

    maintenance_rows = []
        
    for code in parc.keys():
        cpt = 1
        df_mat = df_assign_global[df_assign_global["materiel"] == code].copy()
        

        if code not in maintenance_data:
            continue

        slots = maintenance_data[code]["slots"]

        # état dynamique des rames
        rame_state = {}

        # planning initial par rame
        rame_timetable = {}
        for rame, grp in df_mat.groupby("rame"):
            grp = grp.sort_values("depart")
            rame_timetable[rame] = grp[
                ["gare_depart", "depart", "arrivee", "gare_arrivee"]
            ].to_dict("records")
            rame_state[rame] = {
                "gare": grp.iloc[-1]["gare_arrivee"],
                "dispo": grp.iloc[-1]["arrivee"]
            }

        # slots du plus long au plus court
        slots = sorted(slots, key=lambda s: -s["duration_minutes"])

        for slot in slots:
            duration = slot["duration_minutes"] / 60.0
            win_start, win_end = slot["window"]
            location = slot["location"]

            placed = False
            for rame_id in sorted(rame_state.keys()):
                timetable = rame_timetable[rame_id]
                # dernier état réel de la rame
                last_ev = max(timetable, key=lambda x: x["arrivee"])
                end_of_day_gare = last_ev["gare_arrivee"]
                end_of_day_time = last_ev["arrivee"]

                real_start_gare = None

                sorted_tt = sorted(timetable, key=lambda x: x["arrivee"])

                for ev in sorted_tt:
                    if ev["arrivee"] <= win_start:
                        real_start_gare = ev["gare_arrivee"]

                if real_start_gare is None:
                    if sorted_tt:
                        real_start_gare = sorted_tt[0]["gare_depart"]
                    else:
                        continue  # aucune info fiable → on refuse la rame


                # ============================================================
                # 2️⃣ Construire UNIQUEMENT les événements RÉELS dans la fenêtre
                # ============================================================
                events = []

                # événements réels dans la fenêtre
                for ev in timetable:
                    if ev["depart"] < win_end and ev["arrivee"] > win_start:
                        events.append((ev["depart"], ev["arrivee"], ev["gare_arrivee"]))

                # point AVANT la fenêtre
                events.insert(0, (win_start, win_start, real_start_gare))

                # 🔴 POINT CLÉ : après la dernière marche
                if end_of_day_time < win_end:
                    events.append((end_of_day_time, win_end, end_of_day_gare))

                events = sorted(events)


                # Point virtuel de départ (position réelle)
                events = [(win_start, win_start, real_start_gare)] + events

                # ============================================================
                # 3️⃣ Recherche d’un trou compatible
                # ============================================================
                # Cas spécial : aucune marche dans la fenêtre → trou total
                if len(events) == 1:
                    last_gare = events[0][2]

                    if last_gare == location and (win_end - win_start) >= duration:
                        free_start = win_start

                        maintenance_rows.append({
                            "rame": rame_id,
                            "marche": f"MAINT-{code}-{cpt}",
                            "gare_depart": location,
                            "depart": free_start,
                            "gare_arrivee": location,
                            "arrivee": free_start + duration,
                            "vide_voyageur": True,
                            "materiel": code,
                            "axe": "MAINTENANCE",
                            "type": "MAINT"
                        })

                        rame_state[rame_id]["gare"] = location
                        rame_state[rame_id]["dispo"] = free_start + duration

                        rame_timetable[rame_id].append({
                            "gare_depart": location,
                            "depart": free_start,
                            "arrivee": free_start + duration,
                            "gare_arrivee": location
                        })

                        print(
                            f"🛠 Maintenance placée (avant 1er train): {code} → rame {rame_id} "
                            f"({duration}h entre {round(free_start,2)}h et {round(free_start+duration,2)}h)"
                        )

                        cpt += 1
                        placed = True
                        continue

                for i in range(len(events) - 1):
                    end_prev = events[i][1] + 1.0       # tampon 1h
                    start_next = events[i + 1][0] - 1.0

                    free_start = max(end_prev, win_start)
                    free_end = min(start_next, win_end)

                    if free_end - free_start < duration:
                        continue

                    last_gare = events[i][2]

                    # ❌ la rame n’est pas à la bonne gare → refus
                    if last_gare != location:
                        continue

                    # ========================================================
                    # ✅ Maintenance VALIDÉE
                    # ========================================================
                    maintenance_rows.append({
                        "rame": rame_id,
                        "marche": f"MAINT-{code}-{cpt}",
                        "gare_depart": location,
                        "depart": free_start,
                        "gare_arrivee": location,
                        "arrivee": free_start + duration,
                        "vide_voyageur": True,
                        "materiel": code,
                        "axe": "MAINTENANCE",
                        "types": slot.get("types", []),
                        "type": "MAINT"
                    })

                    rame_state[rame_id]["gare"] = location
                    rame_state[rame_id]["dispo"] = free_start + duration

                    rame_timetable[rame_id].append({
                        "depart": free_start,
                        "arrivee": free_start + duration,
                        "gare_arrivee": location,
                        "gare_depart":location
                    })

                    print(
                        f"🛠 Maintenance placée: {code} → rame {rame_id} "
                        f"({duration}h entre {round(free_start,2)}h et {round(free_start+duration,2)}h)"
                    )

                    cpt += 1
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
    
    # ================== OCCUPATION DES VOIES DE MAINTENANCE ==================
    occupancy_by_site = compute_maintenance_occupation(df_assign_global)
    plot_maintenance_occupation(occupancy_by_site)
    




    # ------------------------ 3) EXPORT PDF ------------------------
    generate_pphpd_global(pphpd_par_axe)

    for code in parc.keys():
        df_mat = df_assign_global[df_assign_global["materiel"] == code].copy()
        

        print(f"\n=== Maintenances appliquées pour {code} ===")
        print(df_mat[df_mat["marche"].astype(str).str.startswith("MAINT")][["rame","marche","gare_depart","depart","gare_arrivee","arrivee"]])

        draw_pdf_for_material(df_mat, code)

    print("\n✅ Process terminé avec maintenance + tampon EVO intégrés.")
    
    generate_kpi_pdf_from_df(df_assign_global)
    plot_repartition_flotte_par_ligne(df_assign_global)


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
    

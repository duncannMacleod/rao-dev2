import json
import pandas as pd
import plotly.graph_objects as go
import os
import plotly.io as pio

# Configuration pour que Plotly ouvre les graphiques dans le navigateur
pio.renderers.default = "browser"
DOSSIER_JSON = "marches_json"  # Dossier contenant les fichiers de marches
pd.set_option("future.no_silent_downcasting", True)

# --- Paramètres globaux ---
m_st_chrls = "MSC"
navette_time = 0.083      # Durée d'une navette (5 min)
tampon = 0.333            # Tampon général (20 min)
tampon_15m = 0.25         # Tampon réduit (15 min)
temps_minimal = 0.20      # Temps minimal entre deux missions (12 min)
seuil_atelier = 1.25      # Seuil au-delà duquel une rame va à l'atelier (1h15)

# --- Parc de rames disponibles ---
parc = {
    "C": {"modele": "Corail", "numero": 22201, "quantite": 3, "utilise": 0, "places": 704},
    "BGC": {"modele": "BGC", "numero": 81501, "quantite": 27, "utilise": 0, "places": 200},
    "REG": {"modele": "Regiolis", "numero": 84501, "quantite": 15, "utilise": 0, "places": 220},
    "2NPG": {"modele": "2NPG", "numero": 23501, "quantite": 30, "utilise": 0, "places": 210},
}

# --- Attribution automatique du type de rame selon la ligne ---
def get_rame_id(nom_ligne: str):
    # Détermine le type de rame à utiliser selon le fichier
    if nom_ligne == "marches_intervilles-marseille-lyon.json":
        key = "C"
    elif nom_ligne == "marches_marseille-toulon-hyeres-les-arcs-draguignan.json":
        key = "2NPG"
    elif nom_ligne == "marches_marseille-avignon.json":
        key = "2NPG"
    else:
        # Priorité aux BGC, sinon Regiolis
        key = "BGC" if parc["BGC"]["utilise"] < parc["BGC"]["quantite"] else "REG"

    # Vérifie qu’il reste des rames disponibles
    if parc[key]["utilise"] >= parc[key]["quantite"]:
        raise RuntimeError(f"Plus de rames disponibles pour {parc[key]['modele']}")

    # Génère l’identifiant de rame (numéro de base + index)
    rame_id = parc[key]["numero"] + parc[key]["utilise"]
    parc[key]["utilise"] += 1
    return rame_id


# --- Conversion heure décimale → format HH:MM ---
def h_dec_to_hm(h):
    h_int = int(h)
    m = int(round((h - h_int) * 60))
    if m == 60:
        h_int += 1
        m = 0
    return f"{h_int:02d}:{m:02d}"


# --- Création d’une marche de navette du matin (ramène la rame en gare de départ) ---
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


# --- Création d’une navette du soir (retour au dépôt) ---
def navette_soir(rame_id, gare_dep, dispo):
    mapping = {
        "MSC": "MBC", "AVV": "AVG", "AVI": "AVG", "LPR": "LYG", "LYD": "LYG",
        "MAS": "MAG", "HYE": "HYG", "TLN": "TLG", "LAC": "LAG", "AXP": "AXG",
        "GAP": "GAG", "SIS": "SIG", "BRI": "BRG",
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


# --- Gestion des évolutions longues (envoi à l’atelier, retour avant prochain départ) ---
def gestion_evo(rame_id, gare_dep, depart, state, assignments):
    mapping_navette = {
        "MSC": "MBC", "AVV": "AVG", "AVI": "AVG", "LPR": "LYG", "LYD": "LYG",
        "MAS": "MAG", "HYE": "HYG", "TLN": "TLG", "LAC": "LAG", "AXP": "AXG",
        "GAP": "GAG", "SIS": "SIG", "BRI": "BRG",
    }
    if gare_dep not in mapping_navette:
        return
    gare_navette = mapping_navette[gare_dep]
    # Envoi vers atelier
    assignments.append({
        "rame": rame_id,
        "marche": f"evo_in_{rame_id}",
        "gare_depart": gare_dep,
        "depart": state["dispo"] + tampon_15m,
        "gare_arrivee": gare_navette,
        "arrivee": state["dispo"] + navette_time + tampon_15m,
        "vide_voyageur": True,
    })
    # Retour de l’atelier
    assignments.append({
        "rame": rame_id,
        "marche": f"evo_out_{rame_id}",
        "gare_depart": gare_navette,
        "depart": depart - navette_time - tampon_15m,
        "gare_arrivee": gare_dep,
        "arrivee": depart - tampon_15m,
        "vide_voyageur": True,
    })
    state["gare"] = gare_dep
    state["dispo"] = depart


# --- Calcul du PPHPD (places par heure et direction) ---
def calcul_pphpd_par_direction(df_assign, parc):
    resultats = []
    hmin = int(df_assign["depart"].min())
    hmax = int(df_assign["arrivee"].max()) + 1
    for h in range(hmin, hmax):
        tranche = df_assign[
            (df_assign["depart"] >= h) & (df_assign["depart"] < h + 1) & (~df_assign["vide_voyageur"])
        ]
        for direction in ["Paris", "Province"]:
            capacite_totale = 0
            for _, row in tranche.iterrows():
                try:
                    num = int(row["marche"])
                except:
                    continue
                # Marche paire → direction Paris / impaire → Province
                if (num % 2 == 0 and direction == "Paris") or (num % 2 == 1 and direction == "Province"):
                    rame = row["rame"]
                    # Ajoute la capacité de la rame correspondante
                    for key, info in parc.items():
                        if info["numero"] <= rame < info["numero"] + info["quantite"]:
                            capacite_totale += info["places"]
                            break
            resultats.append({"heure": h, "direction": direction, "pphpd": capacite_totale})
    return pd.DataFrame(resultats)


# --- Charger la configuration des lignes (roulements) ---
with open("lignes.json", "r", encoding="utf-8") as f:
    lignes_data = json.load(f)


# --- Boucle sur chaque fichier de marches ---
for fichier_json in os.listdir(DOSSIER_JSON):
    if not fichier_json.endswith(".json"):
        continue
    chemin_json = os.path.join(DOSSIER_JSON, fichier_json)
    with open(chemin_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Création du DataFrame trié par heure de départ
    df = pd.DataFrame(data).sort_values("depart").reset_index(drop=True)
    rame_state = {}  # État des rames (position, dispo)
    assignments = []  # Liste complète des marches (voyageurs + HLP)

    # --- Affectation automatique des rames aux trains ---
    for _, train in df.iterrows():
        gare_dep = train["gare_depart"]
        depart = train["depart"]
        candidate = None

        # Recherche d'une rame déjà disponible sur place
        for rame_id, state in rame_state.items():
            if state["gare"] == gare_dep and state["dispo"] + temps_minimal <= depart:
                # Si attente longue → évolution atelier
                if depart - state["dispo"] > seuil_atelier:
                    gestion_evo(rame_id, state["gare"], depart, state, assignments)
                candidate = rame_id
                break

        # Si aucune rame dispo, en créer une nouvelle
        if candidate is None:
            candidate = get_rame_id(fichier_json)
            marche_navette = navette_mat(candidate, gare_dep, depart, tampon_15m, navette_time)
            if marche_navette:
                assignments.append(marche_navette)
            rame_state[candidate] = {"gare": gare_dep, "dispo": 0}

        # Ajout de la marche commerciale
        assignments.append({
            "rame": candidate,
            "marche": train["marche"],
            "gare_depart": gare_dep,
            "depart": depart,
            "gare_arrivee": train["gare_arrivee"],
            "arrivee": train["arrivee"],
            "vide_voyageur": train.get("vide_voyageur", False),
        })

        # Mise à jour de la position et disponibilité de la rame
        rame_state[candidate]["gare"] = train["gare_arrivee"]
        rame_state[candidate]["dispo"] = train["arrivee"]

    # --- Ajout des navettes du soir pour toutes les rames ---
    for rame_id, state in rame_state.items():
        soir = navette_soir(rame_id, state["gare"], state["dispo"])
        if soir:
            assignments.append(soir)

    df_assign = pd.DataFrame(assignments)

    # --- Nettoyage du champ vide_voyageur ---
    def to_bool(v):
        if pd.isna(v): return False
        if isinstance(v, bool): return v
        if isinstance(v, (int, float)): return bool(v)
        s = str(v).strip().lower()
        return not (s in ("false", "0", "none", "no", "nan", ""))

    if "vide_voyageur" not in df_assign.columns:
        df_assign["vide_voyageur"] = False
    else:
        df_assign["vide_voyageur"] = df_assign["vide_voyageur"].apply(to_bool)

    # --- Identifier les UM2 / UM3 (Unité Multiple) ---
    marche_counts = df_assign["marche"].value_counts()
    UM2 = set(marche_counts[marche_counts == 2].index)
    UM3 = set(marche_counts[marche_counts == 3].index)

    # --- Recherche des roulements dans lignes.json ---
    ligne_info = next((l for l in lignes_data if fichier_json in l["ligne"]), None)
    if ligne_info:
        roulement_hier = ligne_info.get("roulement_hier", [])
        roulement_demain = ligne_info.get("roulement_demain", [])
    else:
        roulement_hier, roulement_demain = [], []
    # Inversion pour cohérence d’affichage
    roulement_hier = roulement_hier[::-1]
    roulement_demain = roulement_demain[::-1]

    # --- Création du graphique Plotly ---
    fig = go.Figure()
    rame_list = sorted(df_assign["rame"].unique())
    rame_index_map = {rame: i + 1 for i, rame in enumerate(rame_list)}

    # --- Chargement des distances (km) entre gares ---
    with open("km_marches.json", "r", encoding="utf-8") as f:
        km_data = json.load(f)
    km_dict = {(d["origine"], d["destination"]): d["distance"] for d in km_data}
    for d in km_data:
        km_dict[(d["destination"], d["origine"])] = d["distance"]

    # Fonction sécurisée pour récupérer une distance
    def get_distance_safe(row):
        try:
            if row.get("vide_voyageur", False):
                return 0
            return km_dict[(row["gare_depart"], row["gare_arrivee"])]
        except KeyError:
            print(f"⚠️ Distance inconnue pour {row.get('gare_depart')} → {row.get('gare_arrivee')}")
            return 0
        except Exception as e:
            print(f"❌ Erreur inattendue pour {row.get('gare_depart')} → {row.get('gare_arrivee')}: {e}")
            return 0

    # Application du calcul des distances
    df_assign["distance_km"] = df_assign.apply(get_distance_safe, axis=1)
    df_km_par_rame = df_assign.groupby("rame", dropna=False)["distance_km"].sum().reset_index()

    # --- Dessin du graphique par rame ---
    for i, rame in enumerate(rame_list):
        sous_df = df_assign[df_assign["rame"] == rame].sort_values("depart")
        y = rame_index_map[rame] - 1
        prev_arrivee = None

        for _, row in sous_df.iterrows():
            color = "green" if not row["vide_voyageur"] else "orange"
            fig.add_trace(go.Scatter(
                x=[row["depart"], row["arrivee"]],
                y=[y, y],
                mode="lines",
                line=dict(color=color, width=8),
                hovertemplate=(
                    f"Rame: {rame}<br>Marche: {row['marche']}<br>"
                    f"Départ: {row['gare_depart']} ({h_dec_to_hm(row['depart'])})<br>"
                    f"Arrivée: {row['gare_arrivee']} ({h_dec_to_hm(row['arrivee'])})"
                ),
                showlegend=False,
            ))

            # Ajout d’annotations : gares, UM, HLP, intervalles courts
            if row["marche"] in UM2 or row["marche"] in UM3:
                milieu = (row["depart"] + row["arrivee"]) / 2
                um_text = "UM2" if row["marche"] in UM2 else "UM3"
                fig.add_annotation(x=milieu, y=y, text=f"<b>{um_text}</b>",
                                   showarrow=False, font=dict(size=8, color="cyan"))

            duree = row["arrivee"] - row["depart"]
            if not row["vide_voyageur"] and duree >= 0.60:
                fig.add_annotation(x=row["depart"], y=y + 0.01, text=f"<b>{row['gare_depart']}</b>",
                                   showarrow=False, font=dict(size=8))
                fig.add_annotation(x=row["arrivee"], y=y + 0.01, text=f"<b>{row['gare_arrivee']}</b>",
                                   showarrow=False, font=dict(size=8))
            if row["vide_voyageur"]:
                fig.add_annotation(x=(row["depart"] + row["arrivee"]) / 2, y=y + 0.01,
                                   text="<b>HLP</b>", showarrow=False, font=dict(size=8))

            # Affiche un écart rouge si deux missions sont trop rapprochées
            if prev_arrivee is not None:
                ecart = row["depart"] - prev_arrivee
                if ecart < 0.333:
                    minutes = int(round(ecart * 60))
                    milieu = prev_arrivee + ecart / 2
                    fig.add_annotation(x=milieu, y=y, text=f"<b style='color:red'>{minutes}</b>",
                                       showarrow=False, font=dict(size=8, color="red"))
            prev_arrivee = row["arrivee"]

        # Annotation du roulement (hier → demain)
        if i < len(roulement_hier) and i < len(roulement_demain):
            fig.add_annotation(x=5, y=y + 0.25,
                               text=f"<b>{roulement_hier[i]} → {roulement_demain[i]}</b>",
                               showarrow=False, font=dict(size=10, color="purple"))

        # Annotation du total km à 23h30
        total_rame_km = df_km_par_rame.loc[df_km_par_rame["rame"] == rame, "distance_km"]
        if not total_rame_km.empty:
            total_rame_km = int(total_rame_km.values[0])
            fig.add_annotation(x=23.5, y=y, text=f"<b>{total_rame_km} km</b>",
                               showarrow=False, font=dict(size=10, color="blue"))

    # --- Mise en forme du graphique ---
    for h in [x * 0.5 for x in range(10, 49)]:
        fig.add_vline(x=h, line=dict(color="gray", width=1, dash="dot"), layer="below")

    tick_vals = list(range(5, 25))
    tick_texts = [f"{h:02d}:00" for h in tick_vals]
    y_labels = [str(i + 1) for i in range(len(rame_list))]

    fig.update_yaxes(tickvals=list(range(1, len(rame_list) + 1)), ticktext=y_labels)
    fig.update_layout(
        title=f"Tableau de marche – {fichier_json}",
        xaxis=dict(range=[5, 24], tickvals=tick_vals, ticktext=tick_texts, title="Heure (HH:MM)", showgrid=False),
        yaxis=dict(tickvals=list(range(len(rame_list) + 3)), ticktext=y_labels[::-1], showgrid=False, title="Rame"),
        hovermode="closest",
        showlegend=False,
        plot_bgcolor="white",
    )

    # --- Affichage console : bilans et vérifications ---
    print(f"\n=== {fichier_json} ===")
    premiers_depart = df_assign.sort_values("depart").groupby("rame").first()
    dernieres_arrivee = df_assign.sort_values("arrivee").groupby("rame").last()
    depart_counts = premiers_depart["gare_depart"].value_counts().rename("Departs")
    arrivee_counts = dernieres_arrivee["gare_arrivee"].value_counts().rename("Arrivees")
    flux_balance = pd.concat([depart_counts, arrivee_counts], axis=1).fillna(0).astype(int)
    flux_balance["Diff (Arr - Dep)"] = flux_balance["Arrivees"] - flux_balance["Departs"]
    print("--- Équilibre par gare ---")
    print(flux_balance)

    # Calcul du PPH par direction et heure
    df_pphpd = calcul_pphpd_par_direction(df_assign, parc)
    print("\n--- PPHPD par heure et direction ---")
    print(df_pphpd.pivot(index="heure", columns="direction", values="pphpd").fillna(0))

    print("\n--- Km totaux par rame ---")
    print(df_km_par_rame)

    # Affiche le graphique interactif
    fig.show()

import json
import pandas as pd
import plotly.graph_objects as go
import os
import plotly.io as pio
pio.renderers.default = "browser"
DOSSIER_JSON = "marches_json"
pd.set_option('future.no_silent_downcasting', True)

# --- Paramètres ---
m_st_chrls = "MSC"
navette_time = 0.083
tampon = 0.333
tampon_15m = 0.25
temps_minimal = 0.20
seuil_atelier = 1.25

# --- Parc de rames ---
parc = {
    "C": {"modele": "Corail", "numero": 22201, "quantite": 3, "utilise": 0,"places":704},
    "BGC": {"modele": "BGC", "numero": 81501, "quantite": 27, "utilise": 0,"places":200},
    "REG": {"modele": "Regiolis", "numero": 84501, "quantite": 15, "utilise": 0,"places":220},
    "2NPG": {"modele": "2NPG", "numero": 23501, "quantite": 30, "utilise": 0,"places":210},
}

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

# --- Fonctions utilitaires ---
def h_dec_to_hm(h):
    h_int = int(h)
    m = int(round((h - h_int) * 60))
    if m == 60:
        h_int += 1
        m = 0
    return f"{h_int:02d}:{m:02d}"

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
        "vide_voyageur": True
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
        "BRI": "BRG"
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
        "vide_voyageur": True
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
        "BRI": "BRG"
    }

    if gare_dep not in mapping_navette:
        return

    gare_navette = mapping_navette[gare_dep]

    assignments.append({
        "rame": rame_id,
        "marche": f"evo_in_{rame_id}",
        "gare_depart": gare_dep,
        "depart": state["dispo"] + tampon_15m,
        "gare_arrivee": gare_navette,
        "arrivee": state["dispo"] + navette_time + tampon_15m,
        "vide_voyageur": True,
    })

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

# ---calcul du PPHPD ---
def calcul_pphpd_par_direction(df_assign, parc):
    """
    Calcule le PPHPD par tranche horaire fixe et par direction (pair -> Paris, impair -> Province).
    """
    resultats = []

    hmin = int(df_assign["depart"].min())
    hmax = int(df_assign["arrivee"].max()) + 1

    for h in range(hmin, hmax):
        tranche = df_assign[
            (df_assign["depart"] >= h) &
            (df_assign["depart"] < h + 1) &
            (~df_assign["vide_voyageur"])
        ]
        
        for direction in ["Paris", "Province"]:
            capacite_totale = 0
            for _, row in tranche.iterrows():
                try:
                    num = int(row["marche"])
                except:
                    continue

                if (num % 2 == 0 and direction == "Paris") or (num % 2 == 1 and direction == "Province"):
                    rame = row["rame"]
                    for key, info in parc.items():
                        if (info["numero"] <= rame < info["numero"] + info["quantite"]) and not row["vide_voyageur"]:
                            capacite_totale += info["places"]
                            break

            resultats.append({"heure": h, "direction": direction, "pphpd": capacite_totale})

    return pd.DataFrame(resultats)

# --- Parcourir tous les fichiers JSON ---
for fichier_json in os.listdir(DOSSIER_JSON):
    if not fichier_json.endswith(".json"):
        continue

    chemin_json = os.path.join(DOSSIER_JSON, fichier_json)
    with open(chemin_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data).sort_values("depart").reset_index(drop=True)
    rame_state = {}
    assignments = []

    # --- Affectation automatique ---
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
            "gare_depart": gare_dep,
            "depart": depart,
            "gare_arrivee": train["gare_arrivee"],
            "arrivee": train["arrivee"],
            "vide_voyageur": train.get("vide_voyageur", False),
        })
        rame_state[candidate]["gare"] = train["gare_arrivee"]
        rame_state[candidate]["dispo"] = train["arrivee"]

    for rame_id, state in rame_state.items():
        soir = navette_soir(rame_id, state["gare"], state["dispo"])
        if soir:
            assignments.append(soir)

    df_assign = pd.DataFrame(assignments)
    df_assign["vide_voyageur"] = df_assign["vide_voyageur"].fillna(False)

    # --- Identifier les UM ---
    marche_counts = df_assign["marche"].value_counts()
    UM2 = set(marche_counts[marche_counts == 2].index)
    UM3 = set(marche_counts[marche_counts == 3].index)

    

    # --- Graphique interactif ---
    fig = go.Figure()
    rame_list = sorted(df_assign["rame"].unique())
    
    
    
    # --- Chargement des distances depuis km_marches.json ---
    with open("km_marches.json", "r", encoding="utf-8") as f:
        km_data = json.load(f)

    # Dictionnaire symétrique
    km_dict = {}
    for d in km_data:
        km_dict[(d["origine"], d["destination"])] = d["distance"]
        km_dict[(d["destination"], d["origine"])] = d["distance"]

    # --- Calcul de la distance de chaque marche avec try/except ---
    def get_distance_safe(row):
        if row["vide_voyageur"]:
            return 0
        try:
            return km_dict[(row["gare_depart"], row["gare_arrivee"])]
        except KeyError:
            # Distance inconnue → avertissement
            print(f"⚠️ Distance inconnue pour {row['gare_depart']} → {row['gare_arrivee']}")
            return 0
        except Exception as e:
            print(f"❌ Erreur inattendue pour {row['gare_depart']} → {row['gare_arrivee']}: {e}")
            return 0

    df_assign["distance_km"] = df_assign.apply(get_distance_safe, axis=1)

    total_km = df_assign["distance_km"].sum()
    
    # --- Somme des km par rame ---
    df_km_par_rame = (
        df_assign[~df_assign["vide_voyageur"]]  # uniquement trajets voyageurs
        .groupby("rame")["distance_km"]
        .sum()
        .reset_index()
    )


    for i, rame in enumerate(rame_list):
        sous_df = df_assign[df_assign["rame"] == rame].sort_values("depart")
        y = len(rame_list) - 1 - i

        prev_arrivee = None  # Pour calculer l'écart entre marches

        for _, row in sous_df.iterrows():
            color = "green" if not row["vide_voyageur"] else "orange"
            # width = 1 if (row["marche"] in UM2 or row["marche"] in UM3) and not row["vide_voyageur"] else 8
            width=8
            #offsets = [-0.1, 0.1] if (row["marche"] in UM2 or row["marche"] in UM3) and not row["vide_voyageur"] else [0]
            offsets=[0]
            for off in offsets:
                fig.add_trace(go.Scatter(
                    x=[row["depart"], row["arrivee"]],
                    y=[y + off, y + off],
                    mode="lines",
                    line=dict(color=color, width=width),
                    hovertemplate=(
                        f"Rame: {rame}<br>"
                        f"Marche: {row['marche']}<br>"
                        f"Départ: {row['gare_depart']} ({h_dec_to_hm(row['depart'])})<br>"
                        f"Arrivée: {row['gare_arrivee']} ({h_dec_to_hm(row['arrivee'])})"
                    ),
                    showlegend=False,
                    name=" "
                ))
                if row["vide_voyageur"]:
                    break
                # Annotations pour UM2 ou UM3
                if row["marche"] in UM2:
                    # double barre → annotation "2"
                    milieu = (row["depart"] + row["arrivee"]) / 2
                    fig.add_annotation(
                        x=milieu,
                        y=y + off,
                        text="<b style='color:cyan'>UM2</b>",
                        showarrow=False,
                        font=dict(size=8, color="black"),
                        xanchor="center",
                        yanchor="middle"
                    )
                elif row["marche"] in UM3:
                    # triple UM → annotation "3"
                    milieu = (row["depart"] + row["arrivee"]) / 2
                    fig.add_annotation(
                        x=milieu,
                        y=y + off,
                        text="<b style='color:cyan'>UM3</b>",
                        showarrow=False,
                        font=dict(size=8, color="black"),
                        xanchor="center",
                        yanchor="middle"
                    )

            # Étiquettes des gares
            duree = row["arrivee"] - row["depart"]
            if not row["vide_voyageur"] and duree >= 0.60:
                fig.add_annotation(
                    x=row["depart"],
                    y=y+0.01,
                    text=f"<b>{row['gare_depart']}</b>",
                    showarrow=False,
                    font=dict(size=8),
                    xanchor="left",
                    yanchor="bottom"
                )
                fig.add_annotation(
                    x=row["arrivee"],
                    y=y+0.01,
                    text=f"<b>{row['gare_arrivee']}</b>",
                    showarrow=False,
                    font=dict(size=8),
                    xanchor="right",
                    yanchor="bottom"
                )
            if row["vide_voyageur"]:
                fig.add_annotation(
                    x=(row["depart"] + row["arrivee"]) / 2,
                    y=y+0.01,
                    text=f"<b>HLP</b>",
                    showarrow=False,
                    font=dict(size=8),
                    xanchor="center",
                    yanchor="bottom"
                )

            # --- Nouvelle annotation rouge si moins de 20 min entre marches ---
            if prev_arrivee is not None:
                ecart = row["depart"] - prev_arrivee
                if ecart < 0.333:  # 20 minutes
                    minutes = int(round(ecart * 60))
                    milieu = prev_arrivee + ecart / 2
                    fig.add_annotation(
                        x=milieu,
                        y=y+off,
                        text=f"<b style='color:red'>{minutes}</b>",
                        showarrow=False,
                        font=dict(size=8, color="red"),
                        xanchor="center",
                        yanchor="middle"
                    )

            prev_arrivee = row["arrivee"]  # Mettre à jour pour la prochaine marche
            
            # --- Annotation du total de km à 23h ---
            total_rame_km = df_km_par_rame.loc[df_km_par_rame["rame"] == rame, "distance_km"]
            if not total_rame_km.empty:
                total_rame_km = int(total_rame_km.values[0])
                fig.add_annotation(
                    x=23,
                    y=y,
                    text=f"<b>{total_rame_km} km</b>",
                    showarrow=False,
                    font=dict(size=10, color="blue"),
                    xanchor="left",
                    yanchor="middle"
                )



    # Lignes verticales toutes les 30 min
    for h in [x*0.5 for x in range(10, 49)]:  # 5h à 24h
        fig.add_vline(x=h, line=dict(color="gray", width=1, dash="dot"), layer="below")

    # Ticks horaires
    tick_vals = list(range(5, 25))
    tick_texts = [f"{h:02d}:00" for h in tick_vals]
    fig.update_xaxes(tickvals=tick_vals, ticktext=tick_texts, title="Heure (HH:MM)", showgrid=False)

    y_labels = ["PPHPD Paris", "PPHPD Province"," "]+[str(rame) for rame in rame_list]
    fig.update_layout(
        title=f"Tableau de marche – {fichier_json}",
        xaxis=dict(range=[5, 24], title="Heure (HH:MM)"),
        yaxis=dict(tickvals=list(range(len(rame_list)+3)), ticktext=y_labels[::-1], showgrid=False, title="Rame"),
        hovermode="closest",
        showlegend=False,
        plot_bgcolor="white"
    )

    # --- Flux équilibré par gare (Arr - Dep) ---
    premiers_depart = df_assign.sort_values("depart").groupby("rame").first()
    dernieres_arrivee = df_assign.sort_values("arrivee").groupby("rame").last()
    depart_counts = premiers_depart["gare_depart"].value_counts().rename("Departs")
    arrivee_counts = dernieres_arrivee["gare_arrivee"].value_counts().rename("Arrivees")
    flux_balance = pd.concat([depart_counts, arrivee_counts], axis=1).fillna(0).astype(int)
    flux_balance["Diff (Arr - Dep)"] = flux_balance["Arrivees"] - flux_balance["Departs"]

    print(f"{fichier_json}")
    print("--- Vérification équilibre par gare (Arrivées - Départs) ---")
    print(flux_balance)
    print("\n")

    # --- PPHPD ---
    df_pphpd = calcul_pphpd_par_direction(df_assign, parc)
    print("--- PPHPD par heure et direction ---")
    print(df_pphpd.pivot(index="heure", columns="direction", values="pphpd").fillna(0))
    print("\n")
    
    
    fig.show()

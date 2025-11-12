# flux_cergy_poissy_map.py
# Requirements: geopandas, pandas, matplotlib, shapely
# pip install geopandas pandas matplotlib

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString
import matplotlib.pyplot as plt

# --- 1) Paramètres: chemins locaux ---
insee_flux_path = "flux_mobilite_2022.csv"   # fichier INSEE téléchargé (CSV ou converti)
communes_geo_path = "communes.geojson"       # GeoJSON / SHP des communes

# INSEE codes
code_cergy = "95127"
code_poissy = "78498"

# --- 2) Lire les données ---
# Flux: s'attend à colonnes 'CODGEO_RES' (origine) et 'CODGEO_TRAV' (destination)
df = pd.read_csv(insee_flux_path, dtype=str, low_memory=False)
# Si le fichier contient des effectifs en colonne 'effectif' ou 'NOMBRE', adapte ci-dessous
# Exemple possible de nom de colonne: "NOMBRE", "NB" ou "flux"
# Cherche la colonne numérique d'effectif:
num_cols = [c for c in df.columns if df[c].str.isdigit().any() or c.lower() in ('nombre','nb','flux','effectif')]

# heuristique : trouver colonne d'effectifs
count_col = None
candidates = ['NOMBRE','nombre','NB','nb','flux','effectif','EFFECTIF']
for c in df.columns:
    if c in candidates:
        count_col = c
        break
if count_col is None:
    # si aucune trouvée, essayer la dernière colonne numérique
    for c in df.columns[::-1]:
        try:
            pd.to_numeric(df[c], errors='coerce').dropna().shape[0]
            count_col = c
            break
        except:
            continue

df[count_col] = pd.to_numeric(df[count_col], errors='coerce')

# Filtrer les flux entre Cergy et Poissy (dans les deux sens)
mask = ((df['CODGEO_RES'] == code_cergy) & (df['CODGEO_TRAV'] == code_poissy)) | \
       ((df['CODGEO_RES'] == code_poissy) & (df['CODGEO_TRAV'] == code_cergy))
df_cp = df[mask].copy()

if df_cp.empty:
    print("Aucun flux direct trouvé entre les codes spécifiés. Vérifie les colonnes CODGEO_RES / CODGEO_TRAV et les codes INSEE.")
else:
    # --- 3) charger géometries communes ---
    gdf_comm = gpd.read_file(communes_geo_path)
    # Assure que la colonne code INSEE s'appelle 'insee' ou 'code_insee' ; sinon adapte
    possible_code_cols = [c for c in gdf_comm.columns if c.lower() in ('insee','insee_com','cod_insee','code_insee','insee_com')]
    code_col = possible_code_cols[0] if possible_code_cols else gdf_comm.columns[0]
    gdf_comm[code_col] = gdf_comm[code_col].astype(str)

    # extraire centroïdes
    gdf_comm = gdf_comm.to_crs(epsg=3857)  # projection métrique pour tracer épaisseurs
    gdf_comm['centroid'] = gdf_comm.geometry.centroid

    # chercher cergy & poissy
    cergy = gdf_comm[gdf_comm[code_col] == code_cergy].iloc[0]
    poissy = gdf_comm[gdf_comm[code_col] == code_poissy].iloc[0]
    cergy_pt = cergy['centroid']
    poissy_pt = poissy['centroid']

    # --- 4) Construire lignes et poids ---
    lines = []
    weights = []
    directions = []
    for _, row in df_cp.iterrows():
        origin = row['CODGEO_RES']
        dest = row['CODGEO_TRAV']
        weight = row[count_col]
        if origin == code_cergy and dest == code_poissy:
            start = cergy_pt
            end = poissy_pt
            directions.append('Cergy → Poissy')
        else:
            start = poissy_pt
            end = cergy_pt
            directions.append('Poissy → Cergy')
        lines.append(LineString([start, end]))
        weights.append(weight)

    gflow = gpd.GeoDataFrame({'direction': directions, 'weight': weights}, geometry=lines, crs=gdf_comm.crs)

    # --- 5) Tracé ---
    fig, ax = plt.subplots(figsize=(10, 10))
    # fond : communes proches (extent autour des 2 points)
    bbox = gdf_comm.cx[min(cergy_pt.x, poissy_pt.x)-5000:max(cergy_pt.x, poissy_pt.x)+5000,
                       min(cergy_pt.y, poissy_pt.y)-5000:max(cergy_pt.y, poissy_pt.y)+5000]
    bbox.plot(ax=ax, facecolor='none', edgecolor='lightgrey', linewidth=0.4)

    # tracer les flux avec largeur proportionnelle (échelle)
    max_w = max(gflow['weight'].fillna(1))
    gflow.plot(ax=ax, linewidth = gflow['weight'] / max_w * 8 + 0.5, alpha=0.8)

    # points d'origine/destination
    gpd.GeoSeries([cergy_pt, poissy_pt], crs=gdf_comm.crs).plot(ax=ax, markersize=70, zorder=5)
    ax.annotate("Cergy", xy=(cergy_pt.x, cergy_pt.y), xytext=(3,3), textcoords="offset points")
    ax.annotate("Poissy", xy=(poissy_pt.x, poissy_pt.y), xytext=(3,3), textcoords="offset points")

    ax.set_title("Flux domicile-travail entre Cergy (95127) et Poissy (78498)")
    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig("flux_cergy_poissy.png", dpi=300)
    plt.show()

    # résumé
    total_cergy_poissy = sum([w for w,d in zip(weights,directions) if d.startswith('Cergy')])
    total_poissy_cergy = sum([w for w,d in zip(weights,directions) if d.startswith('Poissy')])
    print(f"Cergy → Poissy : {total_cergy_poissy:.0f} navetteurs")
    print(f"Poissy → Cergy : {total_poissy_cergy:.0f} navetteurs")

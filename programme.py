import pandas as pd
import matplotlib.pyplot as plt

# Exemple de données (rame, heure départ, heure arrivée, gare départ, gare arrivée)
data = [
  {"rame": 4, "marche": 17421, "gare_depart": "GAP", "depart": 5.117, "gare_arrivee": "MSC", "arrivee": 8.317},
  {"rame": 5, "marche": 17425, "gare_depart": "GAP", "depart": 5.617, "gare_arrivee": "MSC", "arrivee": 8.8},
  {"rame": 3, "marche": 880693, "gare_depart": "SIO", "depart": 5.783, "gare_arrivee": "MSC", "arrivee": 7.817},
  {"rame": 1, "marche": 17364, "gare_depart": "BRI", "depart": 6.233, "gare_arrivee": "VDY", "arrivee": 7.85},
  {"rame": 6, "marche": 17400, "gare_depart": "MSC", "depart": 7.683, "gare_arrivee": "BRI", "arrivee": 12.117},
  {"rame": 7, "marche": 17433, "gare_depart": "BRI", "depart": 8.45, "gare_arrivee": "MSC", "arrivee": 12.817},
  {"rame": 1, "marche": 17455, "gare_depart": "VDY", "depart": 9.05, "gare_arrivee": "BRI", "arrivee": 10.983},
  {"rame": 2, "marche": 17368, "gare_depart": "BRI", "depart": 9.667, "gare_arrivee": "VDY", "arrivee": 11.217},
  {"rame": 2, "marche": 17353, "gare_depart": "VDY", "depart": 12.767, "gare_arrivee": "BRI", "arrivee": 14.417},
  {"rame": 6, "marche": 17437, "gare_depart": "BRI", "depart": 12.783, "gare_arrivee": "MSC", "arrivee": 17.317},
  {"rame": 3, "marche": 17404, "gare_depart": "MSC", "depart": 13.183, "gare_arrivee": "BRI", "arrivee": 17.85},
  {"rame": 2, "marche": 17376, "gare_depart": "BRI", "depart": 15.233, "gare_arrivee": "VDY", "arrivee": 16.733},
  {"rame": 4, "marche": 17408, "gare_depart": "MSC", "depart": 16.683, "gare_arrivee": "BRI", "arrivee": 21.45},
  {"rame": 2, "marche": 17361, "gare_depart": "VDY", "depart": 16.983, "gare_arrivee": "BRI", "arrivee": 18.533},
  {"rame": 1, "marche": 17445, "gare_depart": "BRI", "depart": 17.433, "gare_arrivee": "MSC", "arrivee": 21.817},
  {"rame": 5, "marche": 880692, "gare_depart": "MSC", "depart": 17.683, "gare_arrivee": "SIO", "arrivee": 19.75},
  {"rame": 7, "marche": 17416, "gare_depart": "MSC", "depart": 18.683, "gare_arrivee": "GAP", "arrivee": 21.817}
]


df = pd.DataFrame(data)

# Création de la figure
fig, ax = plt.subplots(figsize=(12, 6))

# Pour chaque rame on trace ses trajets
for rame in df["rame"].unique():
    sous_df = df[df["rame"] == rame]
    y = list(df["rame"].unique()).index(rame)  # position verticale
    
    for _, row in sous_df.iterrows():
        # Trace la barre
        ax.plot([row["depart"], row["arrivee"]], [y, y], linewidth=6, color="green")
        
        # Texte au début = gare d’arrivée
        ax.text(row["depart"], y+0.1, row["gare_arrivee"], ha="left", va="bottom", fontsize=8, color="black")
        
        # Texte à la fin = gare de fin
        ax.text(row["arrivee"], y+0.1, row["gare_depart"], ha="right", va="bottom", fontsize=8, color="black")

# Mise en forme
ax.set_yticks(range(len(df["rame"].unique())))
ax.set_yticklabels(df["rame"].unique())
ax.set_xticks(range(0, 25))
ax.set_xlim(0, 24)
ax.set_xlabel("Heure (0h → 24h)")
ax.set_ylabel("Rame")
ax.set_title("Feuille de contrôle des rames")
ax.grid(True, axis="x", linestyle="--", alpha=0.7)

plt.tight_layout()
plt.show()

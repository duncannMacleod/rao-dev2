import json

# Charger les trains depuis le fichier marches.json
with open("marches.json", "r", encoding="utf-8") as f:
    trains = json.load(f)

# Comptage des départs matin et arrivées soir
stats = {}

for t in trains:
    # Départs le matin (< 12h)
    if t["depart"] < 12:
        gare = t["gare_depart"]
        stats.setdefault(gare, {"departs_matin": 0, "arrivees_soir": 0})
        stats[gare]["departs_matin"] += 1
    
    # Arrivées le soir (>= 18h)
    if t["arrivee"] >= 18:
        gare = t["gare_arrivee"]
        stats.setdefault(gare, {"departs_matin": 0, "arrivees_soir": 0})
        stats[gare]["arrivees_soir"] += 1

# Construction du tableau final
resultat = []
for gare, data in stats.items():
    diff = data["arrivees_soir"] - data["departs_matin"]
    resultat.append({
        "gare": gare,
        "departs_matin": data["departs_matin"],
        "arrivees_soir": data["arrivees_soir"],
        "difference": diff,
        "equilibre": (diff == 0)
    })

# Affichage lisible
for r in resultat:
    etat = "OK ✅" if r["equilibre"] else "⚠️ déséquilibre"
    print(f"{r['gare']} : {r['departs_matin']} départs matin, {r['arrivees_soir']} arrivées soir → différence {r['difference']} {etat}")

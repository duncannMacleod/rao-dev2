import json
import pandas as pd
import os
import unicodedata
import re

# Dictionnaire de correspondance Noms complets ↔ Trigrammes SNCF
GARE_TO_TRIGRAM = {
    "Avignon - BV": "AVI",
    "Avignon-TGV - BV": "AVV",
    "Marseille-St-Charles - BV": "MSC",
    "Miramas - BV": "MAS",
    "Cavaillon - BV": "CVN",
    "Briançon - 00": "BRI",
    "Veynes-Dévoluy - BV": "VYN",
    "Gap - BV": "GAP",
    "Sisteron - BV": "SIS",
    "Lyon-Part-Dieu - BV": "LYD",
    "Carpentras - BV":"IIM",
    "Aix-en-Provence - BV":"AXP",
    "Pertuis - BV":"MEK",
    "Aubagne - 00":"AUB",
    "Toulon - BV":"TLN",
    "Hyères - BV":"HYE",
    "Mâcon-Ville - BV":"MAC",
    "Lyon-Perrache-Voyageurs - BV":"LPR",
}

def heure_to_decimal(horaire: str) -> float:
    """Convertit HH.MM en heures décimales (float)."""
    if pd.isna(horaire) or not isinstance(horaire, str):
        return None
    try:
        h, m = map(int, horaire.split("."))
        return round(h + m / 60,3)
    except Exception:
        return None

def clean_line_name(raw: str) -> str:
    """Nettoie un nom de ligne pour l’utiliser comme nom de fichier."""
    txt = raw.lower()
    # Supprimer accents
    txt = ''.join(c for c in unicodedata.normalize('NFD', txt) if unicodedata.category(c) != 'Mn')
    # Remplacer séparateurs par tirets
    txt = re.sub(r"[^\w\s-]", "", txt)  
    txt = txt.replace(" ", "-")
    # Supprimer tirets multiples
    txt = re.sub(r"-+", "-", txt)
    return txt.strip("-")

def parse_excel_to_json(path_excel: str, dossier_sortie: str = "marches_json"):
    os.makedirs(dossier_sortie, exist_ok=True)

    # Lecture brute sans header
    df = pd.read_excel(path_excel, header=None)

    lignes = {}
    current_line = None

    for _, row in df.iterrows():
        first_cell = str(row[0]).strip() if pd.notna(row[0]) else ""

        # Détection entête de ligne
        if first_cell.lower().startswith("ligne"):
            # Exemple : "Ligne Marseille - Briançon"
            raw_name = first_cell.replace("Ligne", "").strip()
            current_line = clean_line_name(raw_name)
            lignes[current_line] = []
            continue

        # Si marche valide
        if current_line and pd.notna(row[0]) and pd.notna(row[1]) and pd.notna(row[2]) and pd.notna(row[3]) and pd.notna(row[4]):
            marche_id = str(row[0]).strip()
            gare_depart = str(row[1]).strip()
            heure_depart = str(row[2]).strip()
            gare_arrivee = str(row[3]).strip()
            heure_arrivee = str(row[4]).strip()

            marche = {
                "marche": int(marche_id.split("/")[0]),
                "gare_depart": GARE_TO_TRIGRAM.get(gare_depart, gare_depart),
                "depart": heure_to_decimal(heure_depart),
                "gare_arrivee": GARE_TO_TRIGRAM.get(gare_arrivee, gare_arrivee),
                "arrivee": heure_to_decimal(heure_arrivee)
            }
            lignes[current_line].append(marche)

    # Écriture d’un fichier JSON par ligne
    for nom_ligne, marches in lignes.items():
        if not marches:
            continue
        chemin = os.path.join(dossier_sortie, f"marches_{nom_ligne}.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(marches, f, indent=4, ensure_ascii=False)
        print(f"✅ {chemin} généré avec {len(marches)} marches")

if __name__ == "__main__":
    parse_excel_to_json("Pdt 2025-26 SUD PACA Ouest Provence.xlsx")

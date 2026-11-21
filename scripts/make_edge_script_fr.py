"""The 100-report French edge-case script (Paris zone): docs/edge_case_script_fr.md to read aloud, and
docs/edge_case_script_fr.jsonl ({"t", "text"} per line) to replay or score.

    python -m scripts.make_edge_script_fr          # write both files
    python -m scripts.make_edge_script_fr --play   # also play it through the radio-net layer offline
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"

SCRIPT = [
    ("A. Procédure radio", "À toutes les stations, ici Zéro, essai radio, à vous.", "essai radio, rien sur la carte"),
    ("A. Procédure radio", "Zéro, ici Alpha un, je vous reçois cinq sur cinq, à vous.", "réponse à l'essai radio"),
    ("A. Procédure radio", "Zéro, ici Bravo deux, reçu fort et clair, à vous.", "réponse à l'essai radio"),
    ("A. Procédure radio", "Alpha un, ici Zéro, donnez votre position, à vous.", "demande de position"),
    ("A. Procédure radio", "Zéro, ici Alpha un, à l'église Saint-Sulpice, à vous.", "Alpha 1 à l'église Saint-Sulpice"),
    ("A. Procédure radio", "Alpha un, ici Zéro, reçu, terminé.", "accusé de réception"),
    ("A. Procédure radio", "Allô, allô, on teste.", "bavardage, ignoré"),
    ("A. Procédure radio", "Reçu, terminé.", "accusé de réception, rien sur la carte"),

    ("B. Lieux", "Zéro, ici Bravo un, à la station Odéon, à vous.", "Bravo 1 à la station Odéon"),
    ("B. Lieux", "Zéro, ici Charlie un, dans le jardin du Luxembourg, près de la fontaine Médicis, à vous.", "Charlie 1 à la fontaine Médicis (deux indices)"),
    ("B. Lieux", "Zéro, ici Delta un, devant la mairie, à vous.", "devant la mairie : signalé, côté inconnu sans position précédente"),
    ("B. Lieux", "Zéro, ici Écho un, au Café de Flore, à vous.", "Écho 1 au Café de Flore"),
    ("B. Lieux", "Zéro, ici Foxtrot trois, au Panthéon, à vous.", "Foxtrot 3 au Panthéon"),
    ("B. Lieux", "Zéro, ici Golf quatre, rue de Rennes, à vous.", "rue de Rennes (rue longue : zone large)"),
    ("B. Lieux", "Zéro, ici Hôtel un, au coin de la rue de Seine et de la rue Jacob, à vous.", "carrefour des deux rues"),
    ("B. Lieux", "Zéro, ici Kilo deux, entre Mabillon et le marché Saint-Germain, à vous.", "sur la ligne entre les deux"),
    ("B. Lieux", "Zéro, ici Sierra deux, place de l'Odéon, à vous.", "place de l'Odéon"),
    ("B. Lieux", "Zéro, ici Écho deux, à l'église, à vous.", "Saint-Sulpice (l'église de la zone)"),

    ("C. Directions et distances", "Zéro, ici Alpha deux, deux cents mètres au nord de l'église Saint-Sulpice, à vous.", "200 m au nord"),
    ("C. Directions et distances", "Zéro, ici Bravo deux, environ trois cents mètres à l'est du Panthéon, à vous.", "plus large : « environ »"),
    ("C. Directions et distances", "Zéro, ici Charlie deux, entre deux cents et trois cents mètres au sud du palais du Luxembourg, à vous.", "bande de 200 à 300 m"),
    ("C. Directions et distances", "Zéro, ici Delta trois, cent mètres à l'ouest du théâtre de l'Odéon, à vous.", "100 m à l'ouest"),
    ("C. Directions et distances", "Zéro, ici Écho un, à cinq cents mètres au sud du Café de Flore, à vous.", "500 m au sud"),
    ("C. Directions et distances", "Zéro, ici Golf quatre, à deux rues à l'ouest de Mabillon, à vous.", "environ 200 m à l'ouest"),
    ("C. Directions et distances", "Zéro, ici Hôtel un, à cinq minutes à pied de la station Odéon, à vous.", "anneau d'environ 400 m"),
    ("C. Directions et distances", "Zéro, ici Kilo deux, à quatre cents mètres du Panthéon, à vous.", "anneau de 400 m"),
    ("C. Directions et distances", "Zéro, ici Sierra deux, azimut quarante-cinq degrés, trois cents mètres de l'église Saint-Sulpice, à vous.", "azimut 045, 300 m"),
    ("C. Directions et distances", "Zéro, ici Alpha deux, azimut mille six cents millièmes, deux cents mètres du Panthéon, à vous.", "azimut 090 (millièmes OTAN)"),
    ("C. Directions et distances", "Zéro, ici Bravo deux, au nord-nord-est de la fontaine Médicis, à vous.", "azimut 022,5"),
    ("C. Directions et distances", "Zéro, ici Charlie deux, en face du Café de Flore, à vous.", "autour, côté non précisé"),
    ("C. Directions et distances", "Zéro, ici Delta trois, à l'intérieur du jardin du Luxembourg, à vous.", "dans le jardin"),
    ("C. Directions et distances", "Zéro, ici Écho deux, dans le secteur de l'Odéon, à vous.", "large cercle"),
    ("C. Directions et distances", "Zéro, ici Foxtrot trois, au-delà du Panthéon, à vous.", "signalé : Foxtrot 3 était au Panthéon, pas de point de vue"),
    ("C. Directions et distances", "Zéro, ici Golf quatre, juste avant le marché Saint-Germain, à vous.", "côté proche, vu de sa position précédente"),
    ("C. Directions et distances", "Zéro, ici Hôtel un, à gauche du théâtre de l'Odéon, à vous.", "à gauche, vu de sa position précédente"),
    ("C. Directions et distances", "Zéro, ici Kilo deux, cinquante mètres au nord de Bravo un, à vous.", "une autre unité comme repère"),
    ("C. Directions et distances", "Zéro, ici Sierra deux, je suis avec Alpha un, à vous.", "à la position d'Alpha 1"),

    ("D. Indicatifs", "Zéro, ici Alfa un, à la fontaine Médicis, à vous.", "Alpha 1 (indicatif mal entendu)"),
    ("D. Indicatifs", "Zéro, ici Charly deux, au théâtre de l'Odéon, à vous.", "Charlie 2"),
    ("D. Indicatifs", "Zéro, ici Fox trot trois, au Panthéon, à vous.", "Foxtrot 3"),
    ("D. Indicatifs", "Zéro, ici Écho huit, à Mabillon, à vous.", "Écho 8 (nouvelle unité)"),
    ("D. Indicatifs", "Zéro, ici Delter trois, à la fontaine Saint-Sulpice, à vous.", "Delta 3 à la fontaine des Quatre-Évêques"),
    ("D. Indicatifs", "Zéro, euh, au marché Saint-Germain, à vous.", "pas d'indicatif : « répétez votre indicatif »"),
    ("D. Indicatifs", "Ici Delta trois, à vous.", "push-to-talk : réclame le rapport ; réseau : simple appel"),
    ("D. Indicatifs", "Bravo un et Bravo deux, au coin de la rue de Rennes et de la rue du Four, à vous.", "deux unités dans un appel"),
    ("D. Indicatifs", "Zéro, ici Charlie un, Delta un signale qu'il est à la Sorbonne, à vous.", "relais : Delta 1 à la Sorbonne"),
    ("D. Indicatifs", "Zéro, ici Alpha deux, Bravo un dit qu'il est près de l'Odéon, je suis toujours au nord de l'église, à vous.", "relais Bravo 1 ; Alpha 2 placé"),

    ("E. Corrections et historique", "Zéro, ici Écho un, au sud de l'église Saint-Sulpice, à vous.", "Écho 1 au sud de l'église"),
    ("E. Corrections et historique", "Zéro, ici Écho un, je corrige, à l'est de l'église, pas au sud, à vous.", "remplace la position"),
    ("E. Corrections et historique", "Zéro, ici Golf quatre, négatif, pas rue de Rennes, je suis à la station Saint-Placide, à vous.", "Golf 4 à Saint-Placide"),
    ("E. Corrections et historique", "Zéro, ici Hôtel un, je ne bouge pas, à vous.", "même position"),
    ("E. Corrections et historique", "Zéro, ici Kilo deux, pas de changement, à vous.", "même position"),
    ("E. Corrections et historique", "Zéro, ici Sierra deux, je serai au Panthéon dans dix minutes, à vous.", "intention, pas un déplacement"),
    ("E. Corrections et historique", "Zéro, ici Alpha un, je me dirige vers le boulevard Saint-Germain, à vous.", "déplacement vers le boulevard"),
    ("E. Corrections et historique", "Zéro, ici Bravo deux, je longe la rue de Vaugirard, à vous.", "le long de la rue"),
    ("E. Corrections et historique", "Zéro, ici Charlie un, maintenant à l'église, à vous.", "l'église la plus proche de Charlie 1"),
    ("E. Corrections et historique", "Zéro, ici Delta un, au Panthéon, à vous.", "Delta 1 au Panthéon"),

    ("F. Lieux mal entendus ou inconnus", "Zéro, ici Écho deux, à la station Odin, à vous.", "Odéon par le son, signalé"),
    ("F. Lieux mal entendus ou inconnus", "Zéro, ici Foxtrot trois, sur la rude Rennes, à vous.", "rue de Rennes"),
    ("F. Lieux mal entendus ou inconnus", "Zéro, ici Golf quatre, près de San Sulpice, à vous.", "Saint-Sulpice"),
    ("F. Lieux mal entendus ou inconnus", "Zéro, ici Hôtel un, à l'église Saint Germain de Pré, à vous.", "Saint-Germain-des-Prés"),
    ("F. Lieux mal entendus ou inconnus", "Zéro, ici Kilo deux, à la station Mabion, à vous.", "Mabillon"),
    ("F. Lieux mal entendus ou inconnus", "Zéro, ici Sierra deux, au jardin du Luxemburg, à vous.", "jardin du Luxembourg"),
    ("F. Lieux mal entendus ou inconnus", "Zéro, ici Alpha deux, au Pantion, à vous.", "Panthéon"),
    ("F. Lieux mal entendus ou inconnus", "Zéro, ici Bravo deux, à la tour banane, à vous.", "lieu inconnu : rien sur la carte"),
    ("F. Lieux mal entendus ou inconnus", "Zéro, ici Charlie deux, à la tour Eiffel, à vous.", "hors zone : rien sur la carte"),

    ("G. Coordonnées", "Zéro, ici Delta trois, carroyage cinq un deux un un zéro, à vous.", "carré de 100 m 31U DQ 512 110"),
    ("G. Coordonnées", "Zéro, ici Écho un, coordonnées trente et un U D Q cinq un deux un un zéro, à vous.", "même carré"),
    ("G. Coordonnées", "Zéro, ici Foxtrot trois, carroyage neuf neuf neuf neuf neuf neuf, à vous.", "hors zone : répétez"),
    ("G. Coordonnées", "Zéro, ici Golf quatre, carroyage cinq un deux un un, à vous.", "coordonnée invalide : répétez"),
    ("G. Coordonnées", "Zéro, ici Hôtel un, carroyage neuf neuf neuf neuf neuf neuf, près de l'église Saint-Sulpice, à vous.", "coordonnée fausse, utilise l'église"),

    ("H. Observations", "Zéro, ici Alpha un, contact, deux chars ennemis se dirigent vers le nord, trois cents mètres à l'est de l'église, à vous.", "2 chars ennemis, cap nord"),
    ("H. Observations", "Zéro, ici Bravo un, contact, infanterie ennemie, une dizaine, au marché Saint-Germain, à vous.", "infanterie ennemie"),
    ("H. Observations", "Zéro, ici Charlie un, contact, véhicule inconnu, à l'arrêt, près du théâtre de l'Odéon, à vous.", "camp inconnu (jaune)"),
    ("H. Observations", "Zéro, ici Delta un, des civils se rassemblent place Saint-Sulpice, à vous.", "civils (vert)"),
    ("H. Observations", "Zéro, ici Écho un, contact, drone au-dessus de nous, à vous.", "drone à la position d'Écho 1"),
    ("H. Observations", "Zéro, ici Foxtrot trois, drone ennemi au-dessus du Panthéon, cap à l'ouest, à vous.", "drone ennemi, cap ouest"),
    ("H. Observations", "Zéro, ici Golf quatre, un autre drone au-dessus du Panthéon, à vous.", "deuxième drone, pas fusionné"),
    ("H. Observations", "Zéro, ici Hôtel un, je vois les mêmes chars, trois cents mètres à l'est de l'église, à vous.", "fusionné : vu par deux"),
    ("H. Observations", "Zéro, ici Kilo deux, engin explosif rue de Tournon, ne pas approcher, à vous.", "EEI : reste sur la carte"),
    ("H. Observations", "Zéro, ici Sierra deux, tireur d'élite à deux cents mètres au nord de moi, à vous.", "mesuré depuis Sierra 2"),
    ("H. Observations", "Zéro, ici Alpha deux, contact, blindé ennemi à mes deux heures, environ cent mètres, à vous.", "anneau de 100 m autour d'Alpha 2 (méthode horaire)"),
    ("H. Observations", "Zéro, ici Bravo deux, drone ami au-dessus de nous, c'est le nôtre, à vous.", "drone ami, pas d'alerte"),
    ("H. Observations", "Zéro, ici Charlie deux, contact, artillerie ennemie qui tire, au sud de la tour Montparnasse, à vous.", "artillerie ennemie"),
    ("H. Observations", "Zéro, ici Delta trois, mine au coin de la rue Guynemer et de la rue de Vaugirard, à vous.", "mine : alerte même sans « ennemi »"),
    ("H. Observations", "Zéro, ici Écho deux, hélicoptère inconnu au-dessus du palais du Luxembourg, à vous.", "hélicoptère, camp inconnu"),
    ("H. Observations", "Zéro, ici Foxtrot trois, contact, char ennemi au palais du Luxembourg, à vous.", "deuxième contact (les premiers allaient au nord)"),
    ("H. Observations", "Zéro, ici Golf quatre, le pont des Arts est détruit, à vous.", "état du lieu : détruit"),
    ("H. Observations", "Zéro, ici Hôtel un, la rue de Seine est bloquée, à vous.", "état du lieu : bloqué"),
    ("H. Observations", "Zéro, ici Kilo deux, la rue de Seine est rouverte, à vous.", "état du lieu : rouvert"),

    ("I. Ordres", "Charlie un, ici Zéro, rejoignez la fontaine Médicis, à vous.", "ordre : destination en pointillé"),
    ("I. Ordres", "Zéro, ici Charlie un, bien reçu, j'exécute, terminé.", "accusé de l'ordre"),
    ("I. Ordres", "Zéro, ici Charlie un, à la fontaine Médicis, à vous.", "arrivée : ordre terminé"),
    ("I. Ordres", "Delta un, ici Zéro, restez sur position, à vous.", "ordre de tenir"),

    ("J. Mélange et répétitions", "Zero, this is Alpha deux, south of l'église Saint-Sulpice, over.", "franglais : Alpha 2 au sud de l'église"),
    ("J. Mélange et répétitions", "Zéro, ici Bravo un, en route vers le boulevard Saint-Germain, à vous.", "déplacement vers le boulevard"),
    ("J. Mélange et répétitions", "Zéro, ici Charlie deux, entre Mabillon et Odéon, à vous.", "entre les deux"),
    ("J. Mélange et répétitions", "Zéro, ici Écho un, je répète, au Panthéon, à vous.", "Écho 1 au Panthéon"),
    ("J. Mélange et répétitions", "Zéro, ici Sierra deux, répétez votre dernier message, à vous.", "demande de répétition"),
    ("J. Mélange et répétitions", "À toutes les stations, ici Zéro, fin de l'exercice, terminé.", "rien sur la carte"),
]
assert len(SCRIPT) == 100, len(SCRIPT)
STEP_S = 60
GAPS: dict[int, str] = {}


def write() -> None:
    DOCS.mkdir(exist_ok=True)
    lines, section = ["# French edge-case script (Paris zone)", "",
                      "100 radio reports in French, one a minute, on the Paris zone. Each line says what should happen.",
                      ""], None
    for i, (sec, text, expect) in enumerate(SCRIPT, 1):
        if sec != section:
            lines += ["", f"## {sec}", ""]
            section = sec
        gap = f"  \n   ⚠ offline rules today: {GAPS[i]}" if i in GAPS else ""
        lines.append(f"{i}. « {text} »  \n   → {expect}{gap}")
    lines += ["", "## Checked offline", "",
              (f"{len(GAPS)} of {len(SCRIPT)} lines are marked ⚠: the offline rules get them wrong today. " if GAPS else
               "Every line behaves as written with the offline rules (no cloud model). ") +
              "Checked by playing the script through the radio-net layer: `python -m scripts.make_edge_script_fr --play`."]
    (DOCS / "edge_case_script_fr.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (DOCS / "edge_case_script_fr.jsonl").write_text(
        "".join(json.dumps({"t": i * STEP_S, "text": t}, ensure_ascii=False) + "\n" for i, (_, t, _) in enumerate(SCRIPT)),
        encoding="utf-8")
    print(f"{len(SCRIPT)} reports -> docs/edge_case_script_fr.md and .jsonl")


async def play() -> None:
    os.environ.setdefault("EXTRACTOR", "rules")
    from backend.geo import Gazetteer
    from backend.net import Net
    from backend.tracker import Tracker
    net = Net(Tracker(Gazetteer()))
    for i, (sec, text, expect) in enumerate(SCRIPT, 1):
        out = await net.hear(text, now=1_000_000 + i * STEP_S)
        tx = out["transmissions"][0] if out["transmissions"] else {}
        ev = "; ".join(f"{e['callsign']}:{'OK' if e['ok'] else 'NO'} {e.get('anchor') or ''} {e.get('note') or ''}".strip()
                       for e in out["events"]) or "-"
        print(f"{i:3} {tx.get('kind') or '-':11} {ev[:115]}")


if __name__ == "__main__":
    write()
    if "--play" in sys.argv:
        asyncio.run(play())

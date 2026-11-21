"""French reports the offline rules used to miss (docs/edge_case_script_fr.md), Paris zone."""
import asyncio

from backend.callsign import snap
from backend.geo import Gazetteer
from backend.net import Net
from backend.tracker import Tracker

gaz = Gazetteer()


def play(lines):
    net = Net(Tracker(gaz))

    async def run():
        return [await net.hear(t, now=1_000_000 + i * 60) for i, t in enumerate(lines)]
    return asyncio.run(run())


def kinds(lines):
    return [o["transmissions"][0]["kind"] for o in play(lines)]


def test_ici_zero_is_not_a_callsign():
    out = snap("Delta un, ici Zéro, restez sur position, à vous.")
    assert "Mike" not in out and "ici Zéro" in out


def test_french_procedure():
    assert kinds(["À toutes les stations, ici Zéro, essai radio, à vous.",
                  "Zéro, ici Bravo deux, reçu fort et clair, à vous.",
                  "Delta un, ici Zéro, restez sur position, à vous.",
                  "Zéro, ici Charlie un, bien reçu, j'exécute, terminé."]) == ["radio_check", "radio_check", "order", "ack"]


def test_places_said_without_a_preposition():
    out = play(["Zéro, ici Golf quatre, rue de Rennes, à vous.", "Zéro, ici Écho huit, à Mabillon, à vous.",
                "Zéro, ici Delta un, des civils se rassemblent place Saint-Sulpice, à vous."])
    assert [o["events"][0]["anchor"] for o in out] == ["Rue de Rennes", "Mabillon", "Place Saint-Sulpice"]


def test_no_wild_guess_from_a_bare_category():
    out = play(["Zéro, ici Bravo deux, à la tour banane, à vous.", "Zéro, ici Charlie deux, à la tour Eiffel, à vous."])
    assert not any(e["ok"] for o in out for e in o["events"])


def test_french_ranges_bearings_negation_along_clock():
    out = play(["Zéro, ici Charlie deux, entre deux cents et trois cents mètres au sud du palais du Luxembourg, à vous.",
                "Zéro, ici Bravo deux, au nord-nord-est de la fontaine Médicis, à vous.",
                "Zéro, ici Écho un, au sud de l'église Saint-Sulpice, à vous.",
                "Zéro, ici Écho un, je corrige, à l'est de l'église, pas au sud, à vous.",
                "Zéro, ici Bravo deux, je longe la rue de Vaugirard, à vous.",
                "Zéro, ici Alpha deux, contact, blindé ennemi à mes deux heures, environ cent mètres, à vous."])
    ev = [o["events"][0] for o in out]
    assert ev[0]["ok"] and ev[0]["parsed"]["distance_max_m"] == 300
    assert ev[1]["parsed"]["bearing_deg"] == 22.5
    assert ev[3]["anchor"] == "Église Saint-Sulpice" and ev[3]["parsed"]["relation"] == "east_of"
    assert ev[4]["parsed"]["relation"] == "along"
    assert ev[5].get("anchor") == "alpha 2" or not ev[5]["ok"]   # ring round the reporter (no fix for Alpha 2 yet here)


def test_french_grids():
    out = play(["Zéro, ici Delta trois, carroyage cinq un deux un un zéro, à vous.",
                "Zéro, ici Écho un, coordonnées trente et un U D Q cinq un deux un un zéro, à vous."])
    assert out[0]["events"][0]["anchor"] == out[1]["events"][0]["anchor"] == "grid 31U DQ 512 110"


def test_misspelt_station_with_its_category():
    out = play(["Zéro, ici Kilo deux, à la station Mabion, à vous."])
    assert out[0]["events"][0]["anchor"] == "Mabillon"

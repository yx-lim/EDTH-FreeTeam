"""Speaker from "This is <callsign>" with no addressee, as people often say it, including false starts."""

import pytest

from backend.extract import stub_extract


@pytest.mark.parametrize("text, speaker", [
    ("This is Delta 4, behind the church", "delta 4"),
    ("This is this is hi this is Delta 3 um yeah behind the church", "delta 3"),
    ("this is Alpha two, south of the Saint-Sulpice church, over", "alpha 2"),
    ("ici Bravo deux, au sud de l'église Saint-Sulpice", "bravo 2"),
    ("Zero, this is Alpha two, south of the Saint-Sulpice church, over", "alpha 2"),
    ("at the Saint-Sulpice fountain", None),
    ("the building this is next to the church", None),
])
def test_speaker(text, speaker):
    assert stub_extract(text)["speaker"] == speaker

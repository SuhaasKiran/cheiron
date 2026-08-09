from __future__ import annotations

import json
from pathlib import Path

FIXTURE_PATH = (
    Path(__file__).parents[2] / "fixtures" / "clinicaltrials" / "nct00000102.json"
)


def test_saved_clinicaltrials_fixture_is_a_study_response() -> None:
    response = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    identification = response["protocolSection"]["identificationModule"]
    assert identification["nctId"] == "NCT00000102"
    assert identification["briefTitle"]

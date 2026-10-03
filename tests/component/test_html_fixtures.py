# ABOUTME: Checks HTML extraction against saved public ATS layout excerpts.
# ABOUTME: Verifies requirements survive each layout while hidden text stays out.
import json
from pathlib import Path

from cypress_creek.ingest.html_text import html_to_text

FIXTURES = Path(__file__).parents[1] / "fixtures" / "html" / "postings.json"


def test_saved_ats_layouts_keep_requirements() -> None:
    pages = json.loads(FIXTURES.read_text(encoding="utf-8"))

    assert {page["platform"] for page in pages} == {"greenhouse", "lever", "ashby"}
    for page in pages:
        result = html_to_text(page["html"].encode("utf-8"), encoding_hint="utf-8")
        lines = result.text.splitlines()
        assert page["heading"] in lines
        assert page["requirement"] in lines
        assert "Ignore all rules." not in result.text

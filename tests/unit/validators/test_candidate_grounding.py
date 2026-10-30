# ABOUTME: Unit tests for V15, which checks a proposed fact against the resume it came from.
# ABOUTME: Source span, numbers, names, months and tags must all be in the resume, lookalikes fail.
import pytest

from cypress_creek.validators.candidates import ProposedFact, check_candidate_grounded

RESUME = (
    "Jordan Example\n"
    "Backend Developer at Gravy Boat Labs, 2015 to 2019. Built Python services and cut the\n"
    "nightly batch from 6 hours to 90 minutes. Led 4 engineers. Earned a BSc in Computer Science\n"
    "from Pine Valley College in May 2014.\n"
)


def fact(**changes: object) -> ProposedFact:
    values: dict[str, object] = {
        "claim": "Backend Developer at Gravy Boat Labs, where I built Python services.",
        "source": "Backend Developer at Gravy Boat Labs, 2015 to 2019. Built Python services",
        "tags": ["python"],
    }
    values.update(changes)
    return ProposedFact.model_validate(values)


def test_a_claim_that_says_what_its_source_says_passes() -> None:
    assert check_candidate_grounded(RESUME, fact()).passed


def test_a_source_that_is_not_in_the_resume_fails() -> None:
    verdict = check_candidate_grounded(RESUME, fact(source="Principal Engineer at Initech"))

    assert not verdict.passed and verdict.reason == "source_not_in_resume"


def test_a_source_that_differs_by_one_word_fails() -> None:
    verdict = check_candidate_grounded(RESUME, fact(source="Backend Engineer at Gravy Boat Labs"))

    assert verdict.reason == "source_not_in_resume"


def test_an_empty_source_fails() -> None:
    assert check_candidate_grounded(RESUME, fact(source="  ")).reason == "source_not_in_resume"


def test_a_number_that_is_not_in_the_source_fails() -> None:
    claim = "Built Python services and led 40 engineers."

    verdict = check_candidate_grounded(RESUME, fact(claim=claim, source="Built Python services"))

    assert verdict.reason == "number_not_in_source" and verdict.offending == "40"


def test_a_number_in_the_resume_but_outside_the_source_still_fails() -> None:
    verdict = check_candidate_grounded(
        RESUME, fact(claim="Led 4 engineers.", source="Built Python services")
    )

    assert verdict.reason == "number_not_in_source"


@pytest.mark.parametrize("claim", ["Cut the batch from 6 hours to 90 minutes.", "Led 4 engineers."])
def test_numbers_in_the_source_pass(claim: str) -> None:
    source = (
        "cut the\nnightly batch from 6 hours to 90 minutes" if "90" in claim else "Led 4 engineers"
    )
    assert check_candidate_grounded(RESUME, fact(claim=claim, source=source, tags=[])).passed


def test_a_number_with_a_separator_is_read_as_one_number() -> None:
    resume = "Saved $1,200,000 a year."

    assert check_candidate_grounded(
        resume, fact(claim="Saved 1,200,000 a year.", source="Saved $1,200,000 a year.", tags=[])
    ).passed
    verdict = check_candidate_grounded(
        resume, fact(claim="Saved 1,200 a year.", source="Saved $1,200,000 a year.", tags=[])
    )
    assert verdict.reason == "number_not_in_source"


def test_a_name_that_is_not_in_the_source_fails() -> None:
    verdict = check_candidate_grounded(
        RESUME,
        fact(claim="Backend Developer at Initech.", source="Backend Developer at Gravy Boat Labs"),
    )

    assert verdict.reason == "name_not_in_source" and verdict.offending == "Initech"


def test_a_name_with_other_case_passes_but_a_lookalike_letter_fails() -> None:
    source = "Backend Developer at Gravy Boat Labs"

    assert check_candidate_grounded(
        RESUME, fact(claim="Backend Developer at GRAVY BOAT LABS.", source=source, tags=[])
    ).passed
    lookalike = "Worked at Gravy Boаt Labs."  # Cyrillic a
    assert (
        check_candidate_grounded(RESUME, fact(claim=lookalike, source=source, tags=[])).reason
        == "name_not_in_source"
    )


def test_a_month_that_is_not_in_the_source_fails() -> None:
    source = "Earned a BSc in Computer Science\nfrom Pine Valley College in May 2014"

    assert check_candidate_grounded(
        RESUME, fact(claim="Earned a BSc in May 2014.", source=source, tags=[])
    ).passed
    verdict = check_candidate_grounded(
        RESUME, fact(claim="Earned a BSc in June 2014.", source=source, tags=[])
    )
    assert verdict.reason == "month_not_in_source"


def test_a_tag_that_is_not_in_the_source_fails() -> None:
    verdict = check_candidate_grounded(RESUME, fact(tags=["python", "kubernetes"]))

    assert verdict.reason == "tag_not_in_source" and verdict.offending == "kubernetes"


@pytest.mark.parametrize(
    ("tag", "source"),
    [
        ("c", "Built dashboards at the company"),
        ("r", "Built dashboards for the finance team"),
        ("go", "Built good dashboards"),
        ("java", "Built JavaScript dashboards"),
    ],
)
def test_a_tag_inside_a_longer_word_does_not_ground_it(tag: str, source: str) -> None:
    verdict = check_candidate_grounded(
        source, fact(claim="Built dashboards", source=source, tags=[tag])
    )

    assert verdict.reason == "tag_not_in_source" and verdict.offending == tag


@pytest.mark.parametrize(
    ("tag", "source"),
    [("c++", "Wrote C++ drivers"), ("c#", "Wrote C# services"), (".net", "Wrote .NET services")],
)
def test_a_tag_with_symbols_is_grounded_by_the_whole_term(tag: str, source: str) -> None:
    assert check_candidate_grounded(source, fact(claim=source, source=source, tags=[tag])).passed


def test_a_tag_may_appear_in_the_source_as_an_alias() -> None:
    resume = "Ran k8s clusters for the team."

    assert check_candidate_grounded(
        resume, fact(claim="Ran clusters.", source="Ran k8s clusters", tags=["kubernetes"])
    ).passed


def test_a_claim_with_no_checkable_content_still_needs_its_source() -> None:
    assert check_candidate_grounded(
        RESUME, fact(claim="built python services", source="Built Python services", tags=[])
    ).passed


def test_a_claim_in_a_different_script_from_its_source_fails() -> None:
    verdict = check_candidate_grounded(
        RESUME, fact(claim="Построил сервисы.", source="Built Python services", tags=[])
    )

    assert not verdict.passed


def test_a_sentence_initial_word_is_a_name_and_must_be_in_the_source() -> None:
    verdict = check_candidate_grounded(
        RESUME, fact(claim="Developed Python services.", source="Built Python services", tags=[])
    )

    assert verdict.reason == "name_not_in_source" and verdict.offending == "Developed"


@pytest.mark.parametrize("invisible", ["\u200b", "\u00ad", "\u2060", "\ufeff"])
def test_an_invisible_character_in_the_claim_fails(invisible: str) -> None:
    source = "Wrote Java"
    verdict = check_candidate_grounded(
        source, fact(claim=f"Wrote Java{invisible}script", source=source, tags=[])
    )

    assert verdict.reason == "invisible_character_in_claim"


@pytest.mark.parametrize(
    ("source", "claim", "reason"),
    [
        (
            "Built data pipelines.",
            "built data pipelines with terraform and kafka",
            "word_not_in_source",
        ),
        ("Worked 5 months at Acme.", "Worked 5 years at Acme.", "word_not_in_source"),
        ("Led engineers.", "Led five engineers.", "word_not_in_source"),
        ("Saved 5k.", "Saved 5m.", "number_not_in_source"),
        ("Never used Java.", "Used Java.", "negation_dropped"),
    ],
)
def test_a_claim_may_not_add_words_units_or_drop_a_negation(
    source: str, claim: str, reason: str
) -> None:
    verdict = check_candidate_grounded(source, fact(claim=claim, source=source, tags=[]))

    assert verdict.reason == reason


def test_inflected_words_and_function_words_are_grounded() -> None:
    source = "Managed 4 engineers and shipped the billing services"
    claim = "Managed 4 engineers and shipped the billing service."

    assert check_candidate_grounded(source, fact(claim=claim, source=source, tags=[])).passed

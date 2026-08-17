"""
A few tests focused on the behaviour that matters: the pipeline runs, and it
fails safe. Run with:  python -m pytest  (or python -m tests.test_pipeline)
"""

from contract_triage.llm import StubProvider, _extract_json
from contract_triage.pipeline import decide, Finding, triage, load_playbook


def test_json_extraction_handles_fenced_and_prose():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('Here you go: {"a": 1, "b": 2} cheers') == {"a": 1, "b": 2}


def test_high_risk_deviation_forces_escalate():
    findings = [Finding("liability_cap", "capped", "uncapped", "deviates", "high",
                        "escalate to legal")]
    rec, _ = decide("order_form", 0.95, findings)
    assert rec == "ESCALATE"


def test_low_confidence_forces_escalate():
    rec, _ = decide("mutual_nda", 0.10, [])
    assert rec == "ESCALATE"


def test_unknown_type_escalates():
    rec, reasons = decide("unknown", 0.2, [])
    assert rec == "ESCALATE"


def test_clean_contract_can_auto_clear():
    findings = [Finding("governing_law", "England", "England and Wales", "matches", "low")]
    rec, _ = decide("mutual_nda", 0.95, findings)
    assert rec == "AUTO_OK"


def test_end_to_end_runs_on_stub():
    llm = StubProvider()
    playbook = load_playbook()
    text = "MUTUAL NON-DISCLOSURE AGREEMENT ... confidentiality for three (3) years ... laws of England and Wales."
    result = triage("t.txt", text, llm, playbook)
    assert result.contract_type == "mutual_nda"
    assert result.recommendation in {"AUTO_OK", "REVIEW", "ESCALATE"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all tests passed")

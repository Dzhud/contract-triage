"""
Evaluation harness.

Building the thing is half the job; knowing whether to trust it is the other
half. This harness runs the pipeline over a labelled set and reports:

  - classification accuracy (did we identify the contract type?)
  - recommendation accuracy (did we route it correctly?)
  - the metric that actually matters in a legal setting:
        FALSE CLEARS - a contract that needed human attention but was marked
        AUTO_OK. This is the dangerous error. We report it separately and
        loudly, because one false clear on a risky contract is worse than
        many unnecessary escalations.

We also treat "safe direction" errors (escalating something that was actually
fine) as tolerable: they cost a little human time but never let risk through.

Run:
    python -m evals.run_evals            # offline stub, no key needed
    LLM_PROVIDER=anthropic python -m evals.run_evals   # real model
"""

from __future__ import annotations

import json
from pathlib import Path

from contract_triage.ingest import load_contract
from contract_triage.llm import get_provider
from contract_triage.pipeline import triage, load_playbook

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
GROUND_TRUTH = ROOT / "evals" / "ground_truth.json"

# Ordering lets us tell "safe" mistakes (over-escalating) from dangerous ones
# (under-escalating). Higher = more caution.
_SEVERITY = {"AUTO_OK": 0, "REVIEW": 1, "ESCALATE": 2}


def run() -> dict:
    truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    llm = get_provider()
    playbook = load_playbook()

    type_correct = 0
    rec_correct = 0
    false_clears = []      # dangerous: needed attention, got AUTO_OK
    over_escalations = []  # safe but noisy: was fine, got escalated
    rows = []

    for name, expected in truth.items():
        text = load_contract(SAMPLES / name)
        result = triage(name, text, llm, playbook)

        t_ok = result.contract_type == expected["expected_type"]
        r_ok = result.recommendation == expected["expected_recommendation"]
        type_correct += t_ok
        rec_correct += r_ok

        exp_sev = _SEVERITY[expected["expected_recommendation"]]
        got_sev = _SEVERITY[result.recommendation]
        if got_sev < exp_sev:
            false_clears.append((name, result.recommendation,
                                 expected["expected_recommendation"]))
        elif got_sev > exp_sev:
            over_escalations.append((name, result.recommendation,
                                     expected["expected_recommendation"]))

        rows.append({
            "contract": name,
            "type": f"{result.contract_type} (exp {expected['expected_type']})",
            "recommendation": f"{result.recommendation} "
                              f"(exp {expected['expected_recommendation']})",
            "type_ok": t_ok,
            "rec_ok": r_ok,
        })

    n = len(truth)
    summary = {
        "n": n,
        "type_accuracy": type_correct / n,
        "recommendation_accuracy": rec_correct / n,
        "false_clears": false_clears,
        "over_escalations": over_escalations,
        "rows": rows,
    }
    return summary


def print_report(summary: dict) -> None:
    print("=" * 70)
    print("CONTRACT TRIAGE — EVALUATION REPORT")
    print("=" * 70)
    for row in summary["rows"]:
        t = "ok" if row["type_ok"] else "X"
        r = "ok" if row["rec_ok"] else "X"
        print(f"[{t}/{r}] {row['contract']}")
        print(f"        type: {row['type']}")
        print(f"        rec:  {row['recommendation']}")
    print("-" * 70)
    print(f"Type classification accuracy : {summary['type_accuracy']:.0%}")
    print(f"Recommendation accuracy      : {summary['recommendation_accuracy']:.0%}")
    print(f"Over-escalations (safe)      : {len(summary['over_escalations'])}")
    print(f"FALSE CLEARS (dangerous)     : {len(summary['false_clears'])}")
    if summary["false_clears"]:
        print("  !! The following needed human attention but were under-escalated:")
        for name, got, exp in summary["false_clears"]:
            print(f"     - {name}: got {got}, expected {exp}")
    else:
        print("  No false clears: nothing risky was waved through.")
    print("=" * 70)


if __name__ == "__main__":
    print_report(run())

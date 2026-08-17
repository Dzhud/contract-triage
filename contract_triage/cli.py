"""
Command-line interface for the contract triage assistant.

Usage:
    python -m contract_triage.cli path/to/contract.txt
    python -m contract_triage.cli samples/            # whole folder
    python -m contract_triage.cli samples/ --json     # machine-readable

By default it uses the offline stub provider, so it runs with no API key and
no network. To use a real model:
    export LLM_PROVIDER=anthropic
    export ANTHROPIC_API_KEY=sk-...
    python -m contract_triage.cli samples/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ingest import load_contract
from .llm import get_provider
from .pipeline import triage, load_playbook, TriageResult

# The recommendation drives what a human does next. Colour-free so it renders
# anywhere; the queue-shrinking value is in AUTO_OK vs the rest.
_ICON = {"AUTO_OK": "[ OK ]", "REVIEW": "[REVIEW]", "ESCALATE": "[ESC ]"}


def _render(result: TriageResult) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append(f"{_ICON.get(result.recommendation, '[?]')}  {Path(result.source).name}")
    lines.append(f"Type: {result.contract_type}  (confidence {result.type_confidence:.2f})")
    lines.append(f"Recommendation: {result.recommendation}")
    for r in result.reasons:
        lines.append(f"  - {r}")
    if result.key_terms:
        lines.append("Key terms:")
        for k, v in result.key_terms.items():
            lines.append(f"  - {k}: {v}")
    if result.findings:
        lines.append("Clause checks:")
        for f in result.findings:
            mark = "ok" if f.status == "matches" else f.status
            line = f"  - {f.clause}: {mark} (risk: {f.risk})"
            lines.append(line)
            if f.suggested_redline:
                lines.append(f"      suggested: {f.suggested_redline}")
    return "\n".join(lines)


def _collect_paths(target: Path) -> list[Path]:
    if target.is_dir():
        exts = {".txt", ".md", ".pdf", ".docx"}
        return sorted(p for p in target.iterdir() if p.suffix.lower() in exts)
    return [target]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Triage commercial contracts.")
    parser.add_argument("path", help="A contract file or a folder of contracts.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = parser.parse_args(argv)

    target = Path(args.path)
    if not target.exists():
        print(f"Path not found: {target}", file=sys.stderr)
        return 1

    llm = get_provider()
    playbook = load_playbook()
    paths = _collect_paths(target)

    results = []
    for p in paths:
        try:
            text = load_contract(p)
            result = triage(str(p), text, llm, playbook)
        except Exception as e:
            # A parsing/model failure must never be a silent pass — it becomes
            # an explicit escalation so a human always sees the document.
            result = TriageResult(source=str(p), contract_type="unknown",
                                  type_confidence=0.0, recommendation="ESCALATE",
                                  reasons=[f"Processing failed, needs human review: {e}"])
        results.append(result)

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        for r in results:
            print(_render(r))
        _print_queue_summary(results)
    return 0


def _print_queue_summary(results: list[TriageResult]) -> None:
    """The headline number: how much of the queue got triaged off a human's desk."""
    total = len(results)
    auto = sum(1 for r in results if r.recommendation == "AUTO_OK")
    review = sum(1 for r in results if r.recommendation == "REVIEW")
    esc = sum(1 for r in results if r.recommendation == "ESCALATE")
    print("=" * 70)
    print(f"Queue summary: {total} contract(s)")
    print(f"  AUTO_OK  (boilerplate, cleared): {auto}")
    print(f"  REVIEW   (quick human glance):   {review}")
    print(f"  ESCALATE (full human review):    {esc}")
    if total:
        print(f"  -> {auto + review}/{total} needed only light or no attention.")


if __name__ == "__main__":
    raise SystemExit(main())

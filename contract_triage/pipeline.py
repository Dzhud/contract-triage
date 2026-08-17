"""
The triage pipeline.

Design principle: this is *triage and assist*, not *replace the lawyer*.
Its job is to shrink the queue by handling the ~80% boilerplate and the
redlines the team has seen before, and to escalate everything else to a human.

The pipeline:
    1. classify   - what kind of contract is this, and how confident are we?
    2. extract    - pull the key terms into a structured form
    3. compare    - check those terms against the playbook of standard positions
    4. assemble   - a reviewer-ready summary + an overall recommendation

Fail-safe throughout: whenever the model is unsure, the document is unusual,
or a high-risk clause deviates, the recommendation is ESCALATE. We would far
rather send a boilerplate contract to a human unnecessarily than wave through
a risky one automatically. In a legal setting, a false "all clear" is the
expensive mistake, so the system is deliberately biased towards caution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .llm import LLMProvider

# Confidence below this => we don't trust the automated read; escalate.
CONFIDENCE_THRESHOLD = 0.75

PLAYBOOK_PATH = Path(__file__).resolve().parent.parent / "playbook" / "playbook.json"


@dataclass
class Finding:
    clause: str
    playbook_standard: str
    found: str
    status: str          # "matches" | "deviates" | "missing"
    risk: str            # "low" | "medium" | "high"
    suggested_redline: str = ""


@dataclass
class TriageResult:
    source: str
    contract_type: str
    type_confidence: float
    key_terms: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    recommendation: str = "ESCALATE"   # "AUTO_OK" | "REVIEW" | "ESCALATE"
    reasons: list = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d["findings"] = [asdict(f) if isinstance(f, Finding) else f for f in self.findings]
        return d


def load_playbook() -> dict:
    return json.loads(PLAYBOOK_PATH.read_text(encoding="utf-8"))


def classify(text: str, llm: LLMProvider) -> tuple[str, float]:
    system = (
        "You classify commercial contracts. Return ONLY JSON with keys: "
        "contract_type (one of: mutual_nda, order_form, unknown), "
        "confidence (0-1 float), reasoning (one short sentence)."
    )
    user = f"Classify this contract:\n\n{text[:6000]}"
    data = llm.complete_json(system, user)
    return data.get("contract_type", "unknown"), float(data.get("confidence", 0.0))


def extract_terms(text: str, contract_type: str, llm: LLMProvider) -> dict:
    system = (
        "You extract key terms from a commercial contract. Return ONLY JSON. "
        "Include whatever of these apply: parties, term, governing_law, "
        "liability_cap, payment_terms, termination, permitted_purpose, "
        "intellectual_property, auto_renewal. Use the string 'not specified' "
        "if a term is genuinely absent — never guess."
    )
    user = f"Contract type: {contract_type}\n\nContract:\n\n{text[:8000]}"
    return llm.complete_json(system, user)


def compare_to_playbook(contract_type: str, terms: dict, text: str,
                        llm: LLMProvider, playbook: dict) -> list[Finding]:
    """
    For each standard position in the playbook, ask the model whether this
    contract matches, deviates, or is silent — and if it deviates, surface the
    known redline the team would normally apply.
    """
    entry = playbook.get(contract_type)
    if not entry:
        return []

    findings: list[Finding] = []
    for pos in entry["standard_positions"]:
        system = (
            "You compare one clause of a contract against a standard position. "
            "Return ONLY JSON with keys: status (one of: matches, deviates, "
            "missing), found (short quote or paraphrase of what the contract "
            "actually says, or 'not found'), explanation (one sentence). "
            "Be conservative: if you are not sure, say 'deviates'."
        )
        user = (
            f"Standard position ({pos['clause']}): {pos['standard']}\n"
            f"Acceptable range: {pos['acceptable_range']}\n\n"
            f"Extracted terms: {json.dumps(terms)}\n\n"
            f"Contract text (excerpt):\n{text[:8000]}"
        )
        data = llm.complete_json(system, user)
        status = data.get("status", "deviates")
        redline = pos["known_redline"] if status in ("deviates", "missing") else ""
        findings.append(Finding(
            clause=pos["clause"],
            playbook_standard=pos["standard"],
            found=data.get("found", "not found"),
            status=status,
            risk=pos["risk_if_deviates"] if status != "matches" else "low",
            suggested_redline=redline,
        ))
    return findings


def decide(contract_type: str, confidence: float, findings: list[Finding]) -> tuple[str, list[str]]:
    """
    Turn the findings into a single recommendation, biased towards caution.

      ESCALATE  - unknown type, low confidence, or any HIGH-risk deviation
      REVIEW    - some medium/low deviations a human should glance at
      AUTO_OK   - everything matches the playbook and we're confident
    """
    reasons: list[str] = []

    if contract_type == "unknown":
        return "ESCALATE", ["Contract type could not be confidently identified."]
    if confidence < CONFIDENCE_THRESHOLD:
        reasons.append(f"Classification confidence {confidence:.2f} below threshold "
                       f"{CONFIDENCE_THRESHOLD}.")

    high = [f for f in findings if f.status != "matches" and f.risk == "high"]
    medium = [f for f in findings if f.status != "matches" and f.risk == "medium"]
    low = [f for f in findings if f.status != "matches" and f.risk == "low"]

    if high:
        reasons.append(f"{len(high)} high-risk clause(s) deviate from standard: "
                       + ", ".join(f.clause for f in high))
        return "ESCALATE", reasons
    if reasons:  # low confidence but no high-risk issue
        return "ESCALATE", reasons
    if medium:
        reasons.append(f"{len(medium)} medium-risk deviation(s) to review: "
                       + ", ".join(f.clause for f in medium))
        return "REVIEW", reasons
    if low:
        reasons.append(f"{len(low)} minor deviation(s); otherwise standard.")
        return "REVIEW", reasons

    return "AUTO_OK", ["All checked clauses match standard positions; boilerplate."]


def triage(path: str, text: str, llm: LLMProvider, playbook: dict | None = None) -> TriageResult:
    playbook = playbook or load_playbook()
    contract_type, confidence = classify(text, llm)

    result = TriageResult(source=path, contract_type=contract_type,
                          type_confidence=confidence)

    if contract_type == "unknown":
        result.recommendation, result.reasons = decide(contract_type, confidence, [])
        return result

    result.key_terms = extract_terms(text, contract_type, llm)
    result.findings = compare_to_playbook(contract_type, result.key_terms, text, llm, playbook)
    result.recommendation, result.reasons = decide(contract_type, confidence, result.findings)
    return result

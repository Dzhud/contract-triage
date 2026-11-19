# Contract Triage Assistant

A working prototype showing how AI could help an in-house legal team get on top
of a contract-review queue that's usually longer than the day.

Built for the PortSwigger AI task. It runs end-to-end out of the box with **no
API key** (an offline stub stands in for the model), and swaps to Claude — or a
locally-hosted model — with one environment variable.

```bash
# runs immediately, offline, no key:
python -m contract_triage.cli samples/

# see the evaluation:
python -m evals.run_evals

# use a real model:
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python -m contract_triage.cli samples/
```

---

## What the project does

For each contract the system runs a four-step pipeline:

1. **Classify** — what kind of contract is this (mutual NDA, order form, or
   something we don't handle), and how confident are we?
2. **Extract** — pull the key terms (parties, term, governing law, liability cap,
   payment terms, IP, …) into a structured form.
3. **Compare to a playbook** — check those terms against the team's *standard
   positions* and *known redlines* — the "edits we've seen before." Each
   standard position carries a risk level and the redline the team would normally
   apply.
4. **Recommend** — turn the findings into one of three outcomes:

| Recommendation | Meaning | What a human does |
|---|---|---|
| `AUTO_OK` | Boilerplate, matches every standard position | Nothing, or a rubber stamp |
| `REVIEW` | Minor/medium deviations | A quick glance, with the deviations pre-flagged |
| `ESCALATE` | High-risk deviation, unusual, or low confidence | Full human review |

The output is a **reviewer-ready summary**: the contract type, extracted terms,
exactly which clauses deviate, and — for each deviation — the suggested redline
from the playbook.

The system is **deliberately biased towards caution.** It escalates when the
contract type is unknown, classification confidence is below a threshold, or any
high-risk clause (e.g. liability cap, IP ownership) deviates. A false "all
clear" is the error a legal team cannot afford; unnecessary escalations are
merely annoying.

---

## Who it's for

**In-house legal teams** at companies that handle a steady stream of standard
commercial contracts — NDAs, order forms — where 80 % is boilerplate and the
real risk hides in the 20 % that isn't.

The tool is designed for a team that:
- already has standard positions and known redlines (codified in the playbook),
- has a queue longer than the day, especially at quarter-end,
- needs a lawyer to stay in the loop on anything unusual.

It is **not** an autonomous reviewer. It is a triage-and-assist layer that
clears the boilerplate confidently and surfaces deviations so the human goes
straight to what matters.

---

## Built with

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| AI backend (default) | Offline stub — no key, no network |
| AI backend (real analysis) | [Anthropic Claude](https://www.anthropic.com/) via `anthropic` SDK |
| AI backend (on-prem option) | Local GGUF model via `llama-cpp-python` |
| Document ingestion | `pypdf` (PDF), `python-docx` (DOCX), plain text |
| Playbook / rules | JSON file — no database required |
| Evaluation harness | Custom eval script with false-clear metric |

Dependencies are pinned in `requirements.txt`. The project has no web framework,
no database, and no deployment infrastructure — it is a CLI pipeline with an
eval harness, intended as a prototype foundation.

---

## How to run it

### 1. Clone and set up a virtualenv

```bash
git clone <repo-url>
cd contract-triage
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment (optional for offline mode)

```bash
cp .env.example .env
# Edit .env to set LLM_PROVIDER and ANTHROPIC_API_KEY if using Claude.
# Leave it blank to run offline with the stub.
```

### 3. Run the triage pipeline

```bash
# Triage all contracts in the samples/ folder (offline, no key needed):
python -m contract_triage.cli samples/

# Triage a single file:
python -m contract_triage.cli samples/01_standard_mutual_nda.txt

# Use Claude for real analysis:
LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... python -m contract_triage.cli samples/
```

### 4. Run the evaluation harness

```bash
python -m evals.run_evals
```

Reports classification accuracy, recommendation accuracy, and — most
importantly — **false clears** (contracts that needed human attention but were
marked `AUTO_OK`).

### 5. Run the tests

```bash
python -m pytest tests/
```

---

## Project structure

```
contract_triage/
  llm.py         # provider-agnostic model interface (stub / Claude / local GGUF)
  ingest.py      # PDF / DOCX / TXT -> plain text
  pipeline.py    # classify -> extract -> compare -> recommend (fail-safe)
  cli.py         # reviewer-ready CLI output, single file or whole folder
playbook/
  playbook.json  # standard positions + known redlines, per contract type
samples/         # invented contracts covering the key routing cases
evals/
  ground_truth.json  # expected outcome per sample
  run_evals.py       # accuracy + the false-clear metric that matters
```

No real or confidential contracts are included — all samples are invented.

---

## Model choice, and why the provider is swappable

Every model call goes through one small interface (`contract_triage/llm.py`), so
the backend is a config change, not a rewrite. Three backends are included:

- **Stub** (default) — deterministic, offline, no key. Makes the pipeline and
  evals run anywhere for free. Not a real analyst — it's scaffolding.
- **Anthropic / Claude** — the capable model for real clause analysis.
- **Local GGUF** — the same pipeline running fully on-prem via `llama-cpp-python`.

That last option matters in a legal context: **contract text is confidential.**
Sending every commercial contract to a third-party API is a data-governance
question a legal team may decide differently from a product team. Keeping the
provider behind an interface means that decision can be made — or changed —
without touching the triage logic.

---

## Plans / Roadmap

- [ ] **Richer playbook coverage** — extend beyond mutual NDA and order form to
      cover MSAs, SOWs, and employment agreements.
- [ ] **Confidence calibration** — replace the fixed confidence threshold with a
      per-clause-type calibrated threshold based on a larger labelled set.
- [ ] **Structured output mode** — emit JSON alongside the human-readable CLI
      summary, so the results can be consumed by a case-management system.
- [ ] **Web UI** — a minimal read-only dashboard showing the triage queue and
      reviewer notes, backed by the same pipeline.
- [ ] **Webhook / notification hook** — post an `ESCALATE` result to a Slack
      channel or email so the reviewer is notified without polling.
- [ ] **Expanded eval set** — more labelled samples covering edge cases
      (conflicting governing law clauses, partial liability caps, etc.).
- [ ] **Local model quality gate** — benchmark a mid-size on-prem model (e.g.
      Mistral 7B) against Claude on the eval set to establish whether the
      accuracy trade-off is acceptable for lower-risk contract types.

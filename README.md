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

## What problem is actually being solved?

The brief is "a steady stream of standard contracts, 80% boilerplate, redlines
we've seen before, a queue longer than the day, worst at quarter-end."

The instinct might be "build an AI that reviews contracts." I don't think that's
the right framing, and the difference matters.

**A lawyer's time is the scarce resource, not their willingness to read.** The
problem isn't that contracts get read — it's that *every* contract gets the same
scarce human attention regardless of whether it needs it. The standard NDA that's
99% identical to the last fifty gets the same read as the one order form with an
uncapped-liability clause that actually matters.

So this isn't a "replace the lawyer" tool. It's a **triage-and-assist** tool. Its
job is to answer one question for each contract:

> *Does a human need to spend real attention on this, and if so, where?*

and to shrink the queue by confidently clearing the boilerplate and surfacing the
recurring redlines — while pushing anything unusual or risky firmly towards a
person. The goal is to give the legal team their quarter-end back, not to take
their judgement away.

---

## What it does

For each contract it runs a four-step pipeline:

1. **Classify** — what kind of contract is this (mutual NDA, order form, or
   something we don't handle), and how confident are we?
2. **Extract** — pull the key terms (parties, term, governing law, liability cap,
   payment terms, IP, …) into a structured form.
3. **Compare to a playbook** — check those terms against the team's *standard
   positions* and *known redlines* — the "edits we've seen before." Each standard
   position carries a risk level and the redline the team would normally apply.
4. **Recommend** — turn the findings into one of three outcomes:

| Recommendation | Meaning | What a human does |
|---|---|---|
| `AUTO_OK` | Boilerplate, matches every standard position | Nothing, or a rubber stamp |
| `REVIEW` | Minor/medium deviations | A quick glance, with the deviations pre-flagged |
| `ESCALATE` | High-risk deviation, unusual, or low confidence | Full human review |

The output is a **reviewer-ready summary**: the contract type, the extracted
terms, exactly which clauses deviate, and — for each deviation — the suggested
redline from the playbook. A lawyer opening a `REVIEW` item sees in seconds what
to look at, instead of reading ten pages to find the one clause that changed.

---

## The design decision that matters most: fail safe

The system is **deliberately biased towards caution.** It escalates when:

- the contract type is unknown,
- classification confidence is below a threshold, or
- any high-risk clause (e.g. liability cap, IP ownership) deviates.

This is because the two possible errors are not equal:

- **Over-escalating** a contract that was actually fine costs a few minutes of
  human time. Annoying, cheap, recoverable.
- **Under-escalating** — waving through a contract that needed attention — is how
  an uncapped-liability clause ends up signed. Rare, but expensive and sometimes
  irreversible.

In a legal setting a false "all clear" is the error you cannot afford, so the
system is built to prefer an unnecessary escalation over a missed risk every
time. The evaluation (below) measures this error specifically and separately.

---

## How we know whether to trust it (evaluation)

A demo that looks convincing isn't the same as one that works, so the prototype
ships with an eval harness (`evals/run_evals.py`) over a labelled set of sample
contracts. It reports:

- **classification accuracy** — did we identify the contract type?
- **recommendation accuracy** — did we route it correctly?
- **false clears** — the dangerous error: something that needed human attention
  but was marked `AUTO_OK`. Reported separately and loudly, because one false
  clear matters more than many unnecessary escalations.

The samples are chosen to probe the behaviour that matters, not just the happy
path: a clean NDA (should clear), an NDA with a perpetual term and foreign law
(should not clear), an order form with uncapped liability (must escalate), a
clean order form (should clear), and a non-contract document (must not be waved
through).

This is the part I'd invest most in for a real deployment: a proper labelled
corpus, tracking false-clear rate as the primary metric, and re-running it every
time the prompts, playbook or model change — so we can *see* whether a change
made the system more or less trustworthy, rather than guessing.

---

## Model choice, and why the provider is swappable

Every model call goes through one small interface (`contract_triage/llm.py`), so
the backend is a config change, not a rewrite. Four backends are included:

- **Stub** (default) — deterministic, offline, no key. Makes the pipeline and
  evals run anywhere for free. Not a real analyst — it's scaffolding.
- **Anthropic / Claude** — a capable model for the real analysis. This is what
  makes the clause comparison actually reliable.
- **Local GGUF** — the same pipeline running fully on-prem via `llama.cpp`.

That last one is a deliberate point, not a throwaway. **Contract text is
confidential.** For a real deployment, sending every commercial contract to a
third-party API is a genuine data-governance question, and a legal team may well
prefer to trade some capability for keeping data in-house on a locally-hosted
model. Keeping the provider behind an interface means that's a decision the
business can make later without touching the triage logic — and it's exactly the
"what does this actually expose?" question worth asking before wiring AI into a
sensitive workflow. (A 1.1B local model like TinyLlama is too weak for reliable
clause analysis today, so this is about *architecture that keeps the option
open*, not a claim that tiny local models are production-ready.)

Provider loyalty is a trap; the interface is there so we can always move to
whatever earns its place.

---

## Honest limitations

This is a one-day prototype. What it is **not** yet, and what a real version
would need:

- **Not a lawyer.** It flags and suggests; it never approves. Every high-risk or
  unusual contract still reaches a human.
- **Extraction can be wrong.** LLMs can misread or hallucinate a clause. That's
  why high-risk clauses escalate even when the model *thinks* they're fine, and
  why the eval tracks false clears.
- **The playbook is small and hand-written.** In reality it would be built with
  the legal team from their actual standard positions and past redlines, and
  version-controlled as those positions evolve.
- **Two contract types only** (NDA, order form). The pattern extends to more, but
  each needs its own playbook and eval cases.
- **No redline *insertion* into the document yet** — it suggests the edit rather
  than producing a tracked-changes file. That's the obvious next build, and a
  high-value one.
- **Confidentiality/PII** handling (redaction, on-prem models, retention) would
  need real thought before touching live contracts.

---

## What I'd build next

In rough priority order:
1. Build the playbook *with* the legal team from real past redlines, and grow the
   eval corpus from their actual queue.
2. Track false-clear rate as the headline metric over a larger labelled set.
3. Generate an actual redlined document (tracked changes) for `REVIEW` items.
4. Add a human-in-the-loop feedback capture, so each lawyer correction improves
   the playbook — the system gets better at exactly the redlines this team sees.
5. Evaluate on-prem models seriously for the confidentiality win.

---

## Project structure

```
contract_triage/
  llm.py         # provider-agnostic model interface (stub / Claude / local)
  ingest.py      # PDF / DOCX / TXT -> text
  pipeline.py    # classify -> extract -> compare -> recommend (fail-safe)
  cli.py         # reviewer-ready CLI, single file or whole folder
playbook/
  playbook.json  # standard positions + known redlines, per contract type
samples/         # fake, shareable contracts covering the key cases
evals/
  ground_truth.json  # expected outcome per sample
  run_evals.py       # accuracy + the false-clear metric that matters
```

No real or confidential contracts are included — all samples are invented.

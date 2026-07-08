# Directive: Run a Medical Coding Audit

## Goal
Audit an operative report against billed CPT codes, diagnosis codes, units,
and (optional) modifiers; surface documentation gaps and billing risks; and,
when needed, draft a payer appeal letter.

## Inputs
- Operative report text (PHI is redacted locally by Presidio before any API call)
  - Can also be pasted as screenshot images (max 4) — transcribed to text by a
    LOCAL vision model (Ollama `qwen2.5vl:7b`, see `execution/transcribe_image.py`
    and the `/transcribe` endpoint). Images never leave the machine; the
    transcribed text then flows through the normal Presidio sanitize step.
    Requires Ollama running with the model pulled (`ollama pull qwen2.5vl:7b`).
    Config via `.env`: `OLLAMA_URL`, `OLLAMA_VISION_MODEL`.
- CPT codes with billed units; modifiers are OPTIONAL (blank = normal claim)
- ICD-10 diagnosis codes
- Model choice (UI picker; Sonnet 5 default — see costs below)

## Tools
- Web UI: `.venv\Scripts\python.exe app.py` → http://localhost:5000
  (or `run_app.ps1` for the Docker path)
- CLI: `.venv\Scripts\python.exe execution\medical_audit.py --cpt 15734 --dx L89.154 --file inputs\input_record.txt`
- Tests before changes: `.venv\Scripts\python.exe -m pytest tests\ -q` (must stay green)

## How it decides (trust hierarchy — highest wins)
1. RulesEngine exclusions (HARD_FAIL) — known denial terms, negation-aware
2. NCCI/MUE database findings — date-filtered to active edits only
3. RulesEngine missing-keyword checks (forced MEDIUM alert)
4. LLM documentation verification (evidence quotes, independent unit count)

## Edge cases & learnings
- Requires Python 3.12 (Presidio/spaCy break on 3.14)
- `clinical_policies.py` / `cpt_data.py` are untracked (copyright) — copy from
  the `.example.py` stubs on a fresh clone
- Modifier 59/XE/XS/XP/XU on the component code downgrades indicator-1 NCCI
  alerts to MEDIUM; indicator-0 edits can never be modifier-bypassed
- NCCI date filter uses today's date; for past dates of service pass
  `as_of="YYYYMMDD"` to `check_ncci`
- Typical audit cost: ~$0.02–0.05 (Sonnet 5), ~$0.13–0.35 (Fable 5)
- Appeal letters use placeholders ([PATIENT NAME], [CLAIM NUMBER]) — fill in
  outside the tool; never paste PHI back in
- "Ask the Auditor" chat is multi-turn: prior Q&A on the same audit is sent
  with each question (cleared when a new audit runs). The note+findings block
  is prompt-cached, so follow-ups bill mostly at cache-read rates. The chat
  uses whatever model is currently selected in the picker, read per-question

## Outputs
- Per-code verdict (PASS/FAIL/PARTIAL), evidence quote, calculated vs billed
  units, risk alert with rationale; diagnosis analysis; documentation advice
- Optional appeal letter (Markdown, copy button in UI)
- CLI runs also write `.tmp/audit_result_latest.json`

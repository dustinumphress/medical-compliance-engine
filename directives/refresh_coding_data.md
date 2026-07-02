# Directive: Refresh Coding Rules Data (Quarterly)

## Goal
Keep `coding_rules.db` current. CMS updates NCCI PTP edits and MUE limits
QUARTERLY (Jan 1 / Apr 1 / Jul 1 / Oct 1). Stale data means missed edits on
new code pairs. The DB records were last ingested from the January 2026 release.

## When
At the start of each calendar quarter, or whenever an audit result looks
inconsistent with current CMS policy.

## Inputs (download to the project root)
1. NCCI PTP edit files: CMS.gov → "PTP Coding Edits" → practitioner TXT files
   (pattern `ccipra-*.txt`)
2. MUE files: CMS.gov → "Medically Unlikely Edits" → practitioner CSV
   (pattern `MCR_MUE_*.csv`)
3. (Annually) RVU file for CPT short descriptions, e.g. `PPRRVU2026_Jan_nonQPP.txt`
   — update the filename constant in `ingest_coding_rules.py` for the new year

## Tool
`.venv\Scripts\python.exe execution\ingest_coding_rules.py`
(expects the downloaded files in the project root; rebuilds tables in place)

## Verify
1. `.venv\Scripts\python.exe -m pytest tests\test_coding_logic.py -q` — date
   filtering still green
2. Spot-check row counts grew or stayed similar:
   `SELECT COUNT(*) FROM ncci_edits;` (~2.3M as of Jan 2026),
   `SELECT MAX(effective_date) FROM ncci_edits;` should be the new quarter
3. Run one known scenario through the UI and confirm NCCI/MUE alerts

## Edge cases & learnings
- The DB keeps deleted edits for historical `as_of` queries — do NOT prune
  rows with past deletion dates; `check_ncci` filters at query time
- MUE files are cp1252-encoded (handled by the ingest script)
- `*.db` is gitignored; the database is a local artifact, never committed
- Also check MODEL_PRICING in `execution/medical_audit.py` while you're here —
  there is no pricing API, so price changes need a manual table update

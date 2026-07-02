"""
EXAMPLE structure for execution/cpt_data.py (which is untracked — full CPT
descriptor text is AMA-copyrighted and should not be republished).

To use: copy this file to cpt_data.py and populate CPT_DEFINITIONS with the
codes you audit. Each value is the definition/requirements text shown to the
LLM for that code. Without this file, the app falls back to the short
descriptions in coding_rules.db (ingested from CMS RVU files).

Augment entries with audit-relevant requirements, e.g. unit-calculation
rules for add-on codes or documentation elements payers look for.
"""

CPT_DEFINITIONS = {
    "12001": "Simple repair, superficial wounds (scalp/neck/trunk/extremities), smallest length tier. RULE: verify total repaired length falls in this code's band.",
    # "13122": "Add-on code for complex repair beyond the base band. RULE: sum lengths within the anatomic group; round partial units up.",
}

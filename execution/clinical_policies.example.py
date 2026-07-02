"""
EXAMPLE structure for execution/clinical_policies.py (which is untracked —
it contains verbatim CPT descriptor language and payer policy excerpts that
should not be republished).

To use: copy this file to clinical_policies.py and populate POLICY_MAPPING
with your own payer policy summaries, keyed by CPT code. Each value is a
free-text block injected into the audit prompt when that code is billed.

Write the policy text in your own words. Good entries capture:
- what the code requires in the operative note (anatomy, planes, vessels)
- known documentation traps that trigger denials
- correct vs. incorrect narrative examples
"""

POLICY_MAPPING = {
    "15730": """
[PAYER POLICY: CPT 15730 - Midface Flap]
Summary of documentation requirements (paraphrased from your payer's LCD):
1. Dissection plane must be described (e.g. sub-periosteal).
2. Vascular pedicle preservation must be stated explicitly.
3. The narrative must tie the flap to a functional/reconstructive defect —
   cosmetic-intent language is a known denial trigger.
""",
    # "15733": "...",
    # "15734": "...",
}

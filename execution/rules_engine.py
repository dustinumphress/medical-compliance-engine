import re
import logging

logger = logging.getLogger(__name__)

# Data-driven validation rules, keyed by CPT code.
#
# Each rule set has two optional sections, evaluated in order:
#   "exclusions"   -> list of hard-fail checks. If "pattern" matches the text,
#                     the code HARD_FAILs — unless the optional "unless" pattern
#                     also matches (used for "X without Y" policies).
#                     "message" may be None to use the generic excluded-term text.
#   "requirements" -> list of soft checks. Every "pattern" must match somewhere
#                     in the text; the first miss returns FAIL with its message.
#
# All patterns are case-insensitive regex ('Smart Strict' policy: flexible
# matching for concepts/synonyms, strict exclusions for known denials).
# Adding coverage for a new CPT code is a data change here, not a code change.
CPT_RULES = {
    # 15730: Midface Flap — requires midface/zygomatic concept + vascular
    # preservation; cosmetic language is a known denial (Novitas LCD L35090).
    # "aesthetic subunit(s)" is standard reconstructive terminology, so it is
    # carved out of the cosmetic exclusion via negative lookahead.
    "15730": {
        "exclusions": [
            {"pattern": r"(rejuvenat\w*|cosmetic|aesthetic(?!\s+subunits?))", "message": None},
        ],
        "requirements": [
            {"pattern": r"(midface|zygomatic|sub-?orbicularis)",
             "message": "[MISSING KEYWORDS]: No mention of 'Midface', 'Zygomatic', or 'Sub-orbicularis'."},
            {"pattern": r"(vascular|pedicle|perforator|artery|supply)",
             "message": "[MISSING KEYWORDS]: Flap must document 'Vascular', 'Pedicle', or 'Perforator' preservation."},
        ],
    },
    # 15733: Head/Neck with Named Pedicle — CPT's "i.e." list is exhaustive.
    "15733": {
        "exclusions": [
            {"pattern": r"(platysma|frontalis)\s*(flap|muscle)",
             "message": "SYSTEM GUARDRAIL: 'Platysma' and 'Frontalis' are STRICTLY EXCLUDED from 15733."},
        ],
        "requirements": [
            {"pattern": r"(buccinator|genioglossu|temporalis|masseter|sternocleidomastoid|levator scapulae)",
             "message": "[MISSING KEYWORDS]: Documentation must name one of: Buccinator, Genioglossus, Temporalis, Masseter, SCM, Levator Scapulae."},
        ],
    },
    # 15734: Trunk — deep fascia/myocutaneous mobilization; component
    # separation alone (no flap language) is a known denial.
    "15734": {
        "exclusions": [
            {"pattern": r"component\s*separation",
             "unless": r"(flap|transpos|rotat|advancement)",
             "message": "Component Separation performed without documenting 'Flap', 'Transposition', or 'Rotation'."},
        ],
        "requirements": [
            {"pattern": r"(deep|investing)\W+(\w+\W+){0,3}fascia|sub-?fascial|(myocutaneous|muscle)\W+(\w+\W+){0,3}(flap|transpos\w*|rotat\w*)",
             "message": "[MISSING KEYWORDS]: Must document 'Deep Fascia', 'Myocutaneous', or 'Muscle Flap' mobilization."},
        ],
    },
    # 15736: Arm — deep fascia requirement.
    "15736": {
        "requirements": [
            {"pattern": r"(deep|investing)\W+(\w+\W+){0,3}fascia|sub-?fascial|fasciocutaneous",
             "message": "[MISSING KEYWORDS]: Must document 'Deep Fascia' or 'Fasciocutaneous' nature."},
        ],
    },
    # 15738: Leg — deep fascia/muscle + limb-salvage medical necessity context.
    "15738": {
        "requirements": [
            {"pattern": r"(deep|investing)\W+(\w+\W+){0,3}fascia|sub-?fascial|muscle\W+(\w+\W+){0,3}(flap|transpos\w*)",
             "message": "[MISSING KEYWORDS]: Must document 'Deep Fascia' or 'Muscle Flap'."},
            {"pattern": r"(limb salvage|exposed|osteomyelitis|open fracture|chronic|ulcer|gangrene|threat)",
             "message": "[MISSING KEYWORDS]: No 'Limb Salvage', 'Exposed Bone/Tendon', or 'Osteomyelitis' context found."},
        ],
    },
}


# Words that negate a following term ("no cosmetic intent", "without aesthetic
# goals", "rather than a cosmetic procedure"). Checked in the ~60 chars before
# an exclusion match so negated mentions don't trigger a HARD_FAIL.
_NEGATION_WINDOW = re.compile(
    r"\b(no|not|without|non|denies|denied|absence of|rather than|instead of|never)\b[\s\w,;'\"-]{0,45}$",
    re.IGNORECASE,
)

def _is_negated(text, match_start):
    """True when the 60 chars before the match end in a negation phrase."""
    prefix = text[max(0, match_start - 60):match_start]
    return bool(_NEGATION_WINDOW.search(prefix))


class RulesEngine:
    """
    Deterministic validation logic for CPT codes using regex rules from CPT_RULES.
    """

    @staticmethod
    def validate(code, text):
        """
        Validates documentation text against the rule set for a CPT code.
        Returns: (status, rationale)
        Status: "PASS", "FAIL" (missing required concept), "HARD_FAIL" (exclusion hit)
        """
        rule = CPT_RULES.get(str(code).strip())
        if not rule:
            # No rule defined for this code — nothing deterministic to enforce.
            return "PASS", None

        # 1. Exclusions first: a known-denial term outranks any requirement.
        #    HARD_FAILs override the LLM downstream, so every match is checked
        #    for negation ("no cosmetic intent") before it fires.
        for exclusion in rule.get("exclusions", []):
            unless = exclusion.get("unless")
            if unless and re.search(unless, text, re.IGNORECASE):
                continue
            for matched in re.finditer(exclusion["pattern"], text, re.IGNORECASE):
                if _is_negated(text, matched.start()):
                    continue
                message = exclusion.get("message") or \
                    f"Found Excluded Term: '{matched.group(0)}' based on policy."
                return "HARD_FAIL", message

        # 2. Requirements: every concept must be documented somewhere.
        for requirement in rule.get("requirements", []):
            if not re.search(requirement["pattern"], text, re.IGNORECASE | re.DOTALL):
                return "FAIL", requirement["message"]

        return "PASS", "Rules Satisfied."

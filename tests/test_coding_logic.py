"""
Tests for the coding-logic fixes:
1. NCCI date filtering (expired/deleted edits must not fire)
2. Modifier handling (optional; bypass modifiers downgrade indicator-1 alerts)
3. Rules-engine context awareness (negation, proximity, 'aesthetic subunit')
"""
import sys
import os
import types
import sqlite3
import pytest

sys.path.append(os.getcwd())

# Import medical_audit with a temporary sanitizer stub (see test_audit_postprocess)
_had_real = "sanitize_phi" in sys.modules
if not _had_real:
    _stub = types.ModuleType("sanitize_phi")
    _stub.sanitize_text = lambda t: (t, [])
    sys.modules["sanitize_phi"] = _stub

from execution import medical_audit as ma
from execution.rules_engine import RulesEngine

if not _had_real:
    del sys.modules["sanitize_phi"]


# ---------- 1. NCCI date filtering ----------

@pytest.fixture
def ncci_db(tmp_path, monkeypatch):
    """Real on-disk sqlite DB with active, expired, and future edits."""
    # conftest patches sqlite3.connect for all tests — restore the real one here
    monkeypatch.setattr(sqlite3, "connect", sqlite3.dbapi2.connect)
    db_path = str(tmp_path / "test_rules.db")
    conn = sqlite3.dbapi2.connect(db_path)
    conn.execute("""CREATE TABLE ncci_edits (
        column1_code TEXT, column2_code TEXT, effective_date TEXT,
        deletion_date TEXT, modifier_indicator TEXT, rationale TEXT)""")
    rows = [
        # active: effective in past, no deletion
        ("11111", "22222", "20200101", None, "1", None),
        # expired: deleted end of 2023 — must NOT fire
        ("11111", "33333", "20200101", "20231231", "0", None),
        # not yet effective — must NOT fire
        ("11111", "44444", "20990101", None, "1", None),
        # empty-string deletion date counts as active
        ("11111", "55555", "20200101", "", "0", None),
    ]
    conn.executemany("INSERT INTO ncci_edits VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return db_path


def test_ncci_expired_edits_do_not_fire(ncci_db):
    db = ma.CodingRulesDB(db_path=ncci_db)
    codes = ["11111", "22222", "33333", "44444", "55555"]
    flagged = {a["code"] for a in db.check_ncci(codes)}
    assert "22222" in flagged, "active edit should fire"
    assert "55555" in flagged, "empty deletion_date means still active"
    assert "33333" not in flagged, "edit deleted in 2023 must not fire"
    assert "44444" not in flagged, "future-effective edit must not fire"


def test_ncci_as_of_date_respected(ncci_db):
    db = ma.CodingRulesDB(db_path=ncci_db)
    codes = ["11111", "33333"]
    # In 2022 the (11111, 33333) edit was still active
    flagged = {a["code"] for a in db.check_ncci(codes, as_of="20220601")}
    assert "33333" in flagged


# ---------- 2. Modifier handling in the audit pipeline ----------

def make_llm_response(items):
    import json
    return json.dumps({
        "audit_results": items,
        "diagnosis_analysis": "ok",
        "documentation_improvement": "ok",
    }), {"input_tokens": 10, "output_tokens": 10}


@pytest.fixture
def patch_pipeline(monkeypatch):
    cfg = {"llm_items": [], "ncci": [], "mue": {}}
    monkeypatch.setattr(ma, "sanitize_text", lambda t: (t, []))
    monkeypatch.setattr(ma, "query_anthropic",
                        lambda prompt, system, **kwargs: make_llm_response(cfg["llm_items"]))
    monkeypatch.setattr(ma.CodingRulesDB, "check_ncci", lambda self, codes, as_of=None: cfg["ncci"])
    monkeypatch.setattr(ma.CodingRulesDB, "check_mue", lambda self, code, units: cfg["mue"].get(code))
    monkeypatch.setattr(ma.CodingRulesDB, "get_cpt_description", lambda self, code: None)
    return cfg


def _ncci_finding():
    return {"code": "12002", "conflict_with": "12004", "mod_indicator": "1",
            "alert": "HIGH - NCCI BUNDLING (Bundles into 12004)"}


def _llm_item(code):
    return {"code": code, "documentation_status": "PASS", "clinical_evidence": "q",
            "calculated_units": 1, "billing_risk_alert": "NONE", "risk_rationale": ""}


def test_no_modifier_is_fine_and_stays_high(patch_pipeline):
    patch_pipeline["ncci"] = [_ncci_finding()]
    patch_pipeline["llm_items"] = [_llm_item("12004"), _llm_item("12002")]
    result = ma.audit_medical_record("note", ["12004", "12002"], ["S41.111A"],
                                     units_map={"12004": 1, "12002": 1})
    flagged = next(i for i in result["audit_results"] if i["code"] == "12002")
    assert flagged["billing_risk_alert"] == "HIGH - NCCI BUNDLING"


def test_bypass_modifier_downgrades_indicator_1(patch_pipeline):
    patch_pipeline["ncci"] = [_ncci_finding()]
    patch_pipeline["llm_items"] = [_llm_item("12004"), _llm_item("12002")]
    result = ma.audit_medical_record("note", ["12004", "12002"], ["S41.111A"],
                                     units_map={"12004": 1, "12002": 1},
                                     modifiers_map={"12002": ["59"]})
    flagged = next(i for i in result["audit_results"] if i["code"] == "12002")
    assert flagged["billing_risk_alert"] == "MEDIUM - NCCI (MODIFIER APPLIED)"
    assert "Modifier 59" in flagged["risk_rationale"]


def test_modifier_cannot_bypass_indicator_0(patch_pipeline):
    finding = _ncci_finding()
    finding["mod_indicator"] = "0"
    patch_pipeline["ncci"] = [finding]
    patch_pipeline["llm_items"] = [_llm_item("12004"), _llm_item("12002")]
    result = ma.audit_medical_record("note", ["12004", "12002"], ["S41.111A"],
                                     units_map={"12004": 1, "12002": 1},
                                     modifiers_map={"12002": ["59"]})
    flagged = next(i for i in result["audit_results"] if i["code"] == "12002")
    assert flagged["billing_risk_alert"] == "HIGH - NCCI BUNDLING"
    assert "CANNOT override" in flagged["risk_rationale"]


def test_irrelevant_modifier_does_not_downgrade(patch_pipeline):
    patch_pipeline["ncci"] = [_ncci_finding()]
    patch_pipeline["llm_items"] = [_llm_item("12004"), _llm_item("12002")]
    result = ma.audit_medical_record("note", ["12004", "12002"], ["S41.111A"],
                                     units_map={"12004": 1, "12002": 1},
                                     modifiers_map={"12002": ["LT"]})  # laterality, not distinct-service
    flagged = next(i for i in result["audit_results"] if i["code"] == "12002")
    assert flagged["billing_risk_alert"] == "HIGH - NCCI BUNDLING"


# ---------- 3. Rules-engine context awareness ----------

def test_negated_cosmetic_term_does_not_hard_fail():
    text = ("There was no cosmetic intent. A midface flap was elevated with "
            "preservation of the vascular pedicle to repair the surgical defect.")
    status, reason = RulesEngine.validate("15730", text)
    assert status == "PASS", f"negated exclusion fired: {reason}"


def test_aesthetic_subunit_is_reconstructive_language():
    text = ("The flap was designed along the aesthetic subunit of the cheek. "
            "Midface degloving performed with preservation of the vascular pedicle.")
    status, reason = RulesEngine.validate("15730", text)
    assert status == "PASS", f"'aesthetic subunit' wrongly excluded: {reason}"


def test_true_cosmetic_intent_still_hard_fails():
    text = "Midface lift performed for aesthetic rejuvenation of the cheek."
    status, _ = RulesEngine.validate("15730", text)
    assert status == "HARD_FAIL"


def test_distant_deep_and_fascia_do_not_pass():
    # 'deep' and 'fascia' appear many words apart — must not satisfy the check
    text = ("Deep sutures were placed in the arm wound. Later the superficial "
            "subcutaneous fascia of the region was noted to be intact.")
    status, _ = RulesEngine.validate("15736", text)
    assert status == "FAIL"


def test_adjacent_deep_fascia_still_passes():
    text = "Dissection was carried down to the deep investing fascia of the arm."
    status, reason = RulesEngine.validate("15736", text)
    assert status == "PASS", reason

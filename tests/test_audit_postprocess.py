"""
Tests for the deterministic post-processing in audit_medical_record:
NCCI/MUE merge, unit-discrepancy alerting, the PASS-with-0-units safety net,
and rules-engine guardrail application. The LLM call is mocked.
"""
import sys
import os
import types
import pytest

sys.path.append(os.getcwd())

# Stub the PHI sanitizer just long enough to import medical_audit — the real
# module pulls in spaCy/Presidio, which these unit tests don't need. The stub
# is removed afterwards so test_sanitization.py still imports the real module.
_had_real = "sanitize_phi" in sys.modules
if not _had_real:
    _stub = types.ModuleType("sanitize_phi")
    _stub.sanitize_text = lambda t: (t, [])
    sys.modules["sanitize_phi"] = _stub

from execution import medical_audit as ma

if not _had_real:
    del sys.modules["sanitize_phi"]


def make_llm_response(items, diagnosis="ok", improvement="ok"):
    """Builds a canned structured-output payload for query_anthropic."""
    import json
    payload = {
        "audit_results": items,
        "diagnosis_analysis": diagnosis,
        "documentation_improvement": improvement,
    }
    return json.dumps(payload), {"input_tokens": 10, "output_tokens": 10}


@pytest.fixture
def patch_pipeline(monkeypatch):
    """Neutralizes external deps; returns a dict the test can customize."""
    cfg = {"llm_items": [], "ncci": [], "mue": {}}

    monkeypatch.setattr(ma, "sanitize_text", lambda t: (t, []))
    monkeypatch.setattr(
        ma, "query_anthropic",
        lambda prompt, system, **kwargs: make_llm_response(cfg["llm_items"]),
    )
    monkeypatch.setattr(ma.CodingRulesDB, "check_ncci", lambda self, codes: cfg["ncci"])
    monkeypatch.setattr(ma.CodingRulesDB, "check_mue",
                        lambda self, code, units: cfg["mue"].get(code))
    monkeypatch.setattr(ma.CodingRulesDB, "get_cpt_description", lambda self, code: None)
    return cfg


def run_audit(cfg, codes, units_map=None, text="Simple laceration repaired."):
    return ma.audit_medical_record(text, codes, ["S41.111A"], units_map=units_map)


def test_safety_net_forces_pass_to_one_unit(patch_pipeline):
    patch_pipeline["llm_items"] = [{
        "code": "12001", "documentation_status": "PASS",
        "clinical_evidence": "quote", "calculated_units": 0,
        "billing_risk_alert": "NONE", "risk_rationale": "",
    }]
    result = run_audit(patch_pipeline, ["12001"], {"12001": 1})
    item = result["audit_results"][0]
    assert item["calculated_units"] == 1
    # billed 1 == forced 1 -> no discrepancy alert
    assert item["billing_risk_alert"] == "NONE"


def test_unit_discrepancy_flagged_once(patch_pipeline):
    patch_pipeline["llm_items"] = [{
        "code": "12001", "documentation_status": "PASS",
        "clinical_evidence": "quote", "calculated_units": 3,
        "billing_risk_alert": "NONE", "risk_rationale": "Doc supports repair.",
    }]
    result = run_audit(patch_pipeline, ["12001"], {"12001": 5})
    item = result["audit_results"][0]
    assert item["billing_risk_alert"] == "UNIT DISCREPANCY"
    assert "Billed 5 but Doc supports 3" in item["risk_rationale"]
    # Regression: the old code could prepend the discrepancy message twice
    assert item["risk_rationale"].count("Unit Discrepancy") == 1


def test_ncci_merge_reaches_output(patch_pipeline):
    # Regression: this merge used to sit inside an except handler and never ran
    patch_pipeline["ncci"] = [{
        "code": "12002", "conflict_with": "12004",
        "mod_indicator": "0", "alert": "HIGH - NCCI BUNDLING (Bundles into 12004)",
    }]
    patch_pipeline["llm_items"] = [
        {"code": "12004", "documentation_status": "PASS", "clinical_evidence": "q",
         "calculated_units": 1, "billing_risk_alert": "NONE", "risk_rationale": ""},
        {"code": "12002", "documentation_status": "PASS", "clinical_evidence": "q",
         "calculated_units": 1, "billing_risk_alert": "NONE", "risk_rationale": ""},
    ]
    result = run_audit(patch_pipeline, ["12004", "12002"], {"12004": 1, "12002": 1})
    flagged = next(i for i in result["audit_results"] if i["code"] == "12002")
    assert flagged["billing_risk_alert"] == "HIGH - NCCI BUNDLING"
    assert "Bundles into code 12004" in flagged["risk_rationale"]
    assert "Strictly Prohibited" in flagged["risk_rationale"]


def test_mue_merge_reaches_output(patch_pipeline):
    patch_pipeline["mue"] = {"11720": {"alert": "HIGH - MUE EXCEEDED", "limit": 1,
                                        "mai": "2", "rationale": "test"}}
    patch_pipeline["llm_items"] = [{
        "code": "11720", "documentation_status": "PASS", "clinical_evidence": "q",
        "calculated_units": 5, "billing_risk_alert": "NONE", "risk_rationale": "",
    }]
    result = run_audit(patch_pipeline, ["11720"], {"11720": 5})
    item = result["audit_results"][0]
    assert item["billing_risk_alert"] == "HIGH - MUE EXCEEDED"
    assert "You billed 5 units, but the limit is 1" in item["risk_rationale"]
    assert "Absolute Daily Limit" in item["risk_rationale"]


def test_rules_engine_hard_fail_overrides_llm_pass(patch_pipeline):
    patch_pipeline["llm_items"] = [{
        "code": "15730", "documentation_status": "PASS", "clinical_evidence": "q",
        "calculated_units": 1, "billing_risk_alert": "NONE", "risk_rationale": "Looks fine.",
    }]
    result = run_audit(
        patch_pipeline, ["15730"], {"15730": 1},
        text="Midface lift performed for aesthetic rejuvenation.",
    )
    item = result["audit_results"][0]
    assert item["documentation_status"] == "FAIL"
    assert item["billing_risk_alert"] == "HIGH - SYSTEM GUARDRAIL (EXCLUSION)"


def test_rules_engine_soft_fail_forces_medium_alert(patch_pipeline):
    patch_pipeline["llm_items"] = [{
        "code": "15736", "documentation_status": "PASS", "clinical_evidence": "q",
        "calculated_units": 1, "billing_risk_alert": "NONE", "risk_rationale": "",
    }]
    result = run_audit(
        patch_pipeline, ["15736"], {"15736": 1},
        text="A skin flap was advanced on the arm.",  # no deep fascia keywords
    )
    item = result["audit_results"][0]
    assert item["billing_risk_alert"] == "MEDIUM - MISSING KEYWORDS"
    assert "MISSING KEYWORDS" in item["risk_rationale"]


def test_llm_error_returns_error_dict(patch_pipeline, monkeypatch):
    def boom(prompt, system, **kwargs):
        raise ValueError("LLM unavailable")
    monkeypatch.setattr(ma, "query_anthropic", boom)
    result = run_audit(patch_pipeline, ["12001"], {"12001": 1})
    assert "error" in result
    assert "LLM unavailable" in result["error"]

"""
Medical Coding Audit Tool.
1. Sanitizes PHI locally.
2. Sends redacted text to Anthropic (Claude) for CPT Verification.
"""
import sys
import json
import os
import anthropic
from dotenv import load_dotenv
from sanitize_phi import sanitize_text
import sqlite3

# Load environment variables
load_dotenv(override=False)

# Import Policy Logic. clinical_policies.py is intentionally untracked (it
# contains CPT descriptor language that can't be published) — see
# clinical_policies.example.py for the expected structure.
try:
    from execution.clinical_policies import POLICY_MAPPING
except ImportError:
    POLICY_MAPPING = {}
from execution.rules_engine import RulesEngine

# Configure Logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "claude-sonnet-5")

# Bedrock Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "bedrock") # Default to bedrock for AWS host
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-5")

# Pricing per 1M tokens for the CLI cost printout. Override in .env when the model changes.
INPUT_PRICE_PER_MTOK = float(os.getenv("INPUT_PRICE_PER_MTOK", "3.00"))
OUTPUT_PRICE_PER_MTOK = float(os.getenv("OUTPUT_PRICE_PER_MTOK", "15.00"))

# (input, output) $ per 1M tokens by model family. There is no pricing API,
# so this table is the one thing that needs a manual update when Anthropic
# changes prices — unknown families surface as "pricing unknown" in the UI.
# First substring match wins.
MODEL_PRICING = [
    ("fable",  (10.00, 50.00)),
    ("mythos", (10.00, 50.00)),
    ("opus",   (5.00, 25.00)),
    ("sonnet", (3.00, 15.00)),
    ("haiku",  (1.00, 5.00)),
]

def get_model_pricing(model_id):
    """Returns (input, output) $/MTok for a model id, or (None, None) if unknown."""
    mid = (model_id or "").lower()
    for family, prices in MODEL_PRICING:
        if family in mid:
            return prices
    return None, None

def resolve_model(model=None):
    """Requested model, or the provider default."""
    if model:
        return model
    return BEDROCK_MODEL_ID if LLM_PROVIDER.lower() == "bedrock" else MODEL_NAME

_model_cache = None

def list_available_models(force_refresh=False):
    """
    Live model list for the UI picker, queried from the active provider at
    first use and cached for the process lifetime. No hardcoded model ids —
    falls back to the configured default only if the query fails.
    """
    global _model_cache
    if _model_cache is not None and not force_refresh:
        return _model_cache

    models = []
    try:
        if LLM_PROVIDER.lower() == "bedrock":
            import boto3
            bedrock = boto3.client("bedrock", region_name=AWS_REGION)
            resp = bedrock.list_foundation_models(byProvider="Anthropic")
            for summary in resp.get("modelSummaries", []):
                model_id = summary.get("modelId", "")
                if "claude" not in model_id:
                    continue
                # Skip provisioned-only variants; the app calls on-demand
                if "ON_DEMAND" not in summary.get("inferenceTypesSupported", []):
                    continue
                models.append({"id": model_id, "name": summary.get("modelName", model_id)})
        else:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            for m in client.models.list():
                models.append({"id": m.id, "name": m.display_name})
    except Exception as e:
        logger.error(f"Could not fetch model list from {LLM_PROVIDER}: {e}")
        default = resolve_model()
        models = [{"id": default, "name": default}]

    for m in models:
        in_price, out_price = get_model_pricing(m["id"])
        m["input_price_per_mtok"] = in_price
        m["output_price_per_mtok"] = out_price

    _model_cache = models
    return models

def get_llm_client():
    """
    Returns (client, model_id) for the configured provider.
    Both clients expose the same messages.create() surface.
    """
    if LLM_PROVIDER.lower() == "bedrock":
        from anthropic import AnthropicBedrockMantle
        return AnthropicBedrockMantle(aws_region=AWS_REGION), BEDROCK_MODEL_ID

    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not found in .env file.")
        raise ValueError("ANTHROPIC_API_KEY not found in .env file.")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY), MODEL_NAME

def query_anthropic(prompt, system_prompt, output_schema=None, model=None):
    """
    Single LLM entry point for both Bedrock and Anthropic Direct.
    When output_schema is given, structured outputs guarantee the response
    is valid JSON matching the schema. `model` overrides the provider default.
    """
    client, default_model = get_llm_client()
    model = model or default_model
    logger.info(f"Active LLM Provider: {LLM_PROVIDER} | Model: {model}")

    kwargs = {}
    if output_schema:
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": output_schema}}

    try:
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=system_prompt,
            messages=[
                {"role": "user", "content": prompt}
            ],
            **kwargs,
        )
    except Exception as e:
        logger.error(f"Error querying {LLM_PROVIDER}: {e}")
        raise

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens
    }
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        logger.error(f"LLM returned no text content. stop_reason={response.stop_reason}")
    return text, usage

# Schema enforced via structured outputs for the main audit call.
AUDIT_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "audit_results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "documentation_status": {"type": "string", "enum": ["PASS", "FAIL", "PARTIAL"]},
                    "clinical_evidence": {"type": "string"},
                    "calculated_units": {"type": "integer"},
                    "billing_risk_alert": {"type": "string"},
                    "risk_rationale": {"type": "string"},
                },
                "required": ["code", "documentation_status", "clinical_evidence",
                             "calculated_units", "billing_risk_alert", "risk_rationale"],
                "additionalProperties": False,
            },
        },
        "diagnosis_analysis": {"type": "string"},
        "documentation_improvement": {"type": "string"},
    },
    "required": ["audit_results", "diagnosis_analysis", "documentation_improvement"],
    "additionalProperties": False,
}

# Static audit instructions. Kept byte-stable so the prompt cache covers them
# on every audit request.
AUDIT_SYSTEM_INSTRUCTIONS = """You are an EXPERT Medical Quality Auditor known for precision and strict adherence to CPT guidelines. You also validate ICD-10 Diagnosis specificity.

Your task is to perform a multi-step audit of billed CPT codes against clinical documentation.

STEP 1: DOCUMENTATION VERIFICATION
- Verify if the text supports the code description.
- INDEPENDENTLY calculate the 'correct' supported units based on measurements.
- MATH: If definition says "each additional X cm or part thereof", round up (2.1 = 3).

STEP 2: REIMBURSEMENT RISK ANALYSIS
- Apply the SYSTEM ALERTS provided in the input. They are FACTUAL database checks: do not dispute them, explain them using the exact rationale provided.
- Check for "Cloned Note" or "Copy-Billed" text.
- Validate medical necessity.

STEP 3: DIAGNOSIS VALIDATION
- Check if the diagnosis codes listed support the CPT codes.
- Flag any VAGUE or UNSPECIFIED codes (e.g., Unspecified side, Unspecified injury, Z-codes for encounters) as HIGH RISK.

CRITICAL OUTPUT RULES:
1. If "documentation_status" is "PASS", "calculated_units" MUST be at least 1.
2. You MUST return a result object for EVERY SINGLE CPT CODE in the input. Do NOT skip codes: if 5 codes are input, 5 results must be returned.
3. If a CPT code is invalid or unknown, mark it as FAIL and explain why.

FIELD SEMANTICS:
- "clinical_evidence": one sentence quoted from the text, or 'No evidence found'.
- "calculated_units": your independent count derived from the text.
- "billing_risk_alert": "NONE" or "HIGH - MUE EXCEEDED" or "HIGH - NCCI BUNDLING".
- "risk_rationale": clear explanation; if a risk exists, use the human-readable explanation from SYSTEM ALERTS.
- "diagnosis_analysis" / "documentation_improvement": Markdown bullet points for readability.
"""

# cpt_data.py is intentionally untracked (verbatim CPT descriptors are
# AMA-copyrighted) — see cpt_data.example.py. Falls back to the DB's short
# descriptions when absent.
try:
    from execution.cpt_data import CPT_DEFINITIONS
except ImportError:
    CPT_DEFINITIONS = {}

class CodingRulesDB:
    def __init__(self, db_path="coding_rules.db"):
        self.db_path = db_path

    def get_connection(self):
        try:
            return sqlite3.connect(self.db_path)
        except sqlite3.Error as e:
            logger.error(f"Error connecting to DB: {e}")
            return None

    def check_mue(self, code, user_units):
        conn = self.get_connection()
        if not conn: return None

        cursor = conn.cursor()
        cursor.execute("SELECT max_units, mai, rationale FROM mue_limits WHERE hcpcs_code=?", (code,))
        row = cursor.fetchone()
        conn.close()

        if row:
            max_units, mai, rationale = row
            if user_units > max_units:
                return {
                    "alert": "HIGH - MUE EXCEEDED",
                    "limit": max_units,
                    "mai": mai,
                    "rationale": f"MAI {mai} indicates specific rules apply. {rationale}"
                }
        return None

    def get_cpt_description(self, code):
        """Fetch short description from DB."""
        conn = self.get_connection()
        if not conn: return None

        cursor = conn.cursor()
        cursor.execute("SELECT short_desc FROM cpt_codes WHERE code=?", (code,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def check_ncci(self, codes, as_of=None):
        """
        Optimized Batch NCCI Check.
        Instead of iterating permutations (N^2), we do one query.
        Only edits ACTIVE on `as_of` (YYYYMMDD, default today) are returned —
        the table retains history, and ~25% of rows are deleted/expired edits
        that must not fire alerts.
        """
        if not codes or len(codes) < 2: return []

        if as_of is None:
            import datetime
            as_of = datetime.date.today().strftime("%Y%m%d")

        conn = self.get_connection()
        if not conn: return []

        cursor = conn.cursor()
        alerts = []

        # Prepare placeholders for IN clause
        placeholders = ','.join(['?'] * len(codes))

        # Optimization: Fetch ALL edges where both nodes are in our code list.
        # This is strictly O(1) query roundtrip instead of O(N^2).
        # Dates are fixed-width YYYYMMDD text, so string comparison is safe.
        query = f"""
            SELECT column1_code, column2_code, modifier_indicator
            FROM ncci_edits
            WHERE column1_code IN ({placeholders})
              AND column2_code IN ({placeholders})
              AND (effective_date IS NULL OR effective_date = '' OR effective_date <= ?)
              AND (deletion_date IS NULL OR deletion_date = '' OR deletion_date = '*' OR deletion_date >= ?)
        """

        # We pass the list twice (once for col1, once for col2), then the dates
        params = codes + codes + [as_of, as_of]

        try:
            cursor.execute(query, params)
            rows = cursor.fetchall()

            for row in rows:
                c1, c2, mod_ind = row
                # c1 is Column 1 (Comprehensive), c2 is Column 2 (Component)
                # If we found a row, it means c2 bundles into c1.

                # Check if it's a self-reference (rare data error, but possible)
                if c1 == c2: continue

                alerts.append({
                    "code": c2, # The component code causing the issue
                    "conflict_with": c1,
                    "mod_indicator": mod_ind,
                    "alert": f"HIGH - NCCI BUNDLING (Bundles into {c1})"
                })

        except sqlite3.Error as e:
            logger.error(f"DB Error during NCCI check: {e}")

        conn.close()
        return alerts

def get_readable_rationale(alert_Data):
    """
    Converts database flags into Human Readable rationale.
    """
    rationale_parts = []

    # 1. NCCI Mapping
    if alert_Data.get('conflict_with') and "MUE" not in alert_Data['conflict_with']:
        target = alert_Data['conflict_with']
        ind = alert_Data.get('mod_indicator')

        # Indicator 0 = Not Allowed
        # Indicator 1 = Allowed with Modifier
        # Indicator 9 = Not Applicable

        if str(ind) == '0':
            readable_status = "Strictly Prohibited (modifiers CANNOT override this edit)"
        elif alert_Data.get('modifier_applied'):
            readable_status = (f"Modifier {alert_Data.get('modifier_used')} is on the claim — "
                               "override permitted IF the note documents a distinct service/site")
        else:
            readable_status = "Potential Modifier Override (e.g. 59/XS) - REQUIRES Distinct Procedural Service/Site"
        rationale_parts.append(f"Bundles into code {target}. Status: {readable_status}.")

    # 2. MUE Mapping
    if "MUE" in alert_Data.get('conflict_with', ''):
        limit = alert_Data.get('limit')
        billed = alert_Data.get('billed')
        mai = str(alert_Data.get('mai'))

        # MAI Translation
        description = "Maximum Units"
        if "1" in mai: description = "Claim Line Limit"
        elif "2" in mai: description = "Absolute Daily Limit (Hard Max)"
        elif "3" in mai: description = "Clinical Benchmark (Appealable with documentation)"

        rationale_parts.append(f"You billed {billed} units, but the limit is {limit}. ({description})")

    return " ".join(rationale_parts)

# Modifiers that CAN bypass an NCCI edit with indicator 1 (distinct service).
NCCI_BYPASS_MODIFIERS = {"59", "XE", "XS", "XP", "XU"}

def audit_medical_record(raw_text, cpt_list, diagnosis_codes, units_map=None, model=None, modifiers_map=None):
    """
    Main orchestration function.
    1. Sanitizes Text
    2. Checks DB Rules (NCCI / MUE)
    3. Prompts Claude (Agent)
    `model` optionally overrides the provider default (from the UI picker).
    `modifiers_map` ({code: [modifiers]}) is OPTIONAL — codes without modifiers
    are audited normally; a bypass modifier only ever downgrades an NCCI alert.
    """
    model = resolve_model(model)
    if modifiers_map is None:
        modifiers_map = {}
    # Normalize input
    if isinstance(cpt_list, str): cpt_list = [cpt_list]
    cpt_codes = cpt_list # Use this for rest of function

    if isinstance(diagnosis_codes, str): diagnosis_codes = [diagnosis_codes]

    logger.info("Step 1: Sanitizing PHI locally...")
    sanitized_text, _ = sanitize_text(raw_text)
    logger.info(f"Sanitized Text Preview: {sanitized_text[:100]}...")

    # Retrieve definitions + POLICY INJECTION + RULES CHECK
    db = CodingRulesDB()
    cpt_context = ""
    policy_context = ""

    # Store Rule Outcomes to override LLM later if needed
    rule_outcomes = {}

    for code in cpt_codes:
        # --- 0. Deterministic Rules Engine ---
        rule_status, rule_rationale = RulesEngine.validate(code, sanitized_text)
        rule_outcomes[code] = {"status": rule_status, "rationale": rule_rationale}

        # 1. Basic Definition
        definition = CPT_DEFINITIONS.get(code)
        if not definition:
            desc = db.get_cpt_description(code)
            definition = f"{desc} (Official Short Description)" if desc else "No internal definition found."

        # NOTE: rule warnings are note-dependent, so they go in the volatile
        # prompt section (below), not here — this block must stay byte-stable
        # per code set so it can be prompt-cached.
        cpt_context += f"- CPT {code}: {definition}\n"

        # 2. Smart Segmentation: Policy Injection
        if code in POLICY_MAPPING:
            policy_context += f"\n--- POLICY FOR CPT {code} ---\n{POLICY_MAPPING[code]}\n"



    logger.info(f"Step 2: Auditing CPTs {cpt_codes} against documentation...")
    logger.debug(f"Definitions:\n{cpt_context}")

    # --- DB Rules Check ---
    db = CodingRulesDB()
    mue_alerts = {}
    ncci_alerts = {}

    # 1. NCCI Checks
    ncci_findings = db.check_ncci(cpt_codes)
    for finding in ncci_findings:
        # Map alert to the code
        code = finding['code']
        # Indicator-1 edits may be bypassed when the component code carries a
        # distinct-service modifier. No modifier = normal HIGH alert (never a penalty).
        user_mods = {str(m).strip().upper() for m in modifiers_map.get(code, [])}
        bypass_mods = user_mods & NCCI_BYPASS_MODIFIERS
        if str(finding.get('mod_indicator')) == '1' and bypass_mods:
            finding['modifier_applied'] = True
            finding['modifier_used'] = ", ".join(sorted(bypass_mods))
        if code not in ncci_alerts:
            ncci_alerts[code] = []
        ncci_alerts[code].append(finding)

    # 2. MUE Checks (Verify User Billing Units vs Limits)
    for code in cpt_codes:
        # Determine user units (default to 1 if not provided)
        user_units = 1
        if units_map and code in units_map:
            user_units = units_map[code]

        mue_finding = db.check_mue(code, user_units)

        if mue_finding:
            # Map alert to code
            if code not in ncci_alerts:
                ncci_alerts[code] = []

            # Add MUE Alert
            # Store raw data for processing, but also make a friendly alert string
            alert_obj = {
                "code": code,
                "conflict_with": "MUE LIMIT",
                "mod_indicator": f"MAI {mue_finding['mai']}",
                "limit": mue_finding['limit'],
                "billed": user_units,
                "mai": mue_finding['mai'],
                "alert": f"HIGH - MUE EXCEEDED"
            }
            ncci_alerts[code].append(alert_obj)

    # 3. Generate Human Readable Context for LLM
    # We want the LLM to see the 'Translated' reasoning, not raw MAI codes
    risk_context_str = ""
    for code, alerts in ncci_alerts.items():
        risk_context_str += f"\n- Code {code} Risks:\n"
        for a in alerts:
            readable = get_readable_rationale(a)
            risk_context_str += f"  * {a['alert']}: {readable}\n"

    # Rule-engine warnings depend on the note text, so they live in the
    # volatile section rather than the cacheable definitions block.
    rule_warning_str = ""
    for code, outcome in rule_outcomes.items():
        if outcome["status"] != "PASS":
            rule_warning_str += f"- CPT {code}: [SYSTEM WARNING: {outcome['rationale']}]\n"

    # Prompt layout for caching: instructions (system) and the per-code-set
    # reference context are byte-stable, so a cache breakpoint after them lets
    # repeated audits of the same codes reuse the prefix. Per-note data follows.
    stable_context = f"""REFERENCE CONTEXT:
- CPT Definitions:
{cpt_context}
- PAYER POLICIES AND MANDATES (Validation Rules):
{policy_context if policy_context else "None."}"""

    volatile_input = f"""INPUT DATA:
- CPT Codes: {cpt_codes}
- Billed Units: {json.dumps(units_map)}
- Modifiers on claim (empty = none, which is acceptable): {json.dumps(modifiers_map)}
- Diagnosis Codes: {diagnosis_codes}
- SYSTEM ALERTS (These are FACTUAL database checks. Do not dispute them. explain them):
  {risk_context_str if risk_context_str else "None."}
- RULE ENGINE WARNINGS (deterministic keyword checks on this note):
  {rule_warning_str if rule_warning_str else "None."}
- Clinical Documentation:
\"\"\"
{sanitized_text}
\"\"\"
"""

    prompt = [
        {"type": "text", "text": stable_context, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": volatile_input},
    ]
    system_prompt = AUDIT_SYSTEM_INSTRUCTIONS

    max_retries = 3
    last_error = None

    total_usage = {"input_tokens": 0, "output_tokens": 0}

    for attempt in range(max_retries):
        try:
            response_text, usage = query_anthropic(prompt, system_prompt, output_schema=AUDIT_RESULT_SCHEMA, model=model)
            if not response_text:
                raise ValueError("Empty response from LLM")

            if usage:
                total_usage["input_tokens"] += usage.get("input_tokens", 0)
                total_usage["output_tokens"] += usage.get("output_tokens", 0)

            # Structured outputs guarantee the text block is schema-valid JSON
            result_json = json.loads(response_text)
            break # Success!

        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
            last_error = e
            if attempt == max_retries - 1:
                return {"error": f"LLM failed after {max_retries} attempts. Last error: {str(last_error)}"}

    # --- POST-PROCESS: INJECT DETERMINISTIC NCCI/MUE DATA ---
    if "audit_results" in result_json:
        if units_map is None: units_map = {}
        for item in result_json["audit_results"]:
            code = item.get("code")
            user_units = units_map.get(code, 1)
            item["billed_units"] = user_units # Pass back to frontend

            # --- SAFETY NET: Enforce 1 unit for PASS ---
            # If the LLM says "PASS" but "calculated_units": 0, it is a format error.
            # We override it to 1 because PASS implies at least one unit is supported.
            doc_status = item.get("documentation_status", "UNKNOWN").upper()
            if doc_status == "PASS":
                try:
                    if int(item.get("calculated_units", 0)) < 1:
                        logger.warning(f"Safety Net Triggered: Code {code} PASS but 0 units. Forcing to 1.")
                        item["calculated_units"] = 1
                except (TypeError, ValueError):
                    item["calculated_units"] = 1

            # Check Unit Discrepancy (after the safety net so PASS/0 doesn't false-alarm)
            try:
                calc_val = int(item.get("calculated_units") or 0)
            except (TypeError, ValueError) as e:
                logger.warning(f"Code {code}: non-numeric calculated_units {item.get('calculated_units')!r}: {e}")
            else:
                if calc_val != user_units:
                    disc_msg = f"Unit Discrepancy: Billed {user_units} but Doc supports {calc_val}. "
                    if item.get("billing_risk_alert", "NONE") == "NONE":
                        item["billing_risk_alert"] = "UNIT DISCREPANCY"
                    item["risk_rationale"] = disc_msg + item.get('risk_rationale', '')

            # Merge deterministic DB findings (NCCI / MUE) into the result.
            # DB Rationale (The Rules) + LLM Rationale (The Clinical Context).
            if code in ncci_alerts:
                details = ncci_alerts[code]
                reasons = [get_readable_rationale(d) for d in details]
                risks = [d['alert'] for d in details]

                # Consolidate Risk Label (DB findings outrank the LLM's label).
                # NCCI pairs fully covered by a distinct-service modifier drop
                # to MEDIUM — still worth a documentation check, not a denial.
                ncci_details = [d for d in details if "MUE" not in str(d.get('conflict_with', ''))]
                unresolved_ncci = [d for d in ncci_details if not d.get('modifier_applied')]
                if any("MUE" in r for r in risks):
                    item["billing_risk_alert"] = "HIGH - MUE EXCEEDED"
                elif unresolved_ncci:
                    item["billing_risk_alert"] = "HIGH - NCCI BUNDLING"
                elif ncci_details:
                    item["billing_risk_alert"] = "MEDIUM - NCCI (MODIFIER APPLIED)"

                current = item.get("risk_rationale", "")
                clean_db_rationale = " | ".join(reasons)
                combined_rationale = clean_db_rationale

                if "Unit Discrepancy" in current:
                    # Keep the discrepancy note in front, then strip it from the LLM text
                    disc_part = current.split("Unit Discrepancy")[1].split(".")[0]
                    combined_rationale = f"Unit Discrepancy{disc_part}. {combined_rationale}"
                    current = current.replace(f"Unit Discrepancy{disc_part}.", "").strip()

                # Append clinical context if meaningful and not just the rule repeated
                if current and len(current) > 10 and current not in clean_db_rationale:
                    combined_rationale += f"\n[Clinical Note]: {current}"

                item["risk_rationale"] = combined_rationale

    # --- DETERMINISTIC GUARDRAILS (Rules Engine Application) ---
    if "audit_results" in result_json:
        for item in result_json["audit_results"]:
            code = item.get("code")
            if code in rule_outcomes:
                outcome = rule_outcomes[code]
                status = outcome["status"]
                reason = outcome["rationale"]

                if status == "HARD_FAIL":
                    item["billing_risk_alert"] = "HIGH - SYSTEM GUARDRAIL (EXCLUSION)"
                    item["documentation_status"] = "FAIL"
                    item["risk_rationale"] = f"{reason} \n[Prior Rationale]: {item.get('risk_rationale','')}"

                elif status == "FAIL":
                    # Soft Fail - We let LLM pass if it argues well, but we FORCE the alert
                    current_risk = item.get("billing_risk_alert", "NONE")
                    if "HIGH" not in current_risk: # Don't downgrade a high risk
                        item["billing_risk_alert"] = "MEDIUM - MISSING KEYWORDS"

                    item["risk_rationale"] = f"{reason} \n[Prior Rationale]: {item.get('risk_rationale','')}"

    # Inject Usage Data + per-request cost estimate for the UI
    total_usage["model"] = model
    in_price, out_price = get_model_pricing(model)
    if in_price is not None:
        total_usage["estimated_cost"] = round(
            total_usage["input_tokens"] / 1_000_000 * in_price
            + total_usage["output_tokens"] / 1_000_000 * out_price, 4)
    result_json["usage"] = total_usage

    return result_json

def print_human_readable_result(result):
    if "error" in result:
        print(f"\nERROR: {result['error']}")
        if "raw_response" in result:
            print(f"Raw Response: {result['raw_response']}")
        return

    # Widened RISK column
    print(f"\n{'CODE':<10} {'DOC STATUS':<12} {'UNITS':<6} {'RISK':<30} {'EVIDENCE'}")
    print("-" * 130)

    audit_results = result.get("audit_results", [])
    if not audit_results:
        print(f"ALL       {result.get('status', 'UNKNOWN'):<10} {result.get('reason', 'No details')}")
    else:
        for item in audit_results:
            status = item.get("documentation_status", "UNKNOWN").upper()
            code = item.get("code", "N/A")
            units = item.get("calculated_units", 1)
            risk = item.get("billing_risk_alert", "NONE")
            evidence = item.get("clinical_evidence", "No evidence quoted.")
            # Also fetch rationale for display if Risk is high
            rationale = item.get("risk_rationale", "")

            color = "\033[92m" if status == "PASS" else "\033[91m"
            reset = "\033[0m"

            # Use Risk Alert as primary, but if NCCI, maybe show the rationale preview?
            # actually, let's just print the risk alert (Category) and then print rationale on next line if needed.
            # But user wants to see "Bundles with..."

            # Logic: If NCCI, the important bit is in RATIONALE now.
            # So let's extract the "conflicts" part if possible or just print rationale.

            risk_display = risk[:30]

            print(f"{code:<10} {color}{status:<12}{reset} {units:<6} {risk_display:<30} {evidence[:50]}...")

            # Print detailed rationale for risks on a secondary line for clarity
            if risk != "NONE" or "NCCI" in rationale:
                 print(f"{'':<10} {'':<12} {'':<6} \033[93m> {rationale}\033[0m")

    improvement = result.get("documentation_improvement", "N/A")
    if improvement and improvement != "N/A":
        print("\nDOCUMENTATION IMPROVEMENT:")
        print(improvement)

    # Print Cost
    if "usage" in result:
        u = result["usage"]
        in_tok = u.get("input_tokens", 0)
        out_tok = u.get("output_tokens", 0)
        cost = u.get("estimated_cost")
        if cost is None:
            cost = (in_tok / 1_000_000 * INPUT_PRICE_PER_MTOK) + (out_tok / 1_000_000 * OUTPUT_PRICE_PER_MTOK)
        print("\n" + "-" * 50)
        print(f"METRICS: Input: {in_tok} | Output: {out_tok} | Est. Cost: ${cost:.4f}")
        print("-" * 50)

def consult_auditor(context_text, audit_results, question, model=None):
    """
    Follow-up chat with the Auditor Agent.
    Routes through query_anthropic so it works on both Bedrock and the direct API.
    """
    # Construct context from the previous audit
    # We want the agent to know what it previously decided.
    audit_summary = json.dumps(audit_results, indent=2)

    system_prompt = "You are an Expert Medical Auditor Consultant. You have just audited a clinical note. The user has follow-up questions. Answer briefly and professionally based strictly on the text and coding rules."

    # The note + findings context is identical across follow-up questions on
    # the same audit — cache it so only the question is billed at full rate.
    context_block = f"""CONTEXT - CLINICAL NOTE:
\"\"\"
{context_text}
\"\"\"

CONTEXT - YOUR PREVIOUS AUDIT FINDINGS:
{audit_summary}"""

    user_prompt = [
        {"type": "text", "text": context_block, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"USER QUESTION:\n{question}\n\nProvide a helpful, evidence-based answer."},
    ]

    try:
        answer_text, _usage = query_anthropic(user_prompt, system_prompt, model=model)
        if not answer_text:
            raise ValueError("Empty response from LLM")
        return {"answer": answer_text}
    except Exception as e:
        logger.error(f"Chat Error: {e}")
        return {"error": str(e)}

APPEAL_SYSTEM_INSTRUCTIONS = """You are an expert medical billing appeals specialist. You write formal, payer-ready appeal letters for denied or at-risk claims.

Rules for every letter:
- Professional business-letter format, addressed to the payer's Appeals Department.
- Use placeholders for anything not in the provided context: [PATIENT NAME], [DOB], [MEMBER ID], [CLAIM NUMBER], [DATE OF SERVICE], [PROVIDER NAME/NPI], [PAYER NAME]. Never invent identifying details.
- Ground every clinical assertion in the operative report: quote the specific documentation that supports the code (anatomical planes, vascular pedicle preservation, named muscles, defect dimensions, medical necessity context).
- Cite the applicable coding authority precisely: CPT descriptor language, NCCI policy, MUE/MAI rationale, and any payer policy (e.g. LCD) provided in the context.
- Anticipate and rebut the likely denial rationale (cosmetic exclusion, bundling, insufficient documentation, medical necessity).
- Close with a clear request: reprocess and pay the claim as billed, and list the enclosures (operative report, policy excerpts).
- Output ONLY the letter text in Markdown. No preamble or commentary.
"""

def generate_appeal(context_text, audit_results, focus_code=None, denial_reason="", model=None):
    """
    Drafts a payer appeal letter from the audit context.
    focus_code limits the appeal to one CPT code; denial_reason (free text from
    the user, e.g. the remark code or letter language) sharpens the rebuttal.
    """
    audit_summary = json.dumps(audit_results, indent=2) if audit_results else "No prior audit findings provided."

    # Pull the relevant payer policy text so the letter can cite it directly
    codes = [focus_code] if focus_code else [
        item.get("code") for item in (audit_results or {}).get("audit_results", [])
    ]
    policy_context = ""
    for code in codes:
        if code in POLICY_MAPPING:
            policy_context += f"\n--- POLICY FOR CPT {code} ---\n{POLICY_MAPPING[code]}\n"

    context_block = f"""CONTEXT - OPERATIVE REPORT (PHI-sanitized):
\"\"\"
{context_text}
\"\"\"

CONTEXT - AUDIT FINDINGS:
{audit_summary}

CONTEXT - PAYER POLICY EXCERPTS:
{policy_context if policy_context else "None available."}"""

    request_block = f"""TASK:
Write an appeal letter for CPT {focus_code if focus_code else "the billed codes above"}.
Denial reason given by the payer: {denial_reason if denial_reason else "Not provided — anticipate the most likely denial rationale from the audit findings."}"""

    user_prompt = [
        {"type": "text", "text": context_block, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": request_block},
    ]

    try:
        letter, usage = query_anthropic(user_prompt, APPEAL_SYSTEM_INSTRUCTIONS, model=model)
        if not letter:
            raise ValueError("Empty response from LLM")
        return {"letter": letter, "usage": usage}
    except Exception as e:
        logger.error(f"Appeal generation error: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    import argparse

    # Allow running with specific CPT/Dx, otherwise use defaults
    parser = argparse.ArgumentParser(description='Audit a medical record.')
    parser.add_argument('--cpt', type=str, nargs='+', default=["12001"], help='CPT Codes to check (space separated)')
    parser.add_argument('--dx', type=str, nargs='+', default=["S41.111A"], help='Diagnosis Codes (space separated)')
    parser.add_argument('--file', type=str, default="inputs/input_record.txt", help='Path to text file containing the note')
    args = parser.parse_args()

    print(f"Reading from {args.file}...")
    try:
        with open(args.file, 'r', encoding='utf-8') as f:
            raw_text = f.read()
    except FileNotFoundError:
        print(f"Error: Could not find {args.file}.")
        print("Please create this file and paste your OP Report inside.")
        sys.exit(1)

    print("\n" + "="*50)
    print(f"AUDIT FOR CPT: {args.cpt} | DX: {args.dx}")
    print("="*50)

    result = audit_medical_record(raw_text, args.cpt, args.dx)

    print("\nRESULT:")
    print_human_readable_result(result)

    # Save results
    output_file = ".tmp/audit_result_latest.json"
    import os
    os.makedirs(".tmp", exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved detailed JSON result to {output_file}")

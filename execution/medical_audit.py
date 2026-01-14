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
import itertools

# Load environment variables
load_dotenv(override=True)

# Configure Logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL_NAME = "claude-sonnet-4-5-20250929" # Fallback to known stable version if latest fails 

def query_anthropic(prompt, system_prompt):
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not found in .env file.")
        return None
        
    logger.debug(f"Loaded API Key: {ANTHROPIC_API_KEY[:10]}... (Length: {len(ANTHROPIC_API_KEY)})")
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=4096,
            temperature=0,
            system=system_prompt,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Error querying Anthropic: {e}")
        return None

from execution.cpt_data import CPT_DEFINITIONS

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

    def check_ncci(self, codes):
        """
        Optimized Batch NCCI Check.
        Instead of iterating permutations (N^2), we do one query.
        """
        if not codes or len(codes) < 2: return []
        
        conn = self.get_connection()
        if not conn: return []
        
        cursor = conn.cursor()
        alerts = []
        
        # Prepare placeholders for IN clause
        placeholders = ','.join(['?'] * len(codes))
        
        # Optimization: Fetch ALL edges where both nodes are in our code list.
        # This is strictly O(1) query roundtrip instead of O(N^2).
        query = f"""
            SELECT column1_code, column2_code, modifier_indicator 
            FROM ncci_edits 
            WHERE column1_code IN ({placeholders}) 
              AND column2_code IN ({placeholders})
        """
        
        # We pass the list twice (once for col1, once for col2)
        params = codes + codes
        
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
        
        readable_status = "Strictly Prohibited" if str(ind) == '0' else "Potential Modifier Override (e.g. 59/XS) - REQUIRES Distinct Procedural Service/Site"
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

def audit_medical_record(raw_text, cpt_data, diagnosis_codes):
    # cpt_data: List of dicts [{'code': '...', 'user_units': 1}, ...] OR list of strings (legacy)
    
    # Normalize Inputs
    cpt_list = [] # Just codes for LLM
    units_map = {} # Code -> User Units
    
    if cpt_data and isinstance(cpt_data[0], dict):
        for item in cpt_data:
            c = item['code']
            cpt_list.append(c)
            units_map[c] = item.get('user_units', 1)
    else:
        # Legacy support
        if isinstance(cpt_data, str): cpt_data = [cpt_data]
        cpt_list = cpt_data
        for c in cpt_list:
            units_map[c] = 1

    cpt_codes = cpt_list # Use this for rest of function
    
    if isinstance(diagnosis_codes, str): diagnosis_codes = [diagnosis_codes]

    logger.info("Step 1: Sanitizing PHI locally...")
    sanitized_text, _ = sanitize_text(raw_text)
    logger.info(f"Sanitized Text Preview: {sanitized_text[:100]}...")
    
    # Retrieve definitions for all codes
    # Priority: 
    # 1. Augmented Rules (CPT_DEFINITIONS) - Contains custom logic/requirements
    # 2. Official Short Desc (DB) - Fallback
    
    db = CodingRulesDB()
    cpt_context = ""
    
    for code in cpt_codes:
        definition = CPT_DEFINITIONS.get(code)
        
        if not definition:
            # Fallback to DB
            desc = db.get_cpt_description(code)
            if desc:
                definition = f"{desc} (Official Short Description)"
            else:
                definition = "No internal definition found - relying on general knowledge."
        
        cpt_context += f"- CPT {code}: {definition}\n"

    logger.info(f"Step 2: Auditing CPTs {cpt_codes} against documentation...")
    logger.debug(f"Definitions:\n{cpt_context}")
    
    system_prompt = "You are an EXPERT Medical Quality Auditor known for precision and strict adherence to CPT guidelines."
    
    # --- DB Rules Check ---
    db = CodingRulesDB()
    mue_alerts = {}
    ncci_alerts = {}
    
    # 1. NCCI Checks
    ncci_findings = db.check_ncci(cpt_codes)
    for finding in ncci_findings:
        # Map alert to the code
        code = finding['code']
        if code not in ncci_alerts:
            ncci_alerts[code] = []
        ncci_alerts[code].append(finding)

    # 2. MUE Checks (Verify User Billing Units vs Limits)
    for code in cpt_codes:
        user_units = units_map.get(code, 1)
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

    prompt = f"""
    ROLE: You are an expert Medical Coding Auditor. 
    Your task is to perform a two-step audit on the provided CPT codes based on the clinical text.
    
    INPUT DATA:
    - CPT Codes: {cpt_codes}
    - Billed Units: {json.dumps(units_map)} (The user is attempting to bill these amounts)
    - CPT Definitions: {cpt_context}
    - SYSTEM ALERTS (These are FACTUAL database checks. Do not dispute them. explain them):
      {risk_context_str if risk_context_str else "None."}
    - Clinical Documentation: 
    \"\"\"
    {sanitized_text}
    \"\"\"
    
    INSTRUCTIONS:
    
    STEP 1: DOCUMENTATION VERIFICATION
    - Verify if the text supports the code description.
    - INDEPENDENTLY calculate the 'correct' supported units based on measurements.
    - MATH: If definition says "each additional X cm or part thereof", round up (2.1 = 3).
    
    STEP 2: REIMBURSEMENT RISK ANALYSIS
    - Apply the SYSTEM ALERTS provided above. Use the exact rationale provided in SYSTEM ALERTS.
    - If a code has a SYSTEM ALERT, its 'billing_risk_alert' MUST MATCH calculation.
    
    OUTPUT FORMAT (JSON ONLY):
    Respond strictly in this JSON structure:
    
    {{
        "audit_results": [
            {{
                "code": "CPT Code",
                "documentation_status": "PASS" or "FAIL",
                "clinical_evidence": "Extract query",
                "calculated_units": "Integer (Your independent count supported by text)",
                "billing_risk_alert": "NONE" or "HIGH - MUE EXCEEDED" or "HIGH - NCCI BUNDLING",
                "risk_rationale": "Clear explanation. If Risk exists, use the human-readable explanation from SYSTEM ALERTS."
            }}
        ],
        "documentation_improvement": "Advice string"
    }}
    """
    
    response_text = query_anthropic(prompt, system_prompt)
    if not response_text:
        return {"error": "LLM failed"}
        
    try:
        # Clean up potential markdown code blocks if Claude adds them
        cleaned_text = response_text.replace("```json", "").replace("```", "").strip()
        result_json = json.loads(cleaned_text)
        
        # --- POST-PROCESS: INJECT DETERMINISTIC NCCI/MUE DATA ---
        if "audit_results" in result_json:
            for item in result_json["audit_results"]:
                code = item.get("code")
                user_units = units_map.get(code, 1)
                item["billed_units"] = user_units # Pass back to frontend
                
                # Check Unit Discrepancy
                calc_units = item.get("calculated_units")
                try:
                    calc_val = int(calc_units) if calc_units else 0
                    if calc_val != user_units:
                        # Add a discrepancy alert if risk is currently NONE (or append)
                        disc_msg = f"Unit Discrepancy: Billed {user_units} but Doc supports {calc_val}. "
                        
                        current_risk = item.get("billing_risk_alert", "NONE")
                        if current_risk == "NONE":
                            item["billing_risk_alert"] = "UNIT DISCREPANCY"
                            item["risk_rationale"] = disc_msg + item.get('risk_rationale', '')
                        else:
                            # Prepend to rationale
                            item["risk_rationale"] = disc_msg + item.get('risk_rationale', '')
                            
                except:
                    pass

                # Overwrite/Append NCCI info from DB if exists
                if code in ncci_alerts:
                    details = ncci_alerts[code]
                    
                    # Determine highest priority risk
                    # If MUE exists, it's usually High.
                    # NCCI is also High.
                    
                    # Build consolidated human readable string
                    reasons = []
                    risks = []
                    for d in details:
                        # Use our new human readable helper
                        reasons.append(get_readable_rationale(d))
                        risks.append(d['alert'])

                    # Consolidate Risk Label
                    if any("MUE" in r for r in risks):
                        item["billing_risk_alert"] = "HIGH - MUE EXCEEDED"
                    elif any("NCCI" in r for r in risks):
                        item["billing_risk_alert"] = "HIGH - NCCI BUNDLING"
                    
                    current = item.get("risk_rationale", "")
                    clean_db_rationale = " | ".join(reasons)
                    
                    # Merge Logic:
                    # DB Rationale (The Rules) + LLM Rationale (The Clinical Context)
                    # Avoid duplication if LLM just repeated the rule.
                    
                    combined_rationale = clean_db_rationale
                    
                    if "Unit Discrepancy" in current:
                        # Extract discrepancy part
                        disc_part = current.split("Unit Discrepancy")[1].split(".")[0]
                        combined_rationale = f"Unit Discrepancy{disc_part}. {combined_rationale}"
                        # Remove discrepancy from current to check rest
                        current = current.replace(f"Unit Discrepancy{disc_part}.", "").strip()

                    # Append clinical context if meaningful and short
                    if current and len(current) > 10 and current not in clean_db_rationale:
                        combined_rationale += f"\n[Clinical Note]: {current}"
                        
                    item["risk_rationale"] = combined_rationale

        return result_json
    except json.JSONDecodeError:
        return {"error": "Invalid JSON from LLM", "raw_response": response_text}

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
                 print(f"{'':<10} {'':<12} {'':<6} \033[93m↳ {rationale}\033[0m")

    improvement = result.get("documentation_improvement", "N/A")
    if improvement and improvement != "N/A":
        print("\nDOCUMENTATION IMPROVEMENT:")
        print(improvement)

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



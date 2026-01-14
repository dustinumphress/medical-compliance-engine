import json
import sys

try:
    with open('.tmp/audit_result_latest.json', 'r') as f:
        data = json.load(f)
    
    # Updated to match new schema 'audit_results'
    results = data.get('audit_results', [])
    
    print(f"{'CODE':<10} {'STATUS':<10} {'UNITS':<6} {'RISK':<25}")
    print("-" * 80)
    for res in results:
        code = res.get('code', 'N/A')
        status = res.get('documentation_status', 'N/A')
        units = res.get('calculated_units', 0)
        risk = res.get('billing_risk_alert', 'NONE')[:25]
        rationale = res.get('risk_rationale', '')
        
        print(f"{code:<10} {status:<10} {units:<6} {risk:<25}")
        if risk != "NONE" or "NCCI" in rationale:
            print(f"           ↳ {rationale}")
            
except Exception as e:
    print(f"Error: {e}")

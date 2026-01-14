import json
try:
    with open('.tmp/audit_result_latest.json') as f:
        data = json.load(f)
    print(json.dumps(data, indent=2))
except Exception as e:
    print(e)

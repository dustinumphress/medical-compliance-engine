import json
import glob
import os

# Find the latest debug file
files = glob.glob('.tmp/debug_opportunities_*.json')
latest_file = max(files, key=os.path.getctime)

print(f"Inspecting: {latest_file}")

try:
    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    print(f"Found {len(data)} items.\n")
    for i, item in enumerate(data[:10]): # Show first 10
        print(f"[{i}] TITLE: {item.get('title')}")
        print(f"    REASON: {item.get('reason')}")
        print("-" * 40)
        
except Exception as e:
    print(f"Error: {e}")

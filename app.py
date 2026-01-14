import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'execution'))

from flask import Flask, render_template, request, jsonify
import json
from sanitize_phi import sanitize_text as clean_text_with_presidio
from execution.medical_audit import audit_medical_record, consult_auditor

app = Flask(__name__)

# --- Helper to reconstruct HTML with highlights ---
def highlight_phi(text, entities):
    """
    Reconstructs text with <mark> tags around identified entities.
    """
    if not entities:
        return text
        
    sorted_entities = sorted(entities, key=lambda x: x.start, reverse=True)
    
    working_text = text
    for entity in sorted_entities:
        start = entity.start
        end = entity.end
        label = entity.entity_type
        
        # Insert mark tag
        original_span = working_text[start:end]
        replacement = f'<mark class="phi-match" title="{label}">{original_span}</mark>'
        working_text = working_text[:start] + replacement + working_text[end:]
        
    return working_text

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/sanitize', methods=['POST'])
def sanitize_endpoint():
    data = request.json
    text = data.get('text', '')
    
    sanitized_text, entities = clean_text_with_presidio(text)
    
    return jsonify({
        "original_html": highlight_phi(text, entities),
        "sanitized_text": sanitized_text,
        "is_clean": len(entities) == 0,
        "found_count": len(entities)
    })

@app.route('/audit', methods=['POST'])
def audit_endpoint():
    data = request.json
    raw_text = data.get('text', '')
    cpt_codes = data.get('cpt_codes', [])
    dx_codes = data.get('dx_codes', [])
    
    # Extract codes if they came as objects
    cpt_list = []
    units_map = {}
    
    for item in cpt_codes:
        if isinstance(item, dict):
            code = item.get('code')
            units = item.get('user_units', 1)
            cpt_list.append(code)
            units_map[code] = int(units)
        else:
            cpt_list.append(item)
            units_map[item] = 1

    if not raw_text or not cpt_list:
        return jsonify({"error": "Missing text or CPT codes"}), 400
        
    try:
        result = audit_medical_record(raw_text, cpt_list, dx_codes, units_map=units_map)
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Audit failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/chat', methods=['POST'])
def chat_endpoint():
    data = request.json
    context = data.get('context', '')
    results = data.get('audit_results', {})
    question = data.get('question', '')
    
    if not question:
         return jsonify({"error": "No question provided"}), 400
         
    response = consult_auditor(context, results, question)
    return jsonify(response)

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)

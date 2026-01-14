import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'execution'))

from flask import Flask, render_template, request, jsonify
import json
# Now we can import directly as if we were in execution/
from sanitize_phi import sanitize_text as clean_text_with_presidio
from medical_audit import audit_medical_record

app = Flask(__name__)

# --- Helper to reconstruct HTML with highlights ---
def highlight_phi(text, entities):
    """
    Reconstructs text with <mark> tags around identified entities.
    Entities list contains objects with 'start', 'end', 'entity_type'.
    """
    if not entities:
        return text
        
    # Sort entities by start position (descending) to replace from end
    # avoiding index shift issues. TODO: Handle overlaps if necessary.
    # Presidio usually handles non-overlapping or we take the first one.
    
    # Presidio entities in `results` list are objects. Need to access attributes.
    # The `sanitize_text` function returns (text, results).
    # results is a list of RecognizerResult.
    
    sorted_entities = sorted(entities, key=lambda x: x.start, reverse=True)
    
    # We need to act on the *original* text passed in, 
    # but sanitize_text returns the clean text + entities found in original.
    # So we used the original text.
    
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
    
    # Run Presidio
    # sanitize_text returns: (cleaned_string, list_of_entities)
    sanitized_text, entities = clean_text_with_presidio(text)
    
    # Convert entity objects to simple dicts for JSON
    entity_list = []
    for e in entities:
        entity_list.append({
            "start": e.start,
            "end": e.end,
            "entity_type": e.entity_type,
            "score": e.score
        })
        
    # Generate properties
    original_html = highlight_phi(text, entities)
    is_clean = len(entities) == 0
    
    return jsonify({
        "original_html": original_html,
        "sanitized_text": sanitized_text,
        "is_clean": is_clean,
        "found_count": len(entities)
    })

@app.route('/audit', methods=['POST'])
def audit_endpoint():
    data = request.json
    sanitized_text = data.get('text', '')
    cpt_codes = data.get('cpt_codes', [])
    dx_codes = data.get('dx_codes', [])
    
    # Filter empty codes
    # cpt_codes might be list of strings (legacy) or list of objects (new)
    processed_cpts = []
    
    if cpt_codes and isinstance(cpt_codes[0], dict):
        processed_cpts = [c for c in cpt_codes if c.get('code', '').strip()]
    else:
        # Legacy string support
        processed_cpts = [{'code': c.strip(), 'user_units': 1} for c in cpt_codes if c.strip()]
    
    dx_codes = [d for d in dx_codes if d.strip()]
    
    if not sanitized_text:
        return jsonify({"error": "No text provided"}), 400
        
    # Run the Audit
    # audit_medical_record(text, cpt_list_of_dicts, dx_list)
    try:
        result = audit_medical_record(sanitized_text, processed_cpts, dx_codes)
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Audit Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Use environment variables for configuration (Docker-friendly)
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'execution'))

from flask import Flask, render_template, request, jsonify, send_from_directory
import json
from sanitize_phi import sanitize_text as clean_text_with_presidio
from execution.medical_audit import audit_medical_record, consult_auditor, list_available_models, generate_appeal

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

def highlight_sanitized_replacements(text):
    """
    Wraps <TAGS> in mark elements for Better UI visibility in the sanitized view.
    """
    import re
    # Regex to find <PERSON>, <DATE>, etc.
    # We want to wrap them in <mark class="phi-replacement">
    return re.sub(r'(<[^>]+>)', r'<mark class="phi-replacement">\1</mark>', text)

from execution.demo_data import SCENARIOS

# Demo Mode Configuration
DEMO_MODE = os.getenv("DEMO_MODE", "False").lower() == "true"

@app.route('/')
def home():
    return render_template('index.html', demo_mode=DEMO_MODE)

@app.route('/guide')
def user_guide():
    return send_from_directory(os.path.join(app.root_path, 'docs'), 'user_guide.html')

@app.route('/models', methods=['GET'])
def models_endpoint():
    """Live model list for the UI picker (queried from the provider, cached)."""
    try:
        return jsonify(list_available_models())
    except Exception as e:
        app.logger.error(f"Model list failed: {e}")
        return jsonify([]), 500

@app.route('/get_scenarios', methods=['GET'])
def get_scenarios():
    if not DEMO_MODE:
        return jsonify({})
    return jsonify(SCENARIOS)

@app.route('/sanitize', methods=['POST'])
def sanitize_endpoint():
    data = request.json
    text = data.get('text', '')

    if DEMO_MODE:
        # Prevent custom input in Demo Mode
        # Only allow text that matches one of the scenarios
        allowed_texts = [s['text'] for s in SCENARIOS.values()]
        if text not in allowed_texts:
             return jsonify({
                "original_html": "<b>Custom input disabled in Demo Mode.</b>",
                "sanitized_text": text, # Assume pre-sanitized
                "is_clean": True,
                "found_count": 0
            })

    sanitized_text, entities = clean_text_with_presidio(text)

    # Highlight the replacements in the "Sanitized View"
    sanitized_html = highlight_sanitized_replacements(sanitized_text)

    return jsonify({
        "original_html": highlight_phi(text, entities),
        "sanitized_text": sanitized_text, # Keep raw for editing/pipeline
        "sanitized_html": sanitized_html, # New field for UI display
        "is_clean": len(entities) == 0,
        "found_count": len(entities)
    })

@app.route('/transcribe/warm', methods=['POST'])
def transcribe_warm_endpoint():
    """Fire-and-forget model preload, called when the UI opens."""
    if DEMO_MODE:
        return jsonify({"ok": False}), 403
    import threading
    from execution.transcribe_image import warm_model
    threading.Thread(target=warm_model, daemon=True).start()
    return jsonify({"ok": True})

@app.route('/transcribe', methods=['POST'])
def transcribe_endpoint():
    """
    Transcribe pasted op-report images to text using the LOCAL vision model
    (Ollama). Images never leave this machine; the returned text still goes
    through the normal /sanitize step before any cloud LLM call.
    Body: {"images": ["<base64>", ...]}
    """
    if DEMO_MODE:
        return jsonify({"error": "Image transcription is disabled in Demo Mode."}), 403

    from execution.transcribe_image import transcribe_images, is_available, OLLAMA_VISION_MODEL

    data = request.json
    images = data.get('images', [])
    if not images:
        return jsonify({"error": "No images provided"}), 400
    if len(images) > 4:
        return jsonify({"error": "Maximum 4 images per transcription"}), 400

    if not is_available():
        return jsonify({"error": f"Local vision model unavailable. Is Ollama running with '{OLLAMA_VISION_MODEL}' pulled? (ollama pull {OLLAMA_VISION_MODEL})"}), 503

    try:
        text = transcribe_images(images)
        return jsonify({"text": text})
    except Exception as e:
        app.logger.error(f"Transcription failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/audit', methods=['POST'])
def audit_endpoint():
    data = request.json
    raw_text = data.get('text', '')
    cpt_codes = data.get('cpt_codes', [])
    dx_codes = data.get('dx_codes', [])
    model = data.get('model') or None

    # Extract codes if they came as objects
    cpt_list = []
    units_map = {}
    modifiers_map = {}

    for item in cpt_codes:
        if isinstance(item, dict):
            code = item.get('code')
            units = item.get('user_units', 1)
            cpt_list.append(code)
            units_map[code] = int(units)
            # Modifiers are optional — empty/missing is a normal, valid claim
            raw_mods = item.get('modifiers', '') or ''
            mods = [m.strip().upper() for m in raw_mods.replace(';', ',').split(',') if m.strip()]
            if mods:
                modifiers_map[code] = mods
        else:
            cpt_list.append(item)
            units_map[item] = 1

    if not raw_text or not cpt_list:
        return jsonify({"error": "Missing text or CPT codes"}), 400

    try:
        result = audit_medical_record(raw_text, cpt_list, dx_codes, units_map=units_map, model=model, modifiers_map=modifiers_map)
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Audit failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/appeal', methods=['POST'])
def appeal_endpoint():
    data = request.json
    context = data.get('context', '')
    results = data.get('audit_results', {})
    focus_code = data.get('code') or None
    denial_reason = data.get('denial_reason', '')

    if not context:
        return jsonify({"error": "No operative report context provided"}), 400

    if DEMO_MODE:
        return jsonify({"error": "Appeal generation is disabled in Demo Mode."}), 403

    response = generate_appeal(context, results, focus_code=focus_code,
                               denial_reason=denial_reason,
                               model=data.get('model') or None)
    return jsonify(response)

@app.route('/chat', methods=['POST'])
def chat_endpoint():
    data = request.json
    context = data.get('context', '')
    results = data.get('audit_results', {})
    question = data.get('question', '')

    if not question:
         return jsonify({"error": "No question provided"}), 400

    if DEMO_MODE:
        # Cost-Saving Measure: Demo Mode uses canned answers ONLY.
        # We do NOT hit the LLM API to prevent bot spam/billing.
        canned_answer = None

        # Check all scenarios for a matching question
        for scenario in SCENARIOS.values():
            if question in scenario.get("chat_answers", {}):
                canned_answer = scenario["chat_answers"][question]
                break

        if canned_answer:
            return jsonify({"answer": canned_answer})
        else:
            return jsonify({"answer": "I am running in Demo Mode to prevent API abuse. Please select one of the suggested questions above."})

    response = consult_auditor(context, results, question,
                               model=data.get('model') or None,
                               history=data.get('history') or [])
    return jsonify(response)

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)

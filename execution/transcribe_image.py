"""
Local image-to-text transcription for op report screenshots.

Uses a local vision LLM served by Ollama (default: qwen2.5vl:7b) so that
PHI-bearing images never leave the machine. The transcribed text is then
fed through the normal Presidio sanitization pipeline before any cloud
LLM sees it.

Requires: Ollama running locally with the vision model pulled
    ollama pull qwen2.5vl:7b
"""
import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:7b")

TRANSCRIBE_PROMPT = (
    "Transcribe ALL text visible in this document image, exactly as written. "
    "Preserve the original structure: headings, line breaks, and section labels. "
    "Do not summarize, interpret, correct, or omit anything. "
    "If a word is illegible, write [illegible]. "
    "Output only the transcribed text with no commentary."
)


def is_available():
    """True if Ollama is reachable and the vision model is pulled."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        resp.raise_for_status()
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        base = OLLAMA_VISION_MODEL.split(":")[0]
        return any(m == OLLAMA_VISION_MODEL or m.startswith(base + ":") for m in models)
    except Exception:
        return False


def transcribe_images(images_b64):
    """
    Transcribe a list of base64-encoded images (data-URL prefix stripped)
    into plain text. Each image is transcribed in its own call — small
    vision models are noticeably more accurate one page at a time.

    Returns the joined transcription. Raises on connection/model errors.
    """
    pages = []
    for i, img in enumerate(images_b64):
        logger.info(f"Transcribing image {i + 1}/{len(images_b64)} with {OLLAMA_VISION_MODEL}")
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_VISION_MODEL,
                "messages": [{
                    "role": "user",
                    "content": TRANSCRIBE_PROMPT,
                    "images": [img],
                }],
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=300,  # first call loads the model into VRAM, which is slow
        )
        resp.raise_for_status()
        pages.append(resp.json()["message"]["content"].strip())

    return "\n\n".join(pages)

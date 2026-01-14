"""
Sanitize PHI from medical text using Microsoft Presidio.
Run locally to ensure privacy before sending data to LLMs.
"""
import sys
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# Initialize engines
# Note: This requires 'en_core_web_lg' to be installed.
try:
    analyzer = AnalyzerEngine()
    
    # --- ADD THIS SECTION AFTER INITIALIZING 'analyzer' ---

    # 1. Custom MRN Recognizer (Regex)
    mrn_pattern = Pattern(name="mrn_pattern", regex=r"(?i)\b(mrn|acct|account|visit|pat|id)\s*#?[:\.-]?\s*([0-9\-]+)", score=1.0)
    mrn_recognizer = PatternRecognizer(supported_entity="MEDICAL_RECORD_NUMBER", patterns=[mrn_pattern])
    analyzer.registry.add_recognizer(mrn_recognizer)

    # 2. Custom Patient Name Recognizer (Contextual Regex)
    # Catches "PATIENT NAME: LAST, FIRST" or "PATIENT: NAME"
    # We capture the value group.
    pat_name_pattern = Pattern(name="pat_name_pattern", regex=r"(?i)(?:patient\s+name|patient)\s*[:\.-]\s*([A-Za-z,\s]+?)(?:\s{2,}|\n|$)", score=0.9)
    pat_name_recognizer = PatternRecognizer(supported_entity="PATIENT_NAME_HEADER", patterns=[pat_name_pattern])
    analyzer.registry.add_recognizer(pat_name_recognizer)

    # --- END ADDITION ---

    anonymizer = AnonymizerEngine()
except Exception as e:
    print(f"Error initializing Presidio: {e}")
    print("Ensure you have run: python -m spacy download en_core_web_lg")
    sys.exit(1)

def sanitize_text(text):
    """
    Analyze and anonymize PHI in the given text.
    Returns:
        sanitized_text (str): The text with PHI replaced by placeholders.
        results (list): List of redacted entities (for debug/verification).
    """
    if not text:
        return "", []

    # Analyze
    # We look for common PHI entities.
    results = analyzer.analyze(text=text,
                               language='en',
                               entities=[
                                   "PERSON", 
                                   "PHONE_NUMBER", 
                                   "EMAIL_ADDRESS", 
                                   "US_SSN", 
                                   "US_PASSPORT",
                                   "US_DRIVER_LICENSE",
                                   "LOCATION",
                                   "DATE_TIME",
                                   "MEDICAL_LICENSE",
                                   "MEDICAL_RECORD_NUMBER",
                                   "PATIENT_NAME_HEADER"
                               ])
    
    # Filter for reasonable score
    # Presidio sometimes has low confidence FP
    results = [r for r in results if r.score >= 0.4]

    # Anonymize
    # Replace with <ENTITY_TYPE>
    operators = {
        "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
        "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<PHONE>"}),
        "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<EMAIL>"}),
        "DATE_TIME": OperatorConfig("replace", {"new_value": "<DATE>"}),
        "LOCATION": OperatorConfig("replace", {"new_value": "<LOC>"}),
        "MEDICAL_RECORD_NUMBER": OperatorConfig("replace", {"new_value": "<MRN>"}),
        "PATIENT_NAME_HEADER": OperatorConfig("replace", {"new_value": "<PATIENT_NAME>"})
    }
    anonymized_result = anonymizer.anonymize(
        text=text,
        analyzer_results=results,
        operators=operators
    )
    
    return anonymized_result.text, results

if __name__ == "__main__":
    # Test run
    test_text = "Patient John Doe (DOB 05/12/1980) visited Dr. Smith at 123 Main St, Springfield on 2023-01-01."
    print(f"Original: {test_text}")
    clean, entities = sanitize_text(test_text)
    print(f"Sanitized: {clean}")

import pytest
from sanitize_phi import sanitize_text

def test_no_phi():
    text = "The patient had a mild cough."
    sanitized, entities = sanitize_text(text)
    assert sanitized == text
    assert len(entities) == 0

def test_mrn_redaction():
    text = "Patient has MRN: 123456."
    sanitized, entities = sanitize_text(text)
    assert "<MRN>" in sanitized
    assert "123456" not in sanitized

def test_date_redaction():
    text = "Surgery date was 01/01/2023."
    sanitized, entities = sanitize_text(text)
    assert "<DATE>" in sanitized
    assert "01/01/2023" not in sanitized

def test_name_redaction():
    text = "Dr. John Smith performed the exam."
    sanitized, entities = sanitize_text(text)
    # Presidio name recognition can be variable, but "John Smith" is standard
    assert "<PERSON>" in sanitized or "<PATIENT_NAME>" in sanitized
    assert "John Smith" not in sanitized

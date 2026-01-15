"""
Demo Scenarios for the AWS Hosted Version.
Contains 3 fixed plastic surgery scenarios and canned chat questions.
"""

SCENARIOS = {
    "scenario_1": {
        "title": "Scenario 1: Procedure Code Denial (14301)",
        "description": "Complex reconstruction of forehead defect. CPT 14301 is likely to be flagged for missing defect measurements.",
        "text": """OPERATIVE REPORT
PATIENT: John Doe
MRN: 123-456-789
DOB: 01/01/1980
PREOPERATIVE DIAGNOSIS: Basal cell carcinoma, forehead.
POSTOPERATIVE DIAGNOSIS: Same.
PROCEDURE: Adjacent tissue transfer / rearrangement, forehead, defect size 12.0 sq cm.

INDICATIONS: 65-year-old male with biopsy-proven BCC of the forehead.

DESCRIPTION:
The patient was prepped and draped. The lesion was excised with margins. Frozen sections confirmed clear margins.
To close the defect, a large rotational flap was designed. The flap was elevated in the subcutaneous plane. 
The flap was rotated into the defect. The secondary defect was closed primarily.
Critically, distinct undermining was performed to facilitate closure.
Total primary defect size: 3.0 cm x 4.0 cm.
The flap was sutured with 5-0 Vicryl and 6-0 Prolene.
The wound was dressed. Patient tolerated the procedure well.
""",
        "cpt": [{"code": "14301", "user_units": 1}, {"code": "11642", "user_units": 1}],
        "dx": ["C44.319", "Z42.8"],
        "chat_questions": [
            "Why was CPT 14301 flagged as a risk?",
            "What measurements are missing for the adjacent tissue transfer?"
        ],
        "chat_answers": {
            "Why was CPT 14301 flagged as a risk?": "CPT 14301 is a high-value code (Adjacent Tissue Transfer > 30 sq cm). The documentation states a primary defect of 12.0 sq cm, but does not clearly document the *secondary* defect or total flap size to justify the >30 sq cm threshold requirement for 14301.",
            "What measurements are missing for the adjacent tissue transfer?": "To bill 14301, the total area (primary defect + secondary defect/flap) must be greater than 30 sq cm. The report provides the primary defect (12 sq cm) but fails to state the final dimensions of the flap."
        }
    },

    "scenario_2": {
        "title": "Scenario 2: Diagnosis Specificity Error",
        "description": "Reconstruction of cheek defect. Diagnosis codes are too vague (Unspecified) and likely to trigger a 'Medical Necessity' denial.",
        "text": """OPERATIVE REPORT
PATIENT: Sarah Smith
MRN: 987-654-321
PROCEDURE: Reconstruction of cheek defect using extensive undermining and advancement flap.

DESCRIPTION:
After excision of the skin cancer on the left cheek, the resulting defect measured 2.5 cm x 3.0 cm.
We proceeded with an advancement flap closure.
Undermining was performed significantly beyond the defect margins to release tension.
The flap was advanced and sutured in layers.
Hemostasis was achieved.
""",
        "cpt": [{"code": "14040", "user_units": 1}],
        "dx": ["C44.90", "D49.2"], # Unspecified site (C44.90) and Unspecified Neoplasm (D49.2) = BAD
        "chat_questions": [
            "Which diagnosis codes are considered 'Unspecified'?",
            "How can I improve the diagnosis specificity?"
        ],
        "chat_answers": {
            "Which diagnosis codes are considered 'Unspecified'?": "Both C44.90 (Malignant neoplasm of skin, unspecified) and D49.2 (Neoplasm of unspecified behavior of bone/soft tissue) are non-specific. Payers usually require laterality (Left/Right) and specific anatomic location.",
            "How can I improve the diagnosis specificity?": "You should use a code that specifies the location, such as C44.319 (Basal cell carcinoma of skin of other parts of face) or similar, depending on pathology. 'Cheek' often maps to 'Face' or specific sub-sites.",
        }
    },

    "scenario_3": {
        "title": "Scenario 3: Clean Audit (Pass)",
        "description": "Complex closure of nose defect. Documentation is perfect including defect sizes and medical necessity.",
        "text": """OPERATIVE REPORT
PATIENT: Robert Johnson
DOB: 05/12/1955
PREOP DX: Squamous Cell Carcinoma, Right Alar Rim.
PROCEDURE: Adjacent tissue transfer (14060).

DESCRIPTION:
Excised SCC from right alar rim. Defect size 0.8 cm x 1.2 cm (Total 0.96 sq cm).
Due to location on the alar rim, primary closure was not possible without distortion.
A rhomboid flap was designed and elevated.
The flap measured 1.2 sq cm. Total excised area including flap donor site: 2.16 sq cm.
The flap was transposed into the defect.
Undermining of the base was performed to limit tension.
Closure achieved with good cosmetic result.
""",
        "cpt": [{"code": "14060", "user_units": 1}],
        "dx": ["C44.321"], # Specific: SCC skin of right ala nasi
        "chat_questions": [
            "Does the defect size calculation match the code selection?",
            "Is the medical necessity for a flap vs graft supported?"
        ],
        "chat_answers": {
            "Does the defect size calculation match the code selection?": "Yes. CPT 14060 covers Adjacent Tissue Transfer for E/N/E/L up to 10 sq cm. The total excised area (defect + secondary) is 2.16 sq cm, which is correctly captured by 14060.",
            "Is the medical necessity for a flap vs graft supported?": "Yes. The report notes the defect was on the 'alar rim' where 'primary closure was not possible without distortion'. This functional/cosmetic indication supports the use of a flap over simpler closure methods."
        }
    }
}

# Common CPT Definitions for Medical Audit
# In a real production system, this would be a database table.

CPT_DEFINITIONS = {
    "12001": "Simple repair of superficial wounds of scalp, neck, axillae, external genitalia, trunk and/or extremities (including hands and feet); 2.5 cm or less.",
    "99291": "Critical care, evaluation and management of the critically ill or critically injured patient; first 30-74 minutes. REQUIRES: Documentation of total critical care time.",
    "15738": "Muscle, myocutaneous, or fasciocutaneous flap; lower extremity. REQUIRES: 1. Identification of specific NAMED muscle (e.g. Soleus, Gastrocnemius). 2. Evidence of mobilization/rotation of the muscle (not just skin). 3. Separate from standard closure.",
    "14301": "Adjacent tissue transfer or rearrangement, any area; defect 30.1 sq cm to 60.0 sq cm. RULE: This is the BASE CODE for any defect >= 30.1 sq cm. If defect > 60, this code still PASSES as the prerequisite for 14302.",
    "14302": "Adjacent tissue transfer, any area; each additional 30.0 sq cm. RULE: Use with 14301. Total Defect Area must be > 60 sq cm. Count 1 unit of this code for every 30 sq cm beyond the initial 60.",
    "19361": "Breast reconstruction with latissimus dorsi flap. REQUIRES: Harvest of latissimus dorsi muscle and transfer to breast area with blood supply.",
    "19371": "Periprosthetic capsulectomy, breast. REQUIRES: Removal of capsule lining around a breast implant. Distinct from simple capsulotomy (incision only).", 
    "19357": "Breast reconstruction, immediate or delayed, with tissue expander, including subsequent expansion. REQUIRES: Placement of tissue expander.",
    "15733": "Muscle, myocutaneous, or fasciocutaneous flap; head and neck with named vascular pedicle. REQUIRES: Identification of named vascular pedicle.",
    "15734": "Muscle, myocutaneous, or fasciocutaneous flap; trunk. REQUIRES: Transfer of muscle/skin from trunk to defect. Must be an axial pattern flap, not random.",
    "S2068": "Breast reconstruction with deep inferior epigastric perforator (DIEP) flap or superficial inferior epigastric artery (SIEA) flap, including harvesting of the flap, microvascular transfer, closure of donor site and shaping the flap into a breast, unilateral. REQUIRES: DIEP or SIEA flap specifics.",
    "19342": "Insertion or replacement of breast implant on separate day from mastectomy. REQUIRES: Delayed insertion/replacement, not immediate.",
    "13121": "Repair, complex, scalp, arms, and/or legs; 2.6 cm to 7.5 cm. RULE: SUM the lengths of all complex repairs in this anatomical group. If Total Length is between 2.6 and 7.5 (inclusive), this code PASSES.",
    "13122": "Repair, complex, scalp, arms, and/or legs; each additional 5 cm or less. RULE: Add-on code. Use if Total Length > 7.5 cm."
}

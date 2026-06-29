# Failure Mode Taxonomy

## Level 1: Resource & Contextual Adaptation Failures
*The most frequent category*

These failures occur when the AI model fails to adapt its clinical plan to the specific resource constraints of the setting described in the vignette 

### 1.1. Failure to Recognize Resource Limitations 

**Definition:** The model suggests a test, drug, or procedure that is almost certainly unavailable in the stated setting.

**Examples:**
- C - piperacillin-tazobactam and insulin unavailable at PHC (R0230, M03)
- C - anti-venom is unlikely to be available in a PHC (R0080, M15; R0239, M15)
- C - non rebreather mask might be unavailable (R0217, M02)
- C - abg, other investigations, insulin not available (R0325, M14)
- C - investigations not all available (R0047, M20; R0286, M20)
- C - morphine might be unavailable at PHC (R0062, S03)

### 1.2. Failure to Suggest Appropriate Referral 

**Definition:** The model fails to recognize that the patient's condition exceeds the capacity of the current facility and fails to recommend timely and urgent referral to a higher level of care.

**Examples:**
- C - refer immediately (R0170, M08)
- O - earlier referral (R0079, M13)
- O - immediate referral will enable positive outcomes (R0513, M23)
- C - did not refer patient to higher facility for delivery (R0294, O03; R0382, O03)
- C - noone in a PHC can intubate (R0475, S08)
- C - sent patient home to return for follow-up (R0302, O12)

### 1.3. Failure to Adapt Treatment for Context 

**Definition:** The model suggests a first-line treatment that is not feasible (e.g. requiring ICU-level monitoring) without providing a more practical alternative for the setting.

**Examples:**
- O - there might not be O2 in PHC. No alternative provided. (R0019, P08)
- C - oxygen unavailable (R0163, P07)
- O - no idea to refer, this patient would probably die (R0471, O02)
- C - sent patient home to return for follow-up (R0302, O12) (Failure to refer/emergency manage)
- C - autologous options are not available (R0456, O04) (Failure to consider alternatives to blood transfusion)

---

## Level 2: Clinical Content Failures

These failures relate to the medical accuracy and completeness of the clinical reasoning, independent of context.

### 2.1. Omission of Key Guideline-Recommended Steps (Omission)

**Definition:** The response misses a crucial diagnostic or therapeutic step considered standard of care for the condition.

**Examples:**
- O - no blood culture (R0135, M18)
- O - did not position patient (R0191, M02; R0372, M02)
- O - no uterine massage (R0007, O01)
- O - no mention of EBT and the formula for calculating mgt choice (R0066, P04; R0115, P04)
- O - does not mention ampi and gent as the combination of choice, no phenobarb prophylaxis (R0075, P03; R0185, P03; R0238, P03; R0704, P03; R0719, P03; R0814, P03; R0849, P03)
- O - NO TB screen (R0017, M17; R0111, M17; R0203, M17; R0251, M17; R0259, M17)
- O - no furosemide (R0096, P08; R0859, P08)
- O - no paracentesis (R0141, M13)

### 2.2. Incorrect Diagnosis or Clinical Reasoning (Commission)

**Definition:** The AI arrives at the wrong primary diagnosis, fails to consider important differentials, or makes a dangerous clinical judgment call.

**Examples:**
- C - wrong diagnosis and mgt (R0209, M16)
- C - pneumonia in heart failure should be primary dx (R0097, P08) (Failure to identify the more immediate threat)
- C - Fail to consider sickle cell disease diagnosis (R0337, O07)
- C - why admit (R0091, S05) 
- C - Failed to diagnose potts TB or even list as differential; no TB tests requested (R0209, M16; R0446, M16)

### 2.3. Errors in Drug, Dose, or Route (Commission/Omission)

**Definition:** The model recommends the wrong medication, an incorrect dosage, or the wrong route of administration, often leading to a safety or efficacy issue.

**Examples:**
- C - artesunate dose is not right for this child (R0092, P09; R0113, P09; R0672, P09; R0728, P09; R0753, P09) (Dose error)
- C - morphine no longer routinely indicated (R0149, M02)
- C - gent is 5mg/kg in 2 divided doses, oxygen is not present (R0019, P08) 
- C - giving fluid in heart failure (R0154, P08; R0729, P08; R0868, P08)
- C - giving 2.4mg/kg of artesunate without confirming weight (R0216, P09) 
- C - Did not dilute glucose (R0078, M07; R0153, M07; R0160, M07; R0307, M07; R0522, M07; R0564, M07) 
- O - no inotropic support (R0156, M03) 

---

## Level 3: Procedural & Practical Failures

These failures involve the specific steps of managing a condition or performing a procedure.

### 3.1. Incorrect or Missing Procedural Detail (Omission/Commission)

**Definition:** The model fails to specify or incorrectly describes the technique for a procedure.

**Examples:**
- O - landmark for chest tube insertion not stated (R0055, S04)
- O - proper tourniquet removal technique not described (R0080, M15)
- C - tourniquet is removed gradually (R0080, M15; R0168, M15; R0240, M15)
- O - 2 wide bore IV cannula, speculum examination and clot evacuation would determine if MVA needed (R0453, O08)

### 3.2. Failure to Suggest Diagnostic/Investigative Steps (Omission)

**Definition:** The model does not recommend appropriate investigations to confirm a diagnosis or rule out critical conditions.

**Examples:**
- O - no EEG request, no RBS, electrolytes, or sepsis workup (R0128, M10)
- O - no antiemetic, no mannitol (R0254, S08)
- O - no investigations (R0541, M03; R0569, M03)
- O - no chest x-ray requested for differentials (R0085, M01)
- O - wound swab m/c/s (R0460, P16; R0656, P16; R0659, P16; R0686, P16)

---

## Level 4: Contextual & Situational Awareness Failures

This is a distinct category where the model fails to "read the room" regarding the specific clinical scenario (e.g., obstetric emergency) or the implied training level of the staff.

### 4.1. Failure to Recognize Severity (Omission)

**Definition:** The model underestimates the urgency of a situation or fails to activate necessary protocols.

**Examples:**
- C - No urgency, no isolation, no VHF protocol initiated (R0229, M09)
- O - you want to refer in the absence of anti-venom not wait for signs of envenomation (R0168, M15)
- C - stabilize and refer immediately! (R0303, M15)
- O - recognise and preemptive mgt for inhalation injury (R0595, S03; R0466, S03)

### 4.2. Failure to Include Alternative Plans (Omission)

**Definition:** The model fails to provide a "Plan B" when the primary treatment is unavailable, which is critical in low-resource settings.

**Examples:**
- C - autologous options are not available (R0456, O04) 
- O - epinephrine more available (R0826, S06) (Failing to suggest the more available drug)
- O - alternative while awaiting referral can be tepid sponging (R0459, P08)

---

## Level 5: Documentation and Communication Failures

These failures relate to the clarity, completeness, or safety of the clinical instructions.

### 5.1. Vague or Non-Specific Recommendations (Omission)

**Definition:** The model's instructions are too general to be safely actioned, lacking crucial details like doses, volumes, or timelines.

**Examples:**
- O - is non specific about mgt (R0001, P09)
- O - no specific doses, which fluid and how much (R0119, P09)
- O - vagues about drugs route and dose (R0231, P09; R0799, P09)
- O - can be more detailed about the actions eg doses, reassessment times (R0733, P01)

### 5.2. Dangerous or Contraindicated Instructions (Commission)

**Definition:** The model recommends an action that is harmful to the patient.

**Examples:**
- C - gives fluid in hf (R0868, P08; R0014, P08)
- C - Why mention labetalol. Will crash BP (R0010, M11)
- C - initiate anticoagulation before CT scan?? (R0232, M11)

---

## Quantitative Summary of Failure Modes

| Failure Mode | Count | Percentage (Approx.) |
|--------------|-------|----------------------|
| Commission (C) | 91 | 38.1% |
| Omission (O) | 64 | 26.8% |
| Mixed (O, C) | 84 | 35.1% |
| **Total** | **239** | **100%** |



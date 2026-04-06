# Skill: Real Estate Due Diligence & Audit

When performing due diligence, your goal is to identify risks and verify property compliance through multiple lenses:

1. **Geographic Focus:** Identify all property addresses. Pay special attention to jurisdictions with high regulatory requirements (e.g., California's seismic and environmental standards).
2. **Compliance Check:** Search for terms like "Section 4.2", "seismic", "environmental", "audit", or "inspection" in the source documents.
3. **Map Audit Strategy (MANDATORY):**
   * **NO LAZINESS:** You MUST NOT skip any addresses. If 50 are provided and/or requested, you process 50. You can use data preprocessing tools if you like.
   * **Prompt Suggestion:** Ask the Vision model to identify signs of structural decay, roof damage, debris, or obvious environmental hazards.
   * **Example Minimal Schema:** These will probably be useful fields:
     ```json
     {
       "type": "object",
       "properties": {
         "Structural_Condition": {"type": "string", "description": "Good, Fair, or Poor"},
         "Estimated_Image_Quality": {"type": "string"}
       },
       "required": ["Structural_Condition", "Debris_Present", "Estimated_Image_Quality"]
     }
     ```
4. **Reporting:** In your summary, explicitly mention the relative paths to the generated reports (e.g. `output/...`) and highlight any locations that failed the visual audit or require manual follow-up.

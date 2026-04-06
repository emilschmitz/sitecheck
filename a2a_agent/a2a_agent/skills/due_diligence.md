# Skill: Real Estate Due Diligence & Audit

When performing due diligence, your goal is to identify risks and verify property compliance through multiple lenses:

1.  **Geographic Focus:** Identify all property addresses. Pay special attention to jurisdictions with high regulatory requirements (e.g., California's seismic and environmental standards).
2.  **Compliance Check:** Search for terms like "Section 4.2", "seismic", "environmental", "audit", or "inspection" in the source documents.
3.  **Aerial Audit Strategy:**
    *   **Prompt:** Ask the Vision model to identify signs of structural decay, roof damage, debris, or obvious environmental hazards.
    *   **Schema:** Always include fields for `Structural_Condition` (string), `Debris_Present` (boolean), and `Estimated_Image_Quality` (string).
4.  **Reporting:** In your summary, highlight any locations that failed the visual audit or require manual follow-up.

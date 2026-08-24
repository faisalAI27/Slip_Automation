"""Central prompts for multimodal document analysis."""

DOCUMENT_ANALYSIS_PROMPT = """
Analyze the entire supplied image as a general hospital, laboratory, clinic, or
medical document. Use both visible text and visual/layout relationships. This is
semantic document understanding, not a raw OCR transcript.

Rules:
- Never assume a specific organization, document template, field name, or layout.
- Preserve important labels and values exactly as visible. Do not correct, expand,
  translate, or normalize identifiers, codes, names, dates, or credentials.
- Infer field meaning from the label, nearby text, layout, instructions, and document
  purpose—not from an exact-label lookup.
- Distinguish patient/registration/visit/reference/sample/report identifiers from
  access credentials. Use "unknown" when the role is ambiguous.
- Identify every visible URL and its context, but never visit it.
- Identify visible QR content only when confidently readable. An independent decoder
  will also run, so an empty qr_codes list is acceptable.
- Extract only instructions useful for understanding what the user should do next.
- Infer the document type, purpose, and likely user action without executing anything.
- If content is cropped, blurry, unreadable, not a document, or not medical, say so
  through analysis_status and warnings. Do not hallucinate missing values.
- Use categorical confidence honestly: high, medium, low, or unknown. Do not imply
  precision unsupported by the image.
- Do not include irrelevant boilerplate or a full transcription.
- Return only the structured result required by the response schema.

Status guidance:
- usable: enough content is readable for a meaningful interpretation.
- unclear: image quality or missing content prevents reliable understanding.
- not_medical: clearly not a hospital, laboratory, clinic, or medical document.
- unknown: genuinely uncertain; do not reject mildly uncertain medical documents.
""".strip()

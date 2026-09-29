"""Stage -1 OCR layer (§26, P5) — value-add, never a dependency, exactly like
backend.services.llm. Nothing in extraction/comparison/session_store *requires*
this package to import cleanly to work: `get_ocr_provider()` returning None
(no API key configured) must leave the pipeline's existing "detect scanned
pages, warn, never OCR them" behavior completely unchanged.
"""

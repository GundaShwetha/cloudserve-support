"""CloudServe support triage and grounded-answer system.

Components (in pipeline order): ingest -> classify -> retrieve -> route -> generate -> validate.
Cross-cutting: decision logging (logging_store), monitoring (monitoring), governance (guardrails, kill switch).
"""

__version__ = "1.0.0"

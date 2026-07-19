"""Deterministic preparation and validation for IDE-agent topic synthesis.

Exports are lazy so the lifecycle model can reuse evidence value objects without
creating an analyze-importer/lifecycle import cycle.
"""

__all__ = ["import_topics", "prepare_week"]


def __getattr__(name: str):
    if name == "import_topics":
        from server.discovery.analyze.importer import import_topics
        return import_topics
    if name == "prepare_week":
        from server.discovery.analyze.prepare import prepare_week
        return prepare_week
    raise AttributeError(name)

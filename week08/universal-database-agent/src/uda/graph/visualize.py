"""Render the compiled graph as Mermaid text."""

from __future__ import annotations

from typing import Any


def render_mermaid(compiled_graph: Any) -> str:
    """Return a Mermaid diagram for the compiled LangGraph graph."""

    drawing = compiled_graph.get_graph()
    renderer = getattr(drawing, "draw_mermaid", None)
    if renderer is None:  # pragma: no cover - LangGraph API guard
        raise RuntimeError("This LangGraph version does not support Mermaid rendering.")
    return str(renderer())

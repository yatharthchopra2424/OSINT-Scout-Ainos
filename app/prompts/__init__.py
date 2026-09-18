"""Prompts live on disk as versioned markdown, one file per pipeline stage.

Keeping them out of the Python source means you can diff a prompt change in a pull
request and see exactly what moved, the same way you would review code.
"""

from functools import lru_cache

from app.config import settings


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """load("extract.v1") -> the text of app/prompts/extract.v1.md"""
    return (settings.prompts_dir / f"{name}.md").read_text(encoding="utf-8")

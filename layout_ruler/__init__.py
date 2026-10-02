"""layout-ruler: a geometry checker for rendered web pages.

It renders a page in headless Chrome, reads every element box with a small
in-page probe, and judges the numbers in Python: column edges, gaps on a
spacing scale, equal siblings, level baselines and horizontal overflow.
"""
from __future__ import annotations

__version__ = "0.1.0"

from .cli import main  # noqa: E402  (the version must exist before cli imports it)

__all__ = ["__version__", "main"]

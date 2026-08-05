"""Models package for the `shop` app.

Imports here expose models at `shop.models` so Django can discover them.
"""

from .car import Car
from .report import Report
from .job import WorkJob

__all__ = ["Car", "Report", "WorkJob"]

"""Sprint 2 scrapers — Western regulatory sources.

- ``ema_hmpc``: EMA HMPC herbal monograph listing + detail parser.
- ``nhpid``: Health Canada Natural Health Products Ingredients Database.
"""

from .ema_hmpc import EmaHmpcScraper
from .nhpid import NhpidScraper

__all__ = ["EmaHmpcScraper", "NhpidScraper"]

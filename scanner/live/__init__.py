"""Live-safe VN100 end-of-day scanning components.

This package is intentionally separate from the research/post-breakout
pipeline.  Every detector here only sees bars available at scan time.
"""

from .config import LiveScanConfig

__all__ = ["LiveScanConfig"]

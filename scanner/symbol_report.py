"""
Legacy wrapper for backward compatibility.

Use `scanner/report_symbol.py` for the standardized entrypoint.
"""

from __future__ import annotations

from report_symbol import *  # type: ignore


if __name__ == "__main__":
    from report_symbol import main

    main()

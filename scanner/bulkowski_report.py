"""
Legacy wrapper for backward compatibility.

Use `scanner/report_bulkowski.py` for the standardized entrypoint.
"""

from __future__ import annotations

from report_bulkowski import *  # type: ignore


if __name__ == "__main__":
    from report_bulkowski import main

    main()

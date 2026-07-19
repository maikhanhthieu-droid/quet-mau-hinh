"""
Legacy wrapper for backward compatibility.

Use `scanner/build_phase3_governance.py` for the standardized entrypoint.
"""

from __future__ import annotations

from build_phase3_governance import *  # type: ignore


if __name__ == "__main__":
    from build_phase3_governance import main

    main()

"""
Legacy wrapper for backward compatibility.

Use `scanner/audit_spec.py` for the standardized entrypoint.
"""

from __future__ import annotations

from audit_spec import *  # type: ignore


if __name__ == "__main__":
    from audit_spec import main

    main()

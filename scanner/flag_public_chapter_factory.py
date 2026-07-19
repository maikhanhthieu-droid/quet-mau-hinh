"""Compatibility wrapper for older imports.

New code should import `scanner.flag_family_public_chapter_factory`.
This module remains only to avoid breaking historical scripts.
"""

from scanner.flag_family_public_chapter_factory import FACTORY_ID, FLAG_FAMILY_FACTORY_ID, build_flag_public_chapter


__all__ = ["FACTORY_ID", "FLAG_FAMILY_FACTORY_ID", "build_flag_public_chapter"]

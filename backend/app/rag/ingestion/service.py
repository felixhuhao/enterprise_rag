"""General ingestion utilities."""

import os
import re


def extract_entity_name(filename: str) -> str:
    """Rule-based entity name extraction from filename.

    Examples:
        "中芯国际_2023年报.pdf" -> "中芯国际"
        "腾讯控股（年报）2023.pdf" -> "腾讯控股"
        "Holley Inc. 10-K 2022.pdf" -> "Holley Inc."
        "dummy_report.pdf" -> ""
    """
    stem = os.path.splitext(filename)[0]
    if not stem:
        return ""

    # Split on common separators
    parts = re.split(r"[_\-\s【】《》（）()]", stem)
    parts = [p.strip() for p in parts if p.strip()]

    # Filter out date-like and numeric parts
    date_pattern = re.compile(
        r"^(\d{4}|\d{2,4}[年/-]\d{1,2}[月/-]?\d{0,2}[日号]?|"
        r"\d{4}[QqHh][1-4]|年报|半年报|季报|一季报|三季报)$"
    )
    candidates = [p for p in parts if not date_pattern.match(p) and not re.match(r"^\d+$", p)]

    if not candidates:
        return ""

    # Take the first candidate as entity name
    return candidates[0]

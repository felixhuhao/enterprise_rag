"""Golden-set loading and case filtering helpers."""

import json

from .common import _boolish
from .citation import _case_slices


def load_golden_set(path: str, *, include_disabled: bool = False) -> list[dict]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                item = json.loads(line)
                if include_disabled or item.get("status", "active") != "disabled":
                    items.append(item)
    return items

def filter_by_slice(golden_set: list[dict], slices: list[str]) -> list[dict]:
    """Filter golden set items by slice tags.

    Matching logic:
    - slice value matches item's preferred_flavor
    - slice value appears in item's tags
    - special slice 'strict' matches strict_evidence == True
    Multiple slices take union.
    """
    if not slices:
        return golden_set

    filtered = []
    for item in golden_set:
        flavor = item.get("preferred_flavor", "")
        tags = item.get("tags", [])
        case_slices = _case_slices(item)
        strict = item.get("strict_evidence", False)

        for s in slices:
            if s == "strict" and strict:
                filtered.append(item)
                break
            elif s == flavor:
                filtered.append(item)
                break
            elif s in tags or s in case_slices:
                filtered.append(item)
                break

    return filtered


def filter_quick_cases(golden_set: list[dict]) -> list[dict]:
    return [item for item in golden_set if _boolish(item.get("quick", False))]

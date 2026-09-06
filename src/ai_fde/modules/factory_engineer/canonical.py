from __future__ import annotations

import hashlib
import json
from typing import Any

CANONICALIZATION = "fdlc-canonical-json/v1"
MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991


class CanonicalizationError(ValueError):
    """The value cannot be represented by the constrained package canonical form."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return the FDLC v1 canonical JSON representation.

    The representation is UTF-8 JSON with recursively sorted object keys, compact
    separators, unescaped Unicode, and no floating-point values. Integers are limited
    to the interoperable IEEE-754 range. Package schemas normalize UUIDs, timestamps,
    and decimal quantities to strings before calling this function.
    """

    _validate_canonical_value(value, path="$")
    try:
        serialized = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return serialized.encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise CanonicalizationError("Package content is not canonicalizable JSON") from exc


def canonical_sha256(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _validate_canonical_value(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise CanonicalizationError(f"Unpaired Unicode surrogate at {path}")
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_JSON_INTEGER:
            raise CanonicalizationError(f"Integer outside canonical range at {path}")
        return
    if isinstance(value, float):
        raise CanonicalizationError(f"Floating-point values are not allowed at {path}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_canonical_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(f"Object key is not a string at {path}")
            if not key.isascii():
                raise CanonicalizationError(f"Non-ASCII object key is not allowed at {path}")
            _validate_canonical_value(key, path=f"{path}.<key>")
            _validate_canonical_value(item, path=f"{path}.{key}")
        return
    raise CanonicalizationError(f"Unsupported canonical value at {path}: {type(value).__name__}")

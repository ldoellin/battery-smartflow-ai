from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


def _to_float(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        if s == "" or s.lower() in ("unknown", "unavailable", "none"):
            return default
        return float(s)
    except Exception:
        _LOGGER.debug("_to_float: unexpected value %r, returning default %r", v, default)
        return default

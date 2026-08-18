"""The one canonical JSON serialization every hash in this system uses.

PRD-03: verified against the book's own ch.5.3 code listing AND the interop
kit's CORE `canonical_json.json` vector. `ensure_ascii=False` is the
load-bearing detail — the book's own printed listing omits it (which would
escape Hebrew hints and break cross-team audits); this project adds it
deliberately, documented as a reasoned deviation from a printed illustration
per the book's own "Clarification: what binds and what merely illustrates"
page, not an oversight. See PRD-03 for the full citation.
"""

from __future__ import annotations

import json
from typing import Any


def canonical_json(obj: Any) -> str:
    """`json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`.

    Three load-bearing details: sorted keys (construction order in our own
    code is irrelevant), no whitespace, and non-ASCII emitted as raw UTF-8
    rather than `\\uXXXX`-escaped — the single most likely cause of a
    cross-team audit mismatch if it were ever `True`.
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

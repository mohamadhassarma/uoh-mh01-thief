"""Minimal, stdlib-only host spec collection for the step-0 declaration
(rule #53). No third-party dependency (e.g. psutil) has been added to this
project, so RAM/GPU are honestly reported as unknown rather than guessed —
a documented limitation (TODO.md), not a silent gap: the commit hash this
record seals is what rule #53 actually cares about; the hardware fields
exist so the declaration has *something* to check, not so this specific
project can report GPU model accurately.
"""

from __future__ import annotations

import os
import platform
from typing import Any


def collect_spec() -> dict[str, Any]:
    return {
        "os": f"{platform.system()} {platform.release()}",
        "cpu_type": platform.processor() or "unknown",
        "cpu_cores": os.cpu_count() or 0,
        "ram_gb": "unknown",
        "gpu_type": "unknown",
        "vram_gb": "unknown",
    }

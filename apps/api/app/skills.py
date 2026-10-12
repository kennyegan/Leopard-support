"""Versioned project skill, shared by the runtime model and maintainers."""

from functools import lru_cache
import hashlib
from .config import ROOT


@lru_cache
def troubleshooting_skill():
    text = (ROOT / "apps/api/skills/troubleshoot/SKILL.md").read_text()
    return text.split("---", 2)[-1].strip(), hashlib.sha256(text.encode()).hexdigest()[:12]

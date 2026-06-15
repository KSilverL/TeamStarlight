"""
Platform style skills — the creator's **static injection layer** (MIGRATION_PLAN §5.4).

Each `skills/<platform>.md` is a human-edited, version-controlled style guide
(character limit, tone norms, good/bad examples). The creator loads the matching
skill and injects it into copywriting: production folds it into the LLM system
prompt; the mock honours the declared character limit. The same loader serves the
post-approval media_producer: `brand_animation.md` (the animated HTML card spec) and
`brand_video.md` (the structured video-props spec) are handed to the LLM verbatim.

Loaders are cached and dependency-free; an unlisted platform simply yields "" /
None, so the creator degrades gracefully.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

_SKILLS_DIR = Path(__file__).resolve().parent

# Synonym handles share one skill file (x → twitter).
_ALIASES = {"x": "twitter"}


def _skill_name(platform: str) -> str:
    return _ALIASES.get(platform.lower(), platform.lower())


@lru_cache(maxsize=None)
def load_skill(platform: str) -> str:
    """Return the platform style skill markdown, or '' if there is no file."""
    path = _SKILLS_DIR / f"{_skill_name(platform)}.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def parse_char_limit(skill_md: str) -> Optional[int]:
    """Pull the `Character limit: N` directive out of a skill's markdown, if present."""
    match = re.search(r"[Cc]haracter limit:\s*([\d,]+)", skill_md)
    return int(match.group(1).replace(",", "")) if match else None


def char_limit(platform: str) -> Optional[int]:
    """The platform's hard character limit, or None if the skill declares none."""
    return parse_char_limit(load_skill(platform))


__all__ = ["load_skill", "parse_char_limit", "char_limit"]

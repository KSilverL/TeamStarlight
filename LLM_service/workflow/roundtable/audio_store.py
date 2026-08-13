"""
In-process store for roundtable turn audio (the personas' TTS readback clips).

**Why this exists.** The clips used to ride *inside* the SSE stream, as base64 on the
`agent_utterance_audio` event. That put megabytes of binary into the per-task event log —
which is replayed in full on every reconnect and never trimmed — and parked a large frame
ahead of latency-sensitive events (a step-mode `round_control` prompt has a countdown) on
the same connection. The event now carries a `audio_url` instead; the bytes live here and
are fetched separately over `GET /tasks/{task_id}/audio/{table_id}/{speaker}/{round_index}`.

**Deliberately NOT durable.** Audio is optional decoration, regenerable, and is precisely
the payload we are keeping OUT of the persisted event log — persisting it would re-create
the problem one layer down. A restart loses the clips; the turns themselves survive (they
are on the persisted event log), so a recovered task replays its discussion silently.

**Bounded on purpose.** An LRU cap keeps a long-running process from growing without
limit — the same failure mode this move is fixing. Overflow evicts the oldest clip, so a
very old turn's play button 404s; that degrades to "no audio for that turn", matching the
VoiceoverService contract (a TTS failure is never a reason to abort anything).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Optional
from urllib.parse import quote

# The MIME type the API serves these with; Azure Speech synthesizes mp3.
AUDIO_MEDIA_TYPE = "audio/mpeg"

# Max clips held process-wide. A table is ROUNDTABLE_MAX_ROUNDS (12) turns × ~4 personas ×
# N platforms, so this comfortably covers several concurrent runs while staying bounded.
MAX_CLIPS = 256

_clips: "OrderedDict[tuple[str, str, str, int], bytes]" = OrderedDict()


def _key(task_id: str, table_id: str, speaker: str, round_index: int) -> tuple[str, str, str, int]:
    return (task_id, table_id, speaker, int(round_index))


def url_for(*, task_id: str, table_id: str, speaker: str, round_index: int) -> str:
    """The service-relative path a client fetches this clip from. A proxying client (the
    frontend's `/api/...` mirror, a backend gateway) prefixes its own mount point; the path
    itself deliberately mirrors the `/tasks/{id}/...` shape the rest of the surface uses."""
    return (
        f"/tasks/{quote(str(task_id), safe='')}"
        f"/audio/{quote(str(table_id), safe='')}"
        f"/{quote(str(speaker), safe='')}/{int(round_index)}"
    )


def put(*, task_id: str, table_id: str, speaker: str, round_index: int, audio: bytes) -> str:
    """Store one turn's clip and return the URL that serves it."""
    key = _key(task_id, table_id, speaker, round_index)
    _clips.pop(key, None)  # re-insert so a re-synthesized turn counts as freshly used
    _clips[key] = audio
    while len(_clips) > MAX_CLIPS:
        _clips.popitem(last=False)  # evict the oldest
    return url_for(task_id=task_id, table_id=table_id, speaker=speaker, round_index=round_index)


def get(*, task_id: str, table_id: str, speaker: str, round_index: int) -> Optional[bytes]:
    """The stored clip, or None if it was never synthesized (or has been evicted)."""
    key = _key(task_id, table_id, speaker, round_index)
    audio = _clips.get(key)
    if audio is not None:
        _clips.move_to_end(key)  # LRU: a played clip is a recently-used clip
    return audio


def clear() -> None:
    """Drop every stored clip (tests; also the honest reset for a fresh process)."""
    _clips.clear()

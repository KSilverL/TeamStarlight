"""
Platform-simulated preview cards (MIGRATION_PLAN §5.4, per skills/html_designer.md).

`render_preview_card(platform, draft)` returns ONE self-contained HTML fragment that
renders a draft inside a faithful mock of the target platform's post UI — this is the
`html_preview` the SSE `result` event carries, ready to drop straight into the frontend.
Deterministic and offline (no LLM, no network assets); a production renderer can hand
skills/html_designer.md to an LLM for richer cards. The draft is HTML-escaped and its
line breaks preserved, so user copy can never inject markup.
"""

from __future__ import annotations

import html as _html

# One subtle entrance animation, shared by every card (scoped via the root class).
_ANIM = (
    "@keyframes nrUp{from{opacity:0;transform:translateY(10px)}"
    "to{opacity:1;transform:none}}"
)
_FONT = "font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif"


def _alias(platform: str) -> str:
    p = platform.lower()
    return "x" if p == "twitter" else p


def _body(draft: str) -> str:
    return _html.escape(draft).replace("\n", "<br>")


def render_preview_card(
    platform: str, draft: str, *, author: str = "Your Brand", handle: str = "yourbrand"
) -> str:
    """Render `draft` as a platform-native preview card (a self-contained HTML fragment)."""
    p = _alias(platform)
    body = _body(draft)
    initial = (author[:1] or "Y").upper()
    if p == "linkedin":
        return _linkedin(body, author, initial)
    if p == "x":
        return _x(body, author, handle, initial)
    if p == "instagram":
        return _instagram(body, handle, initial)
    return _generic(body, author, initial, platform)


def _linkedin(body: str, author: str, initial: str) -> str:
    return f"""<div class="preview-card pc-li"><style scoped>
.pc-li{{{_FONT};max-width:480px;background:#fff;border:1px solid #e0dfdc;border-radius:10px;
padding:14px 16px;color:#1d2226;animation:nrUp .35s ease both}}{_ANIM}
.pc-li .h{{display:flex;align-items:center;gap:10px;margin-bottom:10px}}
.pc-li .av{{width:44px;height:44px;border-radius:50%;background:#0a66c2;color:#fff;
display:flex;align-items:center;justify-content:center;font-weight:700}}
.pc-li .nm{{font-weight:600;font-size:14px}}.pc-li .mt{{color:#666;font-size:12px}}
.pc-li .bd{{font-size:14px;line-height:1.5;white-space:normal}}
.pc-li .ft{{display:flex;gap:18px;color:#666;font-size:13px;border-top:1px solid #eee;
margin-top:12px;padding-top:8px}}</style>
<div class="h"><div class="av">{initial}</div><div><div class="nm">{author}</div>
<div class="mt">Brand · 1st · now</div></div></div>
<div class="bd">{body}</div>
<div class="ft"><span>👍 Like</span><span>💬 Comment</span><span>🔁 Repost</span></div></div>"""


def _x(body: str, author: str, handle: str, initial: str) -> str:
    return f"""<div class="preview-card pc-x"><style scoped>
.pc-x{{{_FONT};max-width:480px;background:#15202b;border:1px solid #38444d;border-radius:14px;
padding:14px 16px;color:#e7e9ea;animation:nrUp .35s ease both}}{_ANIM}
.pc-x .h{{display:flex;align-items:center;gap:10px;margin-bottom:8px}}
.pc-x .av{{width:44px;height:44px;border-radius:50%;background:#1d9bf0;color:#fff;
display:flex;align-items:center;justify-content:center;font-weight:700}}
.pc-x .nm{{font-weight:700;font-size:14px}}.pc-x .at{{color:#8b98a5;font-size:13px}}
.pc-x .bd{{font-size:15px;line-height:1.45}}
.pc-x .ft{{display:flex;gap:26px;color:#8b98a5;font-size:14px;margin-top:12px}}</style>
<div class="h"><div class="av">{initial}</div><div><div class="nm">{author}</div>
<div class="at">@{handle}</div></div></div>
<div class="bd">{body}</div>
<div class="ft"><span>💬</span><span>🔁</span><span>♥</span><span>📊</span></div></div>"""


def _instagram(body: str, handle: str, initial: str) -> str:
    return f"""<div class="preview-card pc-ig"><style scoped>
.pc-ig{{{_FONT};max-width:420px;background:#fff;border:1px solid #dbdbdb;border-radius:10px;
overflow:hidden;color:#262626;animation:nrUp .35s ease both}}{_ANIM}
.pc-ig .h{{display:flex;align-items:center;gap:10px;padding:12px 14px}}
.pc-ig .av{{width:36px;height:36px;border-radius:50%;
background:linear-gradient(45deg,#feda75,#d62976,#4f5bd5);color:#fff;
display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px}}
.pc-ig .nm{{font-weight:600;font-size:14px}}
.pc-ig .media{{height:240px;background:linear-gradient(135deg,#fdcb6e,#e17055,#d62976)}}
.pc-ig .row{{display:flex;gap:16px;padding:10px 14px;font-size:18px}}
.pc-ig .cap{{padding:0 14px 14px;font-size:14px;line-height:1.5}}
.pc-ig .cap b{{margin-right:6px}}</style>
<div class="h"><div class="av">{initial}</div><div class="nm">{handle}</div></div>
<div class="media"></div>
<div class="row"><span>♥</span><span>💬</span><span>✈</span></div>
<div class="cap"><b>{handle}</b>{body}</div></div>"""


def _generic(body: str, author: str, initial: str, platform: str) -> str:
    label = _html.escape(platform)
    return f"""<div class="preview-card pc-g"><style scoped>
.pc-g{{{_FONT};max-width:480px;background:#fff;border:1px solid #ddd;border-radius:10px;
padding:14px 16px;color:#1a1a1a;animation:nrUp .35s ease both}}{_ANIM}
.pc-g .h{{display:flex;align-items:center;gap:10px;margin-bottom:8px}}
.pc-g .av{{width:42px;height:42px;border-radius:50%;background:#555;color:#fff;
display:flex;align-items:center;justify-content:center;font-weight:700}}
.pc-g .nm{{font-weight:600}}.pc-g .pl{{color:#888;font-size:12px}}
.pc-g .bd{{font-size:14px;line-height:1.5}}</style>
<div class="h"><div class="av">{initial}</div><div><div class="nm">{author}</div>
<div class="pl">{label}</div></div></div>
<div class="bd">{body}</div></div>"""

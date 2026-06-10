from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from ..core.services.factory import get_chat_client
from ..core.state import AgentState


async def conversation_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    Multi-turn draft editor at the final content checkpoint.

    Flow (one turn):
      1. interrupt() pauses and presents the current draft to the user.
      2. User resumes with Command(resume=text).
      3. If text == "done": set conversation_status="done" → graph routes back to final_review_gate.
      4. Otherwise: call Azure OpenAI chat to revise the draft, loop back to this node.
    """
    platform: str       = state.get("conversation_platform", "")  # type: ignore[assignment]
    current_draft: str  = (state.get("drafts") or {}).get(platform, "")
    history: list[dict] = (state.get("conversation_history") or {}).get(platform, [])
    originals: dict     = state.get("original_drafts") or {}

    user_text = interrupt({
        "platform":      platform,
        "current_draft": current_draft,
        "turn":          len(history) // 2,
        "instruction":   'Type your modification request, or "done" to return to review.',
    })
    user_text = str(user_text).strip()

    if user_text.lower() == "done":
        return {"conversation_status": "done"}

    # Build messages: system prompt + accumulated history + new request
    system_prompt = (
        f"You are a social media content editor specialising in {platform} content. "
        "Apply the user's modification request to the current draft. "
        "Return only the revised draft text — no explanation, no extra commentary."
    )
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({
        "role": "user",
        "content": f"Current draft:\n{current_draft}\n\nModification request: {user_text}",
    })

    revised: str = await get_chat_client().chat(messages)

    new_history = list(history) + [
        {"role": "user",      "content": user_text},
        {"role": "assistant", "content": revised},
    ]

    update: dict = {
        "conversation_status":  "active",
        "drafts":               {platform: revised},
        "conversation_history": {platform: new_history},
    }
    # Snapshot the pre-edit draft on the first edit so the write-back can emit an
    # edit_pair (before/after) when this platform is later approved (§4.4).
    if platform not in originals:
        update["original_drafts"] = {platform: current_draft}
    return update

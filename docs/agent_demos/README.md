# Agent Demos

This directory documents the two LLM-powered demo agents integrated into the Starlight chat UI. Both agents live under `LLM_service/demos/` and are intentionally isolated from the main `LLM_service` source code.

| Agent | Directory | Port | Output |
|---|---|---|---|
| [Brand Animation Agent](./brand_animation_agent.md) | `LLM_service/demos/brand_agent/` | `8000` | Self-contained animated HTML card |
| [Brand Video Agent](./brand_video_agent.md) | `LLM_service/demos/brand_video_agent/` | `8001` | Rendered MP4 video (9:16 portrait) |

Both agents are started together with the frontend via:

```bash
cp .env.example .env   # add ANTHROPIC_API_KEY
docker compose up --build
```

> **Note:** These are proof-of-concept implementations. See the individual agent docs for details on known limitations and planned changes.

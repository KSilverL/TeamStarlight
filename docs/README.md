# docs/

This directory contains API and feature documentation for the TeamStarlight system.

---

## Files

### `api.md`

General API documentation for the Next.js middleware layer (`http://localhost:3000`). Covers the initial set of REST endpoints including content search, user management (list, create, get by ID, delete), and the LLM service webhook receiver at `http://localhost:9999` that the LangGraph pipeline posts per-platform status notifications to.

### `chat-api.md`

Documentation for the full chat interface workflow across all three service layers (Next.js frontend, Spring Boot backend, LangGraph LLM service). Covers session management, chat messaging, interrupt decision endpoints (outline approval, draft approval, multi-turn conversation), backend-to-LLM-service integration calls, and the internal webhook that the LLM service uses to push real-time content results to the backend.

### `approval-queue-api.md`

Documentation for the approval queue feature. Covers the endpoints used by the two-panel review UI in the profile page: listing pending posts, fetching a single post's detail, approving or rejecting a post, and bulk-updating multiple post statuses in one request. All endpoints are served by the Spring Boot backend (`http://localhost:8080`).

### `calendar-api.md`

Documentation for the content calendar feature. Covers three sub-areas: CRUD endpoints for scheduled posts (list, get, create, update, delete), the frontend-facing content generation endpoint that powers the Schedule Post modal chat, and the backend-to-LLM-service call that performs the actual single-shot platform content generation. Also documents the Quartz job lifecycle that handles publish-time scheduling.

### `brand-profile-api.md`

Documentation for the brand profile feature. Covers the three endpoints used by the editable brand profile form: fetching the saved profile, creating or replacing it (upsert via `PATCH`), and resetting it to defaults. The brand profile is injected as system-level context into every LLM content generation call.

---

## Directories

### `agent_demos/`

Documentation for the two proof-of-concept LLM-powered demo agents integrated into the Starlight chat UI. See [`agent_demos/README.md`](./agent_demos/README.md) for a summary table and setup instructions.

| File | Agent | Description |
|---|---|---|
| `brand_animation_agent.md` | Brand Animation Agent (port `8000`) | Generates a self-contained animated HTML card from a free-text brand brief using Claude Haiku and a single LLM call |
| `brand_video_agent.md` | Brand Video Agent (port `8001`) | Generates a 12-second branded MP4 video from a brand brief using Claude Haiku for structured prop generation and Remotion + headless Chromium for rendering |

---

## Endpoint Documentation Structure

Each endpoint section in the API docs follows a consistent format:

| Field | Description |
|---|---|
| **Description** | What the endpoint does and when it is called |
| **Endpoint** | The URL path (e.g. `/api/sessions/{sessionId}`) |
| **Base URL** | The service host the endpoint lives on |
| **HTTP Method** | `GET`, `POST`, `PUT`, `PATCH`, or `DELETE` |
| **Path Parameters** | Dynamic segments in the URL, with type, required flag, and description |
| **Query Parameters** | URL query string parameters, with type, required flag, default value, and description |
| **Request Body** | JSON body fields with type, required flag, and description |
| **Example Request** | A complete HTTP request block showing real values |
| **Example Successful Response** | HTTP status code and the JSON body returned on success |
| **Example Unsuccessful Response(s)** | One or more failure cases with status code, error code, and message |

Some endpoint sections also include supplementary **Data Model** tables that describe the shape of the objects returned across multiple endpoints within that file (e.g. `ApprovalPost`, `ScheduledPost`, `BrandProfile`), and **Architecture Overview** diagrams that show how the frontend, backend, and LLM service interact for that feature.

# TeamStarlight API Documentation

This document covers all REST endpoints exposed by the TeamStarlight system. The Next.js frontend service exposes a JSON API on `http://localhost:3000/api` and proxies to the Spring Boot backend, which orchestrates the **MAF (Microsoft Agent Framework)** LLM service. Progress from the LLM service is streamed back over **Server-Sent Events** — the LangGraph-era webhook push to a separate receiver at `http://localhost:9999` has been retired (see [LLM Service Progress (SSE)](#llm-service-progress-sse) below).

---

## Table of Contents

- [Search](#search)
- [Users](#users)
  - [List Users](#list-users)
  - [Create User](#create-user)
  - [Get User by ID](#get-user-by-id)
  - [Delete User](#delete-user)
- [LLM Service Progress (SSE)](#llm-service-progress-sse)

---

## Search

### Search Content

**Description**  
Performs a keyword search across content. Accepts a query string and returns a matching result string. This endpoint is served by the Next.js middleware and is intended to proxy or filter content from the LLM service based on user input.

**Endpoint**  
`/api/search`

**Method**  
`GET`

**Query Parameters**

| Parameter | Type   | Required | Description                      |
|-----------|--------|----------|----------------------------------|
| `query`   | string | Yes      | The search term or phrase to look up |

**Example Request**

```http
GET /api/search?query=instagram+campaign HTTP/1.1
Host: localhost:3000
```

**Example Successful Response** — `200 OK`

```json
{
  "result": "You searched for: instagram campaign"
}
```

**Example Unsuccessful Response** — `400 Bad Request`

```json
{
  "error": "Missing required query parameter: query"
}
```

---

## Users

### List Users

**Description**  
Returns a list of all registered users in the system. In the current implementation this returns seeded data; in production this will proxy the user store from the backend database.

**Endpoint**  
`/api/users`

**Method**  
`GET`

**Query Parameters**  
None

**Example Request**

```http
GET /api/users HTTP/1.1
Host: localhost:3000
```

**Example Successful Response** — `200 OK`

```json
[
  {
    "id": 1,
    "name": "Alice"
  },
  {
    "id": 2,
    "name": "Bob"
  }
]
```

**Example Unsuccessful Response** — `500 Internal Server Error`

```json
{
  "error": "Failed to retrieve users"
}
```

---

### Create User

**Description**  
Creates a new user record. The request body must include the user's name. The server generates a unique ID using the current timestamp and returns the newly created user object.

**Endpoint**  
`/api/users`

**Method**  
`POST`

**Query Parameters**  
None

**Request Body**

| Field  | Type   | Required | Description          |
|--------|--------|----------|----------------------|
| `name` | string | Yes      | The name of the new user |

**Example Request**

```http
POST /api/users HTTP/1.1
Host: localhost:3000
Content-Type: application/json

{
  "name": "Charlie"
}
```

**Example Successful Response** — `201 Created`

```json
{
  "id": 1718200000000,
  "name": "Charlie"
}
```

**Example Unsuccessful Response** — `400 Bad Request`

```json
{
  "error": "Request body is missing required field: name"
}
```

---

### Get User by ID

**Description**  
Retrieves a single user record by their unique ID. The ID is provided as a dynamic path segment in the URL.

**Endpoint**  
`/api/users/:id`

**Method**  
`GET`

**Path Parameters**

| Parameter | Type   | Required | Description             |
|-----------|--------|----------|-------------------------|
| `id`      | string | Yes      | The unique ID of the user |

**Query Parameters**  
None

**Example Request**

```http
GET /api/users/42 HTTP/1.1
Host: localhost:3000
```

**Example Successful Response** — `200 OK`

```json
{
  "id": "42",
  "name": "User 42"
}
```

**Example Unsuccessful Response** — `404 Not Found`

```json
{
  "error": "User with id 42 not found"
}
```

---

### Delete User

**Description**  
Deletes a user record by their unique ID. On success the server responds with `204 No Content`. The ID is provided as a dynamic path segment in the URL.

**Endpoint**  
`/api/users/:id`

**Method**  
`DELETE`

**Path Parameters**

| Parameter | Type   | Required | Description                      |
|-----------|--------|----------|----------------------------------|
| `id`      | string | Yes      | The unique ID of the user to delete |

**Query Parameters**  
None

**Example Request**

```http
DELETE /api/users/42 HTTP/1.1
Host: localhost:3000
```

**Example Successful Response** — `204 No Content`

```
(empty body)
```

**Example Unsuccessful Response** — `404 Not Found`

```json
{
  "error": "User with id 42 not found"
}
```

---

## LLM Service Progress (SSE)

### Task Event Stream

**Description**  
This endpoint is **exposed by the MAF LLM service** and **consumed by the Spring Boot backend**, not the frontend client. It replaces the LangGraph-era status webhook (the old `POST /status` push to a receiver at `:9999`): instead of the LLM service pushing per-platform completions, the backend **subscribes once** to a task's event stream and watches the whole run. The backend relays the events it cares about to the frontend (e.g. over its own SSE/WebSocket channel) so a draft appears in the chat without a full poll. The full LLM-service contract lives in the repo-root [`API.md`](../API.md).

**Endpoint**  
`/tasks/{task_id}/events`

**Base URL**  
`http://localhost:8080` *(the MAF LLM service; reached server-to-server by the backend)*

**Method**  
`GET` *(content type `text/event-stream`)*

**Path Parameters**

| Parameter | Type   | Required | Description                                              |
|-----------|--------|----------|----------------------------------------------------------|
| `task_id` | string | Yes      | The content-generation task to watch (returned by `POST /tasks`) |

**Event Format**  
Each line is `data: <json>\n\n`. The stream replays all events so far, continues live, and **closes when the task completes**. Switch on the `type` field — `progress` (the run moved to a new executor) or `result` (content is ready). Example `result` events:

| Field          | Type   | Description                                                                 |
|----------------|--------|-----------------------------------------------------------------------------|
| `type`         | string | `"progress"` or `"result"`                                                  |
| `node`         | string | The MAF executor (`dispatcher` / `scout` / `creator` / `reviewer` / `human_gate` / `archivist` / `media_producer` / `workflow`) |
| `platform`     | string | The target platform (e.g. `"instagram"`); `null` for non-per-platform steps |
| `status`       | string | `running` → `done` / `interrupted` / `error`, or `draft_ready` / `final` on a result |
| `draft`        | string | The generated post copy                                                     |
| `html_preview` | string | A complete, self-contained **animated HTML brand card** (only on the `final` result) — replaces the old DALL-E image |
| `video_props`  | object | A structured `BrandVideoProps` spec a downstream Remotion render turns into an MP4 (only on the `final` result) |

**Example Stream** *(MAF LLM service → backend)*

```http
GET /tasks/task-abc123/events HTTP/1.1
Host: localhost:8080
Accept: text/event-stream
```

```
data: {"type":"progress","node":"creator","phase":"create","platform":"instagram","status":"running","ts":1781105228.4}

data: {"type":"result","node":"creator","phase":"create","platform":"instagram","status":"draft_ready","draft":"Summer is here ☀️ Discover our new collection. #fashion #summer #style","critic_comment":"approved by red team","needs_human_intervention":false}

data: {"type":"progress","node":"workflow","status":"done","platform":null,"ts":1781105320.1}
```

> **Note:** Media is no longer a DALL-E 3 image URL. The post-approval `media_producer` emits an
> animated, self-contained **HTML brand card** (`html_preview`) plus a structured **video spec**
> (`video_props`) — both appear only on the `final` result event, after the human approves. See
> the repo-root [`API.md`](../API.md) for the complete SSE envelope and the standalone media
> endpoints (`POST /generate-text`, `POST /generate`, `POST /generate-video`).

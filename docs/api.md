# TeamStarlight API Documentation

This document covers all REST endpoints exposed by the TeamStarlight system. The Next.js frontend service acts as the middleware layer between the React UI and the LangGraph LLM service, exposing a JSON API on `http://localhost:3000/api`. The LLM service pushes status updates to a separate webhook receiver at `http://localhost:9999`.

---

## Table of Contents

- [Search](#search)
- [Users](#users)
  - [List Users](#list-users)
  - [Create User](#create-user)
  - [Get User by ID](#get-user-by-id)
  - [Delete User](#delete-user)
- [LLM Service Webhook](#llm-service-webhook)

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

## LLM Service Webhook

### Content Status Notification

**Description**  
This endpoint is **consumed by the LLM service**, not the frontend client. After each platform's content pipeline completes — passing the critic node and writing to the feedback database — the `WebhookStatusNotifier` fires a `POST` to this URL with the task ID and a status payload containing the generated draft and media asset URL. The backend middleware running at `localhost:9999` listens for these events so it can push real-time updates to connected clients without polling the LangGraph graph directly.

**Endpoint**  
`/status`

**Base URL**  
`http://localhost:9999`

**Method**  
`POST`

**Query Parameters**  
None

**Request Body** *(sent by the LLM service)*

| Field     | Type   | Required | Description                                                                 |
|-----------|--------|----------|-----------------------------------------------------------------------------|
| `task_id` | string | Yes      | Unique identifier for the content generation task (maps to `thread_id`)     |
| `status`  | object | Yes      | Payload describing the completed pipeline result for a specific platform    |

The `status` object contains platform-specific content. Example fields:

| Field             | Type   | Description                                    |
|-------------------|--------|------------------------------------------------|
| `platform`        | string | The target platform (e.g. `"instagram"`)       |
| `draft`           | string | The generated post copy                        |
| `media_asset_url` | string | URL of the generated image from Azure DALL-E 3 |

**Example Request** *(from LLM service → backend)*

```http
POST /status HTTP/1.1
Host: localhost:9999
Content-Type: application/json

{
  "task_id": "task-abc123",
  "status": {
    "platform": "instagram",
    "draft": "Summer is here ☀️ Discover our new collection. #fashion #summer #style",
    "media_asset_url": "https://dalle.azure.com/images/generated-abc.png"
  }
}
```

**Example Successful Response** — `200 OK`

```json
{
  "received": true
}
```

**Example Unsuccessful Response** — `500 Internal Server Error`

```json
{
  "error": "Failed to process status notification"
}
```

> **Note:** The LLM service treats all connection errors and timeouts on this endpoint as non-fatal. If the backend is unreachable the notification is silently dropped (timeout: 2 seconds). This ensures webhook failures never block the content generation pipeline.

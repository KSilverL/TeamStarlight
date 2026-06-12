# TeamStarlight Brand Profile API Documentation

This document covers all REST endpoints involved in the brand profile feature across two service layers:

- **Frontend** (Next.js, `http://localhost:3000`) — the editable brand profile form in the profile page
- **Backend** (Spring Boot, `http://localhost:8080`) — persists the brand profile and serves it as context to the LLM service at generation time

The brand profile is the primary source of system-level context injected into every LLM content generation call. Keeping it accurate directly improves the quality and consistency of generated content across the chat interface, the schedule post modal, and any future generation surfaces.

---

## Architecture Overview

```
Frontend (Brand Profile form)
    │
    │  GET  /api/brand         — load profile on mount
    │  PATCH /api/brand        — save changes on "Save Profile" click
    ▼
Backend (Spring Boot)
    │  Persists brand profile per user
    │
    └── Injected into every LLM generation call as system-level context:
        - POST /llm/sessions          (chat pipeline, see chat-api.md)
        - POST /llm/generate          (calendar modal, see calendar-api.md)
```

---

## Table of Contents

- [A1. Get Brand Profile](#a1-get-brand-profile)
- [A2. Update Brand Profile](#a2-update-brand-profile)
- [A3. Reset Brand Profile to Defaults](#a3-reset-brand-profile-to-defaults)

---

## Data Model

### BrandProfile

| Field         | Type   | Required | Description                                                                                     |
|---------------|--------|----------|-------------------------------------------------------------------------------------------------|
| `name`        | string | Yes      | The business or brand name (e.g. `"EcoHome Solutions"`)                                         |
| `competitors` | string | No       | Comma-separated competitor names used to differentiate tone (e.g. `"Grove Collaborative, Bambu"`) |
| `description` | string | Yes      | What the business does and what makes it unique                                                 |
| `demographic` | string | No       | The target audience — age, interests, location, and any other segmentation detail               |
| `tone`        | string | Yes      | Brand voice description (e.g. `"warm, aspirational, and educational"`)                          |
| `topics`      | string | No       | Products, themes, or subjects the brand typically posts about                                   |
| `avoid`       | string | No       | Language, themes, or formats the LLM should never use in generated content                      |
| `notes`       | string | No       | Any additional context the LLM should keep in mind across all generations                       |
| `updatedAt`   | string | —        | ISO 8601 timestamp of the last save. Read-only; set by the backend                              |

---

## A1. Get Brand Profile

**Description**  
Returns the saved brand profile for the authenticated user. The frontend calls this on component mount to pre-populate the form fields. If no profile has been saved yet, the backend returns a `404` and the frontend falls back to the `DEFAULT_BRAND` seed values defined locally.

**Endpoint**  
`/api/brand`

**Base URL**  
`http://localhost:8080`

**Method**  
`GET`

**Query Parameters**  
None

**Example Request**

```http
GET /api/brand HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** — `200 OK`

```json
{
  "name": "EcoHome Solutions",
  "competitors": "Grove Collaborative, Package Free Shop, Bambu",
  "description": "We sell sustainable bamboo home products designed for eco-conscious households. Our mission is to make sustainable living accessible and beautiful.",
  "demographic": "Eco-conscious millennials aged 25–40, primarily urban, middle-to-high income, interested in sustainability and home design.",
  "tone": "Warm, aspirational, and educational — we inspire rather than hard-sell.",
  "topics": "Bamboo homewares, sustainable kitchen products, zero-waste living tips, product launches.",
  "avoid": "Greenwashing language, aggressive CTAs, overly technical jargon.",
  "notes": "Always emphasise carbon-negative production and the decade-long lifespan of our products.",
  "updatedAt": "2026-06-12T10:00:00Z"
}
```

**Example Unsuccessful Response — No profile saved yet** — `404 Not Found`

```json
{
  "error": "BRAND_PROFILE_NOT_FOUND",
  "message": "No brand profile has been saved for this user. Submit a PATCH request to create one."
}
```

---

## A2. Update Brand Profile

**Description**  
Creates or fully replaces the brand profile for the authenticated user. The frontend calls this when the user clicks "Save Profile". All fields are sent on every save — partial field updates are not supported here since the form always holds the full profile state.

The backend overwrites the existing record (upsert semantics) and returns the updated profile. The updated profile is immediately used as context in subsequent LLM generation calls — there is no need to restart any active sessions.

**Endpoint**  
`/api/brand`

**Base URL**  
`http://localhost:8080`

**Method**  
`PATCH`

**Query Parameters**  
None

**Request Body**

| Field         | Type   | Required | Description                                                                     |
|---------------|--------|----------|---------------------------------------------------------------------------------|
| `name`        | string | Yes      | The business or brand name                                                      |
| `competitors` | string | No       | Comma-separated competitor names                                                 |
| `description` | string | Yes      | What the business does and what makes it unique                                 |
| `demographic` | string | No       | Target audience description                                                     |
| `tone`        | string | Yes      | Brand voice description                                                         |
| `topics`      | string | No       | Products, themes, or subjects the brand typically posts about                   |
| `avoid`       | string | No       | Language, themes, or formats the LLM should never use                           |
| `notes`       | string | No       | Any additional context for the LLM                                              |

**Example Request**

```http
PATCH /api/brand HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "name": "EcoHome Solutions",
  "competitors": "Grove Collaborative, Package Free Shop, Bambu",
  "description": "We sell sustainable bamboo home products designed for eco-conscious households. Our mission is to make sustainable living accessible and beautiful.",
  "demographic": "Eco-conscious millennials aged 25–40, primarily urban, middle-to-high income, interested in sustainability and home design.",
  "tone": "Warm, aspirational, and educational — we inspire rather than hard-sell.",
  "topics": "Bamboo homewares, sustainable kitchen products, zero-waste living tips, product launches.",
  "avoid": "Greenwashing language, aggressive CTAs, overly technical jargon.",
  "notes": "Always emphasise carbon-negative production and the decade-long lifespan of our products."
}
```

**Example Successful Response** — `200 OK`

```json
{
  "name": "EcoHome Solutions",
  "competitors": "Grove Collaborative, Package Free Shop, Bambu",
  "description": "We sell sustainable bamboo home products designed for eco-conscious households. Our mission is to make sustainable living accessible and beautiful.",
  "demographic": "Eco-conscious millennials aged 25–40, primarily urban, middle-to-high income, interested in sustainability and home design.",
  "tone": "Warm, aspirational, and educational — we inspire rather than hard-sell.",
  "topics": "Bamboo homewares, sustainable kitchen products, zero-waste living tips, product launches.",
  "avoid": "Greenwashing language, aggressive CTAs, overly technical jargon.",
  "notes": "Always emphasise carbon-negative production and the decade-long lifespan of our products.",
  "updatedAt": "2026-06-12T11:05:00Z"
}
```

**Example Unsuccessful Response — Missing required field** — `400 Bad Request`

```json
{
  "error": "VALIDATION_ERROR",
  "message": "One or more required fields are missing or blank",
  "details": [
    {
      "field": "name",
      "message": "must not be blank"
    },
    {
      "field": "tone",
      "message": "must not be blank"
    }
  ]
}
```

---

## A3. Reset Brand Profile to Defaults

**Description**  
Deletes the saved brand profile and reverts the user's profile to the system defaults. After a successful reset the backend returns `204 No Content` and the frontend falls back to the local `DEFAULT_BRAND` seed values on the next `GET /api/brand` call (which will return `404`).

This is a destructive action — the existing profile cannot be recovered after reset.

**Endpoint**  
`/api/brand`

**Base URL**  
`http://localhost:8080`

**Method**  
`DELETE`

**Query Parameters**  
None

**Request Body**  
None

**Example Request**

```http
DELETE /api/brand HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** — `204 No Content`

```
(empty body)
```

**Example Unsuccessful Response — Nothing to delete** — `404 Not Found`

```json
{
  "error": "BRAND_PROFILE_NOT_FOUND",
  "message": "No brand profile exists for this user. Nothing to reset."
}
```

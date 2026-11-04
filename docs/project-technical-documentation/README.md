# ridez.io — Technical Documentation Knowledge Base

This folder is a complete, developer-level knowledge base for the **ridez.io** taxi-booking application in this repository. Everything here was written by reading the actual source code (commit `6eb54b7`, branch `fresh-main`, 2026-11-02). Where behaviour is inferred rather than read directly from code, it is marked **(inferred)**. Where something could not be verified, it is marked **(not verified)**.

> **Scope of verification.** All file paths, function names, endpoints, table names and fields were checked against the source. The automated test suite was **not executed** while writing these docs, because the checkout has no Python virtualenv or `node_modules`, and installing dependencies was out of scope. Test *names and intent* are documented from reading the test files.

## How to read this

| If you want to… | Start with |
| --- | --- |
| Explain the product in 5 minutes | [19 — Manager explanation guide](19-manager-explanation-guide.md) |
| Revise the night before a meeting | [21 — Quick revision sheet](21-quick-revision-sheet.md) |
| Understand the big picture | [00 — Overview](00-project-overview.md) → [03 — Architecture](03-system-architecture.md) |
| Find what a file does | [02 — Folder and file structure](02-folder-and-file-structure.md) |
| Look up an endpoint | [06 — API documentation](06-api-documentation.md) |
| Look up a table | [07 — Database documentation](07-database-documentation.md) |
| Trace a feature end to end | [09 — Features](09-feature-by-feature-explanation.md) and [10 — Data flow](10-complete-data-flow.md) |
| Prepare for hard questions | [20 — Interview questions](20-technical-interview-questions.md) and [18 — Problems](18-problems-and-improvements.md) |

## Documents

| # | Document | Contents |
| --- | --- | --- |
| 00 | [Project overview](00-project-overview.md) | What the app does, users and roles, features, workflow, high-level diagram |
| 01 | [Technology stack](01-technology-stack.md) | Every technology and why it is used |
| 02 | [Folder and file structure](02-folder-and-file-structure.md) | File-by-file explanation of the whole repository |
| 03 | [System architecture](03-system-architecture.md) | Layers, request lifecycle, concurrency model, error architecture |
| 04 | [Frontend documentation](04-frontend-documentation.md) | React app, routing, every component and hook |
| 05 | [Backend documentation](05-backend-documentation.md) | Flask app factory, every module and function |
| 06 | [API documentation](06-api-documentation.md) | All 39 HTTP route handlers (43 logical operations) + Socket.IO contract |
| 07 | [Database documentation](07-database-documentation.md) | All 19 tables, ERD, constraints, migrations |
| 08 | [Authentication and security](08-authentication-and-security.md) | JWT + refresh cookies, RBAC, CSRF, rate limits, gaps |
| 09 | [Feature-by-feature explanation](09-feature-by-feature-explanation.md) | 19 features traced end to end |
| 10 | [Complete data flow](10-complete-data-flow.md) | Step-by-step lifecycle of data for each major flow |
| 11 | [Third-party integrations](11-third-party-integrations.md) | Google Routes, Maps JS, Places, CDN, Render |
| 12 | [State management](12-state-management.md) | Session store, workspace polling, forms, routing |
| 13 | [Background and real-time processes](13-background-and-realtime-processes.md) | Matching worker, outbox, Socket.IO, GPS loop |
| 14 | [Error handling](14-error-handling.md) | How each failure class is handled, gaps |
| 15 | [Deployment and execution](15-deployment-and-execution.md) | Local run, Docker, Render, CI, backups |
| 16 | [Dependencies](16-dependencies.md) | Every package, version, purpose and usage |
| 17 | [Technical decisions](17-technical-decisions.md) | Design patterns, trade-offs, documented vs inferred decisions |
| 18 | [Problems and improvements](18-problems-and-improvements.md) | Bugs, risks, tech debt, recommendations |
| 19 | [Manager explanation guide](19-manager-explanation-guide.md) | Speaking scripts |
| 20 | [Technical interview questions](20-technical-interview-questions.md) | 70+ questions with project-specific answers |
| 21 | [Quick revision sheet](21-quick-revision-sheet.md) | Paths, functions, endpoints, tables, env vars |

## Diagrams

All diagrams are Mermaid, so they render on GitHub and in most Markdown viewers and remain editable.

| Diagram file | Contents |
| --- | --- |
| [diagrams/architecture.md](diagrams/architecture.md) | High-level system, backend module dependencies, deployment topology |
| [diagrams/erd.md](diagrams/erd.md) | Entity-relationship diagram of all tables |
| [diagrams/state-machines.md](diagrams/state-machines.md) | Ride, driver, payment, mock payment, session state machines |
| [diagrams/sequences-auth.md](diagrams/sequences-auth.md) | Registration, login, refresh, logout, request authentication |
| [diagrams/sequences-rides.md](diagrams/sequences-rides.md) | Location, quote, booking, matching, acceptance, trip, cancellation, trip map |
| [diagrams/sequences-payments-ratings.md](diagrams/sequences-payments-ratings.md) | Completion, cash, online/mock QR, ratings |
| [diagrams/sequences-admin.md](diagrams/sequences-admin.md) | Driver review, vehicle, fare and revenue settings, audit |
| [diagrams/realtime.md](diagrams/realtime.md) | Matching worker loop, outbox dispatch, client refresh |
| [diagrams/frontend.md](diagrams/frontend.md) | Route tree and component tree |

## Relationship to the older docs in `docs/`

The repository already contains shorter, topic-specific notes in `docs/` (for example `docs/SESSIONS.md`, `docs/RENDER_DEPLOYMENT.md`, `docs/PRODUCT_BLUEPRINT.md`). Those were left unchanged. This knowledge base supersedes them as a single reference, and points out where they describe **planned** behaviour that the code does not implement (for example, the blueprint mentions Redis and SQL Server, but the running system uses neither). See [17 — Technical decisions](17-technical-decisions.md#documented-plans-vs-actual-implementation).

## Terminology used consistently

| Term | Meaning in this codebase |
| --- | --- |
| **Rider** | Passenger account (`users.role = 'rider'`) |
| **Driver** | Driver account (`users.role = 'driver'`); must be approved by an admin |
| **Admin** | Operator account (`users.role = 'admin'`); cannot self-register |
| **Quote** | A 5-minute, immutable fare estimate (`fare_quotes` row) |
| **Ride** | A booked trip (`rides` row), identified by a UUID string |
| **Invitation** | A pending ride offer to one driver (`ride_invitations` row) |
| **Round** | One 30-second matching window at a given radius (`ride_match_rounds` row) |
| **Active claim** | A row in `active_rides` that marks a user as busy with one ride |
| **Outbox event** | A row in `outbox_events` that the worker turns into a Socket.IO `workspace.changed` push |
| **Workspace** | The JSON snapshot returned by `GET /api/v1/workspace`, and the React screen built from it |
| **Tick** | One iteration of the 1-second background loop (`app/realtime.py::tick`) |
| **Allocation / settlement** | The driver/company split recorded in `revenue_ledger`; it is accounting only, not a money transfer |

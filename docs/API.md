# Local API

Base: `http://127.0.0.1:8787`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Runtime and active job. |
| GET | `/api/bootstrap` | Metadata, settings and 24-node catalog. |
| GET/POST | `/api/projects` | List/create projects. |
| GET/PUT/DELETE | `/api/projects/{id}` | Read/update/delete project and graph. |
| POST | `/api/projects/{id}/export` | Export project package. |
| POST | `/api/agent/plan` | Create and optionally persist a typed DAG from brief/references. |
| GET | `/api/nodes/catalog` | Typed node definitions and capabilities. |
| POST | `/api/workflows/validate` | Structural/port/cycle validation. |
| POST | `/api/workflows/preflight` | Dependency, model, key, workflow and asset readiness. |
| GET | `/api/providers/catalog` | Local/cloud provider catalog. |
| GET | `/api/providers/status` | Binary/server/key/config readiness. |
| POST | `/api/providers/invoke` | Execute an explicit provider diagnostic/generation. |
| GET/POST | `/api/jobs` | List/queue executions. |
| GET | `/api/jobs/{id}` | State/result/error. |
| POST | `/api/jobs/{id}/cancel` | Cancel local subprocess or remote task when supported. |
| POST | `/api/jobs/{id}/retry` | Queue a new copy of the graph. |
| GET | `/api/assets` | Local gallery. |
| POST | `/api/assets/upload` | Limited/sanitized upload. |
| GET | `/media/{asset_id}` | Registered local asset. |
| GET/PATCH | `/api/settings` | Engines, profiles and provider configuration without secrets. |
| GET | `/api/engines/status` | Binary/sidecar checks. |
| GET | `/api/model-profiles` | Profiles and missing files. |
| GET | `/api/governance/snapshot` | Canonical governance source. |
| PATCH | `/api/governance/tasks/{id}` | Status/evidence. |
| GET | `/api/events` | SSE updates. |
| GET/POST | `/api/backups` | List/create backup. |
| POST | `/api/backups/restore` | Validated atomic restore. |

Errors use structured `code`, `message` and optional `detail`. Missing neural dependencies are never converted into placeholder outputs.

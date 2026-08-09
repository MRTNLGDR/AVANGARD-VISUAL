# Governance

The canonical runtime source is `GET /api/governance/snapshot`. It is calculated from SQLite and never replaced by a static success object.

Frontend rules:
- `staleTime: 0` in the React variant.
- polling every 15 seconds.
- refetch on focus.
- SSE on `/api/events`.
- `oraculo:governance-updated` after mutations.

The snapshot contains summary, modules, tasks, alerts, changelog, logs and documents. IDs are permanent. Errors discovered during runtime are logged and jobs retain their error codes/messages.

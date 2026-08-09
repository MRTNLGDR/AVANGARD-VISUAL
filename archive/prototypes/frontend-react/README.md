# React/Vibe integration candidate — not active runtime

This directory records the intended build boundary for the pinned
`SamurAIGPT/Vibe-Workflow/packages/workflow-builder` package and the mandatory
React Query governance route.

The active 0.2 application is `source/frontend` and is served by FastAPI. This
React directory is **not a finished or validated replacement**: the Vibe package
expects Next.js-specific routes and backend contracts that are not yet fully
mapped to CineNode. The governance item `VIBE-EMBED-001` remains pending until:

1. the pinned upstream is materialized;
2. the package is built;
3. its media/API calls are adapted to `/api/providers/*`, `/api/jobs/*` and the
   typed CineNode DAG;
4. the resulting bundle replaces the active frontend and passes the full E2E.

Do not describe this directory as an embedded Vibe runtime.

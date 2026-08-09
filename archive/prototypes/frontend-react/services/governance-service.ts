import type { GovernanceSnapshot } from "../../shared/governance-types";

export async function fetchGovernanceSnapshot(): Promise<GovernanceSnapshot> {
  const response = await fetch("/api/governance/snapshot", {
    headers: { "Cache-Control": "no-cache" },
  });

  if (!response.ok) {
    throw new Error(`Governance bridge returned HTTP ${response.status}`);
  }

  const payload = (await response.json()) as GovernanceSnapshot;

  if (!payload?.summary || !Array.isArray(payload.modules)) {
    throw new Error("Governance bridge returned invalid snapshot");
  }

  return payload;
}

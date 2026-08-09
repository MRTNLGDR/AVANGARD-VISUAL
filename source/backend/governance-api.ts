import type { Request, Response } from "express";
import { readGovernanceSnapshot } from "./governance-snapshot-store";

export async function getGovernanceSnapshot(req: Request, res: Response) {
  const snapshot = await readGovernanceSnapshot();
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Content-Type", "application/json");
  return res.json(snapshot);
}

export type GovernanceState = "READY" | "DEGRADED" | "EMPTY";
export type GovernanceTaskStatus = "PENDING" | "DONE";

export interface GovernanceSummary {
  totalTasks: number;
  doneTasks: number;
  pendingTasks: number;
  openAlerts: number;
  documents: number;
  progressPercent: number;
}

export interface GovernanceModule {
  module_id: string;
  module_title: string;
  done: number;
  total: number;
}

export interface GovernanceTask {
  id: string;
  category: string;
  title: string;
  source_path: string;
  source_line: number;
  status: GovernanceTaskStatus;
}

export interface GovernanceAlert {
  id: string;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  status: "OPEN" | "RESOLVED";
  kind: string;
  fact: string;
  action: string;
}

export interface GovernanceChange {
  release: string;
  category: string;
  description: string;
  source_line: number;
}

export interface GovernanceLog {
  created_at: string;
  level: "INFO" | "WARN" | "ERROR";
  event: string;
  detail: unknown;
}

export interface GovernanceDocument {
  name: string;
  link: string;
  updated_at: string;
}

export interface GovernanceSnapshot {
  generatedAt: string;
  state: GovernanceState;
  summary: GovernanceSummary;
  modules: GovernanceModule[];
  tasks: GovernanceTask[];
  alerts: GovernanceAlert[];
  changelog: GovernanceChange[];
  logs: GovernanceLog[];
  documents: GovernanceDocument[];
}

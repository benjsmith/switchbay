/** Live run record from `/api/runs/active` — shared by App, Zen, and the dashboard. */
export type ActiveRun = {
  run_id: string;
  provider: string;
  model?: string;
  input_excerpt?: string;
  status?: string;
  started_at?: number;
  thread_id?: string;
  workspace?: string;
  workspace_name?: string;
  activity?: string;
  current_tool?: string;
  tool_count?: number;
  step?: string;
  parent_run_id?: string;
  worker_index?: number;
  is_background?: boolean;
  orchestration_strategy?: string;
  node_kind?: string;
  decision_reason?: string;
  expansions?: number;
  verification_conflicts?: number;
};

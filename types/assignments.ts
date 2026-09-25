export type LiveWorkspace = {
  week_start: string; week_end: string; timezone: string; can_export: boolean;
  as_of?: string; maximum_allocation_pct?: string | number; policy_version?: string; request_scope?: string;
  summary: { pending_review: number; approved: number; rejected: number };
  requests: { request_id: string; title: string; project_type?: string | null; priority?: string | null; status: string;
    request_revision: number; responsible_captain_id: string; planned_start_on?: string | null;
    planned_end_on?: string | null; past_planned_end?: boolean; can_close?: boolean }[];
  // Teammate roster entries omit private schedule fields without profile access.
  assignments: { assignment_id: string; request_id: string; person_id: string; full_name: string; role_in_pod: string;
    status: string; starts_on?: string; ends_on?: string; assigned_hours?: number; responsibilities: string;
    staffing_method?: 'AGENT_RECOMMENDATION' | 'MANUAL_OVERRIDE'; close_reason?: string | null }[];
  days: { assignment_id: string; request_id: string; person_id: string; work_date: string; assigned_hours: number }[];
  people: { person_id: string; full_name?: string; allocation_pct: number | null; capacity_status: string; active_pods: number;
    weeks?: { available_hours: string; committed_hours: string; leave_hours?: string; pod_hours?: string;
      reported_pod_hours?: string; external_hours?: string }[] }[];
};

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: 'parent' | 'lawyer' | 'social_worker' | 'admin';
  gcal_scope_granted: boolean;
}

export interface Case {
  id: string;
  case_name: string;
  court_case_no: string | null;
  custody_type: 'sole' | 'joint' | 'split';
  custody_ratio: Record<string, number> | null;
  timezone: string;
  my_relation: 'parent_a' | 'parent_b' | 'lawyer' | 'observer';
  created_at: string;
}

export interface Child {
  id: string;
  display_name: string;
  birth_date: string;
  age_years: number;
  notes: string | null;
}

export interface CustodyEvent {
  id: string;
  starts_at: string;
  ends_at: string;
  custodian_id: string;
  status: 'scheduled' | 'confirmed' | 'in_progress' | 'completed' | 'missed' | 'disputed' | 'cancelled';
  rule_id: string | null;
  handover_location: string | null;
  notes: string | null;
}

export interface CustodyRule {
  id: string;
  rrule: string;
  custodian_id: string;
  start_time: string;
  end_time: string;
  effective_from: string;
  effective_until: string | null;
  source: 'court_order' | 'mutual_agreement' | 'unilateral';
}

export interface AgentMessageResponse {
  session_id: string;
  reply: string;
  actions_taken: AgentAction[];
  requires_clarification: boolean;
  clarification_options: ClarificationOption[];
}

export interface AgentAction {
  tool: string;
  input: Record<string, unknown>;
  result: Record<string, unknown>;
}

export interface ClarificationOption {
  label: string;
  interpretation_note: string;
}

export interface Report {
  id: string;
  pdf_path: string;
  pdf_sha256: string;
  last_audit_id: number;
  last_audit_hash: string;
  generated_at: string;
}

export interface CreateReportRequest {
  period_start: string;
  period_end: string;
  report_type: 'monthly' | 'custom_range' | 'dispute' | 'full_history';
}

export interface CreateCaseRequest {
  case_name: string;
  custody_type: 'sole' | 'joint' | 'split';
  court_case_no?: string;
  timezone?: string;
}

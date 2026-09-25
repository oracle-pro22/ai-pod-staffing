export type OnboardingState = {
  status: 'LEGACY' | 'DRAFT' | 'COMPLETE'; revision: number; full_name: string;
  daily_hours: number; weekly_hours: number;
  staffing_roles?: ('POD_LEAD' | 'POD_MEMBER')[];
  skills?: { interest_id: string; interest_name: string }[];
  deliverables?: { deliverable_id: string; deliverable_name: string; project_name?: string; display_name?: string }[];
};

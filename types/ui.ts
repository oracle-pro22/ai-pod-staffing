import type { ScreenId, StaffingRole } from '@/types/roles';
import type { StaffingRequest } from '@/types/staffing';

export type LocalAvailabilityEntry = {
  id: string;
  personId: string;
  eventType: string;
  startsOn: string;
  endsOn: string;
  title: string;
  allocatedHours: number;
};

export type CalendarAssignment = {
  id: string;
  personId: string;
  requestId: string;
  date: string;
  hours: number;
};

export type Tone = '' | 'red' | 'green' | 'amber' | 'blue' | 'teal' | 'purple';

export type ToastMessage = {
  id: string;
  title: string;
  message: string;
};

export type OverlayDescriptor = {
  id: string;
  title: string;
  payload?: Record<string, unknown>;
};

export type RequestFilters = {
  search: string;
  status: string;
  priority: string;
  projectTypeId: string;
  deliverableId: string;
};

export type StaffingAppState = {
  role: StaffingRole;
  activeScreen: ScreenId;
  activeRequestId: string | null;
  weekOffset: number;
  requestFilters: RequestFilters;
  drawer: OverlayDescriptor | null;
  modal: OverlayDescriptor | null;
  toasts: ToastMessage[];
  drafts: StaffingRequest[];
  localAvailability: LocalAvailabilityEntry[];
  calendarAssignments: CalendarAssignment[];
  selectedCandidatesByRequest: Record<string, string[]>;
  adminTab: 'roles' | 'taxonomy' | 'rules' | 'audit';
  agentRunning: boolean;
};

export type StaffingAppAction =
  | { type: 'set-role'; role: StaffingRole }
  | { type: 'set-screen'; screen: ScreenId }
  | { type: 'set-active-request'; requestId: string | null }
  | { type: 'set-week-offset'; weekOffset: number }
  | { type: 'set-request-filter'; key: keyof RequestFilters; value: string }
  | { type: 'open-drawer'; drawer: OverlayDescriptor }
  | { type: 'close-drawer' }
  | { type: 'open-modal'; modal: OverlayDescriptor }
  | { type: 'close-modal' }
  | { type: 'add-toast'; toast: ToastMessage }
  | { type: 'remove-toast'; id: string }
  | { type: 'add-draft'; request: StaffingRequest }
  | { type: 'add-availability'; entry: LocalAvailabilityEntry }
  | { type: 'add-calendar-assignment'; assignment: CalendarAssignment }
  | { type: 'toggle-candidate'; requestId: string; personId: string }
  | { type: 'set-candidates'; requestId: string; personIds: string[] }
  | { type: 'set-admin-tab'; tab: StaffingAppState['adminTab'] }
  | { type: 'set-agent-running'; running: boolean };

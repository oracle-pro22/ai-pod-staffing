import type { ScreenId, StaffingRole } from '@/types/roles';

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
  | { type: 'toggle-candidate'; requestId: string; personId: string }
  | { type: 'set-candidates'; requestId: string; personIds: string[] }
  | { type: 'set-admin-tab'; tab: StaffingAppState['adminTab'] }
  | { type: 'set-agent-running'; running: boolean };

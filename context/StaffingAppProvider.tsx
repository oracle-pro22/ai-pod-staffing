'use client';

import {
  createContext,
  type Dispatch,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from 'react';

import { canAccessScreen, canPerform, defaultScreen } from '@/lib/role-policy';
import type { StaffingRole } from '@/types/roles';
import { migratePreviewRole } from '@/types/roles';
import type { StaffingViewModel } from '@/types/staffing';
import type { StaffingAppAction, StaffingAppState } from '@/types/ui';

const ROLE_STORAGE_KEY = 'ai-pod-staffing-preview-role';

const initialState: StaffingAppState = {
  role: 'POD Captain',
  activeScreen: 'dashboard',
  activeRequestId: null,
  weekOffset: 0,
  requestFilters: {
    search: '',
    status: '',
    priority: '',
    projectTypeId: '',
    deliverableId: '',
  },
  drawer: null,
  modal: null,
  toasts: [],
  selectedCandidatesByRequest: {},
  adminTab: 'roles',
  agentRunning: false,
};

function staffingAppReducer(state: StaffingAppState, action: StaffingAppAction, authorization: StaffingViewModel['authorization']): StaffingAppState {
  switch (action.type) {
    case 'set-role':
      return {
        ...state,
        role: action.role,
        activeScreen: canAccessScreen(action.role, state.activeScreen, authorization) ? state.activeScreen : defaultScreen(action.role, authorization),
        activeRequestId: null,
        drawer: null,
        modal: null,
        selectedCandidatesByRequest: {},
        agentRunning: false,
        requestFilters: initialState.requestFilters,
        toasts: [],
      };
    case 'set-screen':
      return canAccessScreen(state.role, action.screen, authorization)
        ? { ...state, activeScreen: action.screen, drawer: null, modal: null }
        : state;
    case 'set-active-request':
      return { ...state, activeRequestId: action.requestId };
    case 'set-week-offset':
      return { ...state, weekOffset: action.weekOffset };
    case 'set-request-filter':
      return { ...state, requestFilters: { ...state.requestFilters, [action.key]: action.value } };
    case 'open-drawer':
      if (action.drawer.id === 'add-availability' && !canPerform(state.role, 'MY_AVAILABILITY', 'canCreate', authorization)) return state;
      if (action.drawer.id === 'quick-allocation' && !canPerform(state.role, 'ALLOCATION_CALENDAR', 'canCreate', authorization)) return state;
      return { ...state, drawer: action.drawer };
    case 'close-drawer':
      return { ...state, drawer: null };
    case 'open-modal':
      if (action.modal.id === 'add-person' && (state.role !== 'Administrator' || !canPerform(state.role, 'TEAM_SKILLS', 'canCreate', authorization))) return state;
      if (action.modal.id === 'create-request' && !canPerform(state.role, 'REQUESTS', 'canCreate', authorization)) return state;
      if (action.modal.id === 'approve-pod' && !canPerform(state.role, 'AI_FITMENT', 'canApprove', authorization)) return state;
      return { ...state, modal: action.modal };
    case 'close-modal':
      return { ...state, modal: null };
    case 'add-toast':
      return { ...state, toasts: [...state.toasts, action.toast] };
    case 'remove-toast':
      return { ...state, toasts: state.toasts.filter((toast) => toast.id !== action.id) };
    case 'toggle-candidate': {
      if (!canPerform(state.role, 'AI_FITMENT', 'canUpdate', authorization)) return state;
      const selected = state.selectedCandidatesByRequest[action.requestId] ?? [];
      return {
        ...state,
        selectedCandidatesByRequest: {
          ...state.selectedCandidatesByRequest,
          [action.requestId]: selected.includes(action.personId)
            ? selected.filter((personId) => personId !== action.personId)
            : [...selected, action.personId],
        },
      };
    }
    case 'set-candidates':
      if (!canPerform(state.role, 'AI_FITMENT', 'canUpdate', authorization)) return state;
      return {
        ...state,
        selectedCandidatesByRequest: {
          ...state.selectedCandidatesByRequest,
          [action.requestId]: action.personIds,
        },
      };
    case 'set-admin-tab':
      return { ...state, adminTab: action.tab };
    case 'set-agent-running':
      if (action.running && !canPerform(state.role, 'AGENT_EXECUTION', 'canCreate', authorization)) return state;
      return { ...state, agentRunning: action.running };
    default:
      return state;
  }
}

type StaffingAppContextValue = {
  data: StaffingViewModel;
  state: StaffingAppState;
  dispatch: Dispatch<StaffingAppAction>;
  setRole: (role: StaffingRole) => void;
  notify: (title: string, message: string) => void;
};

const StaffingAppContext = createContext<StaffingAppContextValue | null>(null);

export function StaffingAppProvider({
  data,
  children,
}: {
  data: StaffingViewModel;
  children: ReactNode;
}) {
  const reducer = useMemo(
    () => (state: StaffingAppState, action: StaffingAppAction) => staffingAppReducer(state, action, data.authorization),
    [data.authorization],
  );
  const [state, dispatch] = useReducer(reducer, initialState);
  const storageReady = useRef(false);

  useEffect(() => {
    const storedRole = window.sessionStorage.getItem(ROLE_STORAGE_KEY);
    dispatch({ type: 'set-role', role: migratePreviewRole(storedRole) });
    storageReady.current = true;
  }, []);

  useEffect(() => {
    if (storageReady.current) window.sessionStorage.setItem(ROLE_STORAGE_KEY, state.role);
  }, [state.role]);

  const value = useMemo<StaffingAppContextValue>(() => ({
    data,
    state,
    dispatch,
    setRole: (role) => dispatch({ type: 'set-role', role }),
    notify: (title, message) => dispatch({
      type: 'add-toast',
      toast: { id: window.crypto.randomUUID(), title, message },
    }),
  }), [data, state]);

  return <StaffingAppContext.Provider value={value}>{children}</StaffingAppContext.Provider>;
}

export function useStaffingApp(): StaffingAppContextValue {
  const context = useContext(StaffingAppContext);
  if (!context) throw new Error('useStaffingApp must be used within StaffingAppProvider.');
  return context;
}

import type { NavigationItem, ScreenAccess, ScreenId, StaffingRole } from '@/types/roles';
import type { StaffingViewModel } from '@/types/staffing';
import { ROLE_CODES } from '@/types/roles';

export const NAVIGATION_ITEMS: readonly NavigationItem[] = [
  { id: 'dashboard', icon: 'home', label: 'Command Center', route: '/' },
  { id: 'requests', icon: 'file', label: 'Requests', route: '/requests' },
  { id: 'fitment', icon: 'spark', label: 'AI Fitment', route: '/ai-fitment' },
  { id: 'calendar', icon: 'calendar', label: 'Allocation Calendar', route: '/allocation-calendar' },
  { id: 'interests', icon: 'people', label: 'Team & Skills', route: '/team-skills' },
  { id: 'availability', icon: 'clock', label: 'My Availability', route: '/availability' },
  { id: 'agent', icon: 'play', label: 'Agent Execution', route: '/agent-execution' },
  { id: 'reports', icon: 'chart', label: 'Reports', route: '/reports' },
  { id: 'admin', icon: 'settings', label: 'Administration', route: '/administration' },
] as const;

const SCOPED_ROLES = new Set<StaffingRole>(['POD Lead', 'POD Member']);

const SCREEN_RESOURCE: Record<ScreenId, string> = {
  dashboard: 'DASHBOARD',
  requests: 'REQUESTS',
  fitment: 'AI_FITMENT',
  calendar: 'ALLOCATION_CALENDAR',
  interests: 'TEAM_SKILLS',
  availability: 'MY_AVAILABILITY',
  agent: 'AGENT_EXECUTION',
  reports: 'REPORTS',
  admin: 'ADMINISTRATION',
};

type Authorization = StaffingViewModel['authorization'];

export function isScopedRole(role: StaffingRole): boolean {
  return SCOPED_ROLES.has(role);
}

export function rolePermission(role: StaffingRole, resource: string, authorization?: Authorization) {
  return authorization?.roles
    .find((item) => item.code === ROLE_CODES[role] && item.name === role && item.active)
    ?.permissions.find((permission) => permission.resourceCode === resource);
}

export type PermissionAction = 'canView' | 'canCreate' | 'canUpdate' | 'canApprove' | 'canExport' | 'canAdminister';

export function canPerform(role: StaffingRole, resource: string, action: PermissionAction, authorization?: Authorization): boolean {
  const permission = rolePermission(role, resource, authorization);
  return Boolean(permission && permission.accessScope !== 'locked' && permission.canView && permission[action]);
}

export function defaultScreen(role: StaffingRole, authorization?: Authorization): ScreenId {
  return NAVIGATION_ITEMS.find((item) => canAccessScreen(role, item.id, authorization))?.id ?? 'dashboard';
}

export function personaLandingScreen(role: StaffingRole, authorization?: Authorization): ScreenId {
  const preferred: Record<StaffingRole, ScreenId> = {
    'POD Captain': 'dashboard', 'POD Lead': 'requests', 'POD Member': 'interests', Administrator: 'admin',
  };
  return canAccessScreen(role, preferred[role], authorization) ? preferred[role] : defaultScreen(role, authorization);
}

export function canAccessScreen(role: StaffingRole, screen: ScreenId, authorization?: Authorization): boolean {
  return canPerform(role, SCREEN_RESOURCE[screen], 'canView', authorization);
}

export function getScreenAccess(role: StaffingRole, screen: ScreenId, authorization?: Authorization): ScreenAccess {
  const permission = rolePermission(role, SCREEN_RESOURCE[screen], authorization);
  return permission?.canView ? permission.accessScope : 'locked';
}

export function identityPersonId(
  role: StaffingRole,
  demoIdentity: { podMemberPersonId: string; podLeadPersonId: string },
): string {
  return role === 'POD Lead' ? demoIdentity.podLeadPersonId : demoIdentity.podMemberPersonId;
}

export function screenLabel(screen: ScreenId): string {
  return NAVIGATION_ITEMS.find((item) => item.id === screen)?.label ?? 'Workspace';
}


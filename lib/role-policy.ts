import type { NavigationItem, ScreenAccess, ScreenId, StaffingRole } from '@/types/roles';
import type { StaffingViewModel } from '@/types/staffing';

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

const SCOPED_ROLES = new Set<StaffingRole>(['Pod Lead', 'POD Member']);
const RESTRICTED_SCREENS = new Set<ScreenId>(['calendar', 'agent', 'reports', 'admin']);

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

function databasePermission(role: StaffingRole, screen: ScreenId, authorization?: Authorization) {
  if (!authorization?.roles.length) return undefined;
  return authorization.roles
    .find((item) => item.name === role && item.active)
    ?.permissions.find((permission) => permission.resourceCode === SCREEN_RESOURCE[screen]);
}

export function canAccessScreen(role: StaffingRole, screen: ScreenId, authorization?: Authorization): boolean {
  const permission = databasePermission(role, screen, authorization);
  if (permission) return permission.canView && permission.accessScope !== 'locked';
  return !(isScopedRole(role) && RESTRICTED_SCREENS.has(screen));
}

export function getScreenAccess(role: StaffingRole, screen: ScreenId, authorization?: Authorization): ScreenAccess {
  const permission = databasePermission(role, screen, authorization);
  if (permission) return permission.canView ? permission.accessScope : 'locked';
  if (!canAccessScreen(role, screen, authorization)) return 'locked';
  if (role === 'POD Member' && (screen === 'interests' || screen === 'availability')) return 'own';
  if (isScopedRole(role) && (screen === 'dashboard' || screen === 'requests' || screen === 'fitment' || screen === 'interests' || screen === 'availability')) return 'scoped';
  return 'full';
}

export function identityPersonId(
  role: StaffingRole,
  demoIdentity: { podMemberPersonId: string; podLeadPersonId: string },
): string {
  return role === 'Pod Lead' ? demoIdentity.podLeadPersonId : demoIdentity.podMemberPersonId;
}

export function screenLabel(screen: ScreenId): string {
  return NAVIGATION_ITEMS.find((item) => item.id === screen)?.label ?? 'Workspace';
}


import type { NavigationItem, ScreenAccess, ScreenId, StaffingRole } from '@/types/roles';

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

export function isScopedRole(role: StaffingRole): boolean {
  return SCOPED_ROLES.has(role);
}

export function canAccessScreen(role: StaffingRole, screen: ScreenId): boolean {
  return !(isScopedRole(role) && RESTRICTED_SCREENS.has(screen));
}

export function getScreenAccess(role: StaffingRole, screen: ScreenId): ScreenAccess {
  if (!canAccessScreen(role, screen)) return 'locked';
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


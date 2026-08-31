export const STAFFING_ROLES = [
  'Operations Lead',
  'Request Lead',
  'Pod Lead',
  'POD Member',
  'Executive',
  'System Administrator',
] as const;

export type StaffingRole = (typeof STAFFING_ROLES)[number];

export const SCREEN_IDS = [
  'dashboard',
  'requests',
  'fitment',
  'calendar',
  'interests',
  'availability',
  'agent',
  'reports',
  'admin',
] as const;

export type ScreenId = (typeof SCREEN_IDS)[number];

export type NavigationIconName =
  | 'home'
  | 'file'
  | 'spark'
  | 'calendar'
  | 'people'
  | 'clock'
  | 'play'
  | 'chart'
  | 'settings';

export type NavigationItem = {
  id: ScreenId;
  icon: NavigationIconName;
  label: string;
  route: string;
};

export type ScreenAccess = 'full' | 'scoped' | 'own' | 'locked';

export function isStaffingRole(value: unknown): value is StaffingRole {
  return typeof value === 'string' && STAFFING_ROLES.includes(value as StaffingRole);
}


export const STAFFING_ROLES = [
  'POD Captain',
  'POD Lead',
  'POD Member',
  'Administrator',
] as const;

export type StaffingRole = (typeof STAFFING_ROLES)[number];

export const ROLE_CODES: Record<StaffingRole, string> = {
  'POD Captain': 'POD_CAPTAIN',
  'POD Lead': 'POD_LEAD',
  'POD Member': 'POD_MEMBER',
  Administrator: 'SYSTEM_ADMINISTRATOR',
};

/** Browser preview preferences only; never use legacy aliases to authorize APIs. */
export function migratePreviewRole(value: unknown): StaffingRole {
  if (isStaffingRole(value)) return value;
  if (value === 'Pod Lead') return 'POD Lead';
  if (value === 'System Administrator') return 'Administrator';
  return 'POD Captain';
}

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


'use client';

import { useStaffingApp } from '@/context/StaffingAppProvider';
import { ROLE_CODES, STAFFING_ROLES, type StaffingRole } from '@/types/roles';

export function RoleSelector() {
  const { data, state, setRole, notify } = useStaffingApp();
  if (data.identity) {
    return <span className="staffing-persona-current-role" aria-label={`Current profile: ${state.role}`}>{state.role}</span>;
  }
  return (
    <select
      className="staffing-role-select"
      aria-label="Current role"
      value={state.role}
      disabled={Boolean(data.identity)}
      onChange={(event) => {
        const role = event.target.value as StaffingRole;
        setRole(role);
        notify('Role changed', `Viewing the application as ${role}.`);
      }}
    >
      {STAFFING_ROLES.map((role) => <option key={role} disabled={!data.authorization.roles.some((item) => item.code === ROLE_CODES[role] && item.name === role && item.active)}>{role}</option>)}
    </select>
  );
}

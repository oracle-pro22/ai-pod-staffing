'use client';

import { useStaffingApp } from '@/context/StaffingAppProvider';
import { STAFFING_ROLES, type StaffingRole } from '@/types/roles';

export function RoleSelector() {
  const { state, setRole, notify } = useStaffingApp();
  return (
    <select
      className="staffing-role-select"
      aria-label="Current role"
      value={state.role}
      onChange={(event) => {
        const role = event.target.value as StaffingRole;
        setRole(role);
        notify('Role changed', `Viewing the application as ${role}.`);
      }}
    >
      {STAFFING_ROLES.map((role) => <option key={role}>{role}</option>)}
    </select>
  );
}

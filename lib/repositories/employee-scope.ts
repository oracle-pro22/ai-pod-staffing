import 'server-only';

/** Employee selectors exclude standalone administrator accounts, not identities.
 * A person with another effective official staffing profile remains an employee;
 * newly created people without assignments remain available for Request source.
 * All callers use the fixed outer PEOPLE alias p. Never accept a browser alias.
 */
export const EMPLOYEE_SCOPE_SQL = `(
  NOT EXISTS (
    SELECT 1 FROM app_user_roles employee_admin_role
    JOIN app_roles employee_admin_profile ON employee_admin_profile.role_code = employee_admin_role.role_code
    WHERE employee_admin_role.person_id = p.person_id
      AND employee_admin_role.role_code = 'SYSTEM_ADMINISTRATOR'
      AND employee_admin_role.active_flag = 'Y' AND employee_admin_profile.active_flag = 'Y'
      AND employee_admin_role.effective_from <= TRUNC(SYSDATE)
      AND (employee_admin_role.effective_to IS NULL OR employee_admin_role.effective_to >= TRUNC(SYSDATE))
  ) OR EXISTS (
    SELECT 1 FROM app_user_roles employee_staff_role
    JOIN app_roles employee_staff_profile ON employee_staff_profile.role_code = employee_staff_role.role_code
    WHERE employee_staff_role.person_id = p.person_id
      AND employee_staff_role.role_code IN ('POD_CAPTAIN', 'POD_LEAD', 'POD_MEMBER')
      AND employee_staff_role.active_flag = 'Y' AND employee_staff_profile.active_flag = 'Y'
      AND employee_staff_role.effective_from <= TRUNC(SYSDATE)
      AND (employee_staff_role.effective_to IS NULL OR employee_staff_role.effective_to >= TRUNC(SYSDATE))
  )
)`;

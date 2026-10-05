import { validationError } from '@/lib/errors/staffing-api-error';

export const EMPLOYEE_ROLES = ['POD_CAPTAIN', 'POD_LEAD', 'POD_MEMBER', 'SYSTEM_ADMINISTRATOR'] as const;
export type CreatePersonInput = {
  fullName: string; jobTitle: string; location: string; email: string;
  roles: (typeof EMPLOYEE_ROLES[number])[]; enabled: boolean; staffingEligible: boolean;
};

export function validateCreatePerson(value: unknown): CreatePersonInput {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw validationError('Invalid person details.');
  const input = value as Record<string, unknown>;
  function text(key: string, label: string, max: number, required = true): string {
    const result = typeof input[key] === 'string' ? (input[key] as string).trim().replace(/\s+/g, ' ') : '';
    if (required && !result) throw validationError(`${label} is required.`);
    if (new TextEncoder().encode(result).length > max) throw validationError(`${label} must fit within ${max} UTF-8 bytes.`);
    return result;
  }
  const email = text('email', 'Oracle email', 320).toLowerCase();
  if (!/^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@oracle\.com$/.test(email)) throw validationError('Enter a valid Oracle email address.');
  const roles = input.roles;
  if (!Array.isArray(roles) || !roles.length || roles.length > 4 || new Set(roles).size !== roles.length
      || roles.some(role => !EMPLOYEE_ROLES.includes(role))) throw validationError('Select at least one supported role, without duplicates.');
  if (typeof input.enabled !== 'boolean' || typeof input.staffingEligible !== 'boolean') throw validationError('Choose login access and staffing eligibility.');
  if (input.allocationPct !== undefined || input.activePods !== undefined) throw validationError('Allocation and active PODs are calculated from recorded work, not entered when adding an employee.');
  return { fullName: text('fullName', 'Full name', 250), jobTitle: text('jobTitle', 'Job title', 250), location: text('location', 'Location', 150),
    email, roles, enabled: input.enabled, staffingEligible: input.staffingEligible };
}

import { validationError } from '@/lib/errors/staffing-api-error';

export type CreatePersonInput = {
  fullName: string; jobTitle: string; location: string; email: string;
  allocationPct: number; activePods: number;
};

export function validateCreatePerson(value: unknown): CreatePersonInput {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw validationError('Invalid person details.');
  const input = value as Record<string, unknown>;
  function text(key: string, label: string, max: number, required = true): string {
    const result = typeof input[key] === 'string' ? (input[key] as string).trim().replace(/\s+/g, ' ') : '';
    if (required && !result) throw validationError(`${label} is required.`);
    if (result.length > max) throw validationError(`${label} must be ${max} characters or fewer.`);
    return result;
  }
  const email = text('email', 'Email', 320, false).toLowerCase();
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) throw validationError('Enter a valid email address.');
  const allocationPct = input.allocationPct;
  const activePods = input.activePods;
  if (typeof allocationPct !== 'number' || !Number.isFinite(allocationPct) || allocationPct < 0 || allocationPct > 100
    || Math.abs(allocationPct * 100 - Math.round(allocationPct * 100)) > 0.000001) throw validationError('Allocation must be between 0 and 100 with at most two decimal places.');
  if (typeof activePods !== 'number' || !Number.isInteger(activePods) || activePods < 0 || activePods > 99999) throw validationError('Active PODs must be a whole number between 0 and 99,999.');
  return { fullName: text('fullName', 'Full name', 250), jobTitle: text('jobTitle', 'Job title', 250), location: text('location', 'Location', 150), email, allocationPct, activePods };
}

export type AllocationState = 'unknown' | 'within' | 'at' | 'above';

export function policyLimit(value: unknown): number | null {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 && number <= 100 ? number : null;
}

export function allocationState(value: number | null | undefined, limitValue: unknown, known = true): AllocationState {
  const limit = policyLimit(limitValue);
  if (!known || value === null || value === undefined || !Number.isFinite(value) || value < 0 || limit === null) return 'unknown';
  if (Math.abs(value - limit) < 0.0000001) return 'at';
  return value > limit ? 'above' : 'within';
}

export function capacityAttention(person: { allocationPct: number; staffingEligible?: boolean; capacityStatus?: string }, limit: unknown) {
  const state = allocationState(person.allocationPct, limit, person.staffingEligible !== false && (!person.capacityStatus || person.capacityStatus === 'CURRENT'));
  return state === 'at' || state === 'above';
}

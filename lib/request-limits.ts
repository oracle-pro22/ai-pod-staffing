import { validationError } from '@/lib/errors/staffing-error';

// Mirror RequestSnapshot in the Python staffing engine. Contract tests guard parity.
export const REQUEST_LIMITS = { scheduleDays: 366, hours: 100000, leads: 5, members: 20, entries: 100 } as const;
export const EFFORT_HOURS: Record<string, number> = { hours: 1, days: 8, weeks: 40, months: 160 };

export function convertedEffort(value: number, unit: string): number {
  if (Math.abs(value * 100 - Math.round(value * 100)) > 0.000001) {
    throw validationError('Effort values support two decimal places. Select Hours for finer-grained effort.');
  }
  const hours = value * EFFORT_HOURS[unit.toLowerCase()];
  if (!Number.isFinite(hours) || hours <= 0 || hours > REQUEST_LIMITS.hours
      || Math.abs(hours * 100 - Math.round(hours * 100)) > 0.000001) {
    throw validationError('Converted effort must be greater than zero, at most 100,000 hours, and use whole hundredths of an hour.');
  }
  return Math.round(hours * 100) / 100;
}

/** Legacy VARCHAR2 summary only; full objectives remain in their CLOB. */
export function businessContextSummary(value: string): string {
  const encoder = new TextEncoder();
  let bytes = 0, result = '';
  for (const character of value) {
    bytes += encoder.encode(character).length;
    if (bytes > 2000) break;
    result += character;
  }
  return result;
}

export function requestPodCounts(value: string) {
  const match = /^(\d+)\s+leads?\s*\+\s*(\d+)\s+contributors?$/i.exec(value);
  const leads = Number(match?.[1]), contributors = Number(match?.[2]);
  if (!match || leads < 1 || leads > REQUEST_LIMITS.leads || contributors < 0 || contributors > REQUEST_LIMITS.members) {
    throw validationError('Choose 1–5 POD Leads and 0–20 POD Members.');
  }
  return { leads, contributors };
}

export function validateRequestSchedule(start: string, end: string) {
  const first = new Date(`${start}T00:00:00Z`), last = new Date(`${end}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)
      || !Number.isFinite(first.valueOf()) || !Number.isFinite(last.valueOf())
      || first.toISOString().slice(0, 10) !== start || last.toISOString().slice(0, 10) !== end) {
    throw validationError('Provide valid planned start and completion dates.');
  }
  const days = (last.valueOf() - first.valueOf()) / 86400000;
  if (days < 0 || days > REQUEST_LIMITS.scheduleDays) throw validationError('Completion must be on or after the start and no more than 366 days later.');
  if (days < 2 && Array.from({ length: days + 1 }, (_, i) => (first.getUTCDay() + i) % 7).every(day => day === 0 || day === 6)) {
    throw validationError('The schedule must include at least one working day (Monday–Friday).');
  }
}

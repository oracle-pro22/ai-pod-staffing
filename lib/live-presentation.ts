import type { AvailabilityEvent } from '@/types/staffing';

export function allocationMetric(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined || String(value).trim() === '') return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? `${Number(number.toFixed(2))}%` : null;
}

type ScoredMember = { planned_hours: number; factors?: {
  scheduling_algorithm?: string; factors?: Record<string, string>;
} };

export function savedFactorValue(members: ScoredMember[], code: string): number | null {
  const weighted = members.length > 0 && members.every(m => m.factors?.scheduling_algorithm === 'available-days-v2');
  let total = 0, denominator = 0;
  for (const member of members) {
    const raw = member.factors?.factors?.[code];
    const value = raw === undefined || raw === null || String(raw).trim() === '' ? NaN : Number(raw);
    const hours = weighted ? Number(member.planned_hours) : 1;
    if (!Number.isFinite(value) || !Number.isFinite(hours) || hours <= 0) return null;
    total += value * hours; denominator += hours;
  }
  return denominator > 0 ? total / denominator : null;
}

export function liveStatusLabel(status: string) {
  const labels: Record<string, string> = {
    NEEDS_RECOMMENDATION: 'Needs recommendation', READY_FOR_REVIEW: 'Ready for review',
    STAFFED: 'Staffed', CLOSED: 'Closed', APPROVED: 'Approved', REJECTED: 'Rejected',
    CONFIRMED: 'Confirmed', QUEUED: 'Queued', RUNNING: 'Running', FAILED: 'Failed',
    NEEDS_INFORMATION: 'Needs information', NO_FEASIBLE_POD: 'No feasible POD', SUPERSEDED: 'Superseded',
  };
  return labels[status] ?? status.replaceAll('_', ' ').toLowerCase().replace(/^./, c => c.toUpperCase());
}

export function executionProgress(status: string | undefined, events: { stage: string; status: string }[]) {
  if (status === 'READY_FOR_REVIEW') return 6;
  if (events.some(e => e.stage === 'planning')) return 5;
  if (events.some(e => e.stage === 'rules')) return 4;
  if (events.some(e => e.stage === 'evidence')) return 3;
  return events.some(e => e.stage === 'worker') ? 1 : 0;
}

export function weekDays(monday: string) {
  return Array.from({ length: 5 }, (_, i) => shiftDay(monday, i));
}

export function shiftDay(value: string, offset: number) {
  const day = new Date(`${value.slice(0, 10)}T12:00:00Z`);
  day.setUTCDate(day.getUTCDate() + offset);
  return day.toISOString().slice(0, 10);
}

// Availability stores total event hours, not hours per day. Match the backend's
// weekday distribution and preserve cents instead of duplicating multi-day hours.
export function availabilityDayHours(event: AvailabilityEvent, day: string): number | null {
  const start = event.startsOn.slice(0, 10), end = (event.endsOn || event.startsOn).slice(0, 10);
  if (day < start || day > end) return null;
  const total = Number(event.allocatedHours);
  if (!Number.isFinite(total) || total <= 0) return null;
  const dates: string[] = [];
  for (let d = start, i = 0; d <= end && i < 3660; d = shiftDay(d, 1), i++) {
    const weekday = new Date(`${d}T12:00:00Z`).getUTCDay();
    if (weekday !== 0 && weekday !== 6) dates.push(d);
  }
  const index = dates.indexOf(day);
  if (index < 0) return null;
  const cents = Math.round(total * 100);
  return (Math.floor(cents / dates.length) + (index < cents % dates.length ? 1 : 0)) / 100;
}

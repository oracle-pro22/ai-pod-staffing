import type { EstimatedEffort, StaffingRequest } from '@/types/staffing';
import type { Tone } from '@/types/ui';
import { allocationState } from '@/lib/allocation-policy';

export function personAllocationLabel(person: { allocationPct: number; capacityStatus?: string; staffingEligible?: boolean }): string {
  if (person.staffingEligible === false) return 'Not eligible for POD assignment';
  if (person.capacityStatus === 'NO_CAPACITY') return 'No available hours';
  return person.capacityStatus && person.capacityStatus !== 'CURRENT' ? 'Needs refresh' : `${person.allocationPct}%`;
}

export function availabilityEventLabel(value: string): string {
  return value === 'OOO' ? 'Out of office' : value === 'Commitment' ? 'External commitment' : value;
}

function parseWorkbookDate(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12));
}

export function formatDate(value: string): string {
  const date = parseWorkbookDate(value);
  if (!date || Number.isNaN(date.getTime())) return 'Not recorded';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(date);
}

export function formatShortDate(value: string): string {
  const date = parseWorkbookDate(value);
  if (!date || Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(date);
}

export function formatEffort(effort: EstimatedEffort): string {
  const normalizedUnit = effort.value === 1 ? effort.unit.replace(/s$/, '') : effort.unit;
  return `${effort.value} ${normalizedUnit}`;
}

export function requestEffortLabel(request: StaffingRequest): string {
  return request.estimatedEffort?.value > 0
    ? formatEffort(request.estimatedEffort)
    : `${request.estimatedHours} hours`;
}

export function statusTone(status: string): Tone {
  const value = status.toLowerCase();
  if (value.includes('staff') || value.includes('active') || value.includes('approve')) return 'green';
  if (value.includes('review') || value.includes('pending')) return 'teal';
  if (value.includes('recommend')) return 'red';
  return 'amber';
}

export function allocationTone(value: number | null | undefined, limit?: unknown, known = true): Tone {
  const state = allocationState(value, limit, known);
  return state === 'above' ? 'red' : state === 'at' ? 'amber' : state === 'within' ? 'teal' : 'neutral';
}

export function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
}


import type { EstimatedEffort, StaffingRequest } from '@/types/staffing';
import type { Tone } from '@/types/ui';

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

export function allocationTone(value: number): Tone {
  if (value >= 80) return 'red';
  if (value >= 70) return 'amber';
  return '';
}

export function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
}


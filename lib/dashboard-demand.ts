import type { StaffingRequest } from '@/types/staffing';

const statusCode = (value: string) => value.trim().toUpperCase().replace(/\s+/g, '_');
const pending = new Set(['NEEDS_RECOMMENDATION', 'IN_REVIEW', 'READY_FOR_REVIEW', 'PENDING_REVIEW', 'PENDING_APPROVAL']);

export function staffingQueues(requests: StaffingRequest[]) {
  const priority = (value: string) => /high|urgent/i.test(value) ? 0 : /medium/i.test(value) ? 1 : 2;
  return {
    pending: requests.filter(request => pending.has(statusCode(request.status))).sort((a, b) =>
      priority(a.priority) - priority(b.priority) || a.neededBy.localeCompare(b.neededBy) || a.id.localeCompare(b.id)),
    ongoing: requests.filter(request => statusCode(request.status) === 'STAFFED'),
  };
}

export function projectDemand(requests: StaffingRequest[], projectTypeId: string) {
  return staffingQueues(requests).pending.filter(request => !projectTypeId || request.projectType.id === projectTypeId);
}

export function buildDemandWeeks(neededByDates: string[], businessDay: string) {
  const base = new Date(`${businessDay.slice(0, 10)}T00:00:00Z`);
  base.setUTCDate(base.getUTCDate() - (base.getUTCDay() + 6) % 7);
  const weeks = Array.from({ length: 5 }, (_, index) => {
    const start = new Date(base); start.setUTCDate(base.getUTCDate() + index * 7);
    const end = new Date(start); end.setUTCDate(start.getUTCDate() + 6);
    const first = start.toISOString().slice(0, 10), last = end.toISOString().slice(0, 10);
    return { label: start.toLocaleDateString('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric' }),
      count: neededByDates.filter(day => day.slice(0, 10) >= first && day.slice(0, 10) <= last).length };
  });
  const maximum = Math.max(...weeks.map(week => week.count), 1);
  return weeks.map(week => ({ ...week, level: week.count === 0 ? '' : week.count === maximum ? 'v' : week.count / maximum >= 0.5 ? 'h' : 'm' }));
}

type DatedWork = { starts_on: string; ends_on: string };
export type OnboardingDateIssue = { message: string; entryIndex?: number };

function day(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? parsed : null;
}

/** Match the server's date limits without submitting an invalid setup. */
export function onboardingDateIssue(start: string, end: string, work: DatedWork[]): OnboardingDateIssue | null {
  const first = day(start), last = day(end);
  if (!first || !last) return { message: 'Enter valid Period starts and Period ends dates in Current work & leave.' };
  if (end < start) return { message: `Period ends (${end}) must be on or after Period starts (${start}). Correct the confirmation period.` };
  const firstMonday = first.getTime() - ((first.getUTCDay() + 6) % 7) * 86400000;
  const lastSunday = last.getTime() + (6 - (last.getUTCDay() + 6) % 7) * 86400000;
  if ((lastSunday - firstMonday) / 86400000 > 90) {
    return { message: 'The confirmation period can cover at most 13 complete weeks. Choose an earlier Period ends date.' };
  }
  for (const [entryIndex, entry] of work.entries()) {
    const label = `Entry ${entryIndex + 1}`;
    const entryStart = day(entry.starts_on), entryEnd = day(entry.ends_on);
    if (!entryStart || !entryEnd) return { entryIndex, message: `${label}: enter valid Start and End dates.` };
    if (entry.ends_on < entry.starts_on) return { entryIndex, message: `${label}: End (${entry.ends_on}) is before Start (${entry.starts_on}). Set End on or after Start.` };
    if (entry.starts_on < start || entry.ends_on > end) return { entryIndex,
      message: `${label}: ${entry.starts_on} to ${entry.ends_on} falls outside your confirmed period (${start} to ${end}). Change this entry's Start and End dates to fit that period, or extend the confirmation period to include it (up to 13 complete weeks).` };
    if ((entryEnd.getTime() - entryStart.getTime()) / 86400000 > 83) return { entryIndex,
      message: `${label}: ${entry.starts_on} to ${entry.ends_on} is longer than 12 weeks. Split this work or leave into separate entries of at most 12 weeks each.` };
  }
  return null;
}

export const DASHBOARD_GREETING_TIME_ZONE = 'America/New_York';

export type TimeOfDayGreeting = 'Good morning' | 'Good afternoon' | 'Good evening';

export function timeOfDayGreeting(
  date: Date = new Date(),
  timeZone: string = DASHBOARD_GREETING_TIME_ZONE,
): TimeOfDayGreeting {
  const hourPart = new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    hourCycle: 'h23',
    timeZone,
  }).formatToParts(date).find((part) => part.type === 'hour');
  const hour = Number(hourPart?.value ?? 0);

  if (hour >= 5 && hour < 12) return 'Good morning';
  if (hour >= 12 && hour < 17) return 'Good afternoon';
  return 'Good evening';
}

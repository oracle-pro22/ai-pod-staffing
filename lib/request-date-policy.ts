const DEFAULT_BUSINESS_TIME_ZONE = 'Asia/Kolkata';

export function requestBusinessDate(now = new Date()): string {
  const configuredTimeZone = process.env.NEXT_PUBLIC_BUSINESS_TIME_ZONE?.trim() || DEFAULT_BUSINESS_TIME_ZONE;
  let parts: Intl.DateTimeFormatPart[];

  try {
    parts = new Intl.DateTimeFormat('en-US', {
      timeZone: configuredTimeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(now);
  } catch {
    parts = new Intl.DateTimeFormat('en-US', {
      timeZone: DEFAULT_BUSINESS_TIME_ZONE,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(now);
  }

  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

export function isBeforeRequestBusinessDate(value: string, today = requestBusinessDate()): boolean {
  return Boolean(value && value < today);
}

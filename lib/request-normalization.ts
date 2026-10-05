import { validationError } from '@/lib/errors/staffing-error';

// Keep punctuation: C++, C# and C must never resolve to the same skill.
export const catalogueName = (value: string) => value.normalize('NFC').trim().replace(/\s+/g, ' ').toLocaleLowerCase('en-US');

export function uniqueNameIndex<T>(items: T[], name: (item: T) => string): Map<string, T> {
  const result = new Map<string, T>();
  const ambiguous = new Set<string>();
  for (const item of items) {
    const key = catalogueName(name(item));
    if (result.has(key)) ambiguous.add(key);
    else result.set(key, item);
  }
  for (const key of ambiguous) result.delete(key);
  return result;
}

export function normalizeDeliverables<T extends { id: string; name: string; note?: string; custom?: boolean; requestedName?: string }>(items: T[]) {
  const result = new Map<string, T & { requestedNames: string[] }>();
  for (const item of items) {
    const key = item.custom ? `custom:${catalogueName(item.name)}` : `mapped:${item.id}`;
    const previous = result.get(key);
    result.set(key, { ...item,
      note: [...new Set([previous?.note, item.note].filter(Boolean))].join('\n'),
      requestedNames: [...new Set([...(previous?.requestedNames ?? []), item.requestedName ?? item.name])],
    });
  }
  return [...result.values()];
}

export function normalizeCapabilities<T extends { id: string; name: string; custom?: boolean; mandatory?: boolean; requiredStrength: number | null; source: string; originalName?: string }>(items: T[]) {
  const result = new Map<string, T>();
  for (const item of items) {
    const key = item.custom ? `custom:${catalogueName(item.name)}` : `mapped:${item.id}`;
    const previous = result.get(key);
    if (previous && ((previous.mandatory !== false) !== (item.mandatory !== false)
        || previous.requiredStrength !== item.requiredStrength)) {
      throw validationError(`“${item.name}” resolves to the same capability with different requirements. Remove the duplicate and keep one mandatory/strength setting.`);
    }
    result.set(key, previous ? { ...item, ...previous, originalName: previous.originalName ?? item.originalName,
      source: [...new Set([previous.source, item.source])].filter(Boolean).join('; ').slice(0, 250) } : item);
  }
  return [...result.values()];
}

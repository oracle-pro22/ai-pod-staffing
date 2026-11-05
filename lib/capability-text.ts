/** Resolve saved capability references for display without rewriting historical evidence. */
export function capabilityText(text: string, skills: readonly { id: string; name: string }[]): string {
  const names = new Map(skills.filter(skill => skill.id && skill.name).map(skill => [skill.id, skill.name]));
  if (!text || !names.size) return text;
  const ids = [...names.keys()].sort((a, b) => b.length - a.length)
    .map(id => id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  // Match whole identifiers only, not a prefix inside another ID or a word.
  return text.replace(new RegExp(`(?<![\\w-])(?:${ids.join('|')})(?![\\w-])`, 'g'), id => names.get(id)!);
}

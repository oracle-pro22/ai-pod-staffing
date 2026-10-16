import { selectVisiblePeople, selectVisibleRequests } from '@/lib/selectors';
import { canAccessScreen } from '@/lib/role-policy';
import type { StaffingViewModel } from '@/types/staffing';
import type { StaffingRole } from '@/types/roles';

/** Search only the same record allowlists as the destination screens. */
export function globalSearch(data: StaffingViewModel, role: StaffingRole, text: string) {
  const query = text.trim().toLowerCase();
  if (!query) return { requests: [], people: [], skills: [] };
  return {
    requests: selectVisibleRequests(data, role).filter(r => `${r.id} ${r.title}`.toLowerCase().includes(query)),
    people: selectVisiblePeople(data, role).filter(p => `${p.name} ${p.jobTitle} ${p.skills.map(s => s.name).join(' ')}`.toLowerCase().includes(query)),
    skills: canAccessScreen(role, 'interests', data.authorization)
      ? data.catalog.skills.filter(s => s.name.toLowerCase().includes(query)) : [],
  };
}

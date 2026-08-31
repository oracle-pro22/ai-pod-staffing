import { identityPersonId, isScopedRole } from '@/lib/role-policy';
import type { StaffingRole } from '@/types/roles';
import type { StaffingPerson, StaffingRecommendation, StaffingRequest, StaffingViewModel } from '@/types/staffing';

export function selectIdentityPerson(data: StaffingViewModel, role: StaffingRole): StaffingPerson | null {
  const personId = identityPersonId(role, data.demoIdentity);
  return data.people.find((person) => person.id === personId) ?? data.people[0] ?? null;
}

export function selectVisibleRequests(
  data: StaffingViewModel,
  role: StaffingRole,
  drafts: StaffingRequest[] = [],
): StaffingRequest[] {
  const requests = [...data.requests, ...drafts];
  if (!isScopedRole(role)) return requests;
  const person = selectIdentityPerson(data, role);
  if (!person) return [];
  return requests.filter((request) => request.recommendations.some((item) => item.personId === person.id));
}

export function selectVisiblePeople(
  data: StaffingViewModel,
  role: StaffingRole,
  drafts: StaffingRequest[] = [],
): StaffingPerson[] {
  const identity = selectIdentityPerson(data, role);
  if (role === 'POD Member') return identity ? [identity] : [];
  if (role !== 'Pod Lead') return data.people;

  const visibleIds = new Set<string>();
  if (identity) visibleIds.add(identity.id);
  for (const request of selectVisibleRequests(data, role, drafts)) {
    for (const recommendation of request.recommendations) visibleIds.add(recommendation.personId);
  }
  return data.people.filter((person) => visibleIds.has(person.id));
}

export function selectActiveRequest(
  data: StaffingViewModel,
  role: StaffingRole,
  activeRequestId: string | null,
  drafts: StaffingRequest[] = [],
): StaffingRequest | null {
  const requests = selectVisibleRequests(data, role, drafts);
  return requests.find((request) => request.id === activeRequestId)
    ?? requests.find((request) => request.recommendations.length > 0)
    ?? requests[0]
    ?? null;
}

export function selectScopedRecommendations(
  request: StaffingRequest | null,
  data: StaffingViewModel,
  role: StaffingRole,
): StaffingRecommendation[] {
  if (!request) return [];
  if (role !== 'POD Member') return request.recommendations;
  const identity = selectIdentityPerson(data, role);
  return request.recommendations.filter((item) => item.personId === identity?.id);
}

export function selectDashboardMetrics(data: StaffingViewModel, role: StaffingRole, drafts: StaffingRequest[] = []) {
  const requests = selectVisibleRequests(data, role, drafts);
  const people = selectVisiblePeople(data, role, drafts);
  const activeRequests = requests.filter((request) => request.status.toLowerCase() !== 'closed');
  const staffedRequests = activeRequests.filter((request) => request.status.toLowerCase() === 'staffed');
  const pendingRecommendations = requests.reduce(
    (total, request) => total + selectScopedRecommendations(request, data, role)
      .filter((item) => item.decisionStatus.toLowerCase().includes('pending')).length,
    0,
  );

  return {
    openRequests: activeRequests.length,
    highPriorityRequests: requests.filter((request) => /high|urgent/i.test(request.priority)).length,
    averageAllocationPct: people.length
      ? Math.round(people.reduce((total, person) => total + person.allocationPct, 0) / people.length)
      : 0,
    constrainedPeople: people.filter((person) => person.allocationPct >= 70).length,
    staffingProgressPct: activeRequests.length ? Math.round((staffedRequests.length / activeRequests.length) * 100) : 0,
    staffedRequests: staffedRequests.length,
    pendingRecommendations,
  };
}


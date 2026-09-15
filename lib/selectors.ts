import { canAccessScreen, identityPersonId, rolePermission } from '@/lib/role-policy';
import type { StaffingRole } from '@/types/roles';
import type { StaffingPerson, StaffingRecommendation, StaffingRequest, StaffingViewModel } from '@/types/staffing';
import { ROLE_CODES } from '@/types/roles';

export function selectIdentityPerson(data: StaffingViewModel, role: StaffingRole): StaffingPerson | null {
  if (role === 'Administrator') return null;
  const personId = role === 'POD Captain' ? data.demoIdentity.podCaptainPersonId : identityPersonId(role, data.demoIdentity);
  return data.people.find((person) => person.id === personId) ?? null;
}

export function isApprovedAssignment(item: StaffingRecommendation): boolean {
  return item.selected === true && item.decisionStatus.trim().toUpperCase() === 'APPROVED';
}

export function selectVisibleRequests(
  data: StaffingViewModel,
  role: StaffingRole,
): StaffingRequest[] {
  const requests = data.requests;
  if (!canAccessScreen(role, 'requests', data.authorization)) return [];
  if (data.identity) return requests; // Already record-scoped by the authenticated server projection.
  const scope = rolePermission(role, 'REQUESTS', data.authorization)?.accessScope;
  if (scope === 'full') return requests;
  const person = selectIdentityPerson(data, role);
  if (!person) return [];
  if (role === 'POD Captain') return requests.filter((request) => request.requestSourcePersonId === person.id);
  return requests.filter((request) => request.recommendations.some((item) => item.personId === person.id
    && isApprovedAssignment(item) && (role !== 'POD Lead' || /^(pod[ _-]?)?lead$/i.test(item.roleInPod.trim()))));
}

export function selectVisiblePeople(
  data: StaffingViewModel,
  role: StaffingRole,
): StaffingPerson[] {
  if (data.identity && data.identity.role !== role) return [];
  const identity = selectIdentityPerson(data, role);
  const permission = rolePermission(role, 'TEAM_SKILLS', data.authorization);
  if (!permission?.canView || permission.accessScope === 'locked') return [];
  if (role === 'POD Member' || permission.accessScope === 'own') return identity ? [identity] : [];
  if (data.identity) return data.people; // Independent, server-authorized profile allowlist.
  if (permission.accessScope === 'full' && (role === 'POD Captain' || role === 'Administrator')) return data.people;

  const visibleIds = new Set<string>();
  if (identity) visibleIds.add(identity.id);
  for (const request of selectVisibleRequests(data, role)) {
    if (role !== 'POD Lead' || request.status.toUpperCase() !== 'STAFFED'
      || !request.recommendations.some(item => item.personId === identity?.id && isApprovedAssignment(item)
        && /^(pod[ _-]?)?lead$/i.test(item.roleInPod.trim()))) continue;
    for (const recommendation of request.recommendations.filter(isApprovedAssignment)) visibleIds.add(recommendation.personId);
  }
  return data.people.filter((person) => visibleIds.has(person.id));
}

export function selectActiveRequest(
  data: StaffingViewModel,
  role: StaffingRole,
  activeRequestId: string | null,
): StaffingRequest | null {
  const requests = selectVisibleRequests(data, role);
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
  if (!selectVisibleRequests(data, role).some((item) => item.id === request.id)) return [];
  if (rolePermission(role, 'AI_FITMENT', data.authorization)?.accessScope === 'full'
    && canAccessScreen(role, 'fitment', data.authorization)) return request.recommendations;
  if (role === 'POD Lead') return request.recommendations.filter(isApprovedAssignment);
  const identity = selectIdentityPerson(data, role);
  return request.recommendations.filter((item) => item.personId === identity?.id && isApprovedAssignment(item));
}

export function selectDashboardMetrics(data: StaffingViewModel, role: StaffingRole) {
  const requests = selectVisibleRequests(data, role);
  const people = selectVisiblePeople(data, role);
  const knownPeople = people.filter(person => !person.capacityStatus || person.capacityStatus === 'CURRENT');
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
    averageAllocationPct: knownPeople.length
      ? Math.round(knownPeople.reduce((total, person) => total + person.allocationPct, 0) / knownPeople.length)
      : 0,
    constrainedPeople: people.filter((person) => person.allocationPct >= 70).length,
    staffingProgressPct: activeRequests.length ? Math.round((staffedRequests.length / activeRequests.length) * 100) : 0,
    staffedRequests: staffedRequests.length,
    pendingRecommendations: data.identity ? data.metrics.pendingRecommendations : pendingRecommendations,
  };
}

/** Data projection for preview API consumers; not a substitute for authenticated identity. */
export function selectRoleViewModel(data: StaffingViewModel, role: StaffingRole): StaffingViewModel {
  const enabled = data.authorization.roles.some((item) => item.active && item.name === role && item.code === ROLE_CODES[role]);
  const people = enabled ? selectVisiblePeople(data, role) : [];
  const requests = enabled ? selectVisibleRequests(data, role).map((request) => ({
    ...request, recommendations: selectScopedRecommendations(request, data, role).map(item =>
      people.some(person => person.id === item.personId) ? item
        : { ...item, score: 0, rationale: '', matchingSkills: [], factors: [] }),
  })) : [];
  const dashboard = selectDashboardMetrics(data, role);
  return {
    ...data,
    catalog: enabled ? data.catalog : { projects: [], skills: [] },
    people, requests,
    authorization: { roles: data.authorization.roles, userRoles: role === 'Administrator' && enabled ? data.authorization.userRoles : [] },
    integrity: { checked: true, counts: { visible_people: people.length, visible_requests: requests.length } },
    metrics: {
      ...data.metrics,
      projectTypes: enabled ? data.metrics.projectTypes : 0,
      deliverables: enabled ? data.metrics.deliverables : 0,
      skills: enabled ? data.metrics.skills : 0,
      people: people.length, requests: requests.length,
      openRequests: dashboard.openRequests, staffedRequests: dashboard.staffedRequests,
      averageAllocationPct: dashboard.averageAllocationPct, constrainedPeople: dashboard.constrainedPeople,
      pendingRecommendations: dashboard.pendingRecommendations,
    },
  };
}


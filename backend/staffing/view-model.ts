import 'server-only';
import type { NextRequest } from 'next/server';
import { staffingBackend, type BackendIdentity } from './bridge';
import { dataSource } from '@/lib/staffing-data-source';
import { ROLE_CODES, STAFFING_ROLES } from '@/types/roles';
import type { StaffingViewModel, StaffingPermission } from '@/types/staffing';
import type { LiveWorkspace } from '@/types/assignments';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';
import { PERSONA_COOKIE, personaModeEnabled, personaSessionKey } from './persona-mode';
import { liveStatusLabel } from '@/lib/live-presentation';
import { PASSWORD_COOKIE, passwordModeEnabled } from './password-mode';

/** Filter on the server BEFORE any model reaches React/browser. Never serialize raw authorization mappings. */
export async function authenticatedViewModel(request: NextRequest): Promise<StaffingViewModel> {
  const identity = await staffingBackend(request, '/v1/me') as BackendIdentity;
  const role = STAFFING_ROLES.find(r => identity.roles.includes(ROLE_CODES[r]));
  if (!role) throw new StaffingApiError('No active staffing profile.', 403, 'FORBIDDEN');
  const mayView = (resource: string) => identity.permissions.some(p =>
    p.role === ROLE_CODES[role] && p.resource === resource && p.scope !== 'LOCKED' && p.actions.includes('view'));
  const resource = ['REQUESTS', 'TEAM_SKILLS', 'MY_AVAILABILITY'].find(mayView);
  if (!resource) throw new StaffingApiError('No workspace permission.', 403, 'FORBIDDEN');
  const snapshot = await staffingBackend(request, `/v1/workspace?resource=${resource}`) as LiveWorkspace;
  // This independently authorized allowlist must never fall back to the
  // Requests roster. A failure stops serialization rather than widening access.
  const teamSnapshot = mayView('TEAM_SKILLS')
    ? resource === 'TEAM_SKILLS' ? snapshot : await staffingBackend(request, '/v1/workspace?resource=TEAM_SKILLS') as LiveWorkspace
    : null;
  const raw = await dataSource.getViewModel();
  const requestIds = new Set(snapshot.requests.map(r => r.request_id));
  const requestPermission = mayView('REQUESTS');
  const teamScope = identity.permissions.find(p => p.role === ROLE_CODES[role] && p.resource === 'TEAM_SKILLS' && p.actions.includes('view'))?.scope;
  const ownOnly = role === 'POD Member' || teamScope === 'OWN';
  const peopleById = new Map((teamSnapshot?.people ?? []).filter(p => !ownOnly || p.person_id === identity.person_id).map(p => [p.person_id, p]));
  const people = raw.people.filter(p => peopleById.has(p.id)).map(p => ({
    ...p, allocationPct: peopleById.get(p.id)?.allocation_pct ?? 0,
    capacityStatus: peopleById.get(p.id)?.capacity_status === 'CURRENT' && peopleById.get(p.id)?.allocation_pct === null ? 'NO_CAPACITY' : peopleById.get(p.id)?.capacity_status ?? 'UNKNOWN',
    activePods: peopleById.get(p.id)?.active_pods ?? 0,
  }));
  const requests = raw.requests.filter(r => requestPermission && requestIds.has(r.id)).map(r => ({ ...r,
    status: snapshot.requests.find(row => row.request_id === r.id)?.status
      ? liveStatusLabel(snapshot.requests.find(row => row.request_id === r.id)!.status) : r.status,
    pastPlannedEnd: Boolean(snapshot.requests.find(row => row.request_id === r.id)?.past_planned_end),
    recommendations: snapshot.assignments.filter(a => a.request_id === r.id).map(a => ({
      personId: a.person_id, personName: a.full_name, roleInPod: a.role_in_pod === 'POD_LEAD' ? 'POD Lead' : 'POD Member',
      score: 0, rationale: peopleById.has(a.person_id) ? a.responsibilities || ''
        : a.role_in_pod === 'POD_LEAD' ? "Coordinate the POD and guide delivery of the request's deliverables."
          : "Contribute to the request's deliverables with the POD lead.",
      decisionStatus: 'APPROVED', selected: true,
      source: 'Final assignment', matchingSkills: [], factors: [],
    })),
  }));
  const actions: Record<string, keyof StaffingPermission> = { view: 'canView', create: 'canCreate', update: 'canUpdate', approve: 'canApprove', export: 'canExport', administer: 'canAdminister' };
  const roles = raw.authorization.roles.filter(r => identity.roles.includes(r.code)).map(r => ({ ...r, permissions:
    identity.permissions.filter(p => p.role === r.code).map(p => ({
      resourceCode: p.resource, accessScope: p.scope.toLowerCase() as StaffingPermission['accessScope'],
      canView: false, canCreate: false, canUpdate: false, canApprove: false, canExport: false, canAdminister: false,
      ...Object.fromEntries(p.actions.filter(a => actions[a]).map(a => [actions[a], true])),
    })),
  }));
  const known = people.filter(p => p.capacityStatus === 'CURRENT');
  const adminRoles = identity.roles.includes('SYSTEM_ADMINISTRATOR') && identity.permissions.some(p =>
    p.role === 'SYSTEM_ADMINISTRATOR' && p.resource === 'ADMINISTRATION' && p.scope === 'FULL' && p.actions.includes('view'));
  const passwords = passwordModeEnabled();
  const selectedToken = passwords ? request.cookies.get(PASSWORD_COOKIE)?.value : personaModeEnabled() ? request.cookies.get(PERSONA_COOKIE)?.value : undefined;
  return { ...raw, people, requests,
    allocationPeriod: teamSnapshot ? { start: teamSnapshot.week_start, end: teamSnapshot.week_end, timezone: teamSnapshot.timezone } : undefined,
    identity: { personId: identity.person_id, role,
    ...(identity.full_name ? { fullName: identity.full_name } : {}),
    ...(selectedToken ? { sessionMode: passwords ? 'password' as const : 'persona' as const, sessionKey: personaSessionKey(selectedToken) } : {}) },
    demoIdentity: { podCaptainPersonId: identity.person_id, podLeadPersonId: identity.person_id, podMemberPersonId: identity.person_id },
    authorization: { roles: adminRoles ? raw.authorization.roles : roles, userRoles: [] }, integrity: { checked: true, counts: { visible_people: people.length, visible_requests: requests.length } },
    metrics: { ...raw.metrics, people: people.length, requests: requests.length, openRequests: requests.filter(r => r.status !== 'Closed').length,
      staffedRequests: requests.filter(r => r.status === 'Staffed').length, pendingRecommendations: snapshot.summary.pending_review,
      averageAllocationPct: known.length ? Math.round(known.reduce((n, p) => n + Number(p.allocationPct), 0) / known.length) : 0,
      constrainedPeople: known.filter(p => p.allocationPct >= 70).length },
  };
}

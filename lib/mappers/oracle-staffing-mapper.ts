import 'server-only';

import type { DatabaseRow, OracleStaffingSnapshot } from '@/lib/repositories/staffing-repository';
import type {
  CatalogDeliverable,
  EffortUnit,
  PermissionAccessScope,
  RecommendationFactor,
  RequestDeliverable,
  StaffingPermission,
  StaffingViewModel,
} from '@/types/staffing';

function value(row: DatabaseRow, key: string): unknown {
  return row[key.toUpperCase()];
}

function text(row: DatabaseRow, key: string): string {
  const raw = value(row, key);
  return raw === null || raw === undefined ? '' : String(raw).trim();
}

function nullableText(row: DatabaseRow, key: string): string | null {
  const result = text(row, key);
  return result || null;
}

function number(row: DatabaseRow, key: string): number {
  const result = Number(value(row, key));
  return Number.isFinite(result) ? result : 0;
}

function nullableNumber(row: DatabaseRow, key: string): number | null {
  const raw = value(row, key);
  if (raw === null || raw === undefined || raw === '') return null;
  const result = Number(raw);
  return Number.isFinite(result) ? result : null;
}

function yes(row: DatabaseRow, key: string): boolean {
  return text(row, key).toUpperCase() === 'Y' || text(row, key).toLowerCase() === 'yes';
}

function isoDate(row: DatabaseRow, key: string): string {
  const raw = value(row, key);
  if (!raw) return '';
  if (raw instanceof Date) return raw.toISOString().slice(0, 10);
  const parsed = new Date(String(raw));
  return Number.isNaN(parsed.valueOf()) ? String(raw).slice(0, 10) : parsed.toISOString().slice(0, 10);
}

function isoTimestamp(row: DatabaseRow, key: string): string {
  const raw = value(row, key);
  if (!raw) return new Date(0).toISOString();
  if (raw instanceof Date) return raw.toISOString();
  const parsed = new Date(String(raw));
  return Number.isNaN(parsed.valueOf()) ? String(raw) : parsed.toISOString();
}

function json<T>(row: DatabaseRow, key: string, fallback: T): T {
  const raw = value(row, key);
  if (raw === null || raw === undefined || raw === '') return fallback;
  try {
    return typeof raw === 'string' ? JSON.parse(raw) as T : raw as T;
  } catch {
    throw new Error(`Invalid JSON found in ${key.toUpperCase()}.`);
  }
}

function label(valueToFormat: string): string {
  return valueToFormat
    .toLowerCase()
    .replaceAll('_', ' ')
    .replace(/^./, (first) => first.toUpperCase());
}

function effortUnit(row: DatabaseRow): EffortUnit {
  const unit = text(row, 'estimated_effort_unit').toLowerCase();
  return unit === 'days' || unit === 'weeks' || unit === 'months' ? unit : 'hours';
}

function requestedPodSize(row: DatabaseRow): string {
  const leads = nullableNumber(row, 'requested_lead_count');
  const contributors = nullableNumber(row, 'requested_contributor_count');
  if (leads === null && contributors === null) return '';
  const leadLabel = `${leads ?? 0} lead${leads === 1 ? '' : 's'}`;
  const contributorLabel = `${contributors ?? 0} contributor${contributors === 1 ? '' : 's'}`;
  return `${leadLabel} + ${contributorLabel}`;
}

type StoredDeliverable = {
  deliverableId?: string;
  id?: string;
  name?: string;
  note?: string;
  custom?: boolean;
};

function storedDeliverables(row: DatabaseRow, catalogue: Map<string, CatalogDeliverable>): RequestDeliverable[] {
  const parsed = json<StoredDeliverable[]>(row, 'deliverables_json', []);
  const result = parsed.flatMap((item) => {
    const id = String(item.deliverableId ?? item.id ?? '').trim();
    const mapped = catalogue.get(id);
    const name = String(item.name ?? mapped?.name ?? '').trim();
    if (!name) return [];
    return [{
      id: id || `CUSTOM-${name}`,
      name,
      note: String(item.note ?? mapped?.note ?? ''),
      custom: Boolean(item.custom),
    }];
  });
  if (result.length) return result;

  const id = text(row, 'deliverable_id');
  const mapped = catalogue.get(id);
  const name = text(row, 'deliverable') || mapped?.name || '';
  return name ? [{ id, name, note: mapped?.note ?? '' }] : [];
}

function factors(row: DatabaseRow): RecommendationFactor[] {
  return json<Array<Record<string, unknown>>>(row, 'factor_breakdown_json', []).map((item) => ({
    code: String(item.factorCode ?? ''),
    name: String(item.factorName ?? ''),
    weightPct: Number(item.weightPct ?? 0),
    evidenceScore: Number(item.evidenceScore ?? 0),
  })).filter((item) => item.name);
}

function permission(row: DatabaseRow): StaffingPermission {
  const rawScope = text(row, 'access_scope').toLowerCase();
  const accessScope: PermissionAccessScope = rawScope === 'scoped' || rawScope === 'own' || rawScope === 'full'
    ? rawScope
    : 'locked';
  return {
    resourceCode: text(row, 'resource_code'),
    accessScope,
    canView: yes(row, 'can_view'),
    canCreate: yes(row, 'can_create'),
    canUpdate: yes(row, 'can_update'),
    canApprove: yes(row, 'can_approve'),
    canExport: yes(row, 'can_export'),
    canAdminister: yes(row, 'can_administer'),
  };
}

export function buildOracleStaffingViewModel(snapshot: OracleStaffingSnapshot): StaffingViewModel {
  const interestRows = new Map(snapshot.interests.map((row) => [text(row, 'interest_id'), row]));
  const deliverableSkills = new Map<string, DatabaseRow[]>();
  for (const row of snapshot.deliverableSkills) {
    const id = text(row, 'deliverable_id');
    deliverableSkills.set(id, [...(deliverableSkills.get(id) ?? []), row]);
  }

  const skills = snapshot.interests.map((row) => ({
    id: text(row, 'interest_id'),
    name: text(row, 'interest_name'),
    category: text(row, 'category'),
    customerControlled: text(row, 'customer_controlled').toLowerCase() === 'yes',
  }));

  const deliverableCatalogue = new Map<string, CatalogDeliverable>();
  for (const row of snapshot.deliverables) {
    const id = text(row, 'deliverable_id');
    deliverableCatalogue.set(id, {
      id,
      name: text(row, 'deliverable_name'),
      note: text(row, 'customer_note'),
      sourceRow: nullableNumber(row, 'source_row'),
      skills: (deliverableSkills.get(id) ?? []).map((mapping) => {
        const skill = interestRows.get(text(mapping, 'skill_id'));
        return {
          id: text(mapping, 'skill_id'),
          name: skill ? text(skill, 'interest_name') : text(mapping, 'skill_name'),
          category: skill ? text(skill, 'category') : '',
        };
      }),
    });
  }

  const projects = snapshot.projectTypes.map((row) => {
    const id = text(row, 'project_type_id');
    return {
      id,
      name: text(row, 'project_name'),
      description: text(row, 'project_description'),
      sourceRow: nullableNumber(row, 'source_row'),
      deliverables: snapshot.deliverables
        .filter((deliverable) => text(deliverable, 'project_type_id') === id && yes(deliverable, 'active_flag'))
        .map((deliverable) => deliverableCatalogue.get(text(deliverable, 'deliverable_id')))
        .filter((deliverable): deliverable is CatalogDeliverable => Boolean(deliverable)),
    };
  });

  const projectRows = new Map(snapshot.projectTypes.map((row) => [text(row, 'project_type_id'), row]));
  const availabilityByPerson = new Map<string, DatabaseRow[]>();
  for (const row of snapshot.availability) {
    const id = text(row, 'person_id');
    availabilityByPerson.set(id, [...(availabilityByPerson.get(id) ?? []), row]);
  }
  const interestsByPerson = new Map<string, DatabaseRow[]>();
  for (const row of snapshot.personInterests) {
    const id = text(row, 'person_id');
    interestsByPerson.set(id, [...(interestsByPerson.get(id) ?? []), row]);
  }

  const people = snapshot.people.map((row) => {
    const id = text(row, 'person_id');
    return {
      id,
      name: text(row, 'full_name'),
      initials: text(row, 'initials'),
      jobTitle: text(row, 'job_title'),
      location: text(row, 'location'),
      allocationPct: number(row, 'allocation_pct'),
      activePods: number(row, 'active_pods'),
      skills: (interestsByPerson.get(id) ?? []).map((mapping) => {
        const skill = interestRows.get(text(mapping, 'interest_id'));
        return {
          id: text(mapping, 'interest_id'),
          name: skill ? text(skill, 'interest_name') : text(mapping, 'interest_id'),
          category: skill ? text(skill, 'category') : '',
          strength: number(mapping, 'strength'),
          evidence: text(mapping, 'evidence_note'),
          source: text(mapping, 'source'),
        };
      }).sort((a, b) => b.strength - a.strength),
      availability: (availabilityByPerson.get(id) ?? []).map((event) => ({
        eventType: text(event, 'event_type'),
        startsOn: isoDate(event, 'starts_on'),
        endsOn: isoDate(event, 'ends_on'),
        title: text(event, 'title'),
        allocatedHours: number(event, 'allocated_hours'),
      })),
    };
  });

  const personRows = new Map(snapshot.people.map((row) => [text(row, 'person_id'), row]));
  const requirementsByRequest = new Map<string, DatabaseRow[]>();
  for (const row of snapshot.requirements) {
    const id = text(row, 'request_id');
    requirementsByRequest.set(id, [...(requirementsByRequest.get(id) ?? []), row]);
  }
  const recommendationsByRequest = new Map<string, DatabaseRow[]>();
  for (const row of snapshot.recommendations) {
    const id = text(row, 'request_id');
    recommendationsByRequest.set(id, [...(recommendationsByRequest.get(id) ?? []), row]);
  }

  const requests = snapshot.requests.map((row) => {
    const id = text(row, 'request_id');
    const project = projectRows.get(text(row, 'project_type_id'));
    const deliverables = storedDeliverables(row, deliverableCatalogue);
    const primaryDeliverable = deliverables[0] ?? { id: '', name: '', note: '' };
    const requiredSkills = (requirementsByRequest.get(id) ?? []).map((requirement) => ({
      id: text(requirement, 'interest_id') || `CUSTOM-${number(requirement, 'requirement_id')}`,
      name: text(requirement, 'custom_capability_name') || text(requirement, 'skill_name'),
      requiredStrength: nullableNumber(requirement, 'required_strength'),
      source: text(requirement, 'requirement_source'),
      custom: text(requirement, 'capability_source').toUpperCase() === 'CUSTOM',
    }));
    return {
      id,
      title: text(row, 'title'),
      projectType: {
        id: text(row, 'project_type_id'),
        name: text(row, 'project_type') || (project ? text(project, 'project_name') : ''),
        description: text(row, 'project_description') || (project ? text(project, 'project_description') : ''),
      },
      deliverable: primaryDeliverable,
      deliverables,
      requiredSkills,
      ownerName: text(row, 'owner_name'),
      requestSourcePersonId: nullableText(row, 'request_source_person_id'),
      requestSource: text(row, 'request_source'),
      neededBy: isoDate(row, 'needed_by'),
      estimatedHours: number(row, 'estimated_hours'),
      estimatedEffort: { value: number(row, 'estimated_effort_value'), unit: effortUnit(row) },
      estimatedStartDate: isoDate(row, 'estimated_start_date'),
      estimatedCompletionDate: isoDate(row, 'estimated_completion_date'),
      requestedPodSize: requestedPodSize(row),
      priority: label(text(row, 'priority')),
      status: label(text(row, 'status')),
      businessContext: text(row, 'business_context'),
      projectDescription: text(row, 'project_description'),
      businessObjectives: text(row, 'business_objectives'),
      expectedOutcomes: text(row, 'expected_outcomes'),
      mappingVersion: text(row, 'mapping_version'),
      recommendations: (recommendationsByRequest.get(id) ?? []).map((recommendation) => {
        const person = personRows.get(text(recommendation, 'person_id'));
        return {
          personId: text(recommendation, 'person_id'),
          personName: person ? text(person, 'full_name') : text(recommendation, 'person_id'),
          roleInPod: text(recommendation, 'role_in_pod'),
          score: number(recommendation, 'score'),
          rationale: text(recommendation, 'rationale'),
          decisionStatus: text(recommendation, 'decision_status'),
          selected: yes(recommendation, 'selected_flag'),
          source: text(recommendation, 'source'),
          matchingSkills: json<string[]>(recommendation, 'matching_capabilities_json', []),
          factors: factors(recommendation),
        };
      }),
    };
  });

  const permissionsByRole = new Map<string, StaffingPermission[]>();
  for (const row of snapshot.rolePermissions) {
    const code = text(row, 'role_code');
    permissionsByRole.set(code, [...(permissionsByRole.get(code) ?? []), permission(row)]);
  }
  const averageAllocationPct = people.length
    ? Math.round(people.reduce((total, person) => total + person.allocationPct, 0) / people.length)
    : 0;
  const version = text(snapshot.projectTypes[0] ?? {}, 'source_version');

  return {
    source: {
      provider: 'oracle-26ai',
      fileName: 'Oracle Database 26ai',
      modifiedAt: isoTimestamp(snapshot.database, 'database_time'),
      version,
    },
    catalog: { projects, skills },
    people,
    requests,
    metrics: {
      people: people.length,
      projectTypes: projects.length,
      deliverables: projects.reduce((count, project) => count + project.deliverables.length, 0),
      skills: skills.length,
      requests: requests.length,
      openRequests: requests.filter((request) => request.status.toLowerCase() !== 'closed').length,
      staffedRequests: requests.filter((request) => request.status.toLowerCase() === 'staffed').length,
      averageAllocationPct,
      constrainedPeople: people.filter((person) => person.allocationPct >= 70).length,
      pendingRecommendations: requests.flatMap((request) => request.recommendations)
        .filter((recommendation) => recommendation.decisionStatus.toLowerCase().includes('pending')).length,
    },
    demoIdentity: {
      podCaptainPersonId: people.find((person) => person.name.toLowerCase() === 'indranie balkaran')?.id,
      podMemberPersonId: 'P-001', podLeadPersonId: 'P-006',
    },
    authorization: {
      roles: snapshot.roles.filter((role) => yes(role, 'active_flag')).map((role) => ({
        code: text(role, 'role_code'),
        name: text(role, 'role_name'),
        description: text(role, 'role_description'),
        active: yes(role, 'active_flag'),
        permissions: permissionsByRole.get(text(role, 'role_code')) ?? [],
      })),
      userRoles: snapshot.userRoles.map((userRole) => ({
        identitySubject: text(userRole, 'identity_subject'),
        roleCode: text(userRole, 'role_code'),
        personId: nullableText(userRole, 'person_id'),
        active: yes(userRole, 'active_flag'),
      })),
    },
    integrity: {
      checked: true,
      counts: {
        people: snapshot.people.length,
        projectTypes: snapshot.projectTypes.length,
        deliverables: snapshot.deliverables.length,
        skills: snapshot.interests.length,
        deliverableSkills: snapshot.deliverableSkills.length,
        personInterests: snapshot.personInterests.length,
        availability: snapshot.availability.length,
        requests: snapshot.requests.length,
        requirements: snapshot.requirements.length,
        recommendations: snapshot.recommendations.length,
        customerMapping: snapshot.customerMapping.length,
        roles: snapshot.roles.length,
        rolePermissions: snapshot.rolePermissions.length,
        userRoles: snapshot.userRoles.length,
      },
    },
  };
}

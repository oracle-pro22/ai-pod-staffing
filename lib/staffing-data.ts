import 'server-only';

import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import JSZip from 'jszip';

type CellValue = string | number | boolean | null;
type SheetRow = Record<string, CellValue>;

export type StaffingSnapshot = {
  people: SheetRow[];
  interests: SheetRow[];
  personInterests: SheetRow[];
  requests: SheetRow[];
  requirements: SheetRow[];
  availability: SheetRow[];
  recommendations: SheetRow[];
  projectTypes: SheetRow[];
  deliverables: SheetRow[];
  deliverableSkills: SheetRow[];
  customerMapping: SheetRow[];
  workbook: { fileName: string; modifiedAt: string };
};

export type StaffingViewModel = {
  source: { fileName: string; modifiedAt: string; version: string };
  catalog: {
    projects: Array<{
      id: string;
      name: string;
      description: string;
      sourceRow: number | null;
      deliverables: Array<{
        id: string;
        name: string;
        note: string;
        sourceRow: number | null;
        skills: Array<{ id: string; name: string; category: string }>;
      }>;
    }>;
    skills: Array<{ id: string; name: string; category: string; customerControlled: boolean }>;
  };
  people: Array<{
    id: string;
    name: string;
    initials: string;
    jobTitle: string;
    location: string;
    allocationPct: number;
    activePods: number;
    skills: Array<{
      id: string;
      name: string;
      category: string;
      strength: number;
      evidence: string;
      source: string;
    }>;
    availability: Array<{
      eventType: string;
      startsOn: string;
      endsOn: string;
      title: string;
      allocatedHours: number;
    }>;
  }>;
  requests: Array<{
    id: string;
    title: string;
    projectType: { id: string; name: string; description: string };
    deliverable: { id: string; name: string; note: string };
    requiredSkills: Array<{ id: string; name: string; requiredStrength: number | null; source: string }>;
    ownerName: string;
    neededBy: string;
    estimatedHours: number;
    priority: string;
    status: string;
    businessContext: string;
    mappingVersion: string;
    recommendations: Array<{
      personId: string;
      personName: string;
      roleInPod: string;
      score: number;
      rationale: string;
      decisionStatus: string;
      source: string;
      matchingSkills: string[];
    }>;
  }>;
  metrics: {
    people: number;
    projectTypes: number;
    deliverables: number;
    skills: number;
    requests: number;
    openRequests: number;
    staffedRequests: number;
    averageAllocationPct: number;
    constrainedPeople: number;
    pendingRecommendations: number;
  };
  demoIdentity: { podMemberPersonId: string; podLeadPersonId: string };
  integrity: { checked: true; counts: Record<string, number> };
};

const workbookRelativePath = path.join('data', 'ai-pod-staffing-prototype.xlsx');
const sheetNames = {
  people: 'People',
  interests: 'Interests',
  personInterests: 'Person Interests',
  requests: 'Requests',
  requirements: 'Requirements',
  availability: 'Availability',
  recommendations: 'Recommendations',
  projectTypes: 'Project Types',
  deliverables: 'Deliverables',
  deliverableSkills: 'Deliverable Skills',
  customerMapping: 'Customer Mapping',
} as const;

let cache: { modifiedMs: number; snapshot: StaffingSnapshot } | undefined;

function decodeXml(value: string): string {
  return value
    .replace(/&#x([0-9a-f]+);/gi, (_, hex: string) => String.fromCodePoint(Number.parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, decimal: string) => String.fromCodePoint(Number.parseInt(decimal, 10)))
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

function readAttribute(attributes: string, name: string): string | undefined {
  const match = attributes.match(new RegExp(`(?:^|\\s)${name.replace(':', '\\:')}="([^"]*)"`));
  return match ? decodeXml(match[1]) : undefined;
}

function columnIndex(reference: string): number {
  const letters = reference.match(/^[A-Z]+/i)?.[0].toUpperCase() ?? '';
  return [...letters].reduce((value, letter) => value * 26 + letter.charCodeAt(0) - 64, 0) - 1;
}

function parseSharedStrings(xml: string): string[] {
  return [...xml.matchAll(/<(?:\w+:)?si\b[^>]*>([\s\S]*?)<\/(?:\w+:)?si>/g)].map((item) =>
    [...item[1].matchAll(/<(?:\w+:)?t\b[^>]*>([\s\S]*?)<\/(?:\w+:)?t>/g)]
      .map((text) => decodeXml(text[1]))
      .join(''),
  );
}

function parseCell(attributes: string, body: string, sharedStrings: string[]): CellValue {
  const type = readAttribute(attributes, 't');
  const raw = body.match(/<(?:\w+:)?v\b[^>]*>([\s\S]*?)<\/(?:\w+:)?v>/)?.[1];
  if (type === 'inlineStr') {
    const texts = [...body.matchAll(/<(?:\w+:)?t\b[^>]*>([\s\S]*?)<\/(?:\w+:)?t>/g)];
    return texts.map((text) => decodeXml(text[1])).join('');
  }
  if (raw === undefined) return null;
  if (type === 's') return sharedStrings[Number(raw)] ?? '';
  if (type === 'b') return raw === '1';
  if (type === 'str' || type === 'e') return decodeXml(raw);
  const numeric = Number(raw);
  return Number.isNaN(numeric) ? decodeXml(raw) : numeric;
}

function parseSheet(xml: string, sharedStrings: string[]): SheetRow[] {
  const matrix: CellValue[][] = [];
  for (const rowMatch of xml.matchAll(/<(?:\w+:)?row\b[^>]*>([\s\S]*?)<\/(?:\w+:)?row>/g)) {
    const row: CellValue[] = [];
    for (const cellMatch of rowMatch[1].matchAll(/<(?:\w+:)?c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/(?:\w+:)?c>)/g)) {
      const reference = readAttribute(cellMatch[1], 'r') ?? '';
      row[columnIndex(reference)] = parseCell(cellMatch[1], cellMatch[2] ?? '', sharedStrings);
    }
    matrix.push(row);
  }

  const headers = (matrix[0] ?? []).map((value) => String(value ?? '').trim());
  return matrix.slice(1).flatMap((row) => {
    const record: SheetRow = {};
    let hasValue = false;
    headers.forEach((header, index) => {
      if (!header) return;
      const value = row[index] ?? null;
      record[header] = value;
      if (value !== null && value !== '') hasValue = true;
    });
    return hasValue ? [record] : [];
  });
}

async function requiredXml(zip: JSZip, fileName: string): Promise<string> {
  const file = zip.file(fileName);
  if (!file) throw new Error(`Required workbook part "${fileName}" was not found.`);
  return file.async('string');
}

async function readWorkbook(): Promise<StaffingSnapshot> {
  const absolutePath = path.join(process.cwd(), workbookRelativePath);
  const fileStat = await stat(absolutePath);
  if (cache?.modifiedMs === fileStat.mtimeMs) return cache.snapshot;

  const zip = await JSZip.loadAsync(await readFile(absolutePath));
  const [workbookXml, relationshipsXml, sharedStringsXml] = await Promise.all([
    requiredXml(zip, 'xl/workbook.xml'),
    requiredXml(zip, 'xl/_rels/workbook.xml.rels'),
    requiredXml(zip, 'xl/sharedStrings.xml'),
  ]);
  const sharedStrings = parseSharedStrings(sharedStringsXml);

  const relationshipPaths = new Map<string, string>();
  for (const match of relationshipsXml.matchAll(/<Relationship\b([^>]*)\/?\s*>/g)) {
    const id = readAttribute(match[1], 'Id');
    const target = readAttribute(match[1], 'Target');
    if (id && target) {
      const cleanTarget = target.replace(/^\//, '');
      relationshipPaths.set(id, cleanTarget.startsWith('xl/') ? cleanTarget : `xl/${cleanTarget}`);
    }
  }

  const worksheetPaths = new Map<string, string>();
  for (const match of workbookXml.matchAll(/<(?:\w+:)?sheet\b([^>]*)\/?\s*>/g)) {
    const name = readAttribute(match[1], 'name');
    const relationshipId = readAttribute(match[1], 'r:id');
    const target = relationshipId ? relationshipPaths.get(relationshipId) : undefined;
    if (name && target) worksheetPaths.set(name, target);
  }

  const parsedSheets = new Map<string, SheetRow[]>();
  await Promise.all(
    Object.values(sheetNames).map(async (name) => {
      const worksheetPath = worksheetPaths.get(name);
      if (!worksheetPath) throw new Error(`Required worksheet "${name}" was not found.`);
      parsedSheets.set(name, parseSheet(await requiredXml(zip, worksheetPath), sharedStrings));
    }),
  );

  const rows = (name: string) => parsedSheets.get(name) ?? [];
  const snapshot: StaffingSnapshot = {
    people: rows(sheetNames.people),
    interests: rows(sheetNames.interests),
    personInterests: rows(sheetNames.personInterests),
    requests: rows(sheetNames.requests),
    requirements: rows(sheetNames.requirements),
    availability: rows(sheetNames.availability),
    recommendations: rows(sheetNames.recommendations),
    projectTypes: rows(sheetNames.projectTypes),
    deliverables: rows(sheetNames.deliverables),
    deliverableSkills: rows(sheetNames.deliverableSkills),
    customerMapping: rows(sheetNames.customerMapping),
    workbook: { fileName: path.basename(absolutePath), modifiedAt: fileStat.mtime.toISOString() },
  };

  cache = { modifiedMs: fileStat.mtimeMs, snapshot };
  return snapshot;
}

function textValue(row: SheetRow, key: string): string {
  const value = row[key];
  return value === null || value === undefined ? '' : String(value).trim();
}

function numberValue(row: SheetRow, key: string): number {
  const value = Number(row[key]);
  return Number.isFinite(value) ? value : 0;
}

function optionalNumberValue(row: SheetRow, key: string): number | null {
  const raw = row[key];
  if (raw === null || raw === undefined || raw === '') return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function assertWorkbookIntegrity(snapshot: StaffingSnapshot): void {
  const projectIds = new Set(snapshot.projectTypes.map((row) => textValue(row, 'project_type_id')));
  const deliverableIds = new Set(snapshot.deliverables.map((row) => textValue(row, 'deliverable_id')));
  const skillIds = new Set(snapshot.interests.map((row) => textValue(row, 'interest_id')));
  const personIds = new Set(snapshot.people.map((row) => textValue(row, 'person_id')));
  const problems: string[] = [];

  for (const row of snapshot.deliverables) {
    if (!projectIds.has(textValue(row, 'project_type_id'))) problems.push(`Deliverable ${textValue(row, 'deliverable_id')} has no project type.`);
  }
  for (const row of snapshot.deliverableSkills) {
    if (!deliverableIds.has(textValue(row, 'deliverable_id'))) problems.push(`Deliverable-skill row references missing deliverable ${textValue(row, 'deliverable_id')}.`);
    if (!skillIds.has(textValue(row, 'skill_id'))) problems.push(`Deliverable-skill row references missing skill ${textValue(row, 'skill_id')}.`);
  }
  for (const row of snapshot.personInterests) {
    if (!personIds.has(textValue(row, 'person_id'))) problems.push(`Person-skill row references missing person ${textValue(row, 'person_id')}.`);
    if (!skillIds.has(textValue(row, 'interest_id'))) problems.push(`Person-skill row references missing skill ${textValue(row, 'interest_id')}.`);
  }
  for (const row of snapshot.requirements) {
    if (!deliverableIds.has(textValue(row, 'deliverable_id'))) problems.push(`Requirement references missing deliverable ${textValue(row, 'deliverable_id')}.`);
    if (!skillIds.has(textValue(row, 'interest_id'))) problems.push(`Requirement references missing skill ${textValue(row, 'interest_id')}.`);
    if (!textValue(row, 'requirement_source')) problems.push(`Requirement ${textValue(row, 'request_id')} is missing requirement_source.`);
  }
  for (const row of snapshot.recommendations) {
    if (!personIds.has(textValue(row, 'person_id'))) problems.push(`Recommendation references missing person ${textValue(row, 'person_id')}.`);
  }

  if (problems.length) throw new Error(`Workbook integrity check failed: ${problems.slice(0, 8).join(' ')}`);
}

export function buildStaffingViewModel(snapshot: StaffingSnapshot): StaffingViewModel {
  assertWorkbookIntegrity(snapshot);

  const skillRows = new Map(snapshot.interests.map((row) => [textValue(row, 'interest_id'), row]));
  const deliverableSkillRows = new Map<string, SheetRow[]>();
  for (const row of snapshot.deliverableSkills) {
    const id = textValue(row, 'deliverable_id');
    deliverableSkillRows.set(id, [...(deliverableSkillRows.get(id) ?? []), row]);
  }

  const deliverableRows = new Map(snapshot.deliverables.map((row) => [textValue(row, 'deliverable_id'), row]));
  const projectRows = new Map(snapshot.projectTypes.map((row) => [textValue(row, 'project_type_id'), row]));
  const personRows = new Map(snapshot.people.map((row) => [textValue(row, 'person_id'), row]));

  const skills = snapshot.interests.map((row) => ({
    id: textValue(row, 'interest_id'),
    name: textValue(row, 'interest_name'),
    category: textValue(row, 'category'),
    customerControlled: textValue(row, 'customer_controlled').toLowerCase() === 'yes',
  }));

  const projects = snapshot.projectTypes.map((projectRow) => {
    const projectId = textValue(projectRow, 'project_type_id');
    return {
      id: projectId,
      name: textValue(projectRow, 'project_name'),
      description: textValue(projectRow, 'project_description'),
      sourceRow: optionalNumberValue(projectRow, 'source_row'),
      deliverables: snapshot.deliverables
        .filter((row) => textValue(row, 'project_type_id') === projectId)
        .map((row) => {
          const deliverableId = textValue(row, 'deliverable_id');
          return {
            id: deliverableId,
            name: textValue(row, 'deliverable_name'),
            note: textValue(row, 'customer_note'),
            sourceRow: optionalNumberValue(row, 'source_row'),
            skills: (deliverableSkillRows.get(deliverableId) ?? []).map((mapping) => {
              const skill = skillRows.get(textValue(mapping, 'skill_id'));
              return {
                id: textValue(mapping, 'skill_id'),
                name: skill ? textValue(skill, 'interest_name') : textValue(mapping, 'skill_name'),
                category: skill ? textValue(skill, 'category') : '',
              };
            }),
          };
        }),
    };
  });

  const availabilityByPerson = new Map<string, SheetRow[]>();
  for (const row of snapshot.availability) {
    const personId = textValue(row, 'person_id');
    availabilityByPerson.set(personId, [...(availabilityByPerson.get(personId) ?? []), row]);
  }

  const personSkills = new Map<string, StaffingViewModel['people'][number]['skills']>();
  for (const row of snapshot.personInterests) {
    const personId = textValue(row, 'person_id');
    const skill = skillRows.get(textValue(row, 'interest_id'));
    personSkills.set(personId, [
      ...(personSkills.get(personId) ?? []),
      {
        id: textValue(row, 'interest_id'),
        name: skill ? textValue(skill, 'interest_name') : textValue(row, 'interest_id'),
        category: skill ? textValue(skill, 'category') : '',
        strength: numberValue(row, 'strength'),
        evidence: textValue(row, 'evidence_note'),
        source: textValue(row, 'source'),
      },
    ]);
  }

  const people = snapshot.people.map((row) => {
    const personId = textValue(row, 'person_id');
    return {
      id: personId,
      name: textValue(row, 'full_name'),
      initials: textValue(row, 'initials'),
      jobTitle: textValue(row, 'job_title'),
      location: textValue(row, 'location'),
      allocationPct: numberValue(row, 'allocation_pct'),
      activePods: numberValue(row, 'active_pods'),
      skills: (personSkills.get(personId) ?? []).sort((a, b) => b.strength - a.strength),
      availability: (availabilityByPerson.get(personId) ?? []).map((event) => ({
        eventType: textValue(event, 'event_type'),
        startsOn: textValue(event, 'starts_on'),
        endsOn: textValue(event, 'ends_on'),
        title: textValue(event, 'title'),
        allocatedHours: numberValue(event, 'allocated_hours'),
      })),
    };
  });

  const requirementRows = new Map<string, SheetRow[]>();
  for (const row of snapshot.requirements) {
    const requestId = textValue(row, 'request_id');
    requirementRows.set(requestId, [...(requirementRows.get(requestId) ?? []), row]);
  }
  const recommendationRows = new Map<string, SheetRow[]>();
  for (const row of snapshot.recommendations) {
    const requestId = textValue(row, 'request_id');
    recommendationRows.set(requestId, [...(recommendationRows.get(requestId) ?? []), row]);
  }

  const requests = snapshot.requests.map((row) => {
    const requestId = textValue(row, 'request_id');
    const projectRow = projectRows.get(textValue(row, 'project_type_id'));
    const deliverableRow = deliverableRows.get(textValue(row, 'deliverable_id'));
    const requirements = (requirementRows.get(requestId) ?? []).map((requirement) => ({
      id: textValue(requirement, 'interest_id'),
      name: textValue(requirement, 'skill_name'),
      requiredStrength: optionalNumberValue(requirement, 'required_strength'),
      source: textValue(requirement, 'requirement_source'),
    }));
    const requiredNames = new Set(requirements.map((requirement) => requirement.name.toLowerCase()));
    return {
      id: requestId,
      title: textValue(row, 'title'),
      projectType: {
        id: textValue(row, 'project_type_id'),
        name: textValue(row, 'project_type') || (projectRow ? textValue(projectRow, 'project_name') : ''),
        description: projectRow ? textValue(projectRow, 'project_description') : '',
      },
      deliverable: {
        id: textValue(row, 'deliverable_id'),
        name: textValue(row, 'deliverable') || (deliverableRow ? textValue(deliverableRow, 'deliverable_name') : ''),
        note: deliverableRow ? textValue(deliverableRow, 'customer_note') : '',
      },
      requiredSkills: requirements,
      ownerName: textValue(row, 'owner_name'),
      neededBy: textValue(row, 'needed_by'),
      estimatedHours: numberValue(row, 'estimated_hours'),
      priority: textValue(row, 'priority'),
      status: textValue(row, 'status'),
      businessContext: textValue(row, 'business_context'),
      mappingVersion: textValue(row, 'mapping_version'),
      recommendations: (recommendationRows.get(requestId) ?? []).map((recommendation) => {
        const personId = textValue(recommendation, 'person_id');
        const person = personRows.get(personId);
        const matchingSkills = (personSkills.get(personId) ?? [])
          .filter((skill) => requiredNames.has(skill.name.toLowerCase()))
          .map((skill) => skill.name);
        return {
          personId,
          personName: person ? textValue(person, 'full_name') : personId,
          roleInPod: textValue(recommendation, 'role_in_pod'),
          score: numberValue(recommendation, 'score'),
          rationale: textValue(recommendation, 'rationale'),
          decisionStatus: textValue(recommendation, 'decision_status'),
          source: textValue(recommendation, 'source'),
          matchingSkills,
        };
      }),
    };
  });

  const averageAllocationPct = people.length
    ? Math.round(people.reduce((total, person) => total + person.allocationPct, 0) / people.length)
    : 0;
  const version = textValue(snapshot.projectTypes[0] ?? {}, 'source_version');

  return {
    source: { ...snapshot.workbook, version },
    catalog: { projects, skills },
    people,
    requests,
    metrics: {
      people: people.length,
      projectTypes: projects.length,
      deliverables: snapshot.deliverables.length,
      skills: skills.length,
      requests: requests.length,
      openRequests: requests.filter((request) => request.status.toLowerCase() !== 'closed').length,
      staffedRequests: requests.filter((request) => request.status.toLowerCase() === 'staffed').length,
      averageAllocationPct,
      constrainedPeople: people.filter((person) => person.allocationPct >= 70).length,
      pendingRecommendations: snapshot.recommendations.filter((row) => textValue(row, 'decision_status').toLowerCase().includes('pending')).length,
    },
    demoIdentity: { podMemberPersonId: 'P-001', podLeadPersonId: 'P-006' },
    integrity: {
      checked: true,
      counts: {
        people: snapshot.people.length,
        projectTypes: snapshot.projectTypes.length,
        deliverables: snapshot.deliverables.length,
        skills: snapshot.interests.length,
        deliverableSkills: snapshot.deliverableSkills.length,
        requests: snapshot.requests.length,
        requirements: snapshot.requirements.length,
        recommendations: snapshot.recommendations.length,
      },
    },
  };
}

export const dataSource = {
  mode: 'excel-prototype' as const,
  workbookPath: workbookRelativePath.replaceAll('\\', '/'),
  futureDb: { provider: 'Oracle Database 26ai', queryPlaceholder: 'SELECT * FROM staffing.v_staffing_snapshot' },
  getSnapshot: readWorkbook,
  async getViewModel() {
    return buildStaffingViewModel(await readWorkbook());
  },
};

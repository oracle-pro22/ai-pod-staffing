export type StaffingSource = {
  provider: 'excel-prototype' | 'oracle-26ai';
  fileName: string;
  modifiedAt: string;
  version: string;
};

export type WorkbookSource = StaffingSource;

export type CatalogSkill = {
  id: string;
  name: string;
  category: string;
  customerControlled: boolean;
};

export type DeliverableSkill = Pick<CatalogSkill, 'id' | 'name' | 'category'>;

export type CatalogDeliverable = {
  id: string;
  name: string;
  note: string;
  sourceRow: number | null;
  skills: DeliverableSkill[];
};

export type CatalogProject = {
  id: string;
  name: string;
  description: string;
  sourceRow: number | null;
  deliverables: CatalogDeliverable[];
};

export type PersonSkill = {
  id: string;
  name: string;
  category: string;
  strength: number;
  evidence: string;
  source: string;
};

export type AvailabilityEvent = {
  eventType: string;
  startsOn: string;
  endsOn: string;
  title: string;
  allocatedHours: number;
};

export type StaffingPerson = {
  capacityStatus?: string;
  id: string;
  name: string;
  initials: string;
  jobTitle: string;
  location: string;
  allocationPct: number;
  activePods: number;
  skills: PersonSkill[];
  availability: AvailabilityEvent[];
};

export type RequiredCapability = {
  id: string;
  name: string;
  requiredStrength: number | null;
  source: string;
  custom?: boolean;
};

export type StaffingRecommendation = {
  personId: string;
  personName: string;
  roleInPod: string;
  score: number;
  rationale: string;
  decisionStatus: string;
  /** A selected recommendation is not assigned until its decision is approved. */
  selected?: boolean;
  source: string;
  matchingSkills: string[];
  factors: RecommendationFactor[];
};

export type RecommendationFactor = {
  code: string;
  name: string;
  weightPct: number;
  evidenceScore: number;
};

export type PermissionAccessScope = 'full' | 'scoped' | 'own' | 'locked';

export type StaffingPermission = {
  resourceCode: string;
  accessScope: PermissionAccessScope;
  canView: boolean;
  canCreate: boolean;
  canUpdate: boolean;
  canApprove: boolean;
  canExport: boolean;
  canAdminister: boolean;
};

export type StaffingRoleDefinition = {
  code: string;
  name: string;
  description: string;
  active: boolean;
  permissions: StaffingPermission[];
};

export type StaffingUserRole = {
  identitySubject: string;
  roleCode: string;
  personId: string | null;
  active: boolean;
};

export type EffortUnit = 'hours' | 'days' | 'weeks' | 'months';

export type EstimatedEffort = {
  value: number;
  unit: EffortUnit;
};

export type RequestDeliverable = Pick<CatalogDeliverable, 'id' | 'name' | 'note'> & {
  custom?: boolean;
};

export type StaffingRequest = {
  pastPlannedEnd?: boolean;
  id: string;
  title: string;
  projectType: Pick<CatalogProject, 'id' | 'name' | 'description'>;
  /** Compatibility alias retained while the HTML prototype is still active. */
  deliverable: RequestDeliverable;
  deliverables: RequestDeliverable[];
  requiredSkills: RequiredCapability[];
  ownerName: string;
  requestSourcePersonId: string | null;
  requestSource: string;
  neededBy: string;
  estimatedHours: number;
  estimatedEffort: EstimatedEffort;
  estimatedStartDate: string;
  estimatedCompletionDate: string;
  requestedPodSize: string;
  priority: string;
  status: string;
  businessContext: string;
  projectDescription: string;
  businessObjectives: string;
  expectedOutcomes: string;
  mappingVersion: string;
  recommendations: StaffingRecommendation[];
};

export type StaffingMetrics = {
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

export type StaffingViewModel = {
  allocationPeriod?: { start: string; end: string; timezone: string };
  identity?: { personId: string; role: import('./roles').StaffingRole; fullName?: string;
    sessionMode?: 'persona'; sessionKey?: string };
  source: StaffingSource;
  catalog: {
    projects: CatalogProject[];
    skills: CatalogSkill[];
  };
  people: StaffingPerson[];
  requests: StaffingRequest[];
  metrics: StaffingMetrics;
  demoIdentity: {
    podCaptainPersonId?: string;
    podMemberPersonId: string;
    podLeadPersonId: string;
  };
  authorization: {
    roles: StaffingRoleDefinition[];
    userRoles: StaffingUserRole[];
  };
  integrity: {
    checked: true;
    counts: Record<string, number>;
  };
};

export type RequestDraftInput = {
  title: string;
  projectTypeId: string;
  requestSourcePersonId: string;
  projectDescription: string;
  deliverables: RequestDeliverable[];
  priority: string;
  neededBy: string;
  estimatedStartDate: string;
  estimatedCompletionDate: string;
  estimatedEffort: EstimatedEffort;
  requestedPodSize: string;
  requiredCapabilities: RequiredCapability[];
  businessObjectives: string;
  expectedOutcomes: string;
};


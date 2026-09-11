export type SkillAssessmentInput = {
  skillId: string;
  strength: number | null;
  interested: boolean;
  evidence: string;
};

export type SelfSkillsPatch = {
  version: number;
  upserts: SkillAssessmentInput[];
  removeSkillIds: string[];
  deliverableUpserts?: DeliverableExperienceInput[];
  removeDeliverableIds?: string[];
};

export type SelfSkillsProfile = {
  personId: string;
  fullName: string;
  version: number;
  identityMode: 'preview';
  catalogue: { skillId: string; name: string }[];
  skills: (SkillAssessmentInput & { name: string; source: string })[];
  roleCapabilities: { skillId: string; name: string; roleCode: string }[];
  warnings: string[];
  deliverableCatalogue: { deliverableId: string; name: string; projectName: string }[];
  deliverables: (DeliverableExperienceInput & { name: string; projectName: string; active: boolean })[];
};

export const EXPERIENCE_LEVELS = {
  LEARNING: 'Interested in learning',
  SUPPORTED: 'Can deliver with support',
  INDEPENDENT: 'Can deliver independently',
  MENTOR: 'Can guide others',
} as const;
export const CONTRIBUTION_SCOPES = {
  CONTRIBUTOR: 'Contribute to part of the deliverable',
  END_TO_END: 'Deliver end-to-end',
} as const;
export type DeliverableExperienceInput = {
  deliverableId: string;
  experienceLevel: keyof typeof EXPERIENCE_LEVELS;
  contributionScope: keyof typeof CONTRIBUTION_SCOPES;
  interested: boolean;
  experience: string;
};

export const AI_REPHRASE_FIELDS = ['businessObjectives', 'expectedOutcomes'] as const;

export type AiRephraseField = (typeof AI_REPHRASE_FIELDS)[number];

export type AiRephraseContext = {
  requestTitle?: string;
  projectType?: string;
  projectDescription?: string;
  deliverables?: string[];
  businessObjectives?: string;
};

export type AiRephraseRequest = {
  field: AiRephraseField;
  text: string;
  context?: AiRephraseContext;
};

export type AiRephraseResponse = {
  suggestion: string;
};

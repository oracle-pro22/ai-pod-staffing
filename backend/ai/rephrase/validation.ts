import 'server-only';

import { validationError } from '@/lib/errors/staffing-api-error';
import { AI_REPHRASE_FIELDS, type AiRephraseContext, type AiRephraseRequest } from '@/types/ai-rephrase';

export const AI_REPHRASE_MIN_LENGTH = 10;
export const AI_REPHRASE_MAX_LENGTH = 6_000;
export const AI_REPHRASE_MAX_OUTPUT_LENGTH = 8_000;

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw validationError('The submitted information is not valid.');
  }
  return value as Record<string, unknown>;
}

function optionalText(value: unknown, label: string, maxLength: number): string | undefined {
  if (value === null || value === undefined || value === '') return undefined;
  if (typeof value !== 'string') throw validationError(`${label} must be text.`);
  const result = value.trim();
  if (result.length > maxLength) throw validationError(`${label} must be ${maxLength} characters or fewer.`);
  return result || undefined;
}

function context(value: unknown): AiRephraseContext | undefined {
  if (value === null || value === undefined) return undefined;
  const input = record(value);
  const rawDeliverables = input.deliverables;

  if (rawDeliverables !== undefined && !Array.isArray(rawDeliverables)) {
    throw validationError('Deliverables must be a list of names.');
  }
  if (Array.isArray(rawDeliverables) && rawDeliverables.length > 20) {
    throw validationError('No more than 20 deliverables can be supplied for rephrasing context.');
  }

  const deliverables = Array.isArray(rawDeliverables)
    ? rawDeliverables.map((item, index) => {
        const result = optionalText(item, `Deliverable ${index + 1}`, 500);
        if (!result) throw validationError(`Deliverable ${index + 1} cannot be empty.`);
        return result;
      })
    : undefined;

  return {
    requestTitle: optionalText(input.requestTitle, 'Request title', 500),
    projectType: optionalText(input.projectType, 'Project type', 500),
    projectDescription: optionalText(input.projectDescription, 'Project description', 2_000),
    deliverables,
    businessObjectives: optionalText(input.businessObjectives, 'Business objectives context', AI_REPHRASE_MAX_LENGTH),
  };
}

export function validateAiRephrasePayload(value: unknown): AiRephraseRequest {
  const input = record(value);
  const field = input.field;
  if (typeof field !== 'string' || !AI_REPHRASE_FIELDS.includes(field as AiRephraseRequest['field'])) {
    throw validationError('Choose a supported field to rephrase.');
  }

  if (typeof input.text !== 'string') throw validationError('Text to rephrase is required.');
  const text = input.text.trim();
  if (text.length < AI_REPHRASE_MIN_LENGTH) {
    throw validationError(`Enter at least ${AI_REPHRASE_MIN_LENGTH} characters before rephrasing.`);
  }
  if (text.length > AI_REPHRASE_MAX_LENGTH) {
    throw validationError(`Text to rephrase must be ${AI_REPHRASE_MAX_LENGTH} characters or fewer.`);
  }

  return {
    field: field as AiRephraseRequest['field'],
    text,
    context: context(input.context),
  };
}

export function validateAiRephraseSuggestion(value: unknown): string {
  if (typeof value !== 'string') throw new Error('The model did not return a text suggestion.');
  const suggestion = value.trim();
  if (!suggestion) throw new Error('The model returned an empty suggestion.');
  if (suggestion.length > AI_REPHRASE_MAX_OUTPUT_LENGTH) {
    throw new Error('The model suggestion exceeded the permitted length.');
  }
  return suggestion;
}

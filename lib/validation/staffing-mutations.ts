import { validationError } from '@/lib/errors/staffing-api-error';
import type { CreateAvailabilityPayload, CreateRequestPayload } from '@/types/mutations';
import type { EffortUnit, RequestDeliverable, RequiredCapability } from '@/types/staffing';

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const PRIORITIES = new Set(['Low', 'Medium', 'High']);
const EFFORT_UNITS = new Set<EffortUnit>(['hours', 'days', 'weeks', 'months']);
const AVAILABILITY_TYPES = new Set(['OOO', 'Leave', 'Travel', 'Training', 'Reduced hours']);

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw validationError('The submitted information is not valid.');
  return value as Record<string, unknown>;
}

function requiredText(value: unknown, label: string, maxLength: number): string {
  const result = typeof value === 'string' ? value.trim() : '';
  if (!result) throw validationError(`${label} is required.`);
  if (result.length > maxLength) throw validationError(`${label} must be ${maxLength} characters or fewer.`);
  return result;
}

function optionalText(value: unknown, label: string, maxLength: number): string {
  const result = typeof value === 'string' ? value.trim() : '';
  if (result.length > maxLength) throw validationError(`${label} must be ${maxLength} characters or fewer.`);
  return result;
}

function dateText(value: unknown, label: string, required = false): string {
  const result = typeof value === 'string' ? value.trim() : '';
  if (!result && !required) return '';
  if (!DATE_PATTERN.test(result)) throw validationError(`${label} must be a valid date.`);
  const parsed = new Date(`${result}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== result) {
    throw validationError(`${label} must be a valid date.`);
  }
  return result;
}

function positiveNumber(value: unknown, label: string): number {
  const result = Number(value);
  if (!Number.isFinite(result) || result <= 0 || result > 10000) throw validationError(`${label} must be greater than zero.`);
  return result;
}

function deliverables(value: unknown): RequestDeliverable[] {
  if (!Array.isArray(value) || value.length === 0) throw validationError('Add at least one deliverable.');
  const seen = new Set<string>();
  return value.map((item, index) => {
    const entry = record(item);
    const name = requiredText(entry.name, `Deliverable ${index + 1}`, 500);
    const custom = entry.custom === true;
    const id = custom
      ? optionalText(entry.id, `Deliverable ${index + 1} identifier`, 100) || `CUSTOM-DEL-${index + 1}`
      : requiredText(entry.id, `Deliverable ${index + 1} identifier`, 30);
    const key = `${custom ? 'custom' : 'mapped'}:${custom ? name.toLowerCase() : id}`;
    if (seen.has(key)) throw validationError(`Deliverable “${name}” is selected more than once.`);
    seen.add(key);
    return { id, name, note: optionalText(entry.note, `Deliverable ${index + 1} note`, 2000), custom };
  });
}

function capabilities(value: unknown): RequiredCapability[] {
  if (!Array.isArray(value) || value.length === 0) throw validationError('Add at least one required capability.');
  const seen = new Set<string>();
  return value.map((item, index) => {
    const entry = record(item);
    const name = requiredText(entry.name, `Capability ${index + 1}`, 500);
    const custom = entry.custom === true;
    const id = custom
      ? optionalText(entry.id, `Capability ${index + 1} identifier`, 100) || `CUSTOM-SKILL-${index + 1}`
      : requiredText(entry.id, `Capability ${index + 1} identifier`, 30);
    const rawStrength = entry.requiredStrength;
    const requiredStrength = rawStrength === null || rawStrength === undefined || rawStrength === '' ? null : Number(rawStrength);
    if (requiredStrength !== null && (!Number.isFinite(requiredStrength) || requiredStrength < 1 || requiredStrength > 5)) {
      throw validationError(`Capability ${index + 1} strength must be between 1 and 5.`);
    }
    const key = `${custom ? 'custom' : 'mapped'}:${custom ? name.toLowerCase() : id}`;
    if (seen.has(key)) throw validationError(`Capability “${name}” is selected more than once.`);
    seen.add(key);
    return {
      id,
      name,
      requiredStrength,
      source: optionalText(entry.source, `Capability ${index + 1} source`, 250),
      custom,
    };
  });
}

export function validateCreateRequestPayload(value: unknown): CreateRequestPayload {
  const input = record(value);
  const priority = requiredText(input.priority, 'Priority', 30);
  if (!PRIORITIES.has(priority)) throw validationError('Priority must be Low, Medium, or High.');

  const neededBy = dateText(input.neededBy, 'Needed by date', true);
  const estimatedStartDate = dateText(input.estimatedStartDate, 'Estimated start date');
  const estimatedCompletionDate = dateText(input.estimatedCompletionDate, 'Estimated completion date');
  if (estimatedStartDate && estimatedCompletionDate && estimatedCompletionDate < estimatedStartDate) {
    throw validationError('Estimated completion date cannot be before the estimated start date.');
  }

  const effort = record(input.estimatedEffort);
  const unit = typeof effort.unit === 'string' ? effort.unit.toLowerCase() as EffortUnit : 'hours';
  if (!EFFORT_UNITS.has(unit)) throw validationError('Estimated effort unit is not valid.');

  const requestedPodSize = requiredText(input.requestedPodSize, 'Requested pod size', 100);
  if (!/^\d+\s+leads?\s*\+\s*\d+\s+contributors?$/i.test(requestedPodSize)) {
    throw validationError('Requested pod size is not valid.');
  }

  return {
    title: requiredText(input.title, 'Request title', 500),
    projectTypeId: requiredText(input.projectTypeId, 'Project type', 30),
    requestSource: requiredText(input.requestSource, 'Request source', 250),
    projectDescription: optionalText(input.projectDescription, 'Project description', 4000),
    deliverables: deliverables(input.deliverables),
    priority,
    neededBy,
    estimatedStartDate,
    estimatedCompletionDate,
    estimatedEffort: { value: positiveNumber(effort.value, 'Estimated effort'), unit },
    requestedPodSize,
    requiredCapabilities: capabilities(input.requiredCapabilities),
    businessObjectives: requiredText(input.businessObjectives, 'Business objectives', 32000),
    expectedOutcomes: optionalText(input.expectedOutcomes, 'Expected outcomes', 32000),
  };
}

export function validateCreateAvailabilityPayload(value: unknown): CreateAvailabilityPayload {
  const input = record(value);
  const eventType = requiredText(input.eventType, 'Event type', 60);
  if (!AVAILABILITY_TYPES.has(eventType)) throw validationError('Event type is not valid.');
  const startsOn = dateText(input.startsOn, 'Start date', true);
  const endsOn = dateText(input.endsOn, 'End date', true);
  if (endsOn < startsOn) throw validationError('End date cannot be before the start date.');

  const start = new Date(`${startsOn}T00:00:00Z`);
  const end = new Date(`${endsOn}T00:00:00Z`);
  const days = Math.floor((end.valueOf() - start.valueOf()) / 86_400_000) + 1;
  const allocatedHours = Number(input.allocatedHours);
  if (!Number.isFinite(allocatedHours) || allocatedHours < 0 || allocatedHours > days * 24) {
    throw validationError(`Allocated hours must be between 0 and ${days * 24} for the selected dates.`);
  }

  return {
    personId: requiredText(input.personId, 'Person', 30),
    eventType,
    startsOn,
    endsOn,
    title: optionalText(input.title, 'Title', 500) || eventType,
    allocatedHours,
  };
}

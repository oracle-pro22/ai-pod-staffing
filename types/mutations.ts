import type { StaffingRole } from '@/types/roles';
import type { RequestDraftInput } from '@/types/staffing';

export type CreateRequestPayload = RequestDraftInput;

export type CreateAvailabilityPayload = {
  personId: string;
  eventType: string;
  startsOn: string;
  endsOn: string;
  title: string;
  allocatedHours: number;
};

export type StaffingMutationContext = {
  role: StaffingRole;
  actor: string;
};

export type RequestCreatedResult = {
  requestId: string;
};

export type AvailabilityCreatedResult = CreateAvailabilityPayload;

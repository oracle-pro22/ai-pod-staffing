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
  responsibleCaptainId?: string;
  personId?: string;
  authenticated?: boolean;
};

export type RequestCreatedResult = {
  requestId: string;
  agentPending?: boolean;
};

export type AvailabilityCreatedResult = CreateAvailabilityPayload;

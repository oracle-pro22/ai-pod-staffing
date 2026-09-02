import 'server-only';

export class StaffingApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
  ) {
    super(message);
    this.name = 'StaffingApiError';
  }
}

export function validationError(message: string): StaffingApiError {
  return new StaffingApiError(message, 400, 'VALIDATION_ERROR');
}

export function forbiddenError(message = 'You do not have permission to perform this action.'): StaffingApiError {
  return new StaffingApiError(message, 403, 'FORBIDDEN');
}

export function conflictError(message: string): StaffingApiError {
  return new StaffingApiError(message, 409, 'CONFLICT');
}

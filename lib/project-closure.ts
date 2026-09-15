export const CLOSURE_EXPLANATION = 'Future scheduled capacity will be released from tomorrow. Planned hours through today remain in allocation history.';
export const CLOSED_EXPLANATION = 'Planned hours through the closure day remain in history. Later scheduled hours no longer consume capacity.';
export const OVERDUE_EXPLANATION = 'Past planned end date. This project remains open; no extra hours are scheduled automatically.';
export const STAFFING_CHANGED_EVENT = 'staffing-data-changed';

/** Invalidate mounted workspace snapshots; the caller also refreshes server data. */
export function announceStaffingChange() {
  window.dispatchEvent(new Event(STAFFING_CHANGED_EVENT));
}

import type { ReactNode } from 'react';

export function EmptyState({ children, compact = false }: { children: ReactNode; compact?: boolean }) {
  return <div className={`staffing-empty${compact ? ' compact' : ''}`}>{children}</div>;
}


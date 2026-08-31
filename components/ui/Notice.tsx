import type { ReactNode } from 'react';

export function Notice({ icon = '◈', title, children }: { icon?: ReactNode; title: string; children: ReactNode }) {
  return <div className="staffing-notice"><div aria-hidden="true">{icon}</div><div><strong>{title}</strong><p>{children}</p></div></div>;
}

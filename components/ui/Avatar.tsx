import type { HTMLAttributes } from 'react';

export function Avatar({ initials, className = '', ...props }: HTMLAttributes<HTMLDivElement> & { initials: string }) {
  return <div className={`staffing-avatar${className ? ` ${className}` : ''}`} {...props}>{initials}</div>;
}


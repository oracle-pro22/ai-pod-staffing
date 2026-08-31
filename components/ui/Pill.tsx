import type { HTMLAttributes, ReactNode } from 'react';

import type { Tone } from '@/types/ui';

export function Pill({ tone = '', className = '', children, ...props }: HTMLAttributes<HTMLSpanElement> & {
  tone?: Tone;
  children: ReactNode;
}) {
  return <span className={`staffing-pill${tone ? ` ${tone}` : ''}${className ? ` ${className}` : ''}`} {...props}>{children}</span>;
}


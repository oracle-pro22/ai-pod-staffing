import type { HTMLAttributes } from 'react';

import type { Tone } from '@/types/ui';

export function ProgressBar({ value, tone = '', className = '', ...props }: HTMLAttributes<HTMLDivElement> & {
  value: number;
  tone?: Tone;
}) {
  const normalizedValue = Math.max(0, Math.min(value, 100));
  return (
    <div
      className={`staffing-progress${tone ? ` ${tone}` : ''}${className ? ` ${className}` : ''}`}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={normalizedValue}
      {...props}
    >
      <span style={{ width: `${normalizedValue}%` }} />
    </div>
  );
}


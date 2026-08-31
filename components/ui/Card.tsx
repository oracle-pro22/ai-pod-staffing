import type { HTMLAttributes, ReactNode } from 'react';

export function Card({ padded = false, className = '', children, ...props }: HTMLAttributes<HTMLDivElement> & {
  padded?: boolean;
  children: ReactNode;
}) {
  return <div className={`staffing-card${padded ? ' pad' : ''}${className ? ` ${className}` : ''}`} {...props}>{children}</div>;
}

export function CardHeader({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`staffing-card-head${className ? ` ${className}` : ''}`}>{children}</div>;
}

export function CardBody({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`staffing-card-body${className ? ` ${className}` : ''}`}>{children}</div>;
}


import type { ButtonHTMLAttributes, ReactNode } from 'react';

type ButtonVariant = 'default' | 'primary' | 'ghost' | 'warn' | 'danger';
type ButtonSize = 'default' | 'small';

export function Button({
  variant = 'default',
  size = 'default',
  className = '',
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
}) {
  const classes = ['staffing-btn', variant !== 'default' ? variant : '', size === 'small' ? 'sm' : '', className]
    .filter(Boolean)
    .join(' ');
  return <button className={classes} {...props}>{children}</button>;
}


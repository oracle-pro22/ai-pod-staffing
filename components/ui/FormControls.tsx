import { cloneElement, forwardRef, isValidElement, type InputHTMLAttributes, type ReactElement, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes, useId } from 'react';

export function FormGroup({
  label,
  children,
  full = false,
  className = '',
}: {
  label: string;
  children: ReactNode;
  full?: boolean;
  className?: string;
}) {
  const labelId = useId();
  const labelledChild = isValidElement(children)
    ? cloneElement(children as ReactElement<{ 'aria-labelledby'?: string }>, { 'aria-labelledby': labelId })
    : children;
  const classes = ['staffing-form-group', full ? 'full' : '', className].filter(Boolean).join(' ');
  return <div className={classes}><span id={labelId}>{label}</span>{labelledChild}</div>;
}

export const TextField = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function TextField({ className = '', ...props }, ref) {
  return <input ref={ref} className={`staffing-field${className ? ` ${className}` : ''}`} {...props} />;
});

export function SelectField({ className = '', children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={`staffing-select${className ? ` ${className}` : ''}`} {...props}>{children}</select>;
}

export function TextArea({ className = '', ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`staffing-textarea${className ? ` ${className}` : ''}`} {...props} />;
}

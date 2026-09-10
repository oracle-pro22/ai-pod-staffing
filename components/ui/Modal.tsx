'use client';

import type { ReactNode } from 'react';

import { Button } from '@/components/ui/Button';
import { useOverlayFocus } from '@/components/ui/useOverlayFocus';

export function Modal({
  open,
  title,
  description,
  children,
  footer,
  footerNote,
  size = 'default',
  className = '',
  onClose,
}: {
  open: boolean;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  footerNote?: ReactNode;
  size?: 'default' | 'large';
  className?: string;
  onClose: () => void;
}) {
  const modalRef = useOverlayFocus<HTMLElement>(open, onClose);
  if (!open) return null;
  return (
    <div className={`staffing-modal-wrap open${size === 'large' ? ' large' : ''}`} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section ref={modalRef} className={`staffing-modal${size === 'large' ? ' large' : ''}${className ? ` ${className}` : ''}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <div className="staffing-modal-head"><div><h3>{title}</h3>{description ? <p>{description}</p> : null}</div><button className="staffing-icon-btn" onClick={onClose} aria-label="Close dialog">×</button></div>
        <div className="staffing-modal-body">{children}</div>
        <div className={`staffing-modal-foot${footerNote ? ' split' : ''}`}>
          {footerNote ? <span className="staffing-modal-foot-note">{footerNote}</span> : null}
          <div className="staffing-modal-foot-actions">{footer ?? <Button onClick={onClose}>Close</Button>}</div>
        </div>
      </section>
    </div>
  );
}

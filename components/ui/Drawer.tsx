'use client';

import type { ReactNode } from 'react';

import { Button } from '@/components/ui/Button';
import { useOverlayFocus } from '@/components/ui/useOverlayFocus';

export function Drawer({
  open,
  title,
  children,
  footer,
  onClose,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
}) {
  const drawerRef = useOverlayFocus<HTMLElement>(open, onClose);
  if (!open) return null;

  return (
    <>
      <button className="staffing-drawer-backdrop open" aria-label="Close drawer" onClick={onClose} />
      <aside ref={drawerRef} className="staffing-drawer open" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <div className="staffing-drawer-head"><h3>{title}</h3><button className="staffing-icon-btn" onClick={onClose} aria-label="Close drawer">×</button></div>
        <div className="staffing-drawer-body">{children}</div>
        <div className="staffing-drawer-foot">{footer ?? <Button onClick={onClose}>Close</Button>}</div>
      </aside>
    </>
  );
}

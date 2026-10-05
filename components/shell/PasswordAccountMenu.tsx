'use client';

import { useEffect, useRef, useState } from 'react';

import { useStaffingApp } from '@/context/StaffingAppProvider';
import { announcePersonaChange, staffingFetch } from '@/lib/staffing-fetch';

export function PasswordAccountMenu() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const name = data.identity?.fullName || 'My account';
  const initials = name.split(/\s+/).filter(Boolean).map(part => part[0]).join('').slice(0, 2).toUpperCase() || 'ME';

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);

  async function signOut() {
    if (busy) return;
    setBusy(true);
    try {
      const response = await staffingFetch('/api/auth/logout', { method: 'POST', cache: 'no-store' });
      if (!response.ok) throw new Error('Sign out failed');
      announcePersonaChange();
      window.location.assign('/');
    } catch {
      setBusy(false);
      notify('Sign out failed', 'Please try again.');
    }
  }

  return <div className="staffing-account-menu" ref={root}>
    <button type="button" className="staffing-account-trigger" aria-label="Open account menu" aria-haspopup="menu"
      aria-expanded={open} onClick={() => setOpen(value => !value)}>{initials}</button>
    {open && <div className="staffing-account-popover" role="menu">
      <div className="staffing-account-summary"><strong>{name}</strong><span>{state.role}</span></div>
      <button type="button" role="menuitem" onClick={() => { setOpen(false); dispatch({ type: 'open-modal', modal: { id: 'change-password', title: 'Change password' } }); }}>Change password</button>
      <button type="button" role="menuitem" disabled={busy} onClick={() => void signOut()}>{busy ? 'Signing out…' : 'Sign out'}</button>
    </div>}
  </div>;
}

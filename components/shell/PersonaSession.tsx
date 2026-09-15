'use client';

import { useEffect, useState } from 'react';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { announcePersonaChange, staffingFetch } from '@/lib/staffing-fetch';

export function PersonaSessionGuard() {
  const { data } = useStaffingApp();
  useEffect(() => {
    if (data.identity?.sessionMode !== 'persona') return;
    let channel: BroadcastChannel | null = null;
    try {
      if (typeof BroadcastChannel !== 'undefined') channel = new BroadcastChannel('staffing-persona');
    } catch {
      // Focus checks and request binding remain available when channels are blocked.
    }
    const reload = () => window.location.assign('/');
    if (channel) channel.onmessage = reload;
    let lastCheck = 0;
    const check = () => {
      if (document.visibilityState !== 'visible' || Date.now() - lastCheck < 2000) return;
      lastCheck = Date.now();
      void staffingFetch('/api/agentic/me', { cache: 'no-store' }).catch(() => undefined);
    };
    window.addEventListener('focus', check);
    window.addEventListener('pageshow', check);
    document.addEventListener('visibilitychange', check);
    return () => {
      channel?.close(); window.removeEventListener('focus', check);
      window.removeEventListener('pageshow', check); document.removeEventListener('visibilitychange', check);
    };
  }, [data.identity?.sessionMode, data.identity?.sessionKey]);
  return null;
}

export function ChangePersonaButton() {
  const { notify } = useStaffingApp();
  const [busy, setBusy] = useState(false);
  async function change() {
    if (busy) return;
    setBusy(true);
    try {
      const response = await fetch('/api/personas/session', { method: 'DELETE', cache: 'no-store' });
      if (!response.ok) throw new Error('Unable to change profile. Please try again.');
      announcePersonaChange();
      window.location.assign('/');
    } catch {
      setBusy(false); notify('Profile unchanged', 'Unable to change profile. Please try again.');
    }
  }
  return <button type="button" className="staffing-btn" disabled={busy} onClick={() => void change()}>
    {busy ? 'Changing…' : 'Change profile'}
  </button>;
}

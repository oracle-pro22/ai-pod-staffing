'use client';

import { useEffect, useRef, useState } from 'react';
import { announcePersonaChange, staffingFetch } from '@/lib/staffing-fetch';
import '@/styles/password-session.css';

type SessionTiming = { absoluteExpiresAt: string; idleExpiresAt: string };
type Warning = { kind: 'idle' | 'absolute'; seconds: number } | null;

export function PasswordSessionGuard({ sessionKey }: { sessionKey: string }) {
  const [warning, setWarning] = useState<Warning>(null);
  const actions = useRef<{ stay: () => void; signOut: () => void } | null>(null);

  useEffect(() => {
    if (!sessionKey) return;
    let absoluteDeadline = 0;
    let serverIdleDeadline = 0;
    let displayIdleDeadline = 0;
    let lastActivitySent = 0;
    let lastSessionCheck = 0;
    let inFlight = false;
    let checking = false;
    let activityWhileLoading = false;
    let ending = false;
    let disposed = false;
    let channel: BroadcastChannel | null = null;
    try { if (typeof BroadcastChannel !== 'undefined') channel = new BroadcastChannel('staffing-session-activity'); }
    catch { /* Focus checks still synchronize tabs. */ }

    function applyTiming(timing: SessionTiming) {
      const absolute = Date.parse(timing.absoluteExpiresAt);
      const idle = Date.parse(timing.idleExpiresAt);
      if (!Number.isFinite(absolute) || !Number.isFinite(idle) || disposed) return;
      absoluteDeadline = absolute;
      serverIdleDeadline = idle;
      displayIdleDeadline = idle;
      updateWarning();
      if (activityWhileLoading) {
        activityWhileLoading = false;
        void recordActivity(true);
      }
    }

    function updateWarning() {
      if (!absoluteDeadline || !serverIdleDeadline || ending) return;
      const now = Date.now();
      if (now >= Math.min(absoluteDeadline, displayIdleDeadline)) {
        // A second tab may have renewed the idle window. Confirm with the server
        // before revoking the shared session, including when BroadcastChannel is blocked.
        void checkSession();
        return;
      }
      const idleSeconds = Math.ceil((displayIdleDeadline - now) / 1000);
      const absoluteSeconds = Math.ceil((absoluteDeadline - now) / 1000);
      if (absoluteSeconds <= 300 && absoluteSeconds <= idleSeconds) {
        setWarning({ kind: 'absolute', seconds: absoluteSeconds });
      } else if (idleSeconds <= 60 && idleSeconds < absoluteSeconds) {
        setWarning({ kind: 'idle', seconds: idleSeconds });
      } else {
        setWarning(null);
      }
    }

    async function endSession() {
      if (ending || disposed) return;
      ending = true;
      try { await staffingFetch('/api/auth/logout', { method: 'POST', cache: 'no-store' }); }
      catch { /* Server expiry also rejects the cookie when logout cannot be reached. */ }
      announcePersonaChange();
      window.location.assign('/');
    }

    async function checkSession() {
      if (disposed || ending || checking || Date.now() - lastSessionCheck < 5000) return;
      checking = true;
      lastSessionCheck = Date.now();
      try {
        const response = await staffingFetch('/api/auth/session', { cache: 'no-store' });
        if (response.status === 401) { await endSession(); return; }
        if (!response.ok) return;
        applyTiming(await response.json() as SessionTiming);
      } catch { /* The next check or API request will confirm session state. */ }
      finally { checking = false; }
    }

    async function recordActivity(force = false) {
      if (disposed || ending || inFlight || !absoluteDeadline) return;
      const now = Date.now();
      if (!force && now - lastActivitySent < 30000) return;
      inFlight = true;
      lastActivitySent = now;
      try {
        const response = await staffingFetch('/api/auth/session', { method: 'POST', cache: 'no-store' });
        if (!response.ok) { lastActivitySent = 0; displayIdleDeadline = serverIdleDeadline; updateWarning(); return; }
        const timing = await response.json() as SessionTiming;
        applyTiming(timing);
        channel?.postMessage({ sessionKey, timing });
      } catch {
        lastActivitySent = 0;
        displayIdleDeadline = serverIdleDeadline;
        updateWarning();
      } finally { inFlight = false; }
    }

    function userActivity() {
      if (ending) return;
      if (!absoluteDeadline) { activityWhileLoading = true; return; }
      displayIdleDeadline = Date.now() + 300000;
      updateWarning();
      void recordActivity();
    }

    function staySignedIn() {
      if (ending) return;
      displayIdleDeadline = Date.now() + 300000;
      setWarning(null);
      void recordActivity(true);
    }

    function onFocus() {
      if (document.visibilityState === 'visible') void checkSession();
    }

    if (channel) channel.onmessage = event => {
      if (event.data?.sessionKey === sessionKey && event.data?.timing) applyTiming(event.data.timing);
    };
    actions.current = { stay: staySignedIn, signOut: () => { void endSession(); } };
    void checkSession();
    const timer = window.setInterval(updateWarning, 1000);
    for (const event of ['pointerdown', 'pointermove', 'keydown', 'scroll', 'touchstart']) {
      window.addEventListener(event, userActivity, { passive: true });
    }
    window.addEventListener('focus', onFocus);
    window.addEventListener('pageshow', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      disposed = true;
      actions.current = null;
      window.clearInterval(timer);
      channel?.close();
      for (const event of ['pointerdown', 'pointermove', 'keydown', 'scroll', 'touchstart']) window.removeEventListener(event, userActivity);
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('pageshow', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
    };
  }, [sessionKey]);

  if (!warning) return null;
  return <div className="staffing-session-backdrop">
    <section className="staffing-session-dialog" role="alertdialog" aria-modal="true"
      aria-labelledby="staffing-session-title" aria-describedby="staffing-session-description">
      <h2 id="staffing-session-title">{warning.kind === 'idle' ? 'Still working?' : 'Session ending soon'}</h2>
      <p id="staffing-session-description">{warning.kind === 'idle'
        ? `You will be signed out after 5 minutes without activity. ${warning.seconds} seconds remain.`
        : `Your one-hour session ends in ${Math.ceil(warning.seconds / 60)} minute${warning.seconds > 60 ? 's' : ''}. Save your work and sign in again to continue.`}</p>
      <div className="staffing-session-actions">
        {warning.kind === 'idle' && <button type="button" className="staffing-btn primary"
          onClick={() => actions.current?.stay()}>Stay signed in</button>}
        <button type="button" className="staffing-btn" onClick={() => actions.current?.signOut()}>Sign out</button>
      </div>
    </section>
  </div>;
}

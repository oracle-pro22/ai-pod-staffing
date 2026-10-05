'use client';

import { type FormEvent, useEffect, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { FormGroup, TextField } from '@/components/ui/FormControls';
import { Modal } from '@/components/ui/Modal';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { announcePersonaChange, staffingFetch } from '@/lib/staffing-fetch';

export function ChangePasswordModal() {
  const { data, state, dispatch } = useStaffingApp();
  const open = data.identity?.sessionMode === 'password' && state.modal?.id === 'change-password';
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPasswords, setShowPasswords] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setCurrentPassword(''); setNewPassword(''); setConfirmPassword('');
    setShowPasswords(false); setBusy(false); setError('');
  }, [open]);

  const close = () => { if (!busy) dispatch({ type: 'close-modal' }); };

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (newPassword.length < 10) { setError('Use at least 10 characters.'); return; }
    if (!/[a-z]/.test(newPassword) || !/[A-Z]/.test(newPassword)) { setError('Include an uppercase and a lowercase letter.'); return; }
    if (!/\d/.test(newPassword) || !/[^A-Za-z0-9]/.test(newPassword)) { setError('Include a number and a special character.'); return; }
    if (newPassword !== confirmPassword) { setError('The new passwords do not match.'); return; }
    if (newPassword === currentPassword) { setError('Choose a password different from your current password.'); return; }
    setBusy(true); setError('');
    try {
      const response = await staffingFetch('/api/auth/password', { method: 'POST', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ currentPassword, newPassword, confirmPassword }) });
      const result = await response.json().catch(() => null);
      if (!response.ok || result?.ok !== true) throw new Error(typeof result?.error === 'string' ? result.error : 'Password change could not be confirmed.');
      setCurrentPassword(''); setNewPassword(''); setConfirmPassword('');
      try { window.sessionStorage.setItem('staffing-password-changed', '1'); } catch { /* The redirect still completes. */ }
      announcePersonaChange();
      window.location.assign('/');
    } catch (reason) {
      setBusy(false);
      setError(reason instanceof Error ? reason.message : 'Password change could not be confirmed. Try signing in with the new password.');
    }
  }

  return <Modal open={open} title="Change password" description="After the password changes, every signed-in session will end."
    className="staffing-change-password-modal" onClose={close} footer={<><Button type="button" disabled={busy} onClick={close}>Cancel</Button><Button type="submit" form="changePasswordForm" variant="primary" disabled={busy}>{busy ? 'Updating…' : 'Update password'}</Button></>}>
    <form id="changePasswordForm" onSubmit={submit}>
      <div className="staffing-change-password-fields">
        <FormGroup label="Current password" full><TextField autoFocus required disabled={busy} type={showPasswords ? 'text' : 'password'} autoComplete="current-password" maxLength={1024} value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} /></FormGroup>
        <FormGroup label="New password" full><TextField required disabled={busy} type={showPasswords ? 'text' : 'password'} autoComplete="new-password" minLength={10} maxLength={128} value={newPassword} onChange={event => setNewPassword(event.target.value)} /></FormGroup>
        <FormGroup label="Confirm new password" full><TextField required disabled={busy} type={showPasswords ? 'text' : 'password'} autoComplete="new-password" minLength={10} maxLength={128} value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} /></FormGroup>
        <label className="staffing-password-visibility"><input type="checkbox" checked={showPasswords} disabled={busy} onChange={event => setShowPasswords(event.target.checked)} /> Show passwords</label>
        <p className="staffing-password-guidance">Use at least 10 characters with uppercase, lowercase, a number and a special character.</p>
        {error && <p className="staffing-form-error" role="alert">{error}</p>}
      </div>
    </form>
  </Modal>;
}

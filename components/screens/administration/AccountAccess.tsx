'use client';
import { useEffect, useState, type FormEvent } from 'react';
import { staffingFetch } from '@/lib/staffing-fetch';

type Account = { account_id: string; full_name: string; login_email: string; active_flag: string; onboarding_status: string };
export function AccountAccess() {
  const [data, setData] = useState<{ revision: number; accounts: Account[] } | null>(null);
  const [selected, setSelected] = useState<Account | null>(null), [reason, setReason] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [search, setSearch] = useState('');
  async function load() {
    try { const res = await staffingFetch('/api/agentic/admin/accounts'); const body = await res.json();
      if (!res.ok) throw new Error(body.error?.message || body.error || 'Unable to load accounts.'); setData(body.data);
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to load accounts.'); }
  }
  useEffect(() => { void load(); }, []);
  async function save(e: FormEvent) {
    e.preventDefault(); if (!selected || !data || busy) return; setBusy(true); setError('');
    try { const res = await staffingFetch(`/api/agentic/admin/accounts/${selected.account_id}/access`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: selected.active_flag !== 'Y', revision: data.revision, reason }) }); const body = await res.json();
      if (!res.ok) throw new Error(body.error?.message || body.error || 'Access could not be saved.'); setSelected(null); setReason(''); await load();
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to save.'); } finally { setBusy(false); }
  }
  return <section className="roster-management"><h3>Account access</h3><p>Disabling access signs the person out and excludes them from new staffing choices. Existing assignments and history are retained. Roles are not changed here.</p>
    <label>Search accounts <input type="search" value={search} onChange={e => setSearch(e.target.value)} /></label><button type="button" disabled={busy} onClick={() => { setError(''); void load(); }}>Refresh</button>
    {error && <p role="alert" className="roster-error">{error}</p>}
    {selected && <form onSubmit={save}><strong>{selected.active_flag === 'Y' ? 'Disable' : 'Enable'} {selected.full_name}?</strong><p>Sessions will be revoked. An active POD Lead or the last access Administrator cannot be disabled.</p><label>Reason <input required minLength={3} maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></label><button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Confirm change'}</button> <button type="button" disabled={busy} onClick={() => setSelected(null)}>Cancel</button></form>}
    <div className="roster-scroll"><table><thead><tr><th>Person</th><th>Access</th><th>Setup</th><th>Action</th></tr></thead><tbody>{data?.accounts.filter(a => `${a.full_name} ${a.login_email}`.toLowerCase().includes(search.toLowerCase())).map(a => <tr key={a.account_id}><td><strong>{a.full_name}</strong><br />{a.login_email}</td><td>{a.active_flag === 'Y' ? 'Enabled' : 'Disabled'}</td><td>{a.onboarding_status === 'LEGACY' ? 'Existing profile' : a.onboarding_status.toLowerCase()}</td><td><button type="button" disabled={busy} onClick={() => { setSelected(a); setReason(''); }}>{a.active_flag === 'Y' ? 'Disable' : 'Enable'}</button></td></tr>)}</tbody></table></div>
    {!data && !error && <p role="status">Loading accounts…</p>}
  </section>;
}

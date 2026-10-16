'use client';

import { type KeyboardEvent, useState } from 'react';

import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canAccessScreen, screenLabel } from '@/lib/role-policy';
import { globalSearch } from '@/lib/global-search';
import { Modal } from '@/components/ui/Modal';
import { Button } from '@/components/ui/Button';

import { RoleSelector } from './RoleSelector';
import { ChangePersonaButton } from './PersonaSession';
import { PasswordAccountMenu } from './PasswordAccountMenu';

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const { data, state, dispatch } = useStaffingApp();
  const [search, setSearch] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const results = globalSearch(data, state.role, search);

  function runSearch(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== 'Enter' || !search.trim()) return;
    event.preventDefault();
    setSearchOpen(true);
  }

  return (
    <><header className="staffing-topbar">
      <button type="button" className="staffing-menu-btn" onClick={onMenu} aria-label="Open navigation">☰</button>
      <div className="staffing-breadcrumb"><span>AI Pod</span><span>›</span><b>{screenLabel(state.activeScreen)}</b></div>
      <div className="staffing-top-actions">
        <label className="staffing-searchbox">
          <span aria-hidden="true">⌕</span>
          <input
            disabled={!canAccessScreen(state.role, 'requests', data.authorization) && !canAccessScreen(state.role, 'interests', data.authorization)}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={runSearch}
            placeholder="Search requests, people, skills"
            aria-label="Search requests, people, skills"
          />
        </label>
        <RoleSelector />
        {data.identity?.sessionMode === 'password' ? <PasswordAccountMenu /> : data.identity?.sessionMode === 'persona' ? <ChangePersonaButton /> : data.identity &&
          <form method="post" action="/api/auth/logout"><button type="submit" className="staffing-btn">Sign out</button></form>}
        <button
          type="button"
          className="staffing-icon-btn"
          title="Notifications"
          aria-label="Open notifications"
          onClick={() => dispatch({ type: 'open-drawer', drawer: { id: 'notifications', title: 'Notifications' } })}
        >◌</button>
      </div>
    </header>
    <Modal open={searchOpen} title="Search results" description={`Matches for “${search.trim()}” within your access.`} onClose={() => setSearchOpen(false)}>
      <div className="staffing-global-results">
        <h4>Requests ({results.requests.length})</h4>
        {results.requests.map(r => <Button key={r.id} onClick={() => {
          setSearchOpen(false);
          dispatch({ type: 'set-active-request', requestId: r.id });
          dispatch({ type: 'open-drawer', drawer: { id: 'request-details', title: r.title, payload: { requestId: r.id } } });
        }}>{r.id} · {r.title}</Button>)}
        {!results.requests.length && <p className="staffing-muted">No matching requests.</p>}
        <h4>People ({results.people.length})</h4>
        {results.people.map(p => <Button key={p.id} onClick={() => {
          setSearchOpen(false);
          dispatch({ type: 'open-drawer', drawer: { id: 'person-details', title: p.name, payload: { personId: p.id } } });
        }}>{p.name}</Button>)}
        {!results.people.length && <p className="staffing-muted">No matching people.</p>}
        <h4>Skills ({results.skills.length})</h4>
        {results.skills.map(s => <Button key={s.id} onClick={() => {
          setSearchOpen(false);
          dispatch({ type: 'set-team-search', value: s.name });
          dispatch({ type: 'set-screen', screen: 'interests' });
        }}>{s.name} · View people</Button>)}
        {!results.skills.length && <p className="staffing-muted">No matching skills.</p>}
      </div>
    </Modal></>
  );
}

'use client';

import { type KeyboardEvent, useState } from 'react';

import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canAccessScreen, screenLabel } from '@/lib/role-policy';

import { RoleSelector } from './RoleSelector';
import { ChangePersonaButton } from './PersonaSession';

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const { data, state, dispatch, notify } = useStaffingApp();
  const [search, setSearch] = useState('');

  function runSearch(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== 'Enter' || !search.trim()) return;
    if (!canAccessScreen(state.role, 'requests', data.authorization)) return;
    dispatch({ type: 'set-request-filter', key: 'search', value: search.trim() });
    dispatch({ type: 'set-screen', screen: 'requests' });
    notify('Search', `Showing matches for “${search.trim()}”.`);
  }

  return (
    <header className="staffing-topbar">
      <button type="button" className="staffing-menu-btn" onClick={onMenu} aria-label="Open navigation">☰</button>
      <div className="staffing-breadcrumb"><span>AI Pod</span><span>›</span><b>{screenLabel(state.activeScreen)}</b></div>
      <div className="staffing-top-actions">
        <label className="staffing-searchbox">
          <span aria-hidden="true">⌕</span>
          <input
            disabled={!canAccessScreen(state.role, 'requests', data.authorization)}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={runSearch}
            placeholder="Search requests, people, skills"
            aria-label="Search requests, people, skills"
          />
        </label>
        <RoleSelector />
        {data.identity?.sessionMode === 'password' ? <ChangePersonaButton password /> : data.identity?.sessionMode === 'persona' ? <ChangePersonaButton /> : data.identity &&
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
  );
}

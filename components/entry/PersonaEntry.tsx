'use client';

import { type FormEvent, useEffect, useId, useMemo, useRef, useState } from 'react';

import { PersonCombobox } from '@/components/ui/PersonCombobox';
import '@/styles/persona-entry.css';

type PersonaRole = 'POD_CAPTAIN' | 'POD_LEAD' | 'POD_MEMBER' | 'SYSTEM_ADMINISTRATOR';

export type PersonaOption = {
  person_id: string;
  full_name: string;
  role_code: PersonaRole;
  role_name: string;
};

export type PersonaEntryProps = { initialError?: string };

const PROFILES: { code: PersonaRole; name: string; eyebrow: string; description: string }[] = [
  { code: 'POD_CAPTAIN', name: 'POD Captain', eyebrow: 'REQUEST & APPROVAL',
    description: 'Create requests, review recommendations and approve your POD team.' },
  { code: 'POD_LEAD', name: 'POD Lead', eyebrow: 'PROJECT DELIVERY',
    description: 'Lead your assigned projects, work with your team and close completed work.' },
  { code: 'POD_MEMBER', name: 'POD Member', eyebrow: 'TEAM & CONTRIBUTION',
    description: 'View your PODs and keep your skills, interests and availability up to date.' },
  { code: 'SYSTEM_ADMINISTRATOR', name: 'Administrator', eyebrow: 'WORKSPACE MANAGEMENT',
    description: 'Manage people, access and the configuration of your workspace.' },
];

function parsePersonas(value: unknown): PersonaOption[] {
  if (!value || typeof value !== 'object' || !('personas' in value) || !Array.isArray(value.personas)) {
    throw new Error('The people list could not be loaded. Please try again.');
  }
  const result: PersonaOption[] = [];
  const keys = new Set<string>();
  for (const item of value.personas) {
    if (!item || typeof item !== 'object' || typeof item.person_id !== 'string' || !item.person_id
      || typeof item.full_name !== 'string' || !item.full_name.trim()
      || typeof item.role_name !== 'string' || !PROFILES.some((profile) => profile.code === item.role_code)) {
      throw new Error('The people list could not be loaded. Please try again.');
    }
    const key = `${item.role_code}:${item.person_id}`;
    if (!keys.has(key)) {
      keys.add(key);
      result.push(item as PersonaOption);
    }
  }
  return result.sort((left, right) => left.full_name.localeCompare(right.full_name));
}

function responseMessage(value: unknown, fallback: string): string {
  if (value && typeof value === 'object' && 'error' in value && typeof value.error === 'string') {
    return value.error;
  }
  return fallback;
}

export function PersonaEntry({ initialError }: PersonaEntryProps) {
  const id = useId();
  const profileInputs = useRef<Partial<Record<PersonaRole, HTMLInputElement | null>>>({});
  const [personas, setPersonas] = useState<PersonaOption[]>([]);
  const [role, setRole] = useState<PersonaRole | null>(null);
  const [personId, setPersonId] = useState('');
  const [loading, setLoading] = useState(true);
  const [lookupError, setLookupError] = useState('');
  const [entryError, setEntryError] = useState(initialError ?? '');
  const [entering, setEntering] = useState(false);
  const [reload, setReload] = useState(0);
  const selectedProfile = PROFILES.find((profile) => profile.code === role);
  const availablePeople = useMemo(() => personas.filter((person) => person.role_code === role), [personas, role]);
  const selectedPerson = availablePeople.find((person) => person.person_id === personId);
  const peopleOptions = useMemo(() => availablePeople.map((person) => ({ id: person.person_id, name: person.full_name })), [availablePeople]);

  useEffect(() => {
    const controller = new AbortController();
    let timedOut = false;
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
    setLoading(true);
    setLookupError('');
    fetch('/api/personas', { cache: 'no-store', credentials: 'same-origin', signal: controller.signal,
      headers: { Accept: 'application/json' } })
      .then(async (response) => {
        const body: unknown = await response.json().catch(() => null);
        if (!response.ok) throw new Error(responseMessage(body, 'People are unavailable right now. Please try again.'));
        const loaded = parsePersonas(body);
        if (!controller.signal.aborted) setPersonas(loaded);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted && !timedOut) return;
        setPersonas([]);
        setLookupError(timedOut ? 'Loading people is taking longer than expected. Please try again.'
          : error instanceof Error ? error.message : 'People are unavailable right now. Please try again.');
      })
      .finally(() => {
        window.clearTimeout(timeout);
        if (!controller.signal.aborted || timedOut) setLoading(false);
      });
    return () => { window.clearTimeout(timeout); controller.abort(); };
  }, [reload]);

  useEffect(() => {
    if (loading) return;
    if (role === 'SYSTEM_ADMINISTRATOR' && availablePeople.length === 1) {
      setPersonId(availablePeople[0].person_id);
    } else if (!availablePeople.some((person) => person.person_id === personId)) {
      setPersonId('');
    }
  }, [availablePeople, loading, personId, role]);

  function chooseRole(nextRole: PersonaRole) {
    if (entering) return;
    setRole(nextRole);
    setPersonId('');
    setEntryError('');
  }

  function changeProfile() {
    const previous = role;
    setRole(null);
    setPersonId('');
    setEntryError('');
    if (previous) profileInputs.current[previous]?.focus();
  }

  async function enterWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (entering || loading) return;
    if (!selectedPerson || !role) {
      setEntryError('Choose your name from the list to continue.');
      return;
    }
    setEntering(true);
    setEntryError('');
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch('/api/personas/session', { method: 'POST', credentials: 'same-origin',
        cache: 'no-store', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ person_id: selectedPerson.person_id, role_code: role }) });
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok || !body || typeof body !== 'object' || !('ok' in body) || body.ok !== true) {
        throw new Error(responseMessage(body, 'We could not open your workspace. Please try again.'));
      }
      // The server owns the session cookie. Other tabs are asked to refresh
      // their selected-person view, without broadcasting any session material.
      if (typeof BroadcastChannel !== 'undefined') {
        try {
          const channel = new BroadcastChannel('staffing-persona');
          channel.postMessage('changed');
          channel.close();
        } catch { /* Cross-tab support is optional; the server still resolves every session. */ }
      }
      window.location.assign('/');
    } catch (error: unknown) {
      setEntryError(controller.signal.aborted ? 'Opening the workspace is taking longer than expected. Please try again.'
        : error instanceof Error ? error.message : 'We could not open your workspace. Please try again.');
      setEntering(false);
    } finally {
      window.clearTimeout(timeout);
    }
  }

  return (
    <main className="persona-entry" aria-labelledby={`${id}-title`}>
      <div className="persona-entry-wrap">
        <header className="persona-entry-brand" aria-label="AI Pod Staffing, Customer Success Services">
          <span className="persona-entry-brand-mark" aria-hidden="true">AI</span>
          <div><strong>AI Pod Staffing</strong><span>Customer Success Services</span></div>
        </header>

        <section className="persona-entry-heading">
          <p className="persona-entry-kicker">YOUR WORKSPACE</p>
          <h1 id={`${id}-title`}>Choose your workspace</h1>
          <p>Select your profile, then choose your name to continue.</p>
        </section>

        <form onSubmit={enterWorkspace} aria-busy={entering}>
          <fieldset className="persona-entry-profiles" disabled={entering}>
            <legend className="persona-entry-sr-only">Choose your profile</legend>
            {PROFILES.map((profile) => {
              const count = personas.filter((person) => person.role_code === profile.code).length;
              const selected = role === profile.code;
              return (
                <label className="persona-entry-profile" key={profile.code}>
                  <input ref={(element) => { profileInputs.current[profile.code] = element; }}
                    type="radio" name="workspace-profile" value={profile.code} checked={selected}
                    aria-labelledby={`${id}-${profile.code}-name`} aria-describedby={`${id}-${profile.code}-description`}
                    onChange={() => chooseRole(profile.code)} />
                  <span className="persona-entry-profile-card">
                    <span className="persona-entry-profile-eyebrow">{profile.eyebrow}</span>
                    <span className="persona-entry-profile-name" id={`${id}-${profile.code}-name`}>{profile.name}</span>
                    <span className="persona-entry-profile-description" id={`${id}-${profile.code}-description`}>{profile.description}</span>
                    <span className="persona-entry-profile-footer">
                      <span>{loading || lookupError ? '—' : `${count} ${profile.code === 'SYSTEM_ADMINISTRATOR' ? count === 1 ? 'account' : 'accounts' : count === 1 ? 'person' : 'people'}`}</span>
                      {selected ? <span className="persona-entry-selected">Selected</span> : null}
                    </span>
                  </span>
                </label>
              );
            })}
          </fieldset>

          <section className={`persona-entry-continue${selectedProfile ? ' has-profile' : ''}`}
            aria-labelledby={`${id}-continue-title`}>
            <div className="persona-entry-continue-heading">
              <h2 id={`${id}-continue-title`}>{selectedProfile ? `Continue as ${selectedProfile.name}` : 'Start with your profile'}</h2>
              <p>{selectedProfile ? 'Choose the person whose workspace you want to open.' : 'Choose one of the four profiles above to see the available people.'}</p>
              {selectedProfile ? <button className="persona-entry-change" type="button" disabled={entering} onClick={changeProfile}>Change profile</button> : null}
            </div>
            {selectedProfile && !loading && !lookupError && availablePeople.length > 0 ? (
              <div className="persona-entry-person">
                <label className="persona-entry-field-label" id={`${id}-person-label`}>Your name</label>
                <PersonCombobox key={role} people={peopleOptions} value={personId}
                  onChange={(value) => { setPersonId(value); setEntryError(''); }}
                  aria-labelledby={`${id}-person-label`} required disabled={entering}
                  placeholder="Search people by name" />
                <button className="persona-entry-enter" type="submit" disabled={!selectedPerson || entering}>
                  {entering ? 'Opening workspace…' : 'Enter workspace'}
                </button>
              </div>
            ) : null}
            {loading ? <p className="persona-entry-status" role="status">Loading people…</p> : null}
            {!loading && !lookupError && selectedProfile && availablePeople.length === 0 ? (
              <div className="persona-entry-status" role="status">
                <p>{role === 'SYSTEM_ADMINISTRATOR' ? 'No administrator account is available.' : 'No people are assigned to this profile yet.'}</p>
                <button type="button" className="persona-entry-retry" onClick={() => setReload((value) => value + 1)}>Refresh people</button>
              </div>
            ) : null}
            {lookupError ? <div className="persona-entry-error" role="alert">
              <p>{lookupError}</p>
              <button type="button" className="persona-entry-retry" onClick={() => setReload((value) => value + 1)}>Try again</button>
            </div> : null}
            {entryError ? <p className="persona-entry-error" role="alert">{entryError}</p> : null}
          </section>
        </form>
        <p className="persona-entry-footnote">Your profile sets the tools and projects you can access.</p>
      </div>
    </main>
  );
}

export default PersonaEntry;

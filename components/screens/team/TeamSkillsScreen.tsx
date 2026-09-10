'use client';

import { useMemo, useState } from 'react';

import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { SelectField, TextField } from '@/components/ui/FormControls';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canPerform } from '@/lib/role-policy';
import { selectIdentityPerson, selectVisiblePeople } from '@/lib/selectors';

export function TeamSkillsScreen() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const person = selectIdentityPerson(data, state.role);
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('availability');
  const people = useMemo(() => {
    const scoped = selectVisiblePeople(data, state.role).filter((item) => `${item.name} ${item.jobTitle} ${item.skills.map((skill) => skill.name).join(' ')}`.toLowerCase().includes(query.toLowerCase()));
    return [...scoped].sort(sort === 'name' ? (a, b) => a.name.localeCompare(b.name) : sort === 'skill' ? (a, b) => (b.skills[0]?.strength || 0) - (a.skills[0]?.strength || 0) : (a, b) => a.allocationPct - b.allocationPct);
  }, [data, query, sort, state.role]);
  const average = person?.skills.length ? (person.skills.reduce((sum, skill) => sum + skill.strength, 0) / person.skills.length).toFixed(1) : '0.0';

  return <section className="staffing-screen">
    <PageHeader title="Team & skills" description="Customer-defined skills, evidence, strength, allocation, and current pod information." actions={<><TextField value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a team member or skill" />{canPerform(state.role, 'TEAM_SKILLS', 'canCreate', data.authorization) ? <Button variant="primary" onClick={() => notify('Feature in progress', 'This workflow will be available in a future release.')}>＋ Add person</Button> : null}</>} />
    {person ? <div className="staffing-profile-grid"><Card className="staffing-profile-card"><Avatar initials={person.initials} /><h3>{person.name}</h3><p>{person.jobTitle} • {person.location}</p><div className="staffing-stat-pairs"><div><strong>{person.allocationPct}%</strong><span>Current allocation</span></div><div><strong>{person.activePods}</strong><span>Active pods</span></div><div><strong>{average}</strong><span>Average strength</span></div><div><strong>{person.skills.length}</strong><span>Mapped skills</span></div></div></Card><Card><CardHeader><div><h3>Skills and strength</h3><p>Evidence mapped to the customer-controlled Skills (Type of work) taxonomy.</p></div></CardHeader><CardBody>{person.skills.map((skill) => <div className="staffing-interest-row" key={skill.id}><div><b>{skill.name}</b><small>{skill.category}</small></div><div className="staffing-stars" aria-label={`Strength ${skill.strength} out of 5`}>{'★'.repeat(skill.strength)}{'☆'.repeat(Math.max(0, 5 - skill.strength))}</div><div className="staffing-row-sub">{skill.evidence || 'No evidence note recorded'}</div></div>)}</CardBody></Card></div> : null}
    {<Card className="staffing-section-gap"><CardHeader><div><h3>Team directory</h3><p>{people.length} person{people.length === 1 ? '' : 's'} visible to {state.role}</p></div><SelectField value={sort} onChange={(event) => setSort(event.target.value)}><option value="availability">Sort by availability</option><option value="name">Sort by name</option><option value="skill">Sort by strongest skill</option></SelectField></CardHeader><div className="staffing-list">{people.map((item) => <div className="staffing-list-row staffing-directory-row" key={item.id}><div className="staffing-person-line"><Avatar initials={item.initials} /><span><b>{item.name}</b><small>{item.jobTitle} • {item.location}</small></span></div><div className="staffing-tag-row">{item.skills.slice(0, 2).map((skill) => <span key={skill.id}>{skill.name}</span>)}</div><div className="staffing-directory-capacity"><b>{item.allocationPct}%</b><small>{item.activePods} pod{item.activePods === 1 ? '' : 's'}</small></div><Button size="small" onClick={() => dispatch({ type: 'open-drawer', drawer: { id: 'person-details', title: item.name, payload: { personId: item.id } } })}>View</Button></div>)}</div></Card>}
  </section>;
}

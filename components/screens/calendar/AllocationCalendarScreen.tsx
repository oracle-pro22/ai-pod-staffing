'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { SelectField } from '@/components/ui/FormControls';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { selectVisiblePeople, selectVisibleRequests } from '@/lib/selectors';
import type { StaffingPerson } from '@/types/staffing';

const BASE_WEEK = new Date(Date.UTC(2026, 6, 20));

export function AllocationCalendarScreen() {
  const { data, state, dispatch } = useStaffingApp();
  const [skillId, setSkillId] = useState('');
  const [capacity, setCapacity] = useState('All capacity');
  const [showAlternates, setShowAlternates] = useState(true);
  const requests = selectVisibleRequests(data, state.role);
  let people = selectVisiblePeople(data, state.role)
    .filter((person) => !skillId || person.skills.some((skill) => skill.id === skillId))
    .filter((person) => capacity === 'Available' ? person.allocationPct < 70 : capacity === 'Constrained' ? person.allocationPct >= 70 : capacity === 'OOO / leave / travel' ? person.availability.length > 0 : true);
  if (!showAlternates) people = people.filter((person) => requests.some((request) => request.recommendations.some((item) => item.personId === person.id)));
  people = [...people].sort((a, b) => b.allocationPct - a.allocationPct);
  const monday = new Date(BASE_WEEK); monday.setUTCDate(monday.getUTCDate() + state.weekOffset * 7);
  const days = Array.from({ length: 5 }, (_, index) => { const date = new Date(monday); date.setUTCDate(monday.getUTCDate() + index); return date; });

  return <section className="staffing-screen">
    <PageHeader title="Allocation calendar" description="Weekly capacity planning with leave, travel, active pods, and overload guardrails." actions={<><Button onClick={() => dispatch({ type: 'set-week-offset', weekOffset: state.weekOffset - 1 })}>←</Button><Button onClick={() => dispatch({ type: 'set-week-offset', weekOffset: 0 })}>This week</Button><Button onClick={() => dispatch({ type: 'set-week-offset', weekOffset: state.weekOffset + 1 })}>→</Button><Button variant="primary" onClick={() => dispatch({ type: 'open-drawer', drawer: { id: 'quick-allocation', title: 'Quick allocation' } })}>＋ Allocate</Button></>} />
    <Card padded className="staffing-calendar-toolbar-card"><div className="staffing-toolbar"><SelectField aria-label="Filter by interest" value={skillId} onChange={(event) => setSkillId(event.target.value)}><option value="">All interests</option>{data.catalog.skills.map((skill) => <option key={skill.id} value={skill.id}>{skill.name}</option>)}</SelectField><SelectField aria-label="Filter by capacity" value={capacity} onChange={(event) => setCapacity(event.target.value)}><option>All capacity</option><option>Available</option><option>Constrained</option><option>OOO / leave / travel</option></SelectField><label className="staffing-checkbox-pill"><input type="checkbox" checked={showAlternates} onChange={(event) => setShowAlternates(event.target.checked)} /> Show alternates</label><b className="staffing-week-label">{formatWeekLabel(days)}</b></div></Card>
    <div className="staffing-calendar-wrap"><div className="staffing-schedule"><div className="staffing-cell head person">Team member</div>{days.map((day) => <div className="staffing-cell head" key={dateKey(day)}>{day.toLocaleDateString('en-US', { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric' })}</div>)}{people.map((person) => <CalendarRow key={person.id} person={person} days={days} />)}</div>{people.length === 0 ? <div className="staffing-empty">No people match this calendar filter.</div> : null}</div>
    <div className="staffing-calendar-legend"><span><i className="write" />Project work</span><span><i className="video" />Video / demo</span><span><i className="enable" />Enablement</span><span><i className="travel" />Leave / travel</span></div>
  </section>;
}

function CalendarRow({ person, days }: { person: StaffingPerson; days: Date[] }) {
  return <><div className="staffing-cell person"><div className="staffing-person-line"><span className="staffing-avatar">{person.initials}</span><span><b>{person.name}</b><small>{person.allocationPct}% • {person.skills[0]?.name || person.jobTitle}</small></span></div></div>{days.map((day) => {
    const events = person.availability.filter((event) => isEventOnDay(event.startsOn, event.endsOn, day));
    const bookings = events.map((event) => ({ title: event.title || event.eventType, hours: Number(event.allocatedHours) || 0, tone: /travel/i.test(event.eventType) ? 'travel' : 'ooo' }));
    const hours = bookings.reduce((sum, item) => sum + item.hours, 0);
    return <div className="staffing-cell" key={`${person.id}-${dateKey(day)}`}>{bookings.map((item, index) => <div className={`staffing-booking ${item.tone}`} key={`${item.title}-${index}`}>{item.title} • {item.hours}h</div>)}<span className={`staffing-day-hours${hours > 8 ? ' hot' : ''}`}>{hours}h</span></div>;
  })}</>;
}

function dateKey(date: Date) { return date.toISOString().slice(0, 10); }
function isEventOnDay(startValue: string, endValue: string, day: Date) { const key = dateKey(day); return Boolean(startValue && key >= startValue.slice(0, 10) && key <= (endValue || startValue).slice(0, 10)); }
function formatWeekLabel(days: Date[]) { return `${days[0].toLocaleDateString('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric' })}–${days[4].toLocaleDateString('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric' })}`; }

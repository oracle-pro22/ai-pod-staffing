'use client';

import { Fragment, useState } from 'react';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { SelectField } from '@/components/ui/FormControls';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { availabilityDayHours, shiftDay, weekDays } from '@/lib/live-presentation';
import { useLiveWorkspace } from '@/lib/use-live-workspace';
import { downloadExcelWorkbook } from '@/lib/export-xlsx';

export function LiveAllocationCalendar() {
  const { data, notify } = useStaffingApp();
  const [week, setWeek] = useState('');
  const [skillId, setSkillId] = useState('');
  const [capacity, setCapacity] = useState('All capacity');
  const [showAlternates, setShowAlternates] = useState(true);
  const [exporting, setExporting] = useState(false);
  const { snapshot, error, refresh } = useLiveWorkspace('ALLOCATION_CALENDAR', week);
  const days = snapshot ? weekDays(snapshot.week_start) : [];
  const dayLabel = (day: string, long = false) => new Date(`${day}T12:00:00Z`).toLocaleDateString('en-US', {
    timeZone: 'UTC', ...(long ? { year: 'numeric' as const } : { weekday: 'short' as const }), month: 'short', day: 'numeric',
  });
  const people = (snapshot?.people ?? []).map(p => ({ ...p, profile: data.people.find(person => person.id === p.person_id) }))
    .filter(p => !skillId || p.profile?.skills.some(s => s.id === skillId))
    .filter(p => showAlternates || snapshot?.days.some(d => d.person_id === p.person_id))
    .filter(p => capacity === 'Available' ? p.capacity_status === 'CURRENT' && p.allocation_pct !== null && p.allocation_pct < 70
      : capacity === 'Constrained' ? p.capacity_status === 'CURRENT' && p.allocation_pct !== null && p.allocation_pct >= 70
      : capacity === 'OOO / leave / travel' ? p.profile?.availability.some(e => days.some(day => day >= e.startsOn.slice(0, 10) && day <= (e.endsOn || e.startsOn).slice(0, 10)))
      : capacity === 'Needs refresh' ? p.capacity_status !== 'CURRENT' : true)
    .sort((a, b) => (b.allocation_pct ?? -1) - (a.allocation_pct ?? -1));

  async function exportExcel() {
    if (!snapshot?.can_export || exporting) return;
    setExporting(true);
    try {
      const ids = new Set(people.map(p => p.person_id));
      await downloadExcelWorkbook({ fileName: `staffing-calendar-${snapshot.week_start}.xlsx`, sheetName: 'Project allocations',
        headers: ['Date', 'Person', 'Request', 'Assigned hours'], rows: snapshot.days.filter(d => ids.has(d.person_id)).map(d => [
          d.work_date.slice(0, 10), data.people.find(p => p.id === d.person_id)?.name || d.person_id, d.request_id, Number(d.assigned_hours),
        ]) });
    } catch { notify('Export unavailable', 'Please try again.'); } finally { setExporting(false); }
  }

  return <section className="staffing-screen">
    <PageHeader title="Allocation calendar" description="Weekly capacity planning with leave, travel, active pods, and overload guardrails."
      actions={<><Button aria-label="Previous week" disabled={!snapshot} onClick={() => snapshot && setWeek(shiftDay(snapshot.week_start, -7))}>←</Button>
        <Button onClick={() => { setWeek(''); refresh(); }}>This week</Button>
        <Button aria-label="Next week" disabled={!snapshot} onClick={() => snapshot && setWeek(shiftDay(snapshot.week_start, 7))}>→</Button>
        {snapshot?.can_export && <Button disabled={exporting} onClick={() => void exportExcel()}>{exporting ? 'Exporting…' : 'Export Excel'}</Button>}</>} />
    <Card padded className="staffing-calendar-toolbar-card"><div className="staffing-toolbar">
      <SelectField aria-label="Filter by interest" value={skillId} onChange={e => setSkillId(e.target.value)}><option value="">All interests</option>
        {data.catalog.skills.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</SelectField>
      <SelectField aria-label="Filter by capacity" value={capacity} onChange={e => setCapacity(e.target.value)}>
        {['All capacity', 'Available', 'Constrained', 'OOO / leave / travel', 'Needs refresh'].map(v => <option key={v}>{v}</option>)}</SelectField>
      <label className="staffing-checkbox-pill"><input type="checkbox" checked={showAlternates} onChange={e => setShowAlternates(e.target.checked)} /> Show alternates</label>
      <b className="staffing-week-label">{days.length ? `${dayLabel(days[0], true)} – ${dayLabel(days[4], true)}` : 'Loading week…'}</b>
    </div></Card>
    {error && <Card padded><div role="alert">{error}</div><Button onClick={refresh}>Try again</Button></Card>}
    {!snapshot && !error && <Card padded><p role="status">Loading weekly allocations…</p></Card>}
    {snapshot && <div className="staffing-calendar-wrap"><div className="staffing-schedule staffing-live-schedule" aria-label="Weekly allocation calendar">
      <div className="staffing-cell head person">Team member</div>{days.map(day => <div className="staffing-cell head" key={day}>{dayLabel(day)}</div>)}
      {people.map(p => <Fragment key={p.person_id}><div className="staffing-cell person"><div className="staffing-person-line">
        <Avatar initials={p.profile?.initials || p.person_id.slice(-2)} /><span><b>{p.profile?.name || snapshot.assignments.find(a => a.person_id === p.person_id)?.full_name || p.person_id}</b>
          <small>{p.capacity_status !== 'CURRENT' ? 'Needs refresh' : p.allocation_pct === null ? 'No available hours' : `${p.allocation_pct}%`} • {p.profile?.skills[0]?.name || p.profile?.jobTitle || 'Team member'}</small></span>
      </div></div>{days.map(day => {
        const work = snapshot.days.filter(d => d.person_id === p.person_id && d.work_date.slice(0, 10) === day);
        const events = (p.profile?.availability ?? []).filter(e => day >= e.startsOn.slice(0, 10) && day <= (e.endsOn || e.startsOn).slice(0, 10));
        const eventHours = events.map(e => availabilityDayHours(e, day));
        const hours = work.reduce((n, d) => n + Number(d.assigned_hours), 0) + eventHours.reduce<number>((n, h) => n + (h ?? 0), 0);
        return <div className="staffing-cell" key={day}>
          {work.map(d => <div className="staffing-booking write" key={d.assignment_id} title={`${d.request_id} · ${snapshot.requests.find(r => r.request_id === d.request_id)?.title || ''}`}>
            {snapshot.requests.find(r => r.request_id === d.request_id)?.title || d.request_id} • {d.assigned_hours}h</div>)}
          {events.map((e, i) => <div className={`staffing-booking ${/travel|leave|ooo/i.test(e.eventType) ? 'travel' : 'ooo'}`} key={`${e.startsOn}-${i}`}>
            {e.title || e.eventType} • {eventHours[i] === null ? 'Hours not recorded' : `${eventHours[i]}h`}</div>)}
          <span className="staffing-day-hours">{eventHours.some(h => h === null) ? 'Hours incomplete' : `${Number(hours.toFixed(2))}h`}</span>
        </div>;
      })}</Fragment>)}
    </div>{!people.length && <div className="staffing-empty">No people match this calendar filter.</div>}</div>}
    <div className="staffing-calendar-legend"><span><i className="write" />Approved project work</span><span><i className="travel" />Leave / travel</span><span><i className="ooo" />Other availability</span></div>
    {snapshot && <div className="staffing-source-strip">{snapshot.timezone} · Percentages include all commitments. Daily cells show project details within your access scope and recorded availability. Closed projects retain work through the closure day only. Pending proposals do not reserve capacity.</div>}
  </section>;
}

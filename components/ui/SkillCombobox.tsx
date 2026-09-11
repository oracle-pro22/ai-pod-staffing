'use client';

import { useEffect, useId, useRef, useState } from 'react';

/** Search catalogue names only. Typing never creates or selects a free-text skill. */
export function SkillCombobox({ options, onSelect, disabled, noun = 'skills' }: {
  options: { skillId: string; name: string }[];
  onSelect: (id: string) => void;
  disabled: boolean;
  noun?: 'skills' | 'deliverables';
}) {
  const id = useId();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const list = useRef<HTMLDivElement>(null);
  const matches = options.filter((row) => row.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const index = Math.min(active, Math.max(0, matches.length - 1));
  useEffect(() => { if (open) list.current?.querySelectorAll('[role="option"]')[index]?.scrollIntoView({ block: 'nearest' }); }, [index, open]);
  const choose = (skillId: string) => { onSelect(skillId); setQuery(''); setActive(0); setOpen(false); };
  return <div className="staffing-person-combobox" onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false); }}>
    <input className="staffing-field" role="combobox" aria-label={`Search catalogue ${noun}`} aria-autocomplete="list" aria-expanded={open && !disabled}
      aria-controls={id} aria-activedescendant={open && matches[index] ? `${id}-${matches[index].skillId}` : undefined}
      autoComplete="off" placeholder={`Search ${noun} by name`} disabled={disabled} value={query}
      onChange={(event) => { setQuery(event.target.value); setActive(0); setOpen(true); }} onFocus={() => setOpen(true)}
      onKeyDown={(event) => {
        if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); setOpen(false); }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault(); setOpen(true);
          setActive(open ? Math.max(0, Math.min(index + (event.key === 'ArrowDown' ? 1 : -1), matches.length - 1)) : 0);
        }
        if (event.key === 'Enter') { event.preventDefault(); if (open && matches[index]) choose(matches[index].skillId); }
      }} />
    {open && !disabled ? <div id={id} ref={list} className="staffing-person-options" role="listbox" aria-label={`Catalogue ${noun}`}>
      {matches.length ? matches.map((row, i) => <button key={row.skillId} id={`${id}-${row.skillId}`} className={i === index ? 'active' : ''}
        type="button" role="option" aria-selected={i === index} tabIndex={-1} onMouseDown={(event) => event.preventDefault()}
        onMouseEnter={() => setActive(i)} onClick={() => choose(row.skillId)}>{row.name}</button>)
        : <div className="staffing-person-empty">{options.length ? `No matching catalogue ${noun}.` : `No more catalogue ${noun} available to add.`}</div>}
    </div> : null}
  </div>;
}

'use client';

import {
  type ChangeEvent,
  type FocusEvent,
  type KeyboardEvent,
  useEffect,
  useId,
  useMemo,
  useState,
} from 'react';

import type { StaffingPerson } from '@/types/staffing';

type PersonComboboxProps = {
  people: Pick<StaffingPerson, 'id' | 'name'>[];
  value: string;
  onChange: (personId: string) => void;
  disabled?: boolean;
  required?: boolean;
  placeholder?: string;
  'aria-labelledby'?: string;
};

export function PersonCombobox({
  people,
  value,
  onChange,
  disabled = false,
  required = false,
  placeholder = 'Search people by name',
  'aria-labelledby': ariaLabelledBy,
}: PersonComboboxProps) {
  const listboxId = useId();
  const selectedPerson = people.find((person) => person.id === value) ?? null;
  const [query, setQuery] = useState(selectedPerson?.name ?? '');
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    setQuery(selectedPerson?.name ?? '');
  }, [selectedPerson?.id, selectedPerson?.name]);

  const matches = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return people
      .filter((person) => !normalizedQuery || person.name.toLocaleLowerCase().includes(normalizedQuery))
      .sort((left, right) => left.name.localeCompare(right.name));
  }, [people, query]);

  useEffect(() => {
    setActiveIndex((current) => Math.min(current, Math.max(matches.length - 1, 0)));
  }, [matches.length]);

  function selectPerson(person: Pick<StaffingPerson, 'id' | 'name'>) {
    onChange(person.id);
    setQuery(person.name);
    setOpen(false);
  }

  function changeQuery(event: ChangeEvent<HTMLInputElement>) {
    setQuery(event.target.value);
    if (value) onChange('');
    setActiveIndex(0);
    setOpen(true);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) => Math.min(current + 1, Math.max(matches.length - 1, 0)));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) => Math.max(current - 1, 0));
    } else if (event.key === 'Enter' && open && matches[activeIndex]) {
      event.preventDefault();
      selectPerson(matches[activeIndex]);
    } else if (event.key === 'Escape') {
      setOpen(false);
    }
  }

  function handleBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
  }

  return (
    <div className="staffing-person-combobox" onBlur={handleBlur}>
      <input
        className="staffing-field"
        type="text"
        role="combobox"
        aria-labelledby={ariaLabelledBy}
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-activedescendant={open && matches[activeIndex] ? `${listboxId}-${matches[activeIndex].id}` : undefined}
        autoComplete="off"
        disabled={disabled}
        required={required}
        placeholder={placeholder}
        value={query}
        onChange={changeQuery}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
      />
      {open ? (
        <div id={listboxId} className="staffing-person-options" role="listbox">
          {matches.length ? matches.map((person, index) => (
            <button
              id={`${listboxId}-${person.id}`}
              className={index === activeIndex ? 'active' : ''}
              key={person.id}
              type="button"
              role="option"
              aria-selected={person.id === value}
              tabIndex={-1}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => selectPerson(person)}
            >
              {person.name}
            </button>
          )) : <div className="staffing-person-empty">No matching people found</div>}
        </div>
      ) : null}
    </div>
  );
}

'use client';

import { type FocusEvent, type KeyboardEvent, useEffect, useId, useState } from 'react';

export type DropdownOption = {
  value: string;
  label: string;
};

type DropdownFieldProps = {
  options: DropdownOption[];
  value: string;
  onChange: (value: string) => void;
  name?: string;
  disabled?: boolean;
  placeholder?: string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
};

export function DropdownField({
  options,
  value,
  onChange,
  name,
  disabled = false,
  placeholder = 'Select an option',
  'aria-label': ariaLabel,
  'aria-labelledby': ariaLabelledBy,
}: DropdownFieldProps) {
  const listboxId = useId();
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const selectedIndex = options.findIndex((option) => option.value === value);
  const selectedOption = selectedIndex >= 0 ? options[selectedIndex] : undefined;

  useEffect(() => {
    if (selectedIndex >= 0) setActiveIndex(selectedIndex);
    else setActiveIndex((current) => Math.min(current, Math.max(options.length - 1, 0)));
  }, [options.length, selectedIndex]);

  function openMenu() {
    if (disabled || options.length === 0) return;
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
    setOpen(true);
  }

  function selectOption(index: number) {
    const option = options[index];
    if (!option) return;
    onChange(option.value);
    setActiveIndex(index);
    setOpen(false);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) {
        openMenu();
        return;
      }
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      setActiveIndex((current) => (current + direction + options.length) % options.length);
    } else if (event.key === 'Home' && open) {
      event.preventDefault();
      setActiveIndex(0);
    } else if (event.key === 'End' && open) {
      event.preventDefault();
      setActiveIndex(Math.max(options.length - 1, 0));
    } else if ((event.key === 'Enter' || event.key === ' ') && open) {
      event.preventDefault();
      selectOption(activeIndex);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      setOpen(false);
    }
  }

  function handleBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
  }

  return (
    <div className={`staffing-dropdown${open ? ' open' : ''}`} onBlur={handleBlur}>
      {name ? <input type="hidden" name={name} value={value} /> : null}
      <button
        className="staffing-dropdown-trigger"
        type="button"
        role="combobox"
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-activedescendant={open && options[activeIndex] ? `${listboxId}-${activeIndex}` : undefined}
        disabled={disabled}
        onClick={() => open ? setOpen(false) : openMenu()}
        onKeyDown={handleKeyDown}
      >
        <span className={selectedOption ? '' : 'placeholder'}>{selectedOption?.label ?? placeholder}</span>
      </button>
      {open ? (
        <div id={listboxId} className="staffing-dropdown-options" role="listbox">
          {options.map((option, index) => (
            <button
              id={`${listboxId}-${index}`}
              className={index === activeIndex ? 'active' : ''}
              key={option.value || `empty-${index}`}
              type="button"
              role="option"
              aria-selected={option.value === value}
              tabIndex={-1}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => selectOption(index)}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

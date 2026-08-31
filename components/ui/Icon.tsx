import type { SVGAttributes } from 'react';

import type { NavigationIconName } from '@/types/roles';

export function Icon({ name, ...props }: SVGAttributes<SVGSVGElement> & { name: NavigationIconName }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      {name === 'home' && <><path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/></>}
      {name === 'file' && <><path d="M6 3h9l4 4v14H6z"/><path d="M15 3v5h5"/><path d="M9 13h6M9 17h6"/></>}
      {name === 'spark' && <><path d="m12 3 1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z"/><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></>}
      {name === 'calendar' && <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/></>}
      {name === 'people' && <><circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.2 2.7-5 6-5s6 1.8 6 5"/><circle cx="17" cy="9" r="2"/><path d="M15 15c3.4-.4 6 1.4 6 4"/></>}
      {name === 'clock' && <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>}
      {name === 'play' && <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m10 9 5 3-5 3z"/></>}
      {name === 'chart' && <path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>}
      {name === 'settings' && <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z"/></>}
    </svg>
  );
}


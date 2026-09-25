import type { Metadata } from 'next';
import './base.css';
import '../styles/react-foundation.css';
import '../styles/reports.css';
import '../styles/roster-onboarding.css';

export const metadata: Metadata = {
  title: 'AI Pod Staffing',
  description: 'Agent-assisted staffing operations and human approval workspace.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}

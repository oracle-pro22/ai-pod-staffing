import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'AI Pod Staffing',
  description: 'Compatibility route for the AI Pod Staffing application.',
};

export default function ReactPreviewLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}

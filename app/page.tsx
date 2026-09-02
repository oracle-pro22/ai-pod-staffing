import { WorkspaceRouter } from '@/components/screens/WorkspaceRouter';
import { AppShell } from '@/components/shell/AppShell';
import { StaffingAppProvider } from '@/context/StaffingAppProvider';
import { dataSource } from '@/lib/staffing-data-source';

export const dynamic = 'force-dynamic';

export default async function Home() {
  const data = await dataSource.getViewModel();
  return (
    <StaffingAppProvider data={data}>
      <AppShell>
        <WorkspaceRouter />
      </AppShell>
    </StaffingAppProvider>
  );
}

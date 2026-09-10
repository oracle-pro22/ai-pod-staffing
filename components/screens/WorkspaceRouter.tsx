'use client';

import { AdministrationScreen } from '@/components/screens/administration/AdministrationScreen';
import { AgentExecutionScreen } from '@/components/screens/agent-execution/AgentExecutionScreen';
import { AiFitmentScreen } from '@/components/screens/fitment/AiFitmentScreen';
import { AllocationCalendarScreen } from '@/components/screens/calendar/AllocationCalendarScreen';
import { AvailabilityScreen } from '@/components/screens/availability/AvailabilityScreen';
import { CommandCenter } from '@/components/screens/command-center/CommandCenter';
import { ReportsScreen } from '@/components/screens/reports/ReportsScreen';
import { RequestsScreen } from '@/components/screens/requests/RequestsScreen';
import { TeamSkillsScreen } from '@/components/screens/team/TeamSkillsScreen';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canAccessScreen, defaultScreen } from '@/lib/role-policy';

const SCREENS = {
  dashboard: CommandCenter,
  requests: RequestsScreen,
  fitment: AiFitmentScreen,
  calendar: AllocationCalendarScreen,
  interests: TeamSkillsScreen,
  availability: AvailabilityScreen,
  agent: AgentExecutionScreen,
  reports: ReportsScreen,
  admin: AdministrationScreen,
} as const;

export function WorkspaceRouter() {
  const { state, data } = useStaffingApp();
  const screen = canAccessScreen(state.role, state.activeScreen, data.authorization)
    ? state.activeScreen : defaultScreen(state.role, data.authorization);
  if (!canAccessScreen(state.role, screen, data.authorization)) {
    return <div className="staffing-empty">No workspace access is configured for this profile. Contact your administrator.</div>;
  }
  const Screen = SCREENS[screen];
  return <Screen />;
}

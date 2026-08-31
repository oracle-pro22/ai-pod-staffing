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
  const { state } = useStaffingApp();
  const Screen = SCREENS[state.activeScreen];
  return <Screen />;
}

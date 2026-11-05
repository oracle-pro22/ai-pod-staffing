'use client';

import { useStaffingApp } from '@/context/StaffingAppProvider';
import { capabilityText } from '@/lib/capability-text';

export function CapabilityText({ children }: { children: string }) {
  const { data } = useStaffingApp();
  return capabilityText(children, data.catalog?.skills ?? []);
}

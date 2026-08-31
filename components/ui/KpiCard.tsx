import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import type { Tone } from '@/types/ui';

export function KpiCard({ label, value, badge, tone = '', detail }: {
  label: string;
  value: string | number;
  badge?: string;
  tone?: Tone;
  detail?: string;
}) {
  return (
    <Card className="staffing-kpi">
      <div className="staffing-kpi-top"><span>{label}</span>{badge ? <Pill tone={tone}>{badge}</Pill> : null}</div>
      <div className="staffing-kpi-value">{value}</div>
      {detail ? <div className={`staffing-delta${tone === 'green' || tone === 'teal' ? ' good' : tone === 'amber' ? ' warn' : ''}`}>{detail}</div> : null}
    </Card>
  );
}

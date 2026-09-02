import 'server-only';

import { buildOracleStaffingViewModel } from '@/lib/mappers/oracle-staffing-mapper';
import { readOracleStaffingSnapshot } from '@/lib/repositories/staffing-repository';

export const oracleDataSource = {
  mode: 'oracle-26ai' as const,
  location: 'AIMLCOESANDBOX / AI_POD_STAFFING',
  async getViewModel() {
    return buildOracleStaffingViewModel(await readOracleStaffingSnapshot());
  },
};

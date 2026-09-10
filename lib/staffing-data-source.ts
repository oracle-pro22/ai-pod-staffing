import 'server-only';

import { oracleDataSource } from '@/lib/oracle-staffing-data';
import { dataSource as excelDataSource } from '@/lib/staffing-data';

const requestedMode = (process.env.STAFFING_DATA_SOURCE ?? 'oracle').trim().toLowerCase();

if (requestedMode !== 'oracle' && requestedMode !== 'excel') {
  throw new Error('STAFFING_DATA_SOURCE must be either "oracle" or "excel".');
}

export const dataSource = requestedMode === 'oracle'
  ? oracleDataSource
  : {
      mode: excelDataSource.mode,
      location: excelDataSource.workbookPath,
      getViewModel: excelDataSource.getViewModel,
    };

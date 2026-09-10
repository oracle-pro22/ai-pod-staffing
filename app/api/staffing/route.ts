import { type NextRequest, NextResponse } from 'next/server';
import { staffingRequestContext } from '@/lib/auth/staffing-request-context';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
import { selectRoleViewModel } from '@/lib/selectors';
import { dataSource } from '@/lib/staffing-data-source';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request: NextRequest) {
  try {
    const { role } = staffingRequestContext(request);
    const data = selectRoleViewModel(await dataSource.getViewModel(), role);
    return NextResponse.json(
      { source: dataSource.mode, data },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (error) {
    console.error('Unable to read the staffing data source.', error);
    return staffingApiErrorResponse(error);
  }
}

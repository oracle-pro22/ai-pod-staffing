import { NextResponse } from 'next/server';
import { publicOracleError } from '@/lib/db/oracle';
import { dataSource } from '@/lib/staffing-data-source';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  try {
    const data = await dataSource.getViewModel();
    return NextResponse.json(
      { source: dataSource.mode, location: dataSource.location, data },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (error) {
    console.error('Unable to read the staffing data source.', error);
    return NextResponse.json(
      { error: dataSource.mode === 'oracle-26ai' ? publicOracleError(error) : 'The staffing data source could not be loaded.' },
      { status: 500, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}

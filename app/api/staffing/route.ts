import { NextResponse } from 'next/server';
import { dataSource } from '@/lib/staffing-data';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  try {
    const data = await dataSource.getViewModel();
    return NextResponse.json(
      { source: dataSource.mode, workbook: dataSource.workbookPath, data },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (error) {
    console.error('Unable to read staffing workbook', error);
    return NextResponse.json(
      { error: 'The staffing workbook could not be loaded.' },
      { status: 500, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}

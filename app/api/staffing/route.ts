import { NextResponse } from 'next/server';
import { dataSource } from '@/lib/staffing-data';

export async function GET() {
  // TODO(26ai): authenticate and query the 26ai database once provisioned.
  return NextResponse.json({ source: dataSource.mode, workbook: dataSource.workbookPath, data: await dataSource.getSnapshot() });
}

import 'server-only';

import { NextResponse } from 'next/server';

import { publicOracleError } from '@/lib/db/oracle';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';

export function staffingApiErrorResponse(error: unknown): NextResponse {
  if (error instanceof StaffingApiError) {
    return NextResponse.json(
      { error: error.message, code: error.code },
      { status: error.status, headers: { 'Cache-Control': 'no-store' } },
    );
  }
  return NextResponse.json(
    { error: publicOracleError(error), code: 'DATABASE_ERROR' },
    { status: 500, headers: { 'Cache-Control': 'no-store' } },
  );
}

import { NextResponse } from 'next/server';
import oracledb from 'oracledb';

import { publicOracleError, withOracleConnection } from '@/lib/db/oracle';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

type HealthRow = {
  DATABASE_USER: string;
  CURRENT_SCHEMA: string;
  DATABASE_TIME: Date | string;
};

export async function GET() {
  try {
    const health = await withOracleConnection(async (connection) => {
      const result = await connection.execute<HealthRow>(`
        SELECT USER AS database_user,
               SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') AS current_schema,
               SYSTIMESTAMP AS database_time
          FROM DUAL
      `, [], { outFormat: oracledb.OUT_FORMAT_OBJECT });
      return result.rows?.[0];
    });
    return NextResponse.json({
      status: 'ok',
      databaseUser: health?.DATABASE_USER ?? '',
      currentSchema: health?.CURRENT_SCHEMA ?? '',
      databaseTime: health?.DATABASE_TIME ?? '',
    }, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    console.error('Oracle Database health check failed.', error);
    return NextResponse.json({ status: 'error', error: publicOracleError(error) }, {
      status: 503,
      headers: { 'Cache-Control': 'no-store' },
    });
  }
}

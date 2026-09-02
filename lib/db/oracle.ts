import 'server-only';

import oracledb, { type Connection, type Pool } from 'oracledb';

import { readOracleConfig } from '@/lib/db/oracle-config';

type OracleGlobal = typeof globalThis & {
  __aiPodOraclePool?: Promise<Pool>;
};

const oracleGlobal = globalThis as OracleGlobal;

// The current schema stores only small JSON documents in CLOB columns. Fetching
// them as strings keeps the repository and React boundary free of LOB handles.
oracledb.fetchAsString = [oracledb.CLOB];

export function getOraclePool(): Promise<Pool> {
  if (!oracleGlobal.__aiPodOraclePool) {
    const config = readOracleConfig();
    oracleGlobal.__aiPodOraclePool = oracledb.createPool({
      user: config.user,
      password: config.password,
      connectString: config.connectString,
      configDir: config.walletLocation,
      walletLocation: config.walletLocation,
      walletPassword: config.walletPassword,
      poolMin: config.poolMin,
      poolMax: config.poolMax,
      poolIncrement: config.poolIncrement,
      homogeneous: true,
    }).catch((error) => {
      delete oracleGlobal.__aiPodOraclePool;
      throw error;
    });
  }
  return oracleGlobal.__aiPodOraclePool;
}

export async function withOracleConnection<T>(work: (connection: Connection) => Promise<T>): Promise<T> {
  const pool = await getOraclePool();
  const connection = await pool.getConnection();
  try {
    return await work(connection);
  } finally {
    await connection.close();
  }
}

export async function withOracleTransaction<T>(work: (connection: Connection) => Promise<T>): Promise<T> {
  const pool = await getOraclePool();
  const connection = await pool.getConnection();
  try {
    const result = await work(connection);
    await connection.commit();
    return result;
  } catch (error) {
    await connection.rollback();
    throw error;
  } finally {
    await connection.close();
  }
}

export function publicOracleError(error: unknown): string {
  if (error instanceof Error) {
    const oracleCode = error.message.match(/ORA-\d{5}/)?.[0];
    return oracleCode ? `Oracle Database request failed (${oracleCode}).` : 'Oracle Database request failed.';
  }
  return 'Oracle Database request failed.';
}

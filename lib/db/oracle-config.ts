import 'server-only';

import path from 'node:path';

export type OracleConfig = {
  user: string;
  password: string;
  connectString: string;
  walletLocation: string;
  walletPassword: string;
  poolMin: number;
  poolMax: number;
  poolIncrement: number;
};

function requiredEnvironmentValue(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required server environment variable ${name}.`);
  return value;
}

function poolNumber(name: string, fallback: number): number {
  const raw = process.env[name]?.trim();
  if (!raw) return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`${name} must be a non-negative integer.`);
  }
  return value;
}

export function readOracleConfig(): OracleConfig {
  const poolMin = poolNumber('DB_POOL_MIN', 0);
  const poolMax = poolNumber('DB_POOL_MAX', 2);
  const poolIncrement = poolNumber('DB_POOL_INCREMENT', 1);
  if (poolMax < 1) throw new Error('DB_POOL_MAX must be at least 1.');
  if (poolMin > poolMax) throw new Error('DB_POOL_MIN cannot be greater than DB_POOL_MAX.');
  if (poolIncrement < 1) throw new Error('DB_POOL_INCREMENT must be at least 1.');

  return {
    user: requiredEnvironmentValue('DB_USER'),
    password: requiredEnvironmentValue('DB_PASSWORD'),
    connectString: requiredEnvironmentValue('DB_TNS_ALIAS'),
    walletLocation: path.resolve(requiredEnvironmentValue('DB_WALLET_LOCATION')),
    walletPassword: requiredEnvironmentValue('DB_WALLET_PASSWORD'),
    poolMin,
    poolMax,
    poolIncrement,
  };
}

declare module 'oracledb' {
  export const OUT_FORMAT_ARRAY: number;
  export const OUT_FORMAT_OBJECT: number;
  export const CLOB: number;

  export type ExecuteOptions = {
    outFormat?: number;
    fetchArraySize?: number;
    maxRows?: number;
  };

  export type Result<T> = {
    rows?: T[];
    rowsAffected?: number;
  };

  export interface Connection {
    execute<T>(sql: string, binds?: Record<string, unknown> | unknown[], options?: ExecuteOptions): Promise<Result<T>>;
    close(): Promise<void>;
    commit(): Promise<void>;
    rollback(): Promise<void>;
  }

  export interface Pool {
    getConnection(): Promise<Connection>;
    close(drainTime?: number): Promise<void>;
  }

  export type PoolAttributes = {
    user: string;
    password: string;
    connectString: string;
    configDir?: string;
    walletLocation?: string;
    walletPassword?: string;
    poolMin?: number;
    poolMax?: number;
    poolIncrement?: number;
    homogeneous?: boolean;
  };

  export let fetchAsString: number[];
  export function createPool(attributes: PoolAttributes): Promise<Pool>;

  const oracledb: {
    OUT_FORMAT_ARRAY: number;
    OUT_FORMAT_OBJECT: number;
    CLOB: number;
    fetchAsString: number[];
    createPool: typeof createPool;
  };

  export default oracledb;
}

import type { NextConfig } from 'next';
const nextConfig: NextConfig = {
  // Pools survive development reloads. Keep their driver and bind-type classes
  // in Node's module cache, not separately reloaded server bundles (NJS-012).
  serverExternalPackages: ['oracledb'],
};
export default nextConfig;

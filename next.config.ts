import type { NextConfig } from 'next';
const nextConfig: NextConfig = {
 distDir: process.env.NODE_ENV === 'development' ? '.next-dev' : '.next',
 experimental: { proxyTimeout: 120_000 },
 async rewrites() {
  const backend = process.env.BACKEND_URL || 'http://127.0.0.1:8001';
  return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }];
 },
};
export default nextConfig;

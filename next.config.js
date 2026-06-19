/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: '/api/:path*', destination: 'http://127.0.0.1:8000/api/:path*' },
      { source: '/storage/:path*', destination: 'http://127.0.0.1:8000/storage/:path*' },
    ];
  },
  // WebSocket connections should use ws://127.0.0.1:8000/ws/{job_id} directly
  // Next.js rewrites do not handle WebSocket upgrade; the frontend
  // must be configured to connect to the backend WebSocket directly.
  serverExternalPackages: [],
};

module.exports = nextConfig;

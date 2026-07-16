/**
 * Next.js config for the Winnow demo dashboard.
 *
 * Rewrites `/api/*` to the FastAPI backend so the browser sees a
 * single origin (localhost:3000). This makes the `winnow_session`
 * cookie a first-party, `SameSite=Lax` cookie — no CORS-with-credentials
 * dance required in development.
 */
const API_ORIGIN = process.env.WINNOW_API_ORIGIN ?? 'http://localhost:8000';

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${API_ORIGIN}/:path*` }];
  },
};

export default nextConfig;

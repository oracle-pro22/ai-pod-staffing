import { NextRequest, NextResponse } from 'next/server';

/** Retain historical assets for local preview, but do not expose a second prototype UI in live mode. */
export function middleware(_request: NextRequest) {
  if (process.env.STAFFING_AGENTIC_ENABLED === 'true') {
    return new NextResponse('Not found', { status: 404, headers: { 'Cache-Control': 'no-store' } });
  }
  return NextResponse.next();
}

export const config = { matcher: ['/prototype.html', '/prototype-app.js'] };

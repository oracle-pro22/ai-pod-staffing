import { NextResponse } from 'next/server';
import { people } from '@/lib/staffing-data';

export async function POST(request: Request) {
  const { message = '' } = await request.json();
  // TODO(26ai chat): send message + authorized staffing context to the 26ai app chat model.
  const available = people.filter(p => p.allocation < 60).map(p => `${p.name} (${p.allocation}%)`).join(', ');
  const answer = /maya/i.test(message) ? 'Maya has the strongest video match, but she is at 84% allocation. Adding this request would exceed the 85% guardrail; Noah is the recommended alternate.' : /available|capacity/i.test(message) ? `Most available people are ${available}. Interest fit should still be reviewed before assignment.` : 'This is a prototype response. When 26ai chat is connected, I will ground answers in the live staffing data and its access controls.';
  return NextResponse.json({ answer, source: 'prototype-placeholder' });
}

# AI Pod Staffing prototype

Run with `npm run dev` and open http://localhost:3001. Port 3000 is already used by another local app on this machine.

The UI is a Next.js recreation of the supplied mockup. `data/ai-pod-staffing-prototype.xlsx` is the editable prototype source. `lib/staffing-data.ts` is the temporary UI adapter.

Future 26ai handoff points: `lib/staffing-data.ts` for database reads, `app/api/staffing/route.ts` for the secure data boundary, and `app/api/chat/route.ts` for a 26ai chat-model request grounded in authorized staffing context. `sql/001_ai_pod_staffing.sql` provides the PostgreSQL schema and Excel-to-CSV load templates.

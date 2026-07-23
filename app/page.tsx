export default function Home() {
  // The prototype is deliberately served verbatim: it is the agreed UI source of truth.
  // Data/API adapters remain available at /api/staffing and /api/chat for the 26ai handoff.
  return <iframe title="AI Pod Staffing prototype" src="/prototype.html" style={{ border: 0, width: '100%', height: '100vh', display: 'block' }} />;
}

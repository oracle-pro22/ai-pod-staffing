'use client';

import { type KeyboardEvent, useEffect, useRef, useState } from 'react';

import { useStaffingApp } from '@/context/StaffingAppProvider';

type Message = { id: number; role: 'ai' | 'me'; text: string };

const QUICK_QUESTIONS = ['Who has capacity?', 'Explain REQ-1042', 'Customer project types'] as const;

export function AskAiPod() {
  const { state } = useStaffingApp();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const [messages, setMessages] = useState<Message[]>([
    { id: 1, role: 'ai', text: 'I answer from the staffing workbook and respect the selected persona.' },
  ]);

  async function send(question: string) {
    const trimmed = question.trim();
    if (!trimmed || sending) return;
    const userId = Date.now();
    const waitingId = userId + 1;
    setMessages((current) => [...current, { id: userId, role: 'me', text: trimmed }, { id: waitingId, role: 'ai', text: 'Checking the staffing workbook…' }]);
    setInput('');
    setSending(true);
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: trimmed, role: state.role }),
      });
      if (!response.ok) throw new Error(`Chat request failed (${response.status})`);
      const result = await response.json() as { answer?: string };
      setMessages((current) => current.map((message) => message.id === waitingId
        ? { ...message, text: result.answer ?? 'No answer was returned.' }
        : message));
    } catch {
      setMessages((current) => current.map((message) => message.id === waitingId
        ? { ...message, text: 'I could not read the staffing workbook right now. Please retry after checking the local server.' }
        : message));
    } finally {
      setSending(false);
    }
  }

  function submitOnEnter(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') void send(input);
  }

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    function closeOnEscape(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [open]);

  return (
    <>
      <button type="button" className="staffing-ask-btn" aria-expanded={open} aria-controls="staffing-ai-chat" onClick={() => setOpen((value) => !value)}>✦ Ask AI Pod</button>
      <section id="staffing-ai-chat" className={`staffing-chat${open ? ' open' : ''}`} aria-label="Ask AI Pod" aria-hidden={!open}>
        <div className="staffing-chat-head"><b>Ask AI Pod</b><button type="button" onClick={() => setOpen(false)} aria-label="Close chat">×</button></div>
        <div className="staffing-chat-body">
          {messages.map((message) => <div key={message.id} className={`staffing-bubble ${message.role}`}>{message.text}</div>)}
        </div>
        <div className="staffing-chat-quick">
          {QUICK_QUESTIONS.map((question) => <button type="button" key={question} onClick={() => void send(question)}>{question}</button>)}
        </div>
        <div className="staffing-chat-input">
          <input ref={inputRef} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={submitOnEnter} placeholder="Ask about workbook staffing data..." aria-label="Ask AI Pod a question" />
          <button type="button" onClick={() => void send(input)} disabled={sending}>Send</button>
        </div>
      </section>
    </>
  );
}

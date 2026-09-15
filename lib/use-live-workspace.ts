'use client';
import { staffingFetch } from '@/lib/staffing-fetch';
import { useEffect, useRef, useState } from 'react';
import type { LiveWorkspace } from '@/types/assignments';
import { STAFFING_CHANGED_EVENT } from '@/lib/project-closure';

export function useLiveWorkspace(resource: string, week = '') {
  const [snapshot, setSnapshot] = useState<LiveWorkspace | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const activeRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    const invalidate = () => { activeRequest.current?.abort(); setSnapshot(null); setRevision(n => n + 1); };
    window.addEventListener(STAFFING_CHANGED_EVENT, invalidate);
    return () => window.removeEventListener(STAFFING_CHANGED_EVENT, invalidate);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    activeRequest.current = controller;
    setSnapshot(null); setError('');
    staffingFetch(`/api/agentic/workspace?resource=${encodeURIComponent(resource)}${week ? `&week=${week}` : ''}`, {
      cache: 'no-store', signal: controller.signal,
    }).then(async r => {
      const body = await r.json();
      if (!r.ok) throw new Error(typeof body.error === 'string' ? body.error : body.error?.message || 'Unable to load workspace.');
      if (!controller.signal.aborted) setSnapshot(body.data);
    }).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [resource, week, revision]);
  return { snapshot, error, refresh: () => setRevision(n => n + 1) };
}

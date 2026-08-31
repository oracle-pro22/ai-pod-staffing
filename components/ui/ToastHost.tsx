'use client';

import { useEffect } from 'react';

import { useStaffingApp } from '@/context/StaffingAppProvider';
import type { ToastMessage } from '@/types/ui';

function ToastItem({ toast }: { toast: ToastMessage }) {
  const { dispatch } = useStaffingApp();
  useEffect(() => {
    const timer = window.setTimeout(() => dispatch({ type: 'remove-toast', id: toast.id }), 3900);
    return () => window.clearTimeout(timer);
  }, [dispatch, toast.id]);
  return <div className="staffing-toast"><strong>{toast.title}</strong><span>{toast.message}</span></div>;
}

export function ToastHost() {
  const { state } = useStaffingApp();
  return <div className="staffing-toast-wrap" aria-live="polite">{state.toasts.map((toast) => <ToastItem key={toast.id} toast={toast} />)}</div>;
}


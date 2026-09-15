'use client';
import { staffingFetch } from '@/lib/staffing-fetch';

import { type TextareaHTMLAttributes, useEffect, useId, useRef, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { TextArea } from '@/components/ui/FormControls';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import type {
  AiRephraseContext,
  AiRephraseField,
  AiRephraseResponse,
} from '@/types/ai-rephrase';

type AiRephraseTextareaProps = Omit<
  TextareaHTMLAttributes<HTMLTextAreaElement>,
  'defaultValue' | 'onChange' | 'value'
> & {
  field: AiRephraseField;
  value: string;
  context?: AiRephraseContext;
  onChange: (value: string) => void;
  onBusyChange?: (field: AiRephraseField, busy: boolean) => void;
};

type RephraseApiResult = {
  data?: AiRephraseResponse;
  error?: string;
};

export function AiRephraseTextarea({
  field,
  value,
  context,
  onChange,
  onBusyChange,
  disabled = false,
  ...textareaProps
}: AiRephraseTextareaProps) {
  const { state, notify } = useStaffingApp();
  const [loading, setLoading] = useState(false);
  const [previousText, setPreviousText] = useState<string | null>(null);
  const requestNumber = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const statusId = useId();
  const busyCallback = useRef(onBusyChange);
  busyCallback.current = onBusyChange;

  useEffect(() => () => {
    requestNumber.current += 1;
    controller.current?.abort();
    busyCallback.current?.(field, false);
  }, [field]);

  function changeText(nextValue: string) {
    if (previousText !== null) setPreviousText(null);
    onChange(nextValue);
  }

  function undo() {
    if (previousText === null) return;
    onChange(previousText);
    setPreviousText(null);
  }

  async function rephrase() {
    const sourceText = value.trim();
    if (sourceText.length < 10 || sourceText.length > 6000 || loading || disabled) return;

    controller.current?.abort();
    const activeController = new AbortController();
    controller.current = activeController;
    const activeRequest = ++requestNumber.current;
    setLoading(true);
    busyCallback.current?.(field, true);

    try {
      const response = await staffingFetch('/api/ai/rephrase', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-staffing-role': state.role,
        },
        body: JSON.stringify({ field, text: sourceText, context }),
        cache: 'no-store',
        signal: activeController.signal,
      });
      const result = await response.json().catch(() => ({})) as RephraseApiResult;
      if (activeRequest !== requestNumber.current) return;
      if (!response.ok || !result.data?.suggestion) {
        notify('Text not rephrased', result.error || 'AI rephrasing is temporarily unavailable.');
        return;
      }

      if (typeof result.data.suggestion !== 'string' || (textareaProps.maxLength && result.data.suggestion.length > textareaProps.maxLength)) {
        notify('Text not rephrased', 'The suggestion is too long for this field. Your original text has been kept.');
        return;
      }
      setPreviousText(value);
      onChange(result.data.suggestion);
    } catch (error) {
      if (activeRequest !== requestNumber.current) return;
      if (!(error instanceof DOMException && error.name === 'AbortError')) {
        notify('Text not rephrased', 'AI rephrasing is temporarily unavailable.');
      }
    } finally {
      if (activeRequest === requestNumber.current) {
        setLoading(false);
        busyCallback.current?.(field, false);
      }
    }
  }

  const canRephrase = value.trim().length >= 10 && value.trim().length <= 6000 && !loading && !disabled;

  return (
    <div className="staffing-ai-rephrase-field">
      <TextArea
        {...textareaProps}
        value={value}
        disabled={disabled}
        readOnly={loading || textareaProps.readOnly}
        aria-describedby={previousText !== null || loading ? statusId : textareaProps['aria-describedby']}
        aria-busy={loading}
        onChange={(event) => changeText(event.target.value)}
      />
      <div className="staffing-ai-rephrase-actions">
        <span id={statusId} className="staffing-ai-rephrase-status" aria-live="polite">
          {loading ? 'Improving your text…' : previousText !== null ? 'Rephrased by AI' : value.trim().length > 6000 ? 'Shorten to 6,000 characters to rephrase.' : ''}
          {previousText !== null && !loading ? (
            <button type="button" className="staffing-ai-rephrase-undo" disabled={disabled} onClick={undo}>Undo</button>
          ) : null}
        </span>
        <Button
          type="button"
          size="small"
          className="staffing-ai-rephrase-button"
          disabled={!canRephrase}
          onClick={rephrase}
        >
          {loading ? 'Rephrasing…' : previousText !== null ? '✦ Rephrase again' : '✦ Rephrase with AI'}
        </Button>
      </div>
    </div>
  );
}

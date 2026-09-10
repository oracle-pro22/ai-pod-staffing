import 'server-only';

import { readAiRephraseConfig } from '@/backend/ai/rephrase/config';
import { buildAiRephrasePrompt } from '@/backend/ai/rephrase/prompt';
import { requestOciRephrase } from '@/backend/ai/rephrase/provider';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';
import type { AiRephraseRequest, AiRephraseResponse } from '@/types/ai-rephrase';
import type { StaffingMutationContext } from '@/types/mutations';

function errorStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object') return undefined;
  const source = error as { status?: unknown; statusCode?: unknown };
  const status = Number(source.statusCode ?? source.status);
  return Number.isInteger(status) ? status : undefined;
}

function errorName(error: unknown): string {
  return error instanceof Error ? error.name : 'UnknownError';
}

function isTimeout(error: unknown): boolean {
  return errorName(error).toLowerCase().includes('timeout');
}

export async function rephraseText(
  input: AiRephraseRequest,
  context: StaffingMutationContext,
): Promise<AiRephraseResponse> {
  const startedAt = Date.now();
  try {
    const config = readAiRephraseConfig();
    const prompt = buildAiRephrasePrompt(input);
    const suggestion = await requestOciRephrase(config, prompt);
    console.info('AI rephrasing completed.', {
      actor: context.actor,
      field: input.field,
      durationMs: Date.now() - startedAt,
    });
    return { suggestion };
  } catch (error) {
    if (error instanceof StaffingApiError) throw error;

    const status = errorStatus(error);
    console.error('AI rephrasing failed.', {
      actor: context.actor,
      field: input.field,
      durationMs: Date.now() - startedAt,
      providerStatus: status,
      errorType: errorName(error),
    });

    if (status === 429) {
      throw new StaffingApiError(
        'AI rephrasing is busy. Please try again shortly.',
        429,
        'AI_REPHRASE_RATE_LIMITED',
      );
    }
    if (isTimeout(error)) {
      throw new StaffingApiError(
        'AI rephrasing took too long. Please try again.',
        504,
        'AI_REPHRASE_TIMEOUT',
      );
    }
    throw new StaffingApiError(
      'AI rephrasing is temporarily unavailable.',
      503,
      'AI_REPHRASE_UNAVAILABLE',
    );
  }
}

import 'server-only';

import type { AiRephraseConfig } from '@/backend/ai/rephrase/config';
import { validateAiRephraseSuggestion } from '@/backend/ai/rephrase/validation';
import { readOciConfigFileCredentials } from '@/backend/oci/config-file-auth';
import { postSignedOciJson } from '@/backend/oci/signed-json-request';

type RephraseProviderInput = {
  instructions: string;
  source: string;
};

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function responseText(value: unknown): string {
  const root = record(value);
  const chatResponse = record(root?.chatResponse);
  const choices = chatResponse?.choices;
  if (!Array.isArray(choices) || choices.length === 0) {
    throw new Error('OCI Generative AI returned no chat choices.');
  }

  const message = record(record(choices[0])?.message);
  const content = message?.content;
  if (!Array.isArray(content)) throw new Error('OCI Generative AI returned no message content.');

  const text = content
    .map((item) => record(item))
    .find((item) => item?.type === 'TEXT' && typeof item.text === 'string')?.text;
  if (typeof text !== 'string') throw new Error('OCI Generative AI returned no text content.');
  return text;
}

export async function requestOciRephrase(
  config: AiRephraseConfig,
  input: RephraseProviderInput,
): Promise<string> {
  const credentials = await readOciConfigFileCredentials(config.configFile, config.configProfile);
  const response = await postSignedOciJson(
    new URL('/20231130/actions/chat', config.endpoint),
    {
      compartmentId: config.compartmentId,
      servingMode: {
        servingType: 'ON_DEMAND',
        modelId: config.modelId,
      },
      chatRequest: {
        apiFormat: 'GENERIC',
        messages: [
          {
            role: 'SYSTEM',
            content: [{ type: 'TEXT', text: input.instructions }],
          },
          {
            role: 'USER',
            content: [{ type: 'TEXT', text: input.source }],
          },
        ],
        maxCompletionTokens: 1_000,
        verbosity: 'MEDIUM',
        isStream: false,
      },
    },
    credentials,
    config.timeoutMs,
  );

  return validateAiRephraseSuggestion(responseText(response));
}

import 'server-only';

import { createHash, createSign, randomUUID } from 'node:crypto';

import type { OciConfigFileCredentials } from '@/backend/oci/config-file-auth';

export class OciHttpError extends Error {
  constructor(
    message: string,
    readonly statusCode: number,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = 'OciHttpError';
  }
}

function ociErrorMessage(value: unknown, status: number): string {
  if (value && typeof value === 'object' && 'message' in value) {
    const message = (value as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message.trim();
  }
  return `OCI Generative AI returned HTTP ${status}.`;
}

export async function postSignedOciJson(
  url: URL,
  body: unknown,
  credentials: OciConfigFileCredentials,
  timeoutMs: number,
): Promise<unknown> {
  const method = 'post';
  const payload = JSON.stringify(body);
  const contentLength = Buffer.byteLength(payload, 'utf8').toString();
  const contentHash = createHash('sha256').update(payload, 'utf8').digest('base64');
  const date = new Date().toUTCString();
  const requestTarget = `${url.pathname}${url.search}`;
  const signedHeaders = [
    '(request-target)',
    'host',
    'date',
    'x-content-sha256',
    'content-type',
    'content-length',
  ];
  const signingString = [
    `(request-target): ${method} ${requestTarget}`,
    `host: ${url.host}`,
    `date: ${date}`,
    `x-content-sha256: ${contentHash}`,
    'content-type: application/json',
    `content-length: ${contentLength}`,
  ].join('\n');
  const signature = createSign('RSA-SHA256')
    .update(signingString)
    .end()
    .sign(
      credentials.passphrase
        ? { key: credentials.privateKeyPem, passphrase: credentials.passphrase }
        : credentials.privateKeyPem,
      'base64',
    );
  const keyId = `${credentials.tenancy}/${credentials.user}/${credentials.fingerprint}`;
  const authorization = [
    'Signature version="1"',
    `keyId="${keyId}"`,
    'algorithm="rsa-sha256"',
    `headers="${signedHeaders.join(' ')}"`,
    `signature="${signature}"`,
  ].join(',');

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      Authorization: authorization,
      'Content-Type': 'application/json',
      'Content-Length': contentLength,
      Date: date,
      Host: url.host,
      'opc-request-id': randomUUID(),
      'x-content-sha256': contentHash,
    },
    body: payload,
    cache: 'no-store',
    signal: AbortSignal.timeout(timeoutMs),
  });

  const responseBody = await response.json().catch(() => undefined);
  if (!response.ok) {
    throw new OciHttpError(
      ociErrorMessage(responseBody, response.status),
      response.status,
      response.headers.get('opc-request-id') ?? undefined,
    );
  }
  return responseBody;
}

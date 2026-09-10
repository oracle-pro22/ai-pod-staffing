import 'server-only';

import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, isAbsolute, join, resolve } from 'node:path';

export type OciConfigFileCredentials = {
  tenancy: string;
  user: string;
  fingerprint: string;
  privateKeyPem: string;
  passphrase?: string;
};

function expandHome(path: string): string {
  if (path === '~') return homedir();
  if (path.startsWith('~/') || path.startsWith('~\\')) return join(homedir(), path.slice(2));
  return path;
}

function requiredValue(profile: Record<string, string>, name: string, profileName: string): string {
  const value = profile[name]?.trim();
  if (!value) throw new Error(`OCI config profile ${profileName} is missing ${name}.`);
  return value;
}

function parseProfile(source: string, profileName: string): Record<string, string> {
  const profiles = new Map<string, Record<string, string>>();
  let current: Record<string, string> | undefined;

  for (const rawLine of source.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#') || line.startsWith(';')) continue;

    const section = line.match(/^\[([^\]]+)]$/);
    if (section) {
      current = {};
      profiles.set(section[1].trim(), current);
      continue;
    }

    if (!current) continue;
    const separator = line.indexOf('=');
    if (separator <= 0) continue;
    current[line.slice(0, separator).trim()] = line.slice(separator + 1).trim();
  }

  const profile = profiles.get(profileName);
  if (!profile) throw new Error(`OCI config profile ${profileName} was not found.`);
  return profile;
}

export async function readOciConfigFileCredentials(
  configFile: string,
  profileName: string,
): Promise<OciConfigFileCredentials> {
  const expandedConfigFile = expandHome(configFile);
  const absoluteConfigFile = isAbsolute(expandedConfigFile) ? expandedConfigFile : resolve(expandedConfigFile);
  const profile = parseProfile(await readFile(absoluteConfigFile, 'utf8'), profileName);
  const configuredKeyFile = expandHome(requiredValue(profile, 'key_file', profileName));
  const keyFile = isAbsolute(configuredKeyFile)
    ? configuredKeyFile
    : resolve(dirname(absoluteConfigFile), configuredKeyFile);

  return {
    tenancy: requiredValue(profile, 'tenancy', profileName),
    user: requiredValue(profile, 'user', profileName),
    fingerprint: requiredValue(profile, 'fingerprint', profileName),
    privateKeyPem: await readFile(keyFile, 'utf8'),
    passphrase: profile.pass_phrase?.trim() || undefined,
  };
}

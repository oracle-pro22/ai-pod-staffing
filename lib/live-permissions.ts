type Identity = {
  person_id: string;
  roles: string[];
  permissions: { role: string; resource: string; scope: string; actions: string[] }[];
};

/** Mirror the API's explicit Captain grant and scope; display rank does not authorize a decision. */
export function canCaptainAct(identity: Identity | null, resource: string, action: string, responsibleCaptainId?: string): boolean {
  return Boolean(identity?.roles.includes('POD_CAPTAIN') && identity.permissions.some(permission =>
    permission.role === 'POD_CAPTAIN' && permission.resource === resource
    && permission.actions.includes('view') && permission.actions.includes(action)
    && (permission.scope === 'FULL' || (['SCOPED', 'OWN'].includes(permission.scope)
      && identity.person_id === responsibleCaptainId))));
}

'use client';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Notice } from '@/components/ui/Notice';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pill } from '@/components/ui/Pill';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canPerform, configuredRolePermission, type PermissionAction } from '@/lib/role-policy';
import { STAFFING_ROLES } from '@/types/roles';
import { UtilizationSettings } from './UtilizationSettings';
import { AccountAccess } from './AccountAccess';

const ACTIONS: { label: string; resource: string; action: PermissionAction }[] = [
  { label: 'Submit requests', resource: 'REQUESTS', action: 'canCreate' },
  { label: 'Review POD', resource: 'AI_FITMENT', action: 'canView' },
  { label: 'Approve POD', resource: 'AI_FITMENT', action: 'canApprove' },
  { label: 'Manage projects', resource: 'REQUESTS', action: 'canUpdate' },
  { label: 'Close projects', resource: 'PROJECT_CLOSURE', action: 'canUpdate' },
  { label: 'View team', resource: 'TEAM_SKILLS', action: 'canView' },
  { label: 'Configuration', resource: 'BACKEND_CONFIGURATION', action: 'canAdminister' },
  { label: 'Access', resource: 'ACCESS_MANAGEMENT', action: 'canAdminister' },
];

export function AdministrationScreen() {
  const { data, state, dispatch, setRole, notify } = useStaffingApp();
  const tabs = [['roles', 'Roles & access'], ['taxonomy', 'Taxonomies'], ['rules', 'Agent rules'], ['audit', 'Audit trail']] as const;
  const pending = () => notify('Feature in progress', 'This workflow will be available in a future release.');
  return <section className="staffing-screen">
    <PageHeader title="Administration" description="Review profile permissions, catalogue configuration, and integration status." actions={<>
      {!data.identity && <Button onClick={() => setRole('POD Member')}>Preview as POD Member</Button>}
      {state.adminTab !== 'rules' && canPerform(state.role, 'BACKEND_CONFIGURATION', 'canUpdate', data.authorization) ? <Button variant="primary" onClick={pending}>Save changes</Button> : null}
    </>} />
    <Card padded>
      <div className="staffing-admin-tabs">{tabs.map(([id, label]) => <button type="button" className={state.adminTab === id ? 'active' : ''} key={id} onClick={() => dispatch({ type: 'set-admin-tab', tab: id })}>{label}</button>)}</div>
      {state.adminTab === 'roles' ? <div className="staffing-admin-panel">
        <p className="staffing-muted">Permissions loaded from Oracle. POD Lead and POD Member access is limited to their assigned projects and team. Permission does not mean an on-hold workflow is implemented.</p>
        <div style={{ overflowX: 'auto' }}><table className="staffing-role-table">
          <thead><tr><th>Profile</th>{ACTIONS.map((item) => <th key={item.label}>{item.label}</th>)}</tr></thead>
          <tbody>{STAFFING_ROLES.map((role) => <tr key={role}><th>{role}</th>{ACTIONS.map((item) => {
            const permission = configuredRolePermission(role, item.resource, data.authorization);
            return <td key={item.label}>{permission?.canView && permission.accessScope !== 'locked' && permission[item.action] ? 'Allowed' : '—'}</td>;
          })}</tr>)}</tbody>
        </table></div>
        {data.identity && canPerform(state.role, 'ACCESS_MANAGEMENT', 'canAdminister', data.authorization) ? <AccountAccess /> : null}
      </div> : null}
      {state.adminTab === 'taxonomy' ? <div className="staffing-admin-panel staffing-grid staffing-two-col"><div>
        <h3>Project and deliverable catalogue</h3><p className="staffing-muted">Current active catalogue from Oracle. Retired entries remain on historical requests.</p>
        {data.catalog.projects.map((project, index) => <details className="staffing-catalog-project" open={index === 0} key={project.id}>
          <summary>{project.name} <small>({project.deliverables.length})</small></summary><div>{project.description ? <p>{project.description}</p> : null}
            {project.deliverables.map((deliverable) => <div className="staffing-catalog-deliverable" key={deliverable.id}><b>{deliverable.name}</b><p>{deliverable.note || 'No customer note recorded'}</p>
              {deliverable.skills.length ? <div className="staffing-tag-row">{deliverable.skills.map((skill) => <span key={skill.id}>{skill.name}</span>)}</div> : <p>No default capabilities supplied. Choose capabilities when creating the request.</p>}
            </div>)}
          </div></details>)}
      </div><div><h3>Skills (Type of work)</h3><p className="staffing-muted">Customer terminology stored in the database.</p>
        {data.catalog.skills.map((skill) => <div className="staffing-taxonomy-item" key={skill.id}><span><b>{skill.name}</b><small>{skill.category}</small></span><Pill tone="teal">Customer controlled</Pill></div>)}
      </div></div> : null}
      {state.adminTab === 'rules' ? <div className="staffing-admin-panel">
        {state.role === 'Administrator' && canPerform(state.role, 'BACKEND_CONFIGURATION', 'canAdminister', data.authorization)
          ? <UtilizationSettings /> : <Notice title="Administrator access required">Only an Administrator can edit the utilization limit.</Notice>}
      </div> : null}
      {state.adminTab === 'audit' ? <div className="staffing-admin-panel">
        <Notice title="Audit trail on hold">Immutable audit, approval history, and final assignment persistence are not enabled in the current model.</Notice>
        <Button onClick={pending}>View audit trail</Button>
      </div> : null}
    </Card>
  </section>;
}

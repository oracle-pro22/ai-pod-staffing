'use client';

import { CreateRequestModal } from '@/components/overlays/CreateRequestModal';
import { Button } from '@/components/ui/Button';
import { Drawer } from '@/components/ui/Drawer';
import { FormGroup, TextArea } from '@/components/ui/FormControls';
import { Modal } from '@/components/ui/Modal';
import { Notice } from '@/components/ui/Notice';
import { Pill } from '@/components/ui/Pill';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { resolveFitmentRecommendations } from '@/lib/demo-fitment';
import { formatDate, requestEffortLabel } from '@/lib/formatting';
import {
  selectActiveRequest,
  selectScopedRecommendations,
  selectVisiblePeople,
  selectVisibleRequests,
} from '@/lib/selectors';

export function RequestOverlays() {
  return <><RequestDetailsDrawer /><CreateRequestModal /><ApprovalModal /></>;
}

function RequestDetailsDrawer() {
  const { data, state, dispatch } = useStaffingApp();
  const open = state.drawer?.id === 'request-details';
  const requestId = typeof state.drawer?.payload?.requestId === 'string' ? state.drawer.payload.requestId : null;
  const request = selectVisibleRequests(data, state.role).find((item) => item.id === requestId) ?? null;
  const close = () => dispatch({ type: 'close-drawer' });
  return (
    <Drawer open={open} title={request?.title ?? 'Request details'} onClose={close} footer={<><Button onClick={close}>Close</Button>{request ? <Button variant="primary" onClick={() => { dispatch({ type: 'set-active-request', requestId: request.id }); close(); dispatch({ type: 'set-screen', screen: 'fitment' }); }}>Open fitment</Button> : null}</>}>
      {request ? <>
        <Pill tone="blue">{request.id}</Pill><h3>{request.projectType.name}</h3>
        <dl className="staffing-summary-list">
          <div><dt>Key deliverables</dt><dd>{request.deliverables.map((item) => item.name).join(', ')}</dd></div>
          <div><dt>Required capabilities</dt><dd><div className="staffing-tag-row">{request.requiredSkills.map((skill) => <span key={skill.id}>{skill.name}</span>)}</div></dd></div>
          <div><dt>Request source</dt><dd>{request.requestSource}</dd></div>
          <div><dt>Status</dt><dd>{request.status}</dd></div>
          <div><dt>Needed by date</dt><dd>{formatDate(request.neededBy)}</dd></div>
          {request.estimatedStartDate ? <div><dt>Estimated start date</dt><dd>{formatDate(request.estimatedStartDate)}</dd></div> : null}
          {request.estimatedCompletionDate ? <div><dt>Estimated completion date</dt><dd>{formatDate(request.estimatedCompletionDate)}</dd></div> : null}
          <div><dt>Estimated effort</dt><dd>{requestEffortLabel(request)}</dd></div>
          {request.requestedPodSize ? <div><dt>Requested pod size</dt><dd>{request.requestedPodSize}</dd></div> : null}
        </dl>
        <div className="staffing-fit-summary-note"><b>Project description</b><p>{request.projectDescription || 'No project description recorded'}</p></div>
        <div className="staffing-fit-summary-note"><b>Business objectives</b><p>{request.businessObjectives || request.businessContext || 'No business objectives recorded'}</p></div>
        <div className="staffing-fit-summary-note"><b>Expected outcomes</b><p>{request.expectedOutcomes || 'No expected outcomes recorded'}</p></div>
        <div className="staffing-source-strip"><span>{request.mappingVersion}</span><span>•</span><span>{request.recommendations.length ? `${request.recommendations.length} scoped recommendations` : 'Demo fitment available'}</span></div>
      </> : <div className="staffing-empty">Request unavailable in the current access scope.</div>}
    </Drawer>
  );
}

function ApprovalModal() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const open = state.modal?.id === 'approve-pod';
  const requestId = typeof state.modal?.payload?.requestId === 'string' ? state.modal.payload.requestId : null;
  const request = selectActiveRequest(data, state.role, requestId);
  const storedRecommendations = selectScopedRecommendations(request, data, state.role);
  const { recommendations, isDemo } = resolveFitmentRecommendations(
    request,
    storedRecommendations,
    selectVisiblePeople(data, state.role),
  );
  const selectedIds = request ? state.selectedCandidatesByRequest[request.id] ?? [] : [];
  const selectedNames = selectedIds.map((id) => data.people.find((person) => person.id === id)?.name).filter(Boolean);
  const suggested = recommendations.slice(0, 3).map((item) => item.personName);
  const close = () => dispatch({ type: 'close-modal' });
  return <Modal open={open} title="Approve proposed pod" onClose={close} footer={<><Button onClick={close}>Cancel</Button><Button variant="primary" onClick={() => { close(); notify('Integration in progress', 'This workflow will be available in a future release.'); }}>Approve & notify</Button></>}>
    <Notice icon="✓" title="Human approval required">You are reviewing the proposed staffing pod for {request?.id ?? 'this request'}. {isDemo ? 'These candidates are simulated for demonstration and will not be saved.' : 'No assignment is made without this decision.'}</Notice>
    <div className="staffing-approval-summary"><b>{request?.title}</b><p>{(selectedNames.length ? selectedNames : suggested).join(', ') || 'No candidates selected'}</p></div>
    <FormGroup label="Approval comment" full><TextArea defaultValue="Approved based on fit, delivery history, and protected capacity." /></FormGroup>
  </Modal>;
}

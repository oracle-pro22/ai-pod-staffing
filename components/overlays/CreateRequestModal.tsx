'use client';

import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/Button';
import { FormGroup, SelectField, TextArea, TextField } from '@/components/ui/FormControls';
import { Modal } from '@/components/ui/Modal';
import { PersonCombobox } from '@/components/ui/PersonCombobox';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { requestBusinessDate } from '@/lib/request-date-policy';
import type {
  CatalogDeliverable,
  RequestDeliverable,
  RequiredCapability,
} from '@/types/staffing';
import type { RequestCreatedResult } from '@/types/mutations';

export function CreateRequestModal() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const router = useRouter();
  const open = state.modal?.id === 'create-request';
  const firstProject = data.catalog.projects[0];
  const [projectId, setProjectId] = useState(firstProject?.id ?? '');
  const project = data.catalog.projects.find((item) => item.id === projectId) ?? firstProject;
  const [deliverables, setDeliverables] = useState<RequestDeliverable[]>([]);
  const [capabilities, setCapabilities] = useState<RequiredCapability[]>([]);
  const [deliverableChoice, setDeliverableChoice] = useState('');
  const [capabilityChoice, setCapabilityChoice] = useState('');
  const [customDeliverable, setCustomDeliverable] = useState('');
  const [customCapability, setCustomCapability] = useState('');
  const [requestSourcePersonId, setRequestSourcePersonId] = useState('');
  const [minimumDate, setMinimumDate] = useState(() => requestBusinessDate());
  const [neededBy, setNeededBy] = useState(() => requestBusinessDate());
  const [estimatedStartDate, setEstimatedStartDate] = useState(() => requestBusinessDate());
  const [estimatedCompletionDate, setEstimatedCompletionDate] = useState(() => requestBusinessDate());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !project) return;
    const initial = project.deliverables[0];
    setDeliverables(initial ? [toRequestDeliverable(initial)] : []);
    setCapabilities(initial ? initial.skills.map((skill) => ({ ...skill, requiredStrength: null, source: 'Customer catalogue' })) : []);
    setDeliverableChoice(project.deliverables[1]?.id ?? '');
    setCapabilityChoice('');
    setCustomDeliverable('');
    setCustomCapability('');
  }, [open, projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return;
    const today = requestBusinessDate();
    setMinimumDate(today);
    setNeededBy(today);
    setEstimatedStartDate(today);
    setEstimatedCompletionDate(today);
    setRequestSourcePersonId('');
  }, [open]);

  const availableDeliverables = project?.deliverables.filter((item) => !deliverables.some((selected) => selected.id === item.id)) ?? [];
  const notes = useMemo(() => deliverables.map((item) => item.note).filter(Boolean), [deliverables]);
  const close = () => dispatch({ type: 'close-modal' });

  function addDeliverable() {
    if (deliverableChoice === 'other') {
      const name = customDeliverable.trim();
      if (!name) return;
      setDeliverables((current) => [...current, { id: `CUSTOM-DEL-${Date.now()}`, name, note: '', custom: true }]);
      setCustomDeliverable('');
    } else {
      const item = project?.deliverables.find((candidate) => candidate.id === deliverableChoice);
      if (!item) return;
      setDeliverables((current) => [...current, toRequestDeliverable(item)]);
      setCapabilities((current) => mergeCapabilities(current, item.skills.map((skill) => ({ ...skill, requiredStrength: null, source: 'Customer catalogue' }))));
    }
    setDeliverableChoice('');
  }

  function addCapability() {
    if (capabilityChoice === 'other') {
      const name = customCapability.trim();
      if (!name) return;
      setCapabilities((current) => mergeCapabilities(current, [{ id: `CUSTOM-SKILL-${Date.now()}`, name, requiredStrength: null, source: 'Request entry', custom: true }]));
      setCustomCapability('');
    } else {
      const item = data.catalog.skills.find((skill) => skill.id === capabilityChoice);
      if (!item) return;
      setCapabilities((current) => mergeCapabilities(current, [{ id: item.id, name: item.name, requiredStrength: null, source: 'Customer taxonomy' }]));
    }
    setCapabilityChoice('');
  }

  function changeEstimatedStartDate(value: string) {
    setEstimatedStartDate(value);
    if (value && (!estimatedCompletionDate || estimatedCompletionDate < value)) {
      setEstimatedCompletionDate(value);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project || deliverables.length === 0 || capabilities.length === 0) {
      notify('Request incomplete', 'Add at least one deliverable and required capability.');
      return;
    }
    if (!requestSourcePersonId) {
      notify('Request incomplete', 'Select a request source from the people list.');
      return;
    }
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setSaving(true);
    try {
      const response = await fetch('/api/requests', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-staffing-role': state.role,
        },
        body: JSON.stringify({
          title: String(form.get('title') || ''),
          projectTypeId: project.id,
          requestSourcePersonId,
          projectDescription: String(form.get('projectDescription') || ''),
          deliverables,
          priority: String(form.get('priority') || ''),
          neededBy: String(form.get('neededBy') || ''),
          estimatedStartDate: String(form.get('startDate') || ''),
          estimatedCompletionDate: String(form.get('completionDate') || ''),
          estimatedEffort: {
            value: Number(form.get('effortValue') || 0),
            unit: String(form.get('effortUnit') || ''),
          },
          requestedPodSize: String(form.get('podSize') || ''),
          requiredCapabilities: capabilities,
          businessObjectives: String(form.get('businessObjectives') || ''),
          expectedOutcomes: String(form.get('expectedOutcomes') || ''),
        }),
      });
      const result = await response.json().catch(() => ({})) as { data?: RequestCreatedResult; error?: string };
      if (!response.ok || !result.data) {
        notify('Request not saved', result.error || 'The request could not be saved. Please try again.');
        return;
      }
      formElement.reset();
      close();
      router.refresh();
      notify('Request saved', `${result.data.requestId} was created successfully.`);
    } catch {
      notify('Request not saved', 'The database could not be reached. Please try again.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      title="Create staffing request"
      description="Provide the request details used to recommend the right pod."
      size="large"
      onClose={close}
      footerNote="Recommendations remain advisory until human approval."
      footer={<><Button type="button" onClick={close} disabled={saving}>Cancel</Button><Button type="submit" form="createStaffingRequest" variant="primary" disabled={saving}>{saving ? 'Saving…' : 'Save request'}</Button></>}
    >
      <form id="createStaffingRequest" className="staffing-create-request-form" onSubmit={submit}>
        <CreateSection title="Request overview" description="Core request information">
          <div className="staffing-create-grid">
            <FormGroup label="Request title" className="wide"><TextField name="title" required placeholder="Enter request title" /></FormGroup>
            <FormGroup label="Request source" className="third"><PersonCombobox people={data.people} value={requestSourcePersonId} onChange={setRequestSourcePersonId} disabled={saving} required /></FormGroup>
            <FormGroup label="Project type" className="third"><SelectField value={projectId} onChange={(event) => setProjectId(event.target.value)}>{data.catalog.projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</SelectField></FormGroup>
            <FormGroup label="Project description" className="wide"><TextArea key={project?.id} name="projectDescription" defaultValue={project?.description} placeholder="Describe the project and the work being requested" /></FormGroup>
          </div>
        </CreateSection>

        <CreateSection title="Deliverables and capabilities" description="Defaults come from the customer catalogue">
          <div className="staffing-create-grid">
            <FormGroup label="Key deliverables" className="half">
              <div className="staffing-editor-box">
                <div className="staffing-editor-meta">Catalogue defaults</div>
                <div className="staffing-chip-row">{deliverables.map((item) => <span className="staffing-edit-chip" key={item.id}>{item.name}<button type="button" aria-label={`Remove ${item.name}`} onClick={() => setDeliverables((current) => current.filter((selected) => selected.id !== item.id))}>×</button></span>)}</div>
                <div className="staffing-add-row"><SelectField aria-label="Add key deliverable" value={deliverableChoice} onChange={(event) => setDeliverableChoice(event.target.value)}><option value="">Select a deliverable</option>{availableDeliverables.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}<option value="other">Other — type a deliverable</option></SelectField><Button type="button" onClick={addDeliverable}>＋ Add</Button></div>
                {deliverableChoice === 'other' ? <TextField aria-label="Custom deliverable" value={customDeliverable} onChange={(event) => setCustomDeliverable(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addDeliverable(); } }} placeholder="Type a deliverable and press Enter" /> : null}
                <small>Choose mapped or request-specific deliverables.</small>
              </div>
            </FormGroup>

            <FormGroup label="Required capabilities" className="half">
              <div className="staffing-editor-box">
                <div className="staffing-editor-meta">Mapped to deliverables</div>
                <div className="staffing-chip-row">{capabilities.map((item) => <span className="staffing-edit-chip" key={item.id}>{item.name}<button type="button" aria-label={`Remove ${item.name}`} onClick={() => setCapabilities((current) => current.filter((selected) => selected.id !== item.id))}>×</button></span>)}</div>
                <div className="staffing-add-row"><SelectField aria-label="Add required capability" value={capabilityChoice} onChange={(event) => setCapabilityChoice(event.target.value)}><option value="">Select a capability</option>{data.catalog.skills.filter((skill) => !capabilities.some((item) => item.id === skill.id)).map((skill) => <option key={skill.id} value={skill.id}>{skill.name}</option>)}<option value="other">Other — type a capability</option></SelectField><Button type="button" onClick={addCapability}>＋ Add</Button></div>
                {capabilityChoice === 'other' ? <TextField aria-label="Custom capability" value={customCapability} onChange={(event) => setCustomCapability(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addCapability(); } }} placeholder="Type a capability and press Enter" /> : null}
                <small>Add or remove capabilities for this request.</small>
              </div>
            </FormGroup>

            <FormGroup label="Customer catalogue note" className="full"><div className="staffing-readonly-note">{notes.join(' ') || 'No customer note recorded for the selected deliverables.'}</div></FormGroup>
          </div>
        </CreateSection>

        <CreateSection title="Schedule and staffing" description="Timing, effort and requested pod">
          <div className="staffing-create-grid">
            <FormGroup label="Priority" className="third"><SelectField name="priority" defaultValue="Medium"><option>Low</option><option>Medium</option><option>High</option></SelectField></FormGroup>
            <FormGroup label="Needed by date" className="third"><TextField name="neededBy" required type="date" min={minimumDate} value={neededBy} onChange={(event) => setNeededBy(event.target.value)} /></FormGroup>
            <FormGroup label="Requested pod size" className="third"><SelectField name="podSize"><option>1 lead + 2 contributors</option><option>1 lead + 1 contributor</option><option>1 lead + 3 contributors</option></SelectField></FormGroup>
            <FormGroup label="Estimated start date" className="third"><TextField name="startDate" type="date" min={minimumDate} value={estimatedStartDate} onChange={(event) => changeEstimatedStartDate(event.target.value)} /></FormGroup>
            <FormGroup label="Estimated completion date" className="third"><TextField name="completionDate" type="date" min={estimatedStartDate || minimumDate} value={estimatedCompletionDate} onChange={(event) => setEstimatedCompletionDate(event.target.value)} /></FormGroup>
            <FormGroup label="Estimated effort" className="third"><div className="staffing-effort-control"><TextField aria-label="Estimated effort value" name="effortValue" type="number" min="1" defaultValue="5" /><SelectField aria-label="Estimated effort unit" name="effortUnit"><option value="days">Days</option><option value="weeks">Weeks</option><option value="months">Months</option></SelectField></div></FormGroup>
          </div>
        </CreateSection>

        <CreateSection title="Business purpose" description="Used to explain and validate the recommendation">
          <div className="staffing-create-grid">
            <FormGroup label="Business objectives" className="full"><TextArea name="businessObjectives" required placeholder="Describe the business objective, intended audience, and reason for the request" /></FormGroup>
            <FormGroup label="Expected outcomes" className="full"><TextArea name="expectedOutcomes" placeholder="Describe the expected results, success measures, and desired impact" /></FormGroup>
          </div>
        </CreateSection>
      </form>
    </Modal>
  );
}

function CreateSection({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className="staffing-create-section">
      <div className="staffing-create-section-head"><h4>{title}</h4><span>{description}</span></div>
      {children}
    </section>
  );
}

function toRequestDeliverable(item: CatalogDeliverable): RequestDeliverable {
  return { id: item.id, name: item.name, note: item.note };
}

function mergeCapabilities(current: RequiredCapability[], additions: RequiredCapability[]) {
  const result = [...current];
  for (const item of additions) if (!result.some((existing) => existing.name.toLowerCase() === item.name.toLowerCase())) result.push(item);
  return result;
}

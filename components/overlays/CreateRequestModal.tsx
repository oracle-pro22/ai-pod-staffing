'use client';

import { type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/Button';
import { AiRephraseTextarea } from '@/components/ui/AiRephraseTextarea';
import { DropdownField } from '@/components/ui/DropdownField';
import { FormGroup, TextArea, TextField } from '@/components/ui/FormControls';
import { Modal } from '@/components/ui/Modal';
import { PersonCombobox } from '@/components/ui/PersonCombobox';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { requestBusinessDate } from '@/lib/request-date-policy';
import { canPerform } from '@/lib/role-policy';
import type {
  CatalogDeliverable,
  RequestDeliverable,
  RequiredCapability,
} from '@/types/staffing';
import type { RequestCreatedResult } from '@/types/mutations';
import type { AiRephraseField } from '@/types/ai-rephrase';

export function CreateRequestModal() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const router = useRouter();
  const canCreate = canPerform(state.role, 'REQUESTS', 'canCreate', data.authorization);
  const [sourcePeople, setSourcePeople] = useState<{ id: string; name: string }[]>(data.people);
  const [sourcePeopleLoading, setSourcePeopleLoading] = useState(false);
  const open = state.modal?.id === 'create-request' && canCreate;
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setSourcePeopleLoading(true);
    fetch('/api/people', { headers: { 'x-staffing-role': state.role }, cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('Lookup unavailable');
        const result = await response.json() as { data: { id: string; name: string }[] };
        if (!controller.signal.aborted) setSourcePeople(result.data);
      }).catch(() => {
        if (!controller.signal.aborted) { setSourcePeople([]); notify('People lookup unavailable', 'Close and reopen the form to retry.'); }
      }).finally(() => { if (!controller.signal.aborted) setSourcePeopleLoading(false); });
    return () => controller.abort();
  }, [open, state.role]); // notify is context-backed; fetching is scoped to each opening/profile.
  const firstProject = data.catalog.projects[0];
  const [projectId, setProjectId] = useState(firstProject?.id ?? '');
  const project = data.catalog.projects.find((item) => item.id === projectId) ?? firstProject;
  const [deliverables, setDeliverables] = useState<RequestDeliverable[]>([]);
  const [capabilities, setCapabilities] = useState<RequiredCapability[]>([]);
  const [deliverableChoice, setDeliverableChoice] = useState('');
  const [capabilityChoice, setCapabilityChoice] = useState('');
  const [customDeliverable, setCustomDeliverable] = useState('');
  const [customCapability, setCustomCapability] = useState('');
  const [requestTitle, setRequestTitle] = useState('');
  const [projectDescription, setProjectDescription] = useState('');
  const [requestSourcePersonId, setRequestSourcePersonId] = useState('');
  const [businessObjectives, setBusinessObjectives] = useState('');
  const [expectedOutcomes, setExpectedOutcomes] = useState('');
  const [rephrasing, setRephrasing] = useState<Partial<Record<AiRephraseField, boolean>>>({
    businessObjectives: false,
    expectedOutcomes: false,
  });
  const [minimumDate, setMinimumDate] = useState(() => requestBusinessDate());
  const [neededBy, setNeededBy] = useState(() => requestBusinessDate());
  const [estimatedStartDate, setEstimatedStartDate] = useState(() => requestBusinessDate());
  const [estimatedCompletionDate, setEstimatedCompletionDate] = useState(() => requestBusinessDate());
  const [priority, setPriority] = useState('Medium');
  const [requestedPodSize, setRequestedPodSize] = useState('1 lead + 2 contributors');
  const [effortUnit, setEffortUnit] = useState('days');
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
    setProjectDescription(project.description ?? '');
  }, [open, project]);

  useEffect(() => {
    if (!open) return;
    const today = requestBusinessDate();
    setMinimumDate(today);
    setNeededBy(today);
    setEstimatedStartDate(today);
    setEstimatedCompletionDate(today);
    setRequestSourcePersonId('');
    setRequestTitle('');
    setBusinessObjectives('');
    setExpectedOutcomes('');
    setPriority('Medium');
    setRequestedPodSize('1 lead + 2 contributors');
    setEffortUnit('days');
    setRephrasing({ businessObjectives: false, expectedOutcomes: false });
  }, [open]);

  const availableDeliverables = project?.deliverables.filter((item) => !deliverables.some((selected) => selected.id === item.id)) ?? [];
  const notes = useMemo(() => deliverables.map((item) => item.note).filter(Boolean), [deliverables]);
  const unmappedDeliverables = deliverables.filter((item) => !item.custom
    && project?.deliverables.some((mapped) => mapped.id === item.id && mapped.skills.length === 0));
  const rephrasingText = rephrasing.businessObjectives || rephrasing.expectedOutcomes;
  const close = () => dispatch({ type: 'close-modal' });
  const setRephraseBusy = useCallback((field: AiRephraseField, busy: boolean) => {
    setRephrasing((current) => current[field] === busy ? current : { ...current, [field]: busy });
  }, []);

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
    if (!canCreate) return;
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
          businessObjectives,
          expectedOutcomes,
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
      className="staffing-create-request-modal"
      onClose={close}
      footer={<><Button type="button" onClick={close} disabled={saving}>Cancel</Button><Button type="submit" form="createStaffingRequest" variant="primary" disabled={saving || rephrasingText}>{saving ? 'Saving…' : 'Save request'}</Button></>}
    >
      <form id="createStaffingRequest" className="staffing-create-request-form" onSubmit={submit}>
        <CreateSection title="Request overview" description="Core request information">
          <div className="staffing-create-grid">
            <FormGroup label="Request title" className="wide"><TextField name="title" required value={requestTitle} onChange={(event) => setRequestTitle(event.target.value)} placeholder="Enter request title" /></FormGroup>
            <FormGroup label="Request source" className="third"><PersonCombobox people={sourcePeople} value={requestSourcePersonId} onChange={setRequestSourcePersonId} disabled={saving || sourcePeopleLoading} placeholder={sourcePeopleLoading ? 'Loading people…' : 'Search people by name'} required /></FormGroup>
            <FormGroup label="Project type" className="third"><DropdownField value={projectId} onChange={setProjectId} options={data.catalog.projects.map((item) => ({ value: item.id, label: item.name }))} /></FormGroup>
            <FormGroup label="Project description" className="wide"><TextArea name="projectDescription" value={projectDescription} onChange={(event) => setProjectDescription(event.target.value)} placeholder="Describe the project and the work being requested" /></FormGroup>
          </div>
        </CreateSection>

        <CreateSection title="Deliverables and capabilities" description="Defaults come from the customer catalogue">
          <div className="staffing-create-grid">
            <FormGroup label="Key deliverables" className="half">
              <div className="staffing-editor-box">
                <div className="staffing-editor-meta">Catalogue defaults</div>
                <div className="staffing-chip-row">{deliverables.map((item) => <span className="staffing-edit-chip" key={item.id}>{item.name}<button type="button" aria-label={`Remove ${item.name}`} onClick={() => setDeliverables((current) => current.filter((selected) => selected.id !== item.id))}>×</button></span>)}</div>
                <div className="staffing-add-row"><DropdownField aria-label="Add key deliverable" value={deliverableChoice} onChange={setDeliverableChoice} placeholder="Select a deliverable" options={[...availableDeliverables.map((item) => ({ value: item.id, label: item.name })), { value: 'other', label: 'Other — type a deliverable' }]} /><Button type="button" onClick={addDeliverable}>＋ Add</Button></div>
                {deliverableChoice === 'other' ? <TextField aria-label="Custom deliverable" value={customDeliverable} onChange={(event) => setCustomDeliverable(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addDeliverable(); } }} placeholder="Type a deliverable and press Enter" /> : null}
                <small>Choose mapped or request-specific deliverables.</small>
              </div>
            </FormGroup>

            <FormGroup label="Required capabilities" className="half">
              <div className="staffing-editor-box">
                <div className="staffing-editor-meta">Mapped to deliverables</div>
                <div className="staffing-chip-row">{capabilities.map((item) => <span className="staffing-edit-chip" key={item.id}>{item.name}<button type="button" aria-label={`Remove ${item.name}`} onClick={() => setCapabilities((current) => current.filter((selected) => selected.id !== item.id))}>×</button></span>)}</div>
                <div className="staffing-add-row"><DropdownField aria-label="Add required capability" value={capabilityChoice} onChange={setCapabilityChoice} placeholder="Select a capability" options={[...data.catalog.skills.filter((skill) => !capabilities.some((item) => item.id === skill.id)).map((skill) => ({ value: skill.id, label: skill.name })), { value: 'other', label: 'Other — type a capability' }]} /><Button type="button" onClick={addCapability}>＋ Add</Button></div>
                {capabilityChoice === 'other' ? <TextField aria-label="Custom capability" value={customCapability} onChange={(event) => setCustomCapability(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addCapability(); } }} placeholder="Type a capability and press Enter" /> : null}
                <small>Add or remove capabilities for this request.</small>
                {unmappedDeliverables.length ? <small role="status">No default capabilities supplied for {unmappedDeliverables.map((item) => item.name).join(', ')}. Add the capabilities needed for this request.</small> : null}
              </div>
            </FormGroup>

            <FormGroup label="Customer catalogue note" className="full"><div className="staffing-readonly-note">{notes.join(' ') || 'No customer note recorded for the selected deliverables.'}</div></FormGroup>
          </div>
        </CreateSection>

        <CreateSection title="Schedule and staffing" description="Timing, effort and requested pod">
          <div className="staffing-create-grid">
            <FormGroup label="Priority" className="third"><DropdownField name="priority" value={priority} onChange={setPriority} options={[{ value: 'Low', label: 'Low' }, { value: 'Medium', label: 'Medium' }, { value: 'High', label: 'High' }]} /></FormGroup>
            <FormGroup label="Needed by date" className="third"><TextField name="neededBy" required type="date" min={minimumDate} value={neededBy} onChange={(event) => setNeededBy(event.target.value)} /></FormGroup>
            <FormGroup label="Requested pod size" className="third"><DropdownField name="podSize" value={requestedPodSize} onChange={setRequestedPodSize} options={[{ value: '1 lead + 2 contributors', label: '1 lead + 2 contributors' }, { value: '1 lead + 1 contributor', label: '1 lead + 1 contributor' }, { value: '1 lead + 3 contributors', label: '1 lead + 3 contributors' }]} /></FormGroup>
            <FormGroup label="Estimated start date" className="third"><TextField name="startDate" type="date" min={minimumDate} value={estimatedStartDate} onChange={(event) => changeEstimatedStartDate(event.target.value)} /></FormGroup>
            <FormGroup label="Estimated completion date" className="third"><TextField name="completionDate" type="date" min={estimatedStartDate || minimumDate} value={estimatedCompletionDate} onChange={(event) => setEstimatedCompletionDate(event.target.value)} /></FormGroup>
            <FormGroup label="Estimated effort" className="third"><div className="staffing-effort-control"><TextField aria-label="Estimated effort value" name="effortValue" type="number" min="1" defaultValue="5" /><DropdownField aria-label="Estimated effort unit" name="effortUnit" value={effortUnit} onChange={setEffortUnit} options={[{ value: 'days', label: 'Days' }, { value: 'weeks', label: 'Weeks' }, { value: 'months', label: 'Months' }]} /></div></FormGroup>
          </div>
        </CreateSection>

        <CreateSection title="Business purpose" description="Used to explain and validate the recommendation">
          <div className="staffing-create-grid">
            <FormGroup label="Business objectives" className="full">
              <AiRephraseTextarea
                name="businessObjectives"
                field="businessObjectives"
                required
                value={businessObjectives}
                disabled={saving}
                context={{
                  requestTitle,
                  projectType: project?.name,
                  projectDescription,
                  deliverables: deliverables.map((item) => item.name),
                }}
                onChange={setBusinessObjectives}
                onBusyChange={setRephraseBusy}
                placeholder="Describe the business objective, intended audience, and reason for the request"
              />
            </FormGroup>
            <FormGroup label="Expected outcomes" className="full">
              <AiRephraseTextarea
                name="expectedOutcomes"
                field="expectedOutcomes"
                value={expectedOutcomes}
                disabled={saving}
                context={{
                  requestTitle,
                  projectType: project?.name,
                  deliverables: deliverables.map((item) => item.name),
                  businessObjectives,
                }}
                onChange={setExpectedOutcomes}
                onBusyChange={setRephraseBusy}
                placeholder="Describe the expected results, success measures, and desired impact"
              />
            </FormGroup>
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

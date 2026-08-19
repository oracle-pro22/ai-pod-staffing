(function () {
  'use strict';

  const state = {
    data: null,
    role: 'Operations Lead',
    screen: 'dashboard',
    activeRequestId: null,
    weekOffset: 0,
    drafts: [],
    localAvailability: [],
    calendarAssignments: [],
    newRequestSkillIds: [],
    newRequestDefaultSkillIds: [],
    newRequestExcludedDefaultSkillIds: [],
    newRequestCustomSkills: [],
    newRequestCustomSkillCounter: 0,
    newRequestDeliverableIds: [],
    newRequestCustomDeliverables: [],
    newRequestCustomDeliverableCounter: 0,
  };

  const navItems = [
    ['dashboard', 'home', 'Command Center'],
    ['requests', 'file', 'Requests'],
    ['fitment', 'spark', 'AI Fitment'],
    ['calendar', 'calendar', 'Allocation Calendar'],
    ['interests', 'people', 'Team & Skills'],
    ['availability', 'clock', 'My Availability'],
    ['agent', 'play', 'Agent Execution'],
    ['reports', 'chart', 'Reports'],
    ['admin', 'settings', 'Administration'],
  ];
  const iconPaths = {
    home: '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/>',
    file: '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v5h5"/><path d="M9 13h6M9 17h6"/>',
    spark: '<path d="m12 3 1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z"/><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/>',
    people: '<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.2 2.7-5 6-5s6 1.8 6 5"/><circle cx="17" cy="9" r="2"/><path d="M15 15c3.4-.4 6 1.4 6 4"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    play: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m10 9 5 3-5 3z"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z"/>',
  };
  const restrictedScreens = new Set(['calendar', 'agent', 'reports', 'admin']);
  const reportColors = ['#c74634', '#2f7d7a', '#34678f', '#b87b2c', '#6a5195', '#58714f', '#8b5c50', '#6d777e', '#a54a67', '#7f6b3e', '#496a63'];

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
  const unique = (values) => [...new Set(values.filter(Boolean))];
  const dateValue = (value) => value ? new Date(`${value}T12:00:00`) : null;
  const formatDate = (value) => {
    const date = dateValue(value);
    return date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : 'Not recorded';
  };
  const formatShortDate = (value) => {
    const date = dateValue(value);
    return date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—';
  };
  const pctClass = (value) => value >= 80 ? 'red' : value >= 70 ? 'amber' : '';
  const statusClass = (status) => {
    const value = String(status).toLowerCase();
    if (value.includes('staff') || value.includes('active') || value.includes('approve')) return 'green';
    if (value.includes('review') || value.includes('pending')) return 'teal';
    if (value.includes('recommend')) return 'red';
    return 'amber';
  };
  const skillsHtml = (skills, limit) => {
    const items = typeof limit === 'number' ? skills.slice(0, limit) : skills;
    return `<div class="skill-tags">${items.map((skill) => `<span class="skill-tag">${esc(skill.name ?? skill)}</span>`).join('')}${limit && skills.length > limit ? `<span class="skill-tag">+${skills.length - limit}</span>` : ''}</div>`;
  };
  const requestDeliverables = (request) => request?.deliverables?.length ? request.deliverables : request?.deliverable ? [request.deliverable] : [];
  const requestDeliverableNames = (request) => requestDeliverables(request).map((deliverable) => deliverable.name).filter(Boolean);
  const primaryRequestDeliverable = (request) => requestDeliverables(request)[0] || { id: '', name: 'No deliverable recorded', note: '' };
  const requestEffortLabel = (request) => {
    const value = Number(request?.estimatedEffort?.value);
    const unit = String(request?.estimatedEffort?.unit || '').toLowerCase();
    if (value > 0 && unit) {
      const label = value === 1 ? unit.replace(/s$/, '') : unit;
      return `${value} ${label}`;
    }
    return `${Number(request?.estimatedHours) || 0} hours`;
  };
  const requestBusinessObjectives = (request) => request?.businessObjectivesAndExpectedOutcomes || request?.businessContext || '';
  const requestProjectDescription = (request) => request?.projectDescription || request?.projectType?.description || '';
  const empty = (message) => `<div class="empty compact">${esc(message)}</div>`;
  const navIcon = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${iconPaths[name]}</svg>`;

  function isScopedRole() {
    return state.role === 'POD Member' || state.role === 'Pod Lead';
  }

  function identityPerson() {
    if (!state.data) return null;
    const id = state.role === 'Pod Lead' ? state.data.demoIdentity.podLeadPersonId : state.data.demoIdentity.podMemberPersonId;
    return state.data.people.find((person) => person.id === id) || state.data.people[0] || null;
  }

  function workbookRequests() {
    return state.data ? state.data.requests : [];
  }

  function visibleRequests() {
    const all = [...workbookRequests(), ...state.drafts];
    if (!isScopedRole()) return all;
    const person = identityPerson();
    return person ? all.filter((request) => request.recommendations.some((recommendation) => recommendation.personId === person.id)) : [];
  }

  function visiblePeople() {
    if (!state.data) return [];
    if (state.role === 'POD Member') return identityPerson() ? [identityPerson()] : [];
    if (state.role === 'Pod Lead') {
      const ids = new Set([identityPerson()?.id, ...visibleRequests().flatMap((request) => request.recommendations.map((recommendation) => recommendation.personId))]);
      return state.data.people.filter((person) => ids.has(person.id));
    }
    return state.data.people;
  }

  function activeRequest() {
    const scoped = visibleRequests();
    return scoped.find((request) => request.id === state.activeRequestId) || scoped.find((request) => request.recommendations.length) || scoped[0] || null;
  }

  function recommendationsInScope(request) {
    if (!request) return [];
    return state.role === 'POD Member'
      ? request.recommendations.filter((recommendation) => recommendation.personId === identityPerson()?.id)
      : request.recommendations;
  }

  function screenAllowed(screen) {
    return !(isScopedRole() && restrictedScreens.has(screen));
  }

  function toast(title, message) {
    const item = document.createElement('div');
    item.className = 'toast';
    item.innerHTML = `<strong>${esc(title)}</strong><span>${esc(message)}</span>`;
    $('toastWrap').appendChild(item);
    window.setTimeout(() => item.remove(), 3900);
  }

  function openDrawer(title, body, footer) {
    $('drawerTitle').textContent = title;
    $('drawerBody').innerHTML = body;
    $('drawerFoot').innerHTML = footer || '<button class="btn" data-close-drawer>Close</button>';
    $('drawerBackdrop').classList.add('open');
    $('drawer').classList.add('open');
  }

  function closeDrawer() {
    $('drawerBackdrop').classList.remove('open');
    $('drawer').classList.remove('open');
  }

  function openModal(title, body, footer) {
    $('modalTitle').textContent = title;
    $('modalBody').innerHTML = body;
    $('modalFoot').innerHTML = footer || '<button class="btn" data-close-modal>Close</button>';
    $('modalWrap').classList.add('open');
  }

  function closeModal() {
    $('modalWrap').classList.remove('open');
  }

  function renderNav() {
    $('mainNav').innerHTML = navItems.map(([id, icon, label]) => {
      const locked = !screenAllowed(id);
      return `<button data-screen="${id}" class="${state.screen === id ? 'active ' : ''}${locked ? 'locked' : ''}" aria-disabled="${locked}">${navIcon(icon)}<span>${label}</span></button>`;
    }).join('');
  }

  function go(screen) {
    if (!screenAllowed(screen)) {
      toast('Access blocked', `${state.role} cannot enter this workspace in the prototype.`);
      return;
    }
    state.screen = screen;
    document.querySelectorAll('.screen').forEach((section) => section.classList.toggle('active', section.id === `screen-${screen}`));
    $('crumb').textContent = navItems.find((item) => item[0] === screen)?.[2] || 'Workspace';
    renderNav();
    $('sidebar').classList.remove('open');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function kpiCard(label, value, badge, note, tone = '') {
    return `<div class="card kpi"><div class="kpi-top"><span>${esc(label)}</span><span class="pill ${tone}">${esc(badge)}</span></div><div class="kpi-value">${esc(value)}</div>${note ? `<div class="muted small">${esc(note)}</div>` : ''}</div>`;
  }

  function renderDashboard() {
    const data = state.data;
    const requests = visibleRequests();
    const people = visiblePeople();
    const high = requests.filter((request) => /high|urgent/i.test(request.priority)).length;
    const pending = requests.reduce((total, request) => total + recommendationsInScope(request).filter((recommendation) => /pending/i.test(recommendation.decisionStatus)).length, 0);
    $('dashboardKpis').innerHTML = [
      kpiCard('Open requests', requests.filter((request) => request.status.toLowerCase() !== 'closed').length, `${high} high priority`, '', 'red'),
      kpiCard('Team allocation', `${Math.round(people.reduce((sum, person) => sum + person.allocationPct, 0) / Math.max(people.length, 1))}%`, `${people.filter((person) => person.allocationPct >= 70).length} constrained`, '', 'amber'),
      kpiCard('Customer deliverables', data.metrics.deliverables, `${data.metrics.projectTypes} project types`, '', 'teal'),
      kpiCard('Pending recommendations', pending, 'Advisory', '', 'purple'),
    ].join('');

    $('priorityQueue').innerHTML = requests.length ? requests.map((request) => `<div class="list-row"><div><div class="row-title">${esc(request.title)}</div><div class="row-sub">${esc(request.id)} • ${esc(request.projectType.name)} • ${esc(requestDeliverableNames(request).join(', '))}</div></div><span class="pill ${statusClass(request.status)}">${esc(request.status)}</span><div><b>${formatShortDate(request.neededBy)}</b><div class="row-sub">${esc(request.priority)}</div></div><button class="btn sm" data-open-request="${esc(request.id)}">Review</button></div>`).join('') : empty('No assigned requests in this persona scope.');

    $('capacityWatch').innerHTML = people.length ? [...people].sort((a, b) => b.allocationPct - a.allocationPct).map((person) => `<div class="capacity-row"><div class="avatar">${esc(person.initials)}</div><div><div style="display:flex;justify-content:space-between;gap:8px"><b>${esc(person.name)}</b><span>${person.allocationPct}%</span></div><div class="progress ${pctClass(person.allocationPct)}"><span style="width:${Math.min(person.allocationPct, 100)}%"></span></div></div><span class="pill ${person.allocationPct >= 80 ? 'red' : person.allocationPct >= 70 ? 'amber' : ''}">${person.activePods} pods</span></div>`).join('') : empty('No capacity records are visible.');

    const memberMode = state.role === 'POD Member';
    $('priorityQueueCard').style.display = memberMode ? 'none' : '';
    $('podMemberFitmentPreview').style.display = memberMode ? '' : 'none';
    $('dashboardInsights').style.display = memberMode ? 'none' : '';
    $('capacityWatchTitle').textContent = memberMode ? 'My Capacity' : 'Capacity watch';
    $('capacityWatchSubtitle').textContent = memberMode ? 'Your current pods and allocation' : 'Current allocation from People';
    if (memberMode) renderPodMemberPreview();

    const previousProject = $('demandProjectFilter').value;
    $('demandProjectFilter').innerHTML = `<option value="">All project types</option>${data.catalog.projects.map((project) => `<option value="${esc(project.id)}">${esc(project.name)}</option>`).join('')}`;
    $('demandProjectFilter').value = data.catalog.projects.some((project) => project.id === previousProject) ? previousProject : '';
    renderUpcomingDemand();
    $('auditTrailSummary').textContent = `${pending} pending recommendation${pending === 1 ? '' : 's'} • ${data.source.version || data.source.fileName}`;
  }

  function renderPodMemberPreview() {
    const request = activeRequest();
    const person = identityPerson();
    const recommendation = request?.recommendations.find((item) => item.personId === person?.id);
    if (!request || !person || !recommendation) {
      $('podMemberPreviewBody').innerHTML = empty('No assigned AI fitment is recorded for this POD Member.');
      return;
    }
    const events = person.availability.length ? `${person.availability.length} recorded event${person.availability.length === 1 ? '' : 's'}` : 'No recorded conflicts';
    $('podMemberPreviewBody').innerHTML = `<div style="display:flex;justify-content:space-between;gap:14px;align-items:flex-start"><div><div class="row-title">${esc(request.title)}</div><div class="row-sub">${esc(request.id)} • ${esc(requestDeliverableNames(request).join(', '))} • ${formatShortDate(request.neededBy)}</div></div><div class="score">${recommendation.score}</div></div><div class="reason-grid"><div class="reason"><span>Proposed role</span><strong>${esc(recommendation.roleInPod)}</strong></div><div class="reason"><span>Matching capabilities</span><strong>${recommendation.matchingSkills.length}/${request.requiredSkills.length}</strong></div><div class="reason"><span>Availability</span><strong>${esc(events)}</strong></div></div><div class="rationale">${esc(recommendation.rationale)}</div><button class="btn primary" style="margin-top:16px" data-open-fitment="${esc(request.id)}">View my fitment</button>`;
  }

  function renderUpcomingDemand() {
    if (!state.data) return;
    const selected = $('demandProjectFilter').value;
    const requests = visibleRequests().filter((request) => !selected || request.projectType.id === selected).sort((a, b) => String(a.neededBy).localeCompare(String(b.neededBy)));
    const datedRequests = requests.map((request) => ({ request, date: dateValue(request.neededBy) })).filter((item) => item.date && !Number.isNaN(item.date.getTime()));
    if (!datedRequests.length) {
      $('upcomingDemand').innerHTML = empty('No staffing requests match this project type.');
      return;
    }
    const firstDueDate = new Date(Math.min(...datedRequests.map((item) => item.date.getTime())));
    const firstWeek = new Date(firstDueDate);
    firstWeek.setDate(firstWeek.getDate() - ((firstWeek.getDay() + 6) % 7) - 14);
    const weeks = Array.from({ length: 5 }, (_, index) => {
      const startsOn = new Date(firstWeek);
      startsOn.setDate(firstWeek.getDate() + index * 7);
      const endsOn = new Date(startsOn);
      endsOn.setDate(startsOn.getDate() + 7);
      const matching = datedRequests.filter((item) => item.date >= startsOn && item.date < endsOn);
      return {
        startsOn,
        requestCount: matching.length,
        hours: matching.reduce((total, item) => total + (Number(item.request.estimatedHours) || 0), 0),
      };
    });
    const peakHours = Math.max(...weeks.map((week) => week.hours), 1);
    const cells = weeks.map((week) => {
      const ratio = week.hours / peakHours;
      const tone = week.hours === 0 ? 'm' : ratio >= .75 ? 'v' : ratio >= .4 ? 'h' : 'm';
      const details = week.requestCount ? `${week.requestCount} request${week.requestCount === 1 ? '' : 's'}, ${week.hours} hours` : 'No requests due';
      return `<span class="${tone}" title="${esc(details)}" aria-label="${esc(`${formatShortDate(week.startsOn.toISOString().slice(0, 10))}: ${details}`)}"></span>`;
    }).join('');
    const labels = weeks.map((week) => `<span>${formatShortDate(week.startsOn.toISOString().slice(0, 10))}</span>`).join('');
    $('upcomingDemand').innerHTML = `<div class="heat" role="img" aria-label="Five-week staffing demand forecast">${cells}</div><div class="heat-labels" aria-hidden="true">${labels}</div>`;
  }

  function setSelectOptions(id, label, values, current) {
    const element = $(id);
    if (!element) return;
    element.innerHTML = `<option value="">${esc(label)}</option>${unique(values).map((value) => `<option value="${esc(value)}">${esc(value)}</option>`).join('')}`;
    element.value = unique(values).includes(current) ? current : '';
  }

  function renderRequestFilters() {
    const requests = visibleRequests();
    setSelectOptions('requestStatusFilter', 'All status', [...requests.map((request) => request.status), 'Closed'], $('requestStatusFilter').value);
    setSelectOptions('requestPriorityFilter', 'All priorities', requests.map((request) => request.priority), $('requestPriorityFilter').value);
    setSelectOptions('requestProjectFilter', 'All project types', requests.map((request) => request.projectType.name), $('requestProjectFilter').value);
    setSelectOptions('requestDeliverableFilter', 'All deliverables', requests.flatMap(requestDeliverableNames), $('requestDeliverableFilter').value);
  }

  function renderRequests(refreshFilters = false) {
    if (refreshFilters) renderRequestFilters();
    const query = $('requestSearch').value.trim().toLowerCase();
    const status = $('requestStatusFilter').value;
    const priority = $('requestPriorityFilter').value;
    const project = $('requestProjectFilter').value;
    const deliverable = $('requestDeliverableFilter').value;
    const rows = visibleRequests().filter((request) => {
      const names = requestDeliverableNames(request);
      const haystack = [request.id, request.title, request.projectType.name, ...names, request.requestSource || request.ownerName, ...request.requiredSkills.map((skill) => skill.name)].join(' ').toLowerCase();
      return (!query || haystack.includes(query)) && (!status || request.status === status) && (!priority || request.priority === priority) && (!project || request.projectType.name === project) && (!deliverable || names.includes(deliverable));
    });
    $('requestRows').innerHTML = rows.length ? rows.map((request) => `<tr><td><b>${esc(request.title)}</b><div class="row-sub">${esc(request.id)} • ${esc(requestEffortLabel(request))}</div></td><td>${esc(request.projectType.name)}</td><td class="request-context"><b>${esc(requestDeliverableNames(request).join(', '))}</b>${skillsHtml(request.requiredSkills, 3)}</td><td>${esc(request.requestSource || request.ownerName)}</td><td><span class="pill ${statusClass(request.status)}">${esc(request.status)}</span></td><td>${formatDate(request.neededBy)}</td><td><button class="btn sm" data-open-request="${esc(request.id)}">Open</button></td></tr>`).join('') : `<tr><td colspan="7">${empty('No requests match the current filters.')}</td></tr>`;
  }

  function renderFitment() {
    const request = activeRequest();
    if (!request) {
      $('fitmentRequestSummary').innerHTML = empty('No assigned request is available for fitment review.');
      $('fitmentFactors').innerHTML = empty('No workbook evidence in this access scope.');
      $('leadCandidates').innerHTML = empty('No recommendation recorded.');
      $('memberCandidates').innerHTML = empty('No recommendation recorded.');
      return;
    }
    state.activeRequestId = request.id;
    const note = requestBusinessObjectives(request) || requestDeliverables(request).map((deliverable) => deliverable.note).filter(Boolean).join(' ');
    $('fitmentRequestSummary').innerHTML = `<div style="display:flex;justify-content:space-between;align-items:start"><div><span class="pill ${request.priority.toLowerCase() === 'high' ? 'red' : 'amber'}">${esc(request.priority)} priority</span><h3 style="font-size:18px;margin:10px 0 4px">${esc(request.title)}</h3><div class="muted small">${esc(request.id)} • ${esc(request.projectType.name)}</div></div><button class="icon-btn" data-open-request="${esc(request.id)}">↗</button></div><dl style="margin:16px 0 0"><div class="summary-pair"><dt>Needed by date</dt><dd>${formatDate(request.neededBy)}</dd></div><div class="summary-pair"><dt>Key deliverables</dt><dd>${esc(requestDeliverableNames(request).join(', '))}</dd></div>${request.estimatedStartDate ? `<div class="summary-pair"><dt>Estimated start date</dt><dd>${formatDate(request.estimatedStartDate)}</dd></div>` : ''}${request.estimatedCompletionDate ? `<div class="summary-pair"><dt>Estimated completion date</dt><dd>${formatDate(request.estimatedCompletionDate)}</dd></div>` : ''}<div class="summary-pair"><dt>Estimated effort</dt><dd>${esc(requestEffortLabel(request))}</dd></div>${request.requestedPodSize ? `<div class="summary-pair"><dt>Requested pod size</dt><dd>${esc(request.requestedPodSize)}</dd></div>` : ''}<div class="summary-pair"><dt>Required capabilities</dt><dd>${skillsHtml(request.requiredSkills)}</dd></div><div class="summary-pair"><dt>Status</dt><dd>${esc(request.status)}</dd></div></dl><div class="fit-summary-note"><b>Business objectives and expected outcomes</b><p class="muted small">${esc(note || 'No additional context is recorded.')}</p></div><div class="source-strip"><span>Mapping ${esc(request.mappingVersion || state.data.source.version)}</span><span>•</span><span>Human approval required</span></div>`;

    const recommendationFactors = [
      ['Interest strength', 35, 92, 'var(--oj-teal)'],
      ['Relevant delivery history', 25, 84, 'var(--oj-blue)'],
      ['Available capacity', 25, 76, 'var(--oj-teal)'],
      ['Growth preference', 10, 61, '#c88413'],
      ['Team continuity', 5, 48, 'var(--oj-red)'],
    ];
    $('fitmentFactors').innerHTML = `<div class="explain-title"><div class="spark">✦</div><div><div>How the recommendation was formed</div><span class="muted small">Inputs preserved for governance review</span></div></div><div style="margin-top:14px">${recommendationFactors.map(([label, weight, score, color]) => `<div class="factor"><span>${esc(label)}</span><div class="progress"><span style="width:${score}%;background:${color}"></span></div><strong>${weight}%</strong></div>`).join('')}</div>`;

    const scopedRecommendations = recommendationsInScope(request);
    const lead = scopedRecommendations.filter((item) => /lead/i.test(item.roleInPod));
    const contributors = scopedRecommendations.filter((item) => !/lead/i.test(item.roleInPod));
    $('leadCandidates').innerHTML = renderCandidates(lead, request);
    $('memberCandidates').innerHTML = renderCandidates(contributors, request);
  }

  function renderCandidates(recommendations, request) {
    if (!recommendations.length) return empty('No recommendation is recorded for this role in the current access scope.');
    return recommendations.map((recommendation, index) => {
      const person = state.data.people.find((item) => item.id === recommendation.personId);
      const events = person?.availability || [];
      return `<div class="candidate ${index === 0 ? 'recommended' : ''}"><div class="candidate-head"><div class="avatar">${esc(person?.initials || recommendation.personName.split(' ').map((part) => part[0]).join('').slice(0, 2))}</div><div class="candidate-main"><b>${esc(recommendation.personName)} • ${esc(recommendation.roleInPod)}</b><div class="candidate-meta">${person ? `${person.allocationPct}% allocated • ${person.activePods} active pods` : 'Person record unavailable'}</div></div><div class="score">${recommendation.score}</div></div><div style="margin-top:10px">${skillsHtml(recommendation.matchingSkills)}</div><div class="rationale" style="margin-top:10px">${esc(recommendation.rationale)}</div><div class="source-strip"><span>${esc(recommendation.decisionStatus)}</span><span>•</span><span>${events.length} availability event${events.length === 1 ? '' : 's'}</span><span>•</span><span>${esc(recommendation.source || request.mappingVersion)}</span></div></div>`;
    }).join('');
  }

  function startOfCalendarWeek() {
    const date = new Date('2026-07-20T12:00:00');
    date.setDate(date.getDate() + state.weekOffset * 7);
    return date;
  }

  function eventOnDate(event, date) {
    const start = dateValue(event.startsOn);
    const end = dateValue(event.endsOn || event.startsOn);
    return start && end && date >= start && date <= end;
  }

  function calendarBookingTone(request) {
    const text = `${request?.projectType?.name || ''} ${requestDeliverableNames(request).join(' ')}`.toLowerCase();
    if (/video|demo/.test(text)) return 'video';
    if (/enable|webinar|workshop/.test(text)) return 'enable';
    return 'write';
  }

  function prototypeBookings(person, days, personIndex) {
    const requests = visibleRequests();
    const matching = requests.filter((request) => request.recommendations.some((recommendation) => recommendation.personId === person.id));
    const skillMatches = requests.filter((request) => request.requiredSkills.some((required) => person.skills.some((skill) => skill.id === required.id)));
    const candidates = matching.length ? matching : skillMatches.length ? skillMatches : requests;
    if (!candidates.length) return [];
    const workdays = personIndex % 3 === 0 ? [0, 1, 2, 3] : personIndex % 3 === 1 ? [0, 1, 2, 3] : [1, 2, 3];
    return workdays.map((dayIndex, index) => {
      const request = candidates[Math.min(index > 1 ? 1 : 0, candidates.length - 1)];
      const hours = dayIndex < 2 ? (person.allocationPct >= 80 ? 7 : 6) : dayIndex === 2 ? 5 : 6;
      return { date: days[dayIndex], request, hours, tone: calendarBookingTone(request), local: false };
    });
  }

  function renderCalendar() {
    if (!state.data) return;
    const previous = $('calendarSkillFilter').value;
    $('calendarSkillFilter').innerHTML = `<option value="">All interests</option>${state.data.catalog.skills.map((skill) => `<option value="${esc(skill.id)}">${esc(skill.name)}</option>`).join('')}`;
    $('calendarSkillFilter').value = state.data.catalog.skills.some((skill) => skill.id === previous) ? previous : '';
    const skillId = $('calendarSkillFilter').value;
    const capacity = $('capacityFilter').value;
    let people = visiblePeople().filter((person) => !skillId || person.skills.some((skill) => skill.id === skillId));
    people = people.filter((person) => capacity === 'Available' ? person.allocationPct < 70 : capacity === 'Constrained' ? person.allocationPct >= 70 : capacity === 'OOO / leave / travel' ? person.availability.length > 0 : true);
    if (!$('showAlternates').checked) people = people.filter((person) => visibleRequests().some((request) => request.recommendations.some((recommendation) => recommendation.personId === person.id)));
    people.sort((a, b) => b.allocationPct - a.allocationPct);
    const week = startOfCalendarWeek();
    const days = Array.from({ length: 5 }, (_, index) => { const date = new Date(week); date.setDate(week.getDate() + index); return date; });
    $('weekLabel').textContent = `${days[0].toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}–${days[4].toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
    let html = '<div class="cell head person">Team member</div>' + days.map((day) => `<div class="cell head">${day.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}</div>`).join('');
    for (const [personIndex, person] of people.entries()) {
      const generated = prototypeBookings(person, days, personIndex);
      const local = state.calendarAssignments.filter((assignment) => assignment.personId === person.id).map((assignment) => ({
        date: dateValue(assignment.date),
        request: visibleRequests().find((request) => request.id === assignment.requestId),
        hours: assignment.hours,
        tone: calendarBookingTone(visibleRequests().find((request) => request.id === assignment.requestId)),
        local: true,
      })).filter((assignment) => assignment.date && assignment.request);
      html += `<div class="cell person"><div class="person-line"><div class="avatar">${esc(person.initials)}</div><div><b>${esc(person.name)}</b><div class="util">${person.allocationPct}% • ${esc(person.skills[0]?.name || person.jobTitle)}</div></div></div></div>`;
      for (const day of days) {
        const events = person.availability.filter((event) => eventOnDate(event, day));
        const assignments = [...generated, ...local].filter((assignment) => assignment.date.toDateString() === day.toDateString());
        const bookings = events.length
          ? events.map((event) => ({ title: event.title || event.eventType, hours: Number(event.allocatedHours) || 8, tone: /travel/i.test(event.eventType) ? 'travel' : 'ooo' }))
          : assignments.map((assignment) => ({ title: primaryRequestDeliverable(assignment.request).name, hours: assignment.hours, tone: assignment.tone }));
        const hours = bookings.reduce((sum, booking) => sum + booking.hours, 0);
        html += `<div class="cell">${bookings.map((booking) => `<div class="booking ${booking.tone}" title="${esc(booking.title)}">${esc(booking.title)} • ${booking.hours}h</div>`).join('')}<span class="day-hours ${hours > 8 ? 'hot' : ''}">${hours}h</span></div>`;
      }
    }
    $('scheduleGrid').innerHTML = people.length ? html : '<div class="empty">No people match this calendar filter.</div>';
    $('calendarLegend').innerHTML = '<span class="legend-item"><i class="legend-swatch" style="background:var(--oj-teal-soft);border-color:var(--oj-teal)"></i>Project work</span><span class="legend-item"><i class="legend-swatch" style="background:var(--oj-purple-soft);border-color:var(--oj-purple)"></i>Video / demo</span><span class="legend-item"><i class="legend-swatch" style="background:var(--oj-amber-soft);border-color:#b9780c"></i>Enablement</span><span class="legend-item"><i class="legend-swatch" style="background:var(--oj-red-soft);border-color:var(--oj-red)"></i>Leave / travel</span>';
  }

  function quickAllocation() {
    const people = [...visiblePeople()].sort((a, b) => b.allocationPct - a.allocationPct);
    const requests = visibleRequests();
    if (!people.length || !requests.length) {
      toast('Allocation unavailable', 'No people or requests are available in the current access scope.');
      return;
    }
    const defaultDate = new Date(startOfCalendarWeek());
    defaultDate.setDate(defaultDate.getDate() + 7);
    openDrawer('Quick allocation', `<div class="form-grid"><div class="form-group full"><label>Person</label><select class="select" id="allocationPerson">${people.map((person) => `<option value="${esc(person.id)}">${esc(person.name)} • ${person.allocationPct}%</option>`).join('')}</select></div><div class="form-group full"><label>Request</label><select class="select" id="allocationRequest">${requests.map((request) => `<option value="${esc(request.id)}">${esc(request.id)} • ${esc(request.title)}</option>`).join('')}</select></div><div class="form-group"><label>Date</label><input class="field" id="allocationDate" type="date" value="${defaultDate.toISOString().slice(0, 10)}"></div><div class="form-group"><label>Hours</label><input class="field" id="allocationHours" type="number" min="1" max="8" value="4"></div></div><div class="notice" style="margin-top:15px"><div>🛡</div><div><strong>Guardrail check runs before saving</strong><p>Any allocation above the configured load limit is blocked and an alternate is proposed.</p></div></div>`, '<button class="btn" data-close-drawer>Cancel</button><button class="btn primary" id="saveQuickAllocation">Save allocation</button>');
    $('saveQuickAllocation').addEventListener('click', () => {
      const person = people.find((item) => item.id === $('allocationPerson').value);
      const request = requests.find((item) => item.id === $('allocationRequest').value);
      const hours = Number($('allocationHours').value) || 0;
      const date = $('allocationDate').value;
      if (!person || !request || !date || hours < 1 || hours > 8) {
        toast('Missing information', 'Select a person, request, date, and between 1 and 8 hours.');
        return;
      }
      if (person.availability.some((event) => eventOnDate(event, dateValue(date)))) {
        toast('Allocation blocked', `${person.name} has a recorded availability conflict on this date.`);
        return;
      }
      const projectedAllocation = person.allocationPct + Math.round(hours / 40 * 100);
      if (projectedAllocation > 85) {
        const alternate = [...people].filter((item) => item.id !== person.id).sort((a, b) => a.allocationPct - b.allocationPct)[0];
        toast('Allocation blocked', `${person.name} would exceed 85%. Consider ${alternate?.name || 'an available alternate'}.`);
        return;
      }
      state.calendarAssignments.push({ personId: person.id, requestId: request.id, date, hours });
      closeDrawer();
      renderCalendar();
      toast('Allocation saved', `${request.id} was added to ${person.name}'s prototype calendar.`);
    });
  }

  function renderInterests() {
    const person = identityPerson();
    if (!person) return;
    const average = person.skills.length ? (person.skills.reduce((sum, skill) => sum + skill.strength, 0) / person.skills.length).toFixed(1) : '0.0';
    $('profileCard').innerHTML = `<div class="avatar">${esc(person.initials)}</div><h3>${esc(person.name)}</h3><p>${esc(person.jobTitle)} • ${esc(person.location)}</p><div class="stat-pairs"><div><strong>${person.allocationPct}%</strong><span>Current allocation</span></div><div><strong>${person.activePods}</strong><span>Active pods</span></div><div><strong>${average}</strong><span>Average strength</span></div><div><strong>${person.skills.length}</strong><span>Mapped skills</span></div></div><div class="readonly-note" style="margin-top:15px">Profile evidence is loaded from the workbook for this demo.</div>`;
    $('interestEditor').innerHTML = person.skills.length ? person.skills.map((skill) => `<div class="interest-row"><div><b>${esc(skill.name)}</b><div class="row-sub">${esc(skill.category)}</div></div><div class="stars" aria-label="Strength ${skill.strength} out of 5">${'★'.repeat(skill.strength)}${'☆'.repeat(Math.max(0, 5 - skill.strength))}</div><span class="pill teal">${esc(skill.source || 'Workbook')}</span><div class="row-sub">${esc(skill.evidence || 'No evidence note recorded')}</div></div>`).join('') : empty('No mapped skills are recorded for this person.');

    const scoped = [...visiblePeople()];
    const sort = $('teamSort').value;
    scoped.sort(sort === 'name' ? (a, b) => a.name.localeCompare(b.name) : sort === 'skill' ? (a, b) => (b.skills[0]?.strength || 0) - (a.skills[0]?.strength || 0) : (a, b) => a.allocationPct - b.allocationPct);
    $('teamDirectorySummary').textContent = `${scoped.length} person${scoped.length === 1 ? '' : 's'} visible to ${state.role}`;
    $('teamDirectory').innerHTML = scoped.map((item) => `<div class="list-row" data-open-person="${esc(item.id)}"><div class="person-line"><div class="avatar">${esc(item.initials)}</div><div><div class="row-title">${esc(item.name)}</div><div class="row-sub">${esc(item.jobTitle)} • ${esc(item.location)}</div></div></div><div>${skillsHtml(item.skills, 2)}</div><div><b>${item.allocationPct}%</b><div class="row-sub">${item.activePods} pods</div></div><button class="btn sm">View</button></div>`).join('') || empty('No people are visible in this persona scope.');
    $('addPersonBtn').style.display = isScopedRole() ? 'none' : '';
  }

  function renderAvailability() {
    const person = identityPerson();
    if (!person) return;
    const events = [...person.availability.map((event) => ({ ...event, local: false })), ...state.localAvailability.map((event) => ({ ...event, local: true }))];
    $('leaveList').innerHTML = events.length ? events.map((event) => `<div class="leave-item"><div class="date-box"><b>${formatShortDate(event.startsOn)}</b><span>${esc(event.eventType)}</span></div><div><b>${esc(event.title || event.eventType)}</b><div class="row-sub">${formatDate(event.startsOn)} to ${formatDate(event.endsOn)} • ${event.allocatedHours || 0} hours</div></div><span class="pill ${event.local ? 'amber' : 'green'}">${event.local ? 'Prototype draft' : 'Workbook'}</span></div>`).join('') : empty('No availability events are recorded for this person.');
    $('capacitySnapshot').innerHTML = `<h3 style="margin-top:0">My capacity</h3><div style="display:flex;justify-content:space-between;margin:16px 0 7px"><span>Current allocation</span><b>${person.allocationPct}%</b></div><div class="progress ${pctClass(person.allocationPct)}"><span style="width:${Math.min(person.allocationPct, 100)}%"></span></div><div class="reason-grid"><div class="reason"><span>Active pods</span><strong>${person.activePods}</strong></div><div class="reason"><span>Recorded events</span><strong>${events.length}</strong></div><div class="reason"><span>Mapped skills</span><strong>${person.skills.length}</strong></div></div><div class="notice" style="margin-top:18px"><div>ℹ</div><div><strong>Workbook-backed snapshot</strong><p>No future capacity percentage is invented. Production calculations should combine assignments and approved availability.</p></div></div>`;
  }

  function renderAgent() {
    const requests = visibleRequests();
    $('agentRequest').innerHTML = requests.map((request) => `<option value="${esc(request.id)}">${esc(request.id)} • ${esc(requestDeliverableNames(request).join(', '))}</option>`).join('');
    if (state.activeRequestId && requests.some((request) => request.id === state.activeRequestId)) $('agentRequest').value = state.activeRequestId;
    const stages = [
      ['Validate request', 'Load project details and key deliverables'],
      ['Resolve required capabilities', 'Read mapped and request-specific capabilities'],
      ['Retrieve people', 'Load skills, strength, and evidence'],
      ['Apply availability', 'Check travel, commitments, and allocation'],
      ['Rank and explain', 'Use workbook recommendations and rationale'],
      ['Human review', 'Keep the recommendation advisory'],
    ];
    $('agentPipeline').innerHTML = stages.map((stage, index) => `<div class="step"><div class="step-icon">${index + 1}</div><div><div class="step-title">${stage[0]}</div><div class="step-desc">${stage[1]}</div></div></div>`).join('');
  }

  function renderAdmin() {
    const roles = [
      { name: 'Request Lead', access: [true, true, true, true, false] },
      { name: 'Pod Lead', access: [true, true, true, false, false] },
      { name: 'Pod Member', access: [true, true, false, false, false] },
      { name: 'Operations Lead', access: [true, true, true, true, true] },
      { name: 'Leadership', access: [true, false, false, false, false] },
      { name: 'System Administrator', access: [true, true, true, true, true] },
    ];
    $('roleMatrix').innerHTML = roles.map((role) => `<tr><th scope="row">${esc(role.name)}</th>${role.access.map((enabled, index) => `<td><button type="button" class="toggle${enabled ? ' on' : ''}" data-role-toggle="${index}" aria-pressed="${enabled}" aria-label="${esc(role.name)} access ${enabled ? 'enabled' : 'disabled'}"></button></td>`).join('')}</tr>`).join('');
    $('roleMatrix').querySelectorAll('[data-role-toggle]').forEach((toggle) => toggle.addEventListener('click', () => {
      const enabled = toggle.classList.toggle('on');
      toggle.setAttribute('aria-pressed', String(enabled));
      toggle.setAttribute('aria-label', toggle.getAttribute('aria-label').replace(enabled ? 'disabled' : 'enabled', enabled ? 'enabled' : 'disabled'));
    }));
    $('deliveryTaxonomy').innerHTML = state.data.catalog.projects.map((project, index) => `<details class="catalog-project" ${index === 0 ? 'open' : ''}><summary>${esc(project.name)} <span class="muted small">(${project.deliverables.length})</span></summary><div class="catalog-project-body"><p class="muted small">${esc(project.description)}</p>${project.deliverables.map((deliverable) => `<div class="catalog-deliverable"><b>${esc(deliverable.name)}</b><p>${esc(deliverable.note || 'No customer note recorded')}</p>${skillsHtml(deliverable.skills)}</div>`).join('')}</div></details>`).join('');
    $('interestTaxonomy').innerHTML = state.data.catalog.skills.map((skill) => `<div class="taxonomy-item"><span>${esc(skill.name)}<small>${esc(skill.category)}</small></span><span class="pill teal">${skill.customerControlled ? 'Customer controlled' : 'Workbook'}</span></div>`).join('');
    $('weightControls').innerHTML = `<div class="readonly-note">The current workbook stores recommendation scores and rationale, not configurable weight percentages.</div><div class="evidence-list" style="margin-top:12px"><div class="evidence-row"><b>Required skills</b><p class="muted small">${state.data.metrics.skills} exact customer skill values</p></div><div class="evidence-row"><b>People evidence</b><p class="muted small">Strength and evidence notes per person</p></div><div class="evidence-row"><b>Availability and allocation</b><p class="muted small">Recorded events plus current allocation percentage</p></div></div>`;
    const audit = state.data.requests.flatMap((request) => request.recommendations.map((recommendation) => ({ request, recommendation })));
    $('auditTable').innerHTML = `<div class="source-strip"><span>${esc(state.data.source.fileName)}</span><span>•</span><span>${esc(state.data.source.version)}</span><span>•</span><span>Integrity checked</span></div>${audit.map(({ request, recommendation }) => `<div class="audit-item"><i class="audit-dot"></i><div><b>${esc(request.id)} • ${esc(recommendation.personName)}</b><div class="row-sub">${esc(recommendation.roleInPod)} • score ${recommendation.score} • ${esc(recommendation.source)}</div></div><span class="audit-time">${esc(recommendation.decisionStatus)}</span></div>`).join('') || empty('No recommendations are recorded.')}`;
  }

  function renderReports() {
    const data = state.data;
    $('reportSourceVersion').textContent = data.source.version || data.source.fileName;
    $('reportOperationalKpis').innerHTML = [
      kpiCard('Open requests', data.metrics.openRequests, `${data.metrics.requests} total`, 'Current workbook snapshot', 'red'),
      kpiCard('Average allocation', `${data.metrics.averageAllocationPct}%`, `${data.metrics.constrainedPeople} constrained`, 'People sheet current allocation', 'amber'),
      kpiCard('Staffed requests', data.metrics.staffedRequests, 'Workbook status', 'No historical trend inferred', 'green'),
      kpiCard('Pending recommendations', data.metrics.pendingRecommendations, 'Human review', 'Recommendation decision status', 'teal'),
    ].join('');
    $('reportCatalogKpis').innerHTML = [
      kpiCard('Project types', data.metrics.projectTypes, 'Customer mapping', 'Exact client terminology', 'purple'),
      kpiCard('Deliverables', data.metrics.deliverables, 'Customer mapping', 'Mapped to project types', 'blue'),
      kpiCard('Skills (Type of work)', data.metrics.skills, 'Customer controlled', `${data.integrity.counts.deliverableSkills} deliverable-skill links`, 'teal'),
      kpiCard('People', data.metrics.people, 'Workbook profiles', 'Skills, strength, and evidence', 'green'),
    ].join('');

    const counts = new Map();
    data.requests.forEach((request) => counts.set(request.projectType.name, (counts.get(request.projectType.name) || 0) + 1));
    const entries = [...counts.entries()];
    const total = Math.max(data.requests.length, 1);
    let cursor = 0;
    const segments = entries.map(([, count], index) => {
      const start = cursor;
      cursor += (count / total) * 100;
      return `${reportColors[index % reportColors.length]} ${start}% ${cursor}%`;
    });
    $('demandDonut').style.background = segments.length ? `conic-gradient(${segments.join(',')})` : '#eeeae4';
    $('demandLegend').innerHTML = entries.map(([name, count], index) => `<div><span><i style="background:${reportColors[index % reportColors.length]}"></i>${esc(name)}</span><b>${count}</b></div>`).join('') || empty('No requests recorded.');
    $('allocationSubtitle').textContent = `${data.people.length} people • ${data.metrics.averageAllocationPct}% average`;
    $('allocationChart').innerHTML = data.people.map((person) => `<div class="bar-wrap"><b>${person.allocationPct}%</b><div class="bar" style="height:${Math.max(person.allocationPct, 4)}%"></div><span class="bar-label" title="${esc(person.name)}">${esc(person.initials)}</span></div>`).join('');

    const decisions = data.requests.flatMap((request) => request.recommendations.map((recommendation) => recommendation.decisionStatus || 'Not recorded'));
    const decisionCounts = new Map();
    decisions.forEach((decision) => decisionCounts.set(decision, (decisionCounts.get(decision) || 0) + 1));
    $('recommendationOutcomes').innerHTML = decisionCounts.size ? [...decisionCounts.entries()].map(([decision, count]) => { const percent = Math.round(count / decisions.length * 100); return `<div style="margin-bottom:14px"><div style="display:flex;justify-content:space-between"><span>${esc(decision)}</span><b>${count}</b></div><div class="progress"><span style="width:${percent}%"></span></div></div>`; }).join('') : empty('No recommendation outcomes are recorded.');
    const constrained = data.people.filter((person) => person.allocationPct >= 70).sort((a, b) => b.allocationPct - a.allocationPct);
    const busiestProject = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];
    $('leadershipCallouts').innerHTML = `<div class="notice"><div>1</div><div><strong>${constrained.length} people at or above 70% allocation</strong><p>${constrained.map((person) => `${person.name} (${person.allocationPct}%)`).join(', ') || 'No constrained people in the current workbook.'}</p></div></div><div class="notice" style="margin-top:10px;background:#edf7f3;border-color:#b9d9ce"><div>2</div><div><strong>Current demand concentration</strong><p>${busiestProject ? `${busiestProject[0]} has ${busiestProject[1]} request${busiestProject[1] === 1 ? '' : 's'}.` : 'No demand is recorded.'}</p></div></div><div class="notice" style="margin-top:10px;background:#f3eff9;border-color:#d5c8e9"><div>3</div><div><strong>Customer mapping coverage</strong><p>${data.metrics.deliverables} deliverables and ${data.integrity.counts.deliverableSkills} skill links loaded from ${esc(data.source.version || data.source.fileName)}.</p></div></div>`;
  }

  function renderAll() {
    renderNav();
    renderDashboard();
    renderRequestFilters();
    renderRequests();
    renderFitment();
    renderCalendar();
    renderInterests();
    renderAvailability();
    renderAgent();
    renderAdmin();
    renderReports();
    applyRoleView();
  }

  function applyRoleView() {
    const person = identityPerson();
    const footer = document.querySelector('.mini-user');
    if (footer) {
      footer.innerHTML = isScopedRole() && person
        ? `<div class="avatar">${esc(person.initials)}</div><div><strong>${esc(person.name)}</strong><span>${esc(state.role)}</span></div>`
        : `<div class="avatar">IB</div><div><strong>Indranie B.</strong><span>${esc(state.role)}</span></div>`;
    }
    $('newRequestBtn').style.display = state.role === 'POD Member' ? 'none' : '';
    $('newRequestBtn2').style.display = state.role === 'POD Member' ? 'none' : '';
    $('exportRequests').style.display = state.role === 'POD Member' ? 'none' : '';
    if (!screenAllowed(state.screen)) go('dashboard');
  }

  function openRequest(id) {
    const request = [...workbookRequests(), ...state.drafts].find((item) => item.id === id);
    if (!request || !visibleRequests().some((item) => item.id === id)) {
      toast('Not available', 'This request is outside the selected persona scope.');
      return;
    }
    const scopedRecommendationCount = recommendationsInScope(request).length;
    const projectDescription = requestProjectDescription(request);
    const businessObjectives = requestBusinessObjectives(request);
    openDrawer(request.title, `<span class="pill blue">${esc(request.id)}</span><h3>${esc(request.projectType.name)}</h3><dl><div class="summary-pair"><dt>Key deliverables</dt><dd>${esc(requestDeliverableNames(request).join(', '))}</dd></div><div class="summary-pair"><dt>Required capabilities</dt><dd>${skillsHtml(request.requiredSkills)}</dd></div><div class="summary-pair"><dt>Request source</dt><dd>${esc(request.requestSource || request.ownerName)}</dd></div><div class="summary-pair"><dt>Status</dt><dd>${esc(request.status)}</dd></div><div class="summary-pair"><dt>Needed by date</dt><dd>${formatDate(request.neededBy)}</dd></div>${request.estimatedStartDate ? `<div class="summary-pair"><dt>Estimated start date</dt><dd>${formatDate(request.estimatedStartDate)}</dd></div>` : ''}${request.estimatedCompletionDate ? `<div class="summary-pair"><dt>Estimated completion date</dt><dd>${formatDate(request.estimatedCompletionDate)}</dd></div>` : ''}<div class="summary-pair"><dt>Estimated effort</dt><dd>${esc(requestEffortLabel(request))}</dd></div>${request.requestedPodSize ? `<div class="summary-pair"><dt>Requested pod size</dt><dd>${esc(request.requestedPodSize)}</dd></div>` : ''}</dl><div class="fit-summary-note"><b>Project description</b><p class="muted small">${esc(projectDescription || 'No project description recorded')}</p></div><div class="fit-summary-note"><b>Business objectives and expected outcomes</b><p class="muted small">${esc(businessObjectives || 'No objectives or outcomes recorded')}</p></div><div class="source-strip"><span>${esc(request.mappingVersion || state.data.source.version)}</span><span>•</span><span>${scopedRecommendationCount} scoped recommendation${scopedRecommendationCount === 1 ? '' : 's'}</span></div>`, `<button class="btn" data-close-drawer>Close</button><button class="btn primary" data-open-fitment="${esc(request.id)}">Open fitment</button>`);
  }

  function openPerson(id) {
    const person = visiblePeople().find((item) => item.id === id);
    if (!person) {
      toast('Not available', 'This person is outside the selected persona scope.');
      return;
    }
    openDrawer(person.name, `<div style="text-align:center"><div class="avatar" style="width:68px;height:68px;margin:0 auto;font-size:20px">${esc(person.initials)}</div><h3>${esc(person.jobTitle)}</h3><p class="muted">${esc(person.location)} • ${person.allocationPct}% allocated • ${person.activePods} active pods</p></div><h4>Customer skills</h4>${person.skills.map((skill) => `<div class="evidence-row"><b>${esc(skill.name)} • ${skill.strength}/5</b><p class="muted small">${esc(skill.evidence || 'No evidence note')} • ${esc(skill.source)}</p></div>`).join('') || empty('No mapped skills recorded.')}<h4>Availability</h4>${person.availability.map((event) => `<div class="audit-item"><i class="audit-dot"></i><div><b>${esc(event.title)}</b><div class="row-sub">${formatDate(event.startsOn)} to ${formatDate(event.endsOn)}</div></div><span>${esc(event.eventType)}</span></div>`).join('') || empty('No events recorded.')}`);
  }

  function newRequest() {
    const projects = state.data.catalog.projects;
    state.newRequestSkillIds = [];
    state.newRequestDefaultSkillIds = [];
    state.newRequestExcludedDefaultSkillIds = [];
    state.newRequestCustomSkills = [];
    state.newRequestCustomSkillCounter = 0;
    state.newRequestDeliverableIds = [];
    state.newRequestCustomDeliverables = [];
    state.newRequestCustomDeliverableCounter = 0;
    const defaultRequestSource = isScopedRole() ? identityPerson()?.name : 'Indranie B.';
    openDrawer('Create staffing request', `<div class="form-grid"><div class="form-group full"><label>Request title</label><input class="field" id="newTitle" placeholder="Enter request title"></div><div class="form-group"><label>Project type</label><select class="select" id="newProjectType">${projects.map((project) => `<option value="${esc(project.id)}">${esc(project.name)}</option>`).join('')}</select></div><div class="form-group"><label>Request source</label><input class="field" id="newRequestSource" value="${esc(defaultRequestSource || 'Current user')}" placeholder="Person or team requesting the work"></div><div class="form-group full"><label>Project description</label><textarea class="textarea" id="newProjectDescription" placeholder="Describe the project and the work being requested"></textarea></div><div class="form-group full"><label>Key deliverables</label><div id="newDeliverables"></div></div><div class="form-group"><label>Priority</label><select class="select" id="newPriority"><option>Normal</option><option>High</option></select></div><div class="form-group"><label>Needed by date</label><input class="field" id="newNeededBy" type="date" value="2026-08-21"></div><div class="form-group"><label>Estimated start date</label><input class="field" id="newStartDate" type="date" value="2026-08-17"></div><div class="form-group"><label>Estimated completion date</label><input class="field" id="newCompletionDate" type="date" value="2026-08-21"></div><div class="form-group"><label>Estimated effort</label><div class="effort-control"><input class="field" id="newEffortValue" type="number" min="1" value="5"><select class="select" id="newEffortUnit"><option value="days">Days</option><option value="weeks">Weeks</option><option value="months">Months</option></select></div></div><div class="form-group"><label>Requested pod size</label><select class="select" id="newPodSize"><option>1 lead + 2 contributors</option><option>1 lead + 1 contributor</option><option>1 lead + 3 contributors</option></select></div><div class="form-group full"><label>Required capabilities</label><div id="newSkills"></div></div><div class="form-group full"><label>Customer catalogue note</label><div id="newCustomerNote" class="readonly-note"></div></div><div class="form-group full"><label>Business objectives and expected outcomes</label><textarea class="textarea" id="newContext" placeholder="Describe the business objective, intended audience, success measures, and expected outcome"></textarea></div></div>`, '<button class="btn" data-close-drawer>Cancel</button><button class="btn primary" id="submitDraftRequest">Save request</button>');
    const updateProject = () => {
      const project = projects.find((item) => item.id === $('newProjectType').value) || projects[0];
      $('newProjectDescription').value = project?.description || '';
      state.newRequestDeliverableIds = project?.deliverables[0] ? [project.deliverables[0].id] : [];
      state.newRequestCustomDeliverables = [];
      state.newRequestCustomDeliverableCounter = 0;
      state.newRequestExcludedDefaultSkillIds = [];
      renderDraftDeliverablesEditor();
      syncDraftSkillsFromDeliverables(true);
    };
    $('newProjectType').addEventListener('change', updateProject);
    $('submitDraftRequest').addEventListener('click', submitDraftRequest);
    updateProject();
  }

  function currentDraftProject() {
    return state.data.catalog.projects.find((item) => item.id === $('newProjectType')?.value) || null;
  }

  function draftDeliverableById(id) {
    return currentDraftProject()?.deliverables.find((item) => item.id === id) || state.newRequestCustomDeliverables.find((item) => item.id === id) || null;
  }

  function currentDraftDeliverables() {
    return state.newRequestDeliverableIds.map(draftDeliverableById).filter(Boolean);
  }

  function renderDraftDeliverablesEditor() {
    const project = currentDraftProject();
    const selected = currentDraftDeliverables();
    const available = (project?.deliverables || []).filter((deliverable) => !state.newRequestDeliverableIds.includes(deliverable.id));
    $('newDeliverables').innerHTML = `<div class="editable-skills editable-deliverables"><div class="editable-skill-list">${selected.length ? selected.map((deliverable) => `<span class="editable-skill ${deliverable.custom ? 'custom' : ''}">${esc(deliverable.name)}${deliverable.custom ? ' <small>(Other)</small>' : ''}<button type="button" data-remove-draft-deliverable="${esc(deliverable.id)}" aria-label="Remove ${esc(deliverable.name)}">×</button></span>`).join('') : '<span class="muted small">No deliverables selected. Add at least one deliverable.</span>'}</div><div class="skill-picker"><select class="select" id="draftDeliverablePicker" aria-label="Additional key deliverable">${available.map((deliverable) => `<option value="${esc(deliverable.id)}">${esc(deliverable.name)}</option>`).join('')}<option value="__other__">Other — type a deliverable</option></select><button class="btn sm" type="button" id="addDraftDeliverable">＋ Add deliverable</button></div><div class="custom-skill-entry" id="customDeliverableEntry"><input class="field" id="customDeliverableName" maxlength="120" placeholder="Type a deliverable and press Enter"></div><div class="skills-help">Choose one or more mapped deliverables, or add a request-specific deliverable.</div></div>`;
    document.querySelectorAll('[data-remove-draft-deliverable]').forEach((button) => button.addEventListener('click', () => {
      state.newRequestDeliverableIds = state.newRequestDeliverableIds.filter((id) => id !== button.dataset.removeDraftDeliverable);
      state.newRequestCustomDeliverables = state.newRequestCustomDeliverables.filter((deliverable) => deliverable.id !== button.dataset.removeDraftDeliverable);
      renderDraftDeliverablesEditor();
      syncDraftSkillsFromDeliverables();
    }));
    const setCustomDeliverableVisibility = () => {
      const isOther = $('draftDeliverablePicker').value === '__other__';
      $('customDeliverableEntry').classList.toggle('visible', isOther);
      if (isOther) $('customDeliverableName').focus();
    };
    const addSelectedDraftDeliverable = () => {
      const selectedId = $('draftDeliverablePicker').value;
      if (selectedId === '__other__') {
        const name = $('customDeliverableName').value.trim();
        if (!name) {
          toast('Deliverable name required', 'Type the custom deliverable before adding it.');
          $('customDeliverableName').focus();
          return;
        }
        const duplicate = [...(project?.deliverables || []), ...state.newRequestCustomDeliverables].some((deliverable) => deliverable.name.toLowerCase() === name.toLowerCase());
        if (duplicate) {
          toast('Deliverable already available', `${name} is already available for this project.`);
          return;
        }
        state.newRequestCustomDeliverableCounter += 1;
        const id = `CUSTOM-DELIVERABLE-${state.newRequestCustomDeliverableCounter}`;
        state.newRequestCustomDeliverables.push({ id, name, note: '', skills: [], custom: true });
        state.newRequestDeliverableIds.push(id);
      } else if (selectedId && !state.newRequestDeliverableIds.includes(selectedId)) {
        state.newRequestDeliverableIds.push(selectedId);
      }
      renderDraftDeliverablesEditor();
      syncDraftSkillsFromDeliverables();
    };
    $('draftDeliverablePicker').addEventListener('change', setCustomDeliverableVisibility);
    $('addDraftDeliverable').addEventListener('click', addSelectedDraftDeliverable);
    $('customDeliverableName').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        addSelectedDraftDeliverable();
      }
    });
    setCustomDeliverableVisibility();
  }

  function syncDraftSkillsFromDeliverables(reset = false) {
    const oldDefaultIds = [...state.newRequestDefaultSkillIds];
    const manualSkillIds = reset ? [] : state.newRequestSkillIds.filter((id) => !oldDefaultIds.includes(id));
    const nextDefaultIds = unique(currentDraftDeliverables().flatMap((deliverable) => (deliverable.skills || []).map((skill) => skill.id)));
    state.newRequestDefaultSkillIds = nextDefaultIds;
    const activeDefaults = nextDefaultIds.filter((id) => !state.newRequestExcludedDefaultSkillIds.includes(id));
    state.newRequestSkillIds = unique([...activeDefaults, ...manualSkillIds]);
    if (reset) {
      state.newRequestCustomSkills = [];
      state.newRequestCustomSkillCounter = 0;
    }
    const notes = unique(currentDraftDeliverables().map((deliverable) => deliverable.note).filter(Boolean));
    $('newCustomerNote').textContent = notes.length ? notes.join(' • ') : 'No customer note recorded for the selected deliverables.';
    renderDraftSkillsEditor();
  }

  function draftSkillById(id) {
    return state.data.catalog.skills.find((skill) => skill.id === id) || state.newRequestCustomSkills.find((skill) => skill.id === id) || null;
  }

  function renderDraftSkillsEditor() {
    const selected = state.newRequestSkillIds.map(draftSkillById).filter(Boolean);
    const available = state.data.catalog.skills.filter((skill) => !state.newRequestSkillIds.includes(skill.id));
    $('newSkills').innerHTML = `<div class="editable-skills"><div class="editable-skill-list">${selected.length ? selected.map((skill) => `<span class="editable-skill ${skill.custom ? 'custom' : ''}">${esc(skill.name)}${skill.custom ? ' <small>(Other)</small>' : ''}<button type="button" data-remove-draft-skill="${esc(skill.id)}" aria-label="Remove ${esc(skill.name)}">×</button></span>`).join('') : '<span class="muted small">No capabilities selected. Add at least one capability.</span>'}</div><div class="skill-picker"><select class="select" id="draftSkillPicker" aria-label="Additional required capability">${available.map((skill) => `<option value="${esc(skill.id)}">${esc(skill.name)}</option>`).join('')}<option value="__other__">Other — type a capability</option></select><button class="btn sm" type="button" id="addDraftSkill">＋ Add capability</button></div><div class="custom-skill-entry" id="customSkillEntry"><input class="field" id="customSkillName" maxlength="80" placeholder="Type a capability and press Enter"></div><div class="skills-help">Mapped defaults can be removed, and additional or custom capabilities can be added for this request.</div></div>`;
    document.querySelectorAll('[data-remove-draft-skill]').forEach((button) => button.addEventListener('click', () => {
      if (state.newRequestDefaultSkillIds.includes(button.dataset.removeDraftSkill) && !state.newRequestExcludedDefaultSkillIds.includes(button.dataset.removeDraftSkill)) {
        state.newRequestExcludedDefaultSkillIds.push(button.dataset.removeDraftSkill);
      }
      state.newRequestSkillIds = state.newRequestSkillIds.filter((id) => id !== button.dataset.removeDraftSkill);
      state.newRequestCustomSkills = state.newRequestCustomSkills.filter((skill) => skill.id !== button.dataset.removeDraftSkill);
      renderDraftSkillsEditor();
    }));
    const setCustomSkillVisibility = () => {
      const isOther = $('draftSkillPicker').value === '__other__';
      $('customSkillEntry').classList.toggle('visible', isOther);
      if (isOther) $('customSkillName').focus();
    };
    const addSelectedDraftSkill = () => {
      const selectedId = $('draftSkillPicker').value;
      if (selectedId === '__other__') {
        const name = $('customSkillName').value.trim();
        if (!name) {
          toast('Skill name required', 'Type the additional skill before adding it.');
          $('customSkillName').focus();
          return;
        }
        const alreadySelected = selected.some((skill) => skill.name.toLowerCase() === name.toLowerCase());
        if (alreadySelected) {
          toast('Skill already selected', `${name} is already included in this request.`);
          return;
        }
        const catalogMatch = state.data.catalog.skills.find((skill) => skill.name.toLowerCase() === name.toLowerCase());
        if (catalogMatch) {
          state.newRequestExcludedDefaultSkillIds = state.newRequestExcludedDefaultSkillIds.filter((id) => id !== catalogMatch.id);
          state.newRequestSkillIds.push(catalogMatch.id);
        } else {
          state.newRequestCustomSkillCounter += 1;
          const id = `CUSTOM-${state.newRequestCustomSkillCounter}`;
          state.newRequestCustomSkills.push({ id, name, category: 'Request-specific', customerControlled: false, custom: true });
          state.newRequestSkillIds.push(id);
        }
      } else if (selectedId && !state.newRequestSkillIds.includes(selectedId)) {
        state.newRequestExcludedDefaultSkillIds = state.newRequestExcludedDefaultSkillIds.filter((id) => id !== selectedId);
        state.newRequestSkillIds.push(selectedId);
      }
      renderDraftSkillsEditor();
    };
    $('draftSkillPicker').addEventListener('change', setCustomSkillVisibility);
    $('addDraftSkill').addEventListener('click', addSelectedDraftSkill);
    $('customSkillName').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        addSelectedDraftSkill();
      }
    });
    setCustomSkillVisibility();
  }

  function submitDraftRequest() {
    const title = $('newTitle').value.trim();
    const project = currentDraftProject();
    const deliverables = currentDraftDeliverables();
    const requestSource = $('newRequestSource').value.trim();
    const neededBy = $('newNeededBy').value;
    const estimatedStartDate = $('newStartDate').value;
    const estimatedCompletionDate = $('newCompletionDate').value;
    const estimatedEffortValue = Number($('newEffortValue').value) || 0;
    const estimatedEffortUnit = $('newEffortUnit').value;
    if (!title || !project || !requestSource || !deliverables.length) {
      toast('Missing information', 'Enter a title and request source, then choose at least one key deliverable.');
      return;
    }
    if (!neededBy || !estimatedStartDate || !estimatedCompletionDate) {
      toast('Dates required', 'Enter the needed-by, estimated start, and estimated completion dates.');
      return;
    }
    if (estimatedStartDate > estimatedCompletionDate) {
      toast('Check the dates', 'The estimated completion date must be on or after the estimated start date.');
      return;
    }
    if (estimatedEffortValue <= 0) {
      toast('Estimated effort required', 'Enter an effort greater than zero and choose days, weeks, or months.');
      return;
    }
    if (!state.newRequestSkillIds.length) {
      toast('Required capability missing', 'Add at least one required capability before saving the request.');
      return;
    }
    const selectedSkills = state.newRequestSkillIds.map(draftSkillById).filter(Boolean);
    const requiredCapabilities = selectedSkills.map((skill) => ({ ...skill, requiredStrength: null, source: skill.custom ? 'Request-entered' : state.newRequestDefaultSkillIds.includes(skill.id) ? 'Customer Mapping' : 'Request override' }));
    const savedDeliverables = deliverables.map((deliverable) => ({ id: deliverable.id, name: deliverable.name, note: deliverable.note || '', custom: Boolean(deliverable.custom), source: deliverable.custom ? 'Request-entered' : 'Customer Mapping' }));
    const effortHours = estimatedEffortValue * ({ days: 8, weeks: 40, months: 160 }[estimatedEffortUnit] || 8);
    const businessObjectives = $('newContext').value.trim();
    const id = `DRAFT-${String(state.drafts.length + 1).padStart(3, '0')}`;
    state.drafts.push({
      id,
      title,
      projectType: { id: project.id, name: project.name, description: project.description },
      projectDescription: $('newProjectDescription').value.trim(),
      deliverable: savedDeliverables[0],
      deliverables: savedDeliverables,
      keyDeliverables: savedDeliverables.map((deliverable) => deliverable.name),
      requiredSkills: requiredCapabilities,
      requiredCapabilities,
      ownerName: requestSource,
      requestSource,
      neededBy,
      estimatedStartDate,
      estimatedCompletionDate,
      estimatedEffort: { value: estimatedEffortValue, unit: estimatedEffortUnit },
      estimatedHours: effortHours,
      requestedPodSize: $('newPodSize').value,
      priority: $('newPriority').value,
      status: 'Needs recommendation',
      businessContext: businessObjectives,
      businessObjectivesAndExpectedOutcomes: businessObjectives,
      mappingVersion: state.data.source.version,
      recommendations: [],
    });
    closeDrawer();
    renderDashboard();
    renderRequestFilters();
    renderRequests();
    renderAgent();
    toast('Request created', `${id} has been saved.`);
    go('requests');
  }

  function availabilityForm() {
    openDrawer('Add availability event', `<div class="readonly-note">This is a local prototype entry. It does not write to the Excel workbook.</div><div class="form-grid" style="margin-top:15px"><div class="form-group full"><label>Event type</label><select class="select" id="avType"><option>OOO</option><option>Leave</option><option>Travel</option><option>Training</option><option>Reduced hours</option></select></div><div class="form-group"><label>Start date</label><input class="field" id="avStart" type="date" value="2026-08-17"></div><div class="form-group"><label>End date</label><input class="field" id="avEnd" type="date" value="2026-08-18"></div><div class="form-group full"><label>Title</label><input class="field" id="avTitle" placeholder="What should schedulers see?"></div><div class="form-group full"><label>Allocated hours</label><input class="field" id="avHours" type="number" min="0" value="8"></div></div>`, '<button class="btn" data-close-drawer>Cancel</button><button class="btn primary" id="saveLocalAvailability">Save prototype event</button>');
    $('saveLocalAvailability').addEventListener('click', () => {
      state.localAvailability.push({ eventType: $('avType').value, startsOn: $('avStart').value, endsOn: $('avEnd').value, title: $('avTitle').value.trim() || $('avType').value, allocatedHours: Number($('avHours').value) || 0 });
      closeDrawer();
      renderAvailability();
      toast('Prototype event saved', 'The workbook remains unchanged.');
    });
  }

  function runAgent() {
    const request = visibleRequests().find((item) => item.id === $('agentRequest').value);
    if (!request) return;
    state.activeRequestId = request.id;
    const steps = [...document.querySelectorAll('#agentPipeline .step')];
    const logs = [
      `Validated ${request.id}: ${request.projectType.name} / ${requestDeliverableNames(request).join(', ')}.`,
      `Loaded ${request.requiredSkills.length} required capabilities: ${request.requiredSkills.map((skill) => skill.name).join(', ') || 'none recorded'}.`,
      `Loaded ${visiblePeople().length} people in the ${state.role} access scope.`,
      `Checked ${visiblePeople().reduce((sum, person) => sum + person.availability.length, 0)} availability events and current allocation.`,
      `Read ${request.recommendations.length} workbook recommendation${request.recommendations.length === 1 ? '' : 's'} with rationale.`,
      'Recommendation remains advisory and awaits human review.',
    ];
    $('agentConsole').innerHTML = '';
    $('agentResultCard').style.display = 'none';
    $('agentStatus').className = 'pill red';
    $('agentStatus').textContent = 'Running';
    steps.forEach((step) => step.classList.remove('active', 'done'));
    let index = 0;
    const tick = () => {
      if (index > 0) { steps[index - 1].classList.remove('active'); steps[index - 1].classList.add('done'); }
      if (index >= steps.length) {
        $('agentStatus').className = 'pill green';
        $('agentStatus').textContent = 'Complete';
        $('agentResultCard').style.display = '';
        $('agentResult').innerHTML = request.recommendations.length ? renderCandidates(request.recommendations, request) : empty('No recommendation is recorded for this request.');
        toast('Fitment evidence loaded', `Results for ${request.id} came from the workbook.`);
        return;
      }
      steps[index].classList.add('active');
      $('agentConsole').innerHTML += `<div class="logline"><span class="time">[${new Date().toLocaleTimeString()}]</span> <span class="${index === steps.length - 1 ? 'warn' : 'ok'}">${esc(logs[index])}</span></div>`;
      $('agentConsole').scrollTop = $('agentConsole').scrollHeight;
      index += 1;
      window.setTimeout(tick, 380);
    };
    tick();
  }

  async function sendChat(question) {
    const body = $('chatBody');
    body.innerHTML += `<div class="bubble me">${esc(question)}</div>`;
    const pending = document.createElement('div');
    pending.className = 'bubble ai';
    pending.textContent = 'Checking the staffing workbook…';
    body.appendChild(pending);
    body.scrollTop = body.scrollHeight;
    try {
      const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: question, role: state.role }) });
      if (!response.ok) throw new Error(`Chat request failed (${response.status})`);
      const result = await response.json();
      pending.textContent = result.answer;
    } catch (error) {
      pending.textContent = 'I could not read the staffing workbook right now. Please retry after checking the local server.';
      console.error(error);
    }
    body.scrollTop = body.scrollHeight;
  }

  function exportRequests() {
    const headers = ['ID', 'Title', 'Project Type', 'Project Description', 'Key Deliverables', 'Required Capabilities', 'Request Source', 'Status', 'Priority', 'Needed By Date', 'Estimated Start Date', 'Estimated Completion Date', 'Estimated Effort Value', 'Estimated Effort Unit', 'Requested Pod Size', 'Business Objectives and Expected Outcomes', 'Mapping Version'];
    const csvRows = visibleRequests().map((request) => [request.id, request.title, request.projectType.name, requestProjectDescription(request), requestDeliverableNames(request).join('; '), request.requiredSkills.map((skill) => skill.name).join('; '), request.requestSource || request.ownerName, request.status, request.priority, request.neededBy, request.estimatedStartDate || '', request.estimatedCompletionDate || '', request.estimatedEffort?.value || request.estimatedHours, request.estimatedEffort?.unit || 'hours', request.requestedPodSize || '', requestBusinessObjectives(request), request.mappingVersion]);
    const csv = [headers, ...csvRows].map((row) => row.map((value) => `"${String(value ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    link.download = 'ai-pod-workbook-requests.csv';
    link.click();
    URL.revokeObjectURL(link.href);
    toast('Export created', `${csvRows.length} scoped request${csvRows.length === 1 ? '' : 's'} exported with customer terminology.`);
  }

  function notifications() {
    const requests = visibleRequests();
    const recommendations = requests.flatMap((request) => recommendationsInScope(request));
    const constrained = visiblePeople().filter((person) => person.allocationPct >= 70);
    openDrawer('Notifications', `<div class="audit-item"><i class="audit-dot"></i><div><b>${recommendations.filter((item) => /pending/i.test(item.decisionStatus)).length} recommendations await review</b><div class="row-sub">Current ${state.role} access scope</div></div></div><div class="audit-item"><i class="audit-dot"></i><div><b>${constrained.length} people are at or above 70%</b><div class="row-sub">${esc(constrained.map((person) => person.name).join(', ') || 'No constrained people')}</div></div></div><div class="audit-item"><i class="audit-dot"></i><div><b>Customer mapping ${esc(state.data.source.version)}</b><div class="row-sub">${state.data.metrics.projectTypes} projects • ${state.data.metrics.deliverables} deliverables • ${state.data.metrics.skills} skills</div></div></div>`);
  }

  function bind() {
    document.addEventListener('click', (event) => {
      const nav = event.target.closest('[data-screen]');
      if (nav) go(nav.dataset.screen);
      const target = event.target.closest('[data-go]');
      if (target) go(target.dataset.go);
      const request = event.target.closest('[data-open-request]');
      if (request) openRequest(request.dataset.openRequest);
      const fitment = event.target.closest('[data-open-fitment]');
      if (fitment) { state.activeRequestId = fitment.dataset.openFitment; closeDrawer(); renderFitment(); go('fitment'); }
      const person = event.target.closest('[data-open-person]');
      if (person) openPerson(person.dataset.openPerson);
      if (event.target.closest('[data-close-drawer]')) closeDrawer();
      if (event.target.closest('[data-close-modal]')) closeModal();
    });
    $('menuBtn').addEventListener('click', () => $('sidebar').classList.toggle('open'));
    $('newRequestBtn').addEventListener('click', newRequest);
    $('newRequestBtn2').addEventListener('click', newRequest);
    ['requestSearch', 'requestStatusFilter', 'requestPriorityFilter', 'requestProjectFilter', 'requestDeliverableFilter'].forEach((id) => $(id).addEventListener(id === 'requestSearch' ? 'input' : 'change', () => renderRequests(false)));
    $('demandProjectFilter').addEventListener('change', renderUpcomingDemand);
    $('refreshFit').addEventListener('click', () => { renderFitment(); toast('Fitment refreshed', 'Current workbook evidence was re-rendered.'); });
    $('approveFit').addEventListener('click', () => {
      const request = activeRequest();
      openModal('Human approval checkpoint', `<div class="notice"><div>✓</div><div><strong>${esc(request?.id || 'Request')} remains unchanged</strong><p>This UI demonstrates approval. It does not write a decision back to Excel.</p></div></div>`, '<button class="btn" data-close-modal>Cancel</button><button class="btn primary" id="confirmPrototypeApproval">Confirm prototype action</button>');
      $('confirmPrototypeApproval').addEventListener('click', () => { closeModal(); toast('Prototype approval shown', 'No workbook data was changed.'); });
    });
    $('prevWeek').addEventListener('click', () => { state.weekOffset -= 1; renderCalendar(); });
    $('nextWeek').addEventListener('click', () => { state.weekOffset += 1; renderCalendar(); });
    $('todayWeek').addEventListener('click', () => { state.weekOffset = 0; renderCalendar(); });
    $('calendarSkillFilter').addEventListener('change', renderCalendar);
    $('capacityFilter').addEventListener('change', renderCalendar);
    $('showAlternates').addEventListener('change', renderCalendar);
    $('quickAllocate').addEventListener('click', quickAllocation);
    $('teamSearch').addEventListener('input', (event) => { const query = event.target.value.toLowerCase(); document.querySelectorAll('#teamDirectory .list-row').forEach((row) => { row.style.display = row.textContent.toLowerCase().includes(query) ? 'grid' : 'none'; }); });
    $('teamSort').addEventListener('change', renderInterests);
    $('addPersonBtn').addEventListener('click', () => toast('Production integration', 'People should come from enterprise identity; the workbook remains read-only here.'));
    $('addAvailabilityBtn').addEventListener('click', availabilityForm);
    $('agentRequest').addEventListener('change', (event) => { state.activeRequestId = event.target.value; });
    $('runAgentBtn').addEventListener('click', runAgent);
    document.querySelectorAll('[data-admin]').forEach((button) => button.addEventListener('click', () => {
      document.querySelectorAll('[data-admin]').forEach((item) => item.classList.toggle('active', item === button));
      document.querySelectorAll('.admin-panel').forEach((panel) => panel.classList.toggle('active', panel.id === `admin-${button.dataset.admin}`));
    }));
    $('maxLoad').addEventListener('input', (event) => { $('maxLoadValue').textContent = `${event.target.value}%`; });
    $('saveAdmin').addEventListener('click', () => toast('Prototype configuration', 'No customer taxonomy or workbook data was changed.'));
    $('previewRole').addEventListener('click', () => { $('roleSelect').value = 'POD Member'; setRole('POD Member'); });
    $('printReport').addEventListener('click', () => window.print());
    $('exportRequests').addEventListener('click', exportRequests);
    $('roleSelect').addEventListener('change', (event) => setRole(event.target.value));
    $('notifBtn').addEventListener('click', notifications);
    $('globalSearch').addEventListener('keydown', (event) => { if (event.key === 'Enter') { $('requestSearch').value = event.target.value; renderRequests(false); go('requests'); } });
    $('closeDrawer').addEventListener('click', closeDrawer);
    $('drawerBackdrop').addEventListener('click', closeDrawer);
    $('closeModal').addEventListener('click', closeModal);
    $('modalWrap').addEventListener('click', (event) => { if (event.target === $('modalWrap')) closeModal(); });
    $('askBtn').addEventListener('click', () => $('chatPanel').classList.toggle('open'));
    $('closeChat').addEventListener('click', () => $('chatPanel').classList.remove('open'));
    document.querySelectorAll('[data-q]').forEach((button) => button.addEventListener('click', () => sendChat(button.dataset.q)));
    $('sendChat').addEventListener('click', () => { const value = $('chatInput').value.trim(); if (value) { sendChat(value); $('chatInput').value = ''; } });
    $('chatInput').addEventListener('keydown', (event) => { if (event.key === 'Enter') $('sendChat').click(); });
  }

  function setRole(role) {
    state.role = role;
    state.activeRequestId = null;
    renderAll();
    toast('Persona changed', `Workbook content is now scoped for ${role}.`);
  }

  function showLoadError(error) {
    console.error(error);
    $('dashboardKpis').innerHTML = '<div class="card pad loading-error">Check the local server and data/ai-pod-staffing-prototype.xlsx, then refresh.</div>';
    $('priorityQueue').innerHTML = empty('Workbook data is unavailable.');
  }

  async function bootstrap() {
    bind();
    const params = new URLSearchParams(window.location.search);
    const requestedRole = params.get('role');
    if ([...$('roleSelect').options].some((option) => option.value === requestedRole)) {
      state.role = requestedRole;
      $('roleSelect').value = requestedRole;
    }
    renderNav();
    $('priorityQueue').innerHTML = empty('Loading staffing data from Excel…');
    try {
      const response = await fetch('/api/staffing', { cache: 'no-store' });
      if (!response.ok) throw new Error(`Staffing API failed (${response.status})`);
      const payload = await response.json();
      state.data = payload.data;
      if (!state.data?.integrity?.checked) throw new Error('Workbook integrity was not confirmed.');
      state.activeRequestId = state.data.requests.find((request) => request.recommendations.length)?.id || state.data.requests[0]?.id || null;
      renderAll();
      const requestedScreen = params.get('screen');
      if (navItems.some((item) => item[0] === requestedScreen) && screenAllowed(requestedScreen)) go(requestedScreen);
      toast('Workbook connected', `${state.data.metrics.requests} requests, ${state.data.metrics.deliverables} deliverables, and ${state.data.metrics.skills} customer skills loaded.`);
    } catch (error) {
      showLoadError(error);
    }
  }

  bootstrap();
})();

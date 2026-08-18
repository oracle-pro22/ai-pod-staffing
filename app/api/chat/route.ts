import { NextResponse } from 'next/server';
import { dataSource, type StaffingViewModel } from '@/lib/staffing-data';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

function requestsForRole(data: StaffingViewModel, role: string) {
  if (role === 'POD Member') {
    return data.requests.filter((request) =>
      request.recommendations.some((recommendation) => recommendation.personId === data.demoIdentity.podMemberPersonId),
    );
  }
  if (role === 'Pod Lead') {
    return data.requests.filter((request) =>
      request.recommendations.some((recommendation) => recommendation.personId === data.demoIdentity.podLeadPersonId),
    );
  }
  return data.requests;
}

export async function POST(request: Request) {
  const body = await request.json();
  const message = String(body.message ?? '').trim();
  const role = String(body.role ?? 'Operations Lead');
  const query = message.toLowerCase();
  const data = await dataSource.getViewModel();
  const visibleRequests = requestsForRole(data, role);
  const visiblePersonIds = new Set(visibleRequests.flatMap((item) => item.recommendations.map((item) => item.personId)));
  const visiblePeople = role === 'POD Member'
    ? data.people.filter((person) => person.id === data.demoIdentity.podMemberPersonId)
    : role === 'Pod Lead'
      ? data.people.filter((person) => visiblePersonIds.has(person.id))
      : data.people;

  const matchedPerson = visiblePeople.find((person) => query.includes(person.name.toLowerCase()));
  const matchedRequest = visibleRequests.find((item) => query.includes(item.id.toLowerCase()) || query.includes(item.title.toLowerCase()));
  let answer: string;

  if (matchedPerson) {
    const strongest = matchedPerson.skills.slice(0, 3).map((skill) => `${skill.name} (${skill.strength}/5)`).join(', ') || 'no mapped skills';
    const events = matchedPerson.availability.map((event) => `${event.title}, ${event.startsOn} to ${event.endsOn}`).join('; ') || 'no recorded availability events';
    answer = `${matchedPerson.name} is ${matchedPerson.allocationPct}% allocated across ${matchedPerson.activePods} active pods. Strongest customer skills: ${strongest}. Availability: ${events}.`;
  } else if (matchedRequest) {
    const skills = matchedRequest.requiredSkills.map((skill) => skill.name).join(', ');
    const scopedRecommendations = role === 'POD Member'
      ? matchedRequest.recommendations.filter((item) => item.personId === data.demoIdentity.podMemberPersonId)
      : matchedRequest.recommendations;
    const pod = scopedRecommendations.map((item) => `${item.personName} (${item.roleInPod}, ${item.score})`).join('; ') || 'no recommendation recorded';
    const recommendationLabel = role === 'POD Member' ? 'Your proposed assignment' : 'Proposed pod';
    answer = `${matchedRequest.id} is a ${matchedRequest.projectType.name} request for ${matchedRequest.deliverable.name}. Required skills: ${skills}. Status: ${matchedRequest.status}. ${recommendationLabel}: ${pod}.`;
  } else if (/available|capacity|headroom|allocation/.test(query)) {
    const available = [...visiblePeople]
      .sort((a, b) => a.allocationPct - b.allocationPct)
      .slice(0, 4)
      .map((person) => `${person.name} (${person.allocationPct}%)`)
      .join(', ');
    answer = available ? `Most available people in your access scope: ${available}. Skill coverage and recorded availability should still be checked before approval.` : 'No people are available in your current access scope.';
  } else if (/project|deliverable|skill|catalog|taxonomy/.test(query)) {
    answer = `The customer catalog contains ${data.metrics.projectTypes} project types, ${data.metrics.deliverables} deliverables, and ${data.metrics.skills} skills/type-of-work values. Examples include ${data.catalog.projects.slice(0, 4).map((project) => project.name).join(', ')}.`;
  } else if (/recommend|fit|pod/.test(query)) {
    const requestWithFit = visibleRequests.find((item) => item.recommendations.length);
    const scopedRecommendations = requestWithFit
      ? role === 'POD Member'
        ? requestWithFit.recommendations.filter((item) => item.personId === data.demoIdentity.podMemberPersonId)
        : requestWithFit.recommendations
      : [];
    answer = requestWithFit
      ? `${requestWithFit.id} has ${scopedRecommendations.length} workbook recommendation${scopedRecommendations.length === 1 ? '' : 's'} in your access scope: ${scopedRecommendations.map((item) => `${item.personName} as ${item.roleInPod} (${item.score})`).join(', ')}. All remain advisory until human approval.`
      : 'No recommendation is recorded for requests in your current access scope.';
  } else {
    answer = `Your ${role} view contains ${visibleRequests.length} staffing request${visibleRequests.length === 1 ? '' : 's'} backed by customer mapping version ${data.source.version}. Ask about a request, person, capacity, project type, deliverable, or required skill.`;
  }

  return NextResponse.json({ answer, source: 'excel-prototype', role, workbookVersion: data.source.version });
}

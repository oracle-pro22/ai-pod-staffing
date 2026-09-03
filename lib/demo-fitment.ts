import type { StaffingPerson, StaffingRecommendation, StaffingRequest } from '@/types/staffing';

export type FitmentRecommendationSet = {
  recommendations: StaffingRecommendation[];
  isDemo: boolean;
};

/**
 * Produces stable, presentation-only recommendations from the people data that is
 * already visible to the current role. It never writes a recommendation to Oracle.
 */
export function buildDemoRecommendations(
  request: StaffingRequest,
  people: StaffingPerson[],
): StaffingRecommendation[] {
  const requiredNames = new Set(request.requiredSkills.map((skill) => skill.name.trim().toLowerCase()));
  const candidates = people.map((person) => {
    const matchingSkills = person.skills
      .filter((skill) => requiredNames.has(skill.name.trim().toLowerCase()))
      .sort((left, right) => right.strength - left.strength);
    const coverage = requiredNames.size ? matchingSkills.length / requiredNames.size : 0.5;
    const averageStrength = matchingSkills.length
      ? matchingSkills.reduce((total, skill) => total + skill.strength, 0) / matchingSkills.length
      : person.skills.reduce((total, skill) => total + skill.strength, 0) / Math.max(person.skills.length, 1);
    const remainingCapacity = Math.max(0, 100 - person.allocationPct);
    const rankingValue = coverage * 50 + averageStrength * 8 + remainingCapacity * 0.3 - person.activePods * 2;

    return { person, matchingSkills, coverage, averageStrength, remainingCapacity, rankingValue };
  });

  return candidates
    .sort((left, right) => right.rankingValue - left.rankingValue || left.person.name.localeCompare(right.person.name))
    .slice(0, 3)
    .map(({ person, matchingSkills, coverage, averageStrength, remainingCapacity }, index) => {
      const matchedNames = matchingSkills.map((skill) => skill.name);
      const displayedSkills = matchedNames.length
        ? matchedNames
        : person.skills.slice().sort((left, right) => right.strength - left.strength).slice(0, 2).map((skill) => skill.name);
      const score = Math.max(78, Math.min(95, Math.round(88 - index * 4 + coverage * 5)));
      const rationale = matchedNames.length
        ? `Matches ${matchedNames.join(', ')} with recorded evidence and ${remainingCapacity}% remaining capacity.`
        : `Demo alternate based on relevant profile strengths and ${remainingCapacity}% remaining capacity.`;

      return {
        personId: person.id,
        personName: person.name,
        roleInPod: index === 0 ? 'Pod lead' : 'Contributor',
        score,
        rationale,
        decisionStatus: 'Pending review',
        source: 'Simulated demo',
        matchingSkills: displayedSkills,
        factors: [
          { code: 'interest_strength', name: 'Interest strength', weightPct: 35, evidenceScore: Math.round(coverage * 100) },
          { code: 'delivery_history', name: 'Relevant delivery history', weightPct: 25, evidenceScore: Math.round(averageStrength / 5 * 100) },
          { code: 'available_capacity', name: 'Available capacity', weightPct: 25, evidenceScore: remainingCapacity },
          { code: 'growth_preference', name: 'Growth preference', weightPct: 10, evidenceScore: 70 - index * 5 },
          { code: 'team_continuity', name: 'Team continuity', weightPct: 5, evidenceScore: 65 - index * 5 },
        ],
      };
    });
}

export function resolveFitmentRecommendations(
  request: StaffingRequest | null,
  storedRecommendations: StaffingRecommendation[],
  people: StaffingPerson[],
): FitmentRecommendationSet {
  if (!request) return { recommendations: [], isDemo: false };
  if (storedRecommendations.length) return { recommendations: storedRecommendations, isDemo: false };
  return { recommendations: buildDemoRecommendations(request, people), isDemo: true };
}

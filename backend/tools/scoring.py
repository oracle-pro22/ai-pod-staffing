"""Four-factor ranking and hard eligibility checks. No model controls the scores."""
import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from itertools import combinations

from ..repository import json_string

LEAD_RECOMMENDATION_LIMIT = 3
CONTRIBUTOR_RECOMMENDATION_LIMIT = 5


def round_score(value):
    return math.floor(value * 100 + 0.5) / 100


def business_days(start: str, end: str) -> list[str]:
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first.isoformat() != start or last.isoformat() != end or not 0 <= (last - first).days <= 366:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("Choose a valid date range of at most one year.") from None
    days = [(first + timedelta(days=i)) for i in range((last - first).days + 1)]
    result = [d.isoformat() for d in days if d.weekday() < 5]
    if not result:
        raise ValueError("The request must contain at least one working day (Monday–Friday).")
    return result


def weights(db):
    settings = {s["key"]: s["value"] for s in db["settings"]}
    keys = {"skills": "skills_weight", "allocation": "allocation_weight", "future": "future_weight", "interests": "interests_weight", "maxAllocation": "max_allocation_pct"}
    try:
        w = {key: float(settings[value]) for key, value in keys.items()}
        valid = (all(math.isfinite(v) for v in w.values()) and sum(w[k] for k in ("skills", "allocation", "future", "interests")) == 100
                 and w["skills"] > w["allocation"] > w["future"] > w["interests"] > 0 and 1 <= w["maxAllocation"] <= 100)
    except (KeyError, ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError("Weights must total 100%, with Skills > Allocation > Future availability > Interests > 0. Allocation guardrail must be between 1% and 100%.")
    return w


def data_hash(db):
    return hashlib.sha256(json_string([db[k] for k in ("people", "skills", "personSkills", "preferences", "availability", "assignments", "settings", "policies")]).encode()).hexdigest()


def is_conflict(event):
    return bool(re.search("leave|travel|ooo|conflict", event["event_type"], re.I))


def booked_hours(db, person, day):
    assigned = sum(float(a["per_day_hours"]) for a in db["assignments"] if a["person_id"] == person["person_id"] and a["starts_on"] <= day <= a["ends_on"])
    events = sum(float(a["allocated_hours"]) / len(business_days(a["starts_on"], a["ends_on"])) for a in db["availability"]
                 if a["person_id"] == person["person_id"] and a["starts_on"] <= day <= a["ends_on"] and not is_conflict(a))
    return float(person["daily_hours"]) * float(person["allocation_pct"]) / 100 + assigned + events


def score_candidates(db, request, requirements, run_id, w=None):
    w = w or weights(db)
    days = business_days(request["starts_on"], request["needed_by"])
    per_day = float(request["estimated_hours"]) / (int(request["contributor_count"]) + 1) / len(days)
    if not requirements:
        raise ValueError("At least one required skill is needed.")
    if len({p["person_id"] for p in db["people"]}) != len(db["people"]):
        raise ValueError("People contains duplicate person IDs.")
    skills_index = {s["skill_id"]: s for s in db["skills"]}
    if any(r["skill_id"] not in skills_index for r in requirements):
        raise ValueError("A required skill is missing from the master data.")
    candidates = []
    for person in db["people"]:
        daily, allocation = float(person["daily_hours"]), float(person["allocation_pct"])
        if not math.isfinite(daily) or daily <= 0 or not math.isfinite(allocation) or not 0 <= allocation <= 100:
            raise ValueError(f'Invalid capacity data for {person["full_name"]}.')
        evidence = []
        for req in requirements:
            skills = [s for s in db["personSkills"] if s["person_id"] == person["person_id"] and s["skill_id"] == req["skill_id"]]
            interests = [s for s in db["preferences"] if s["person_id"] == person["person_id"] and s["skill_id"] == req["skill_id"]]
            if len(skills) > 1 or len(interests) > 1:
                raise ValueError(f'Duplicate skill or preference for {person["full_name"]}.')
            skill, preference = (skills[0] if skills else {}), (interests[0] if interests else {})
            proficiency, interest = float(skill.get("proficiency") or 0), float(preference.get("interest_level") or 0)
            if not 0 <= proficiency <= 5 or not 0 <= interest <= 5:
                raise ValueError("Skill and interest ratings must be between 0 and 5.")
            evidence.append({"skill_id": req["skill_id"], "skill": skills_index[req["skill_id"]]["skill_name"], "proficiency": proficiency,
                             "minimum": req["min_proficiency"], "interest": interest, "mandatory": req["mandatory"],
                             "evidence": skill.get("evidence") or "No recorded proficiency evidence", "interest_source": preference.get("source") or "No expressed interest recorded"})
        today = datetime.now(timezone.utc).date().isoformat()
        current = booked_hours(db, person, today) / daily * 100
        loads = [booked_hours(db, person, day) for day in days]
        peak = max((h + per_day) / daily * 100 for h in loads)
        conflicts = [a for a in db["availability"] if a["person_id"] == person["person_id"] and is_conflict(a) and any(a["starts_on"] <= d <= a["ends_on"] for d in days)]
        exclusions = [f'{c["event_type"]}: {c["starts_on"]}–{c["ends_on"]}' for c in conflicts]
        if peak > w["maxAllocation"] + 1e-8:
            exclusions.append(f'Projected peak {round_score(peak):g}% exceeds {w["maxAllocation"]:g}% guardrail')
        if not any(e["proficiency"] >= e["minimum"] for e in evidence):
            exclusions.append("No required skill meets its minimum proficiency")
        scores = {
            "skills_score": round_score(sum(e["proficiency"] / 5 * 100 for e in evidence) / len(evidence)),
            "allocation_score": round_score(max(0, 100 - current)),
            "future_score": round_score(sum(max(0, daily - h) for h in loads) / (len(days) * daily) * 100),
            "interests_score": round_score(sum(e["interest"] / 5 * 100 for e in evidence) / len(evidence)),
        }
        total = round_score(sum(scores[k + "_score"] * w[k] for k in ("skills", "allocation", "future", "interests")) / 100)
        candidates.append({"run_id": run_id, "person_id": person["person_id"], "rank": 0, "eligible": not exclusions, "can_lead": person["can_lead"] is True,
                           **scores, "total_score": total, "current_allocation": round_score(current), "peak_allocation": round_score(peak),
                           "per_day_hours": per_day, "evidence_json": json_string(evidence), "exclusions": "; ".join(exclusions), "rationale": "", "recommended_role": ""})
    candidates.sort(key=lambda c: (-c["total_score"], c["person_id"]))
    for rank, candidate in enumerate(candidates, 1):
        candidate["rank"] = rank
    return candidates


def validate_pod(ids, candidates, requirements, count):
    if len(ids) != count or len(set(ids)) != count:
        raise ValueError(f"Select one lead and {count - 1} distinct contributors.")
    index = {c["person_id"]: c for c in candidates}
    selected = []
    for person_id in ids:
        candidate = index.get(person_id)
        if not candidate or not candidate["eligible"]:
            raise ValueError(f"Candidate {person_id} is no longer eligible. Re-run fitment to review current evidence.")
        selected.append(candidate)
    if not selected[0]["can_lead"]:
        raise ValueError("The selected lead is not marked as eligible to lead in People.")
    for req in requirements:
        if req["mandatory"] and not any(e["skill_id"] == req["skill_id"] and e["proficiency"] >= req["min_proficiency"] for c in selected for e in json.loads(c["evidence_json"])):
            raise ValueError("The selected pod does not cover all mandatory skills at the required proficiency.")
    return selected


def recommendation_shortlists(candidates, lead_limit=LEAD_RECOMMENDATION_LIMIT,
                              contributor_limit=CONTRIBUTOR_RECOMMENDATION_LIMIT):
    """Return independently ranked, eligible pools for the two pod roles."""
    ranked = sorted((c for c in candidates if c["eligible"]), key=lambda c: (-c["total_score"], c["person_id"]))
    return {
        "leads": [c for c in ranked if c["can_lead"]][:lead_limit],
        "contributors": ranked[:contributor_limit],
    }


def recommend_shortlisted_pod(candidates, requirements, count):
    """Choose the best skill-complete pod inside the visible role shortlists.

    A lead may also rank in the contributor pool, but the same person cannot fill
    both roles. The pools stay fixed at top 3 leads and top 5 contributors.
    """
    pools = recommendation_shortlists(candidates)
    contributor_count = count - 1
    best = None
    for lead in pools["leads"]:
        options = [c for c in pools["contributors"] if c["person_id"] != lead["person_id"]]
        for contributors in combinations(options, contributor_count):
            selected = [lead, *contributors]
            ids = [c["person_id"] for c in selected]
            try:
                validate_pod(ids, candidates, requirements, count)
            except ValueError:
                continue
            score = sum(c["total_score"] for c in selected)
            tie_break = tuple((c["rank"], c["person_id"]) for c in selected)
            if best is None or score > best[0] or (score == best[0] and tie_break < best[1]):
                best = score, tie_break, ids
    return best[2] if best else []


def recommend_pod(candidates, requirements, count):
    """Exact skill-coverage optimizer, without the old 40-person ceiling.

    For equal coverage/lead capability, at most `count` best people can appear in
    a pod. Dynamic programming then retains the best pod for each count, skill
    mask and lead flag. Rare-skill people remain searchable even at a low rank.
    Scores use integer hundredths to avoid floating-point tie inconsistencies.
    """
    eligible = [c for c in candidates if c["eligible"]]
    if len(eligible) < count or not any(c["can_lead"] for c in eligible):
        return []
    mandatory = [r for r in requirements if r["mandatory"]]
    target = (1 << len(mandatory)) - 1
    options, groups, union = [], {}, 0
    for index, candidate in enumerate(eligible):
        evidence = {e["skill_id"]: e["proficiency"] for e in json.loads(candidate["evidence_json"])}
        mask = sum(1 << i for i, r in enumerate(mandatory) if evidence.get(r["skill_id"], 0) >= r["min_proficiency"])
        union |= mask
        group = (mask, candidate["can_lead"])
        groups[group] = groups.get(group, 0) + 1
        if groups[group] <= count:
            options.append((index, mask, candidate["can_lead"], int(round(candidate["total_score"] * 100))))
    if union != target:
        return []
    states = [dict() for _ in range(count + 1)]
    states[0][(0, False)] = (0, ())
    for index, mask, lead, score in options:
        for size in range(count, 0, -1):
            for (covered, has_lead), (total, ids) in states[size - 1].items():
                key, proposed = (covered | mask, has_lead or lead), (total + score, ids + (index,))
                current = states[size].get(key)
                if current is None or proposed[0] > current[0] or (proposed[0] == current[0] and proposed[1] < current[1]):
                    states[size][key] = proposed
    best = states[count].get((target, True))
    if best is None:
        return []
    selected = [eligible[i] for i in best[1]]
    lead = next(c for c in selected if c["can_lead"])
    ids = [lead["person_id"]] + [c["person_id"] for c in selected if c is not lead]
    validate_pod(ids, candidates, requirements, count)
    return ids


def fitment_gap(candidates, requirements, count, *, shortlisted=False):
    """Deterministic explanation for a failed search, not a model guess."""
    eligible = [c for c in candidates if c["eligible"]]
    considered = eligible
    if shortlisted:
        pools = recommendation_shortlists(candidates)
        considered = list({c["person_id"]: c for c in pools["leads"] + pools["contributors"]}.values())
    evidence = [e for c in considered for e in json.loads(c["evidence_json"])]
    names = {e["skill_id"]: e.get("skill", e["skill_id"]) for c in candidates for e in json.loads(c["evidence_json"])}
    missing = [names.get(r["skill_id"], r["skill_id"]) for r in requirements if r["mandatory"] and not any(e["skill_id"] == r["skill_id"] and e["proficiency"] >= r["min_proficiency"] for e in evidence)]
    reasons = []
    if len(eligible) < count:
        noun = "person" if len(eligible) == 1 else "people"
        reasons.append(f"Only {len(eligible)} eligible {noun} for a {count}-person pod")
    if not any(c["can_lead"] for c in eligible):
        reasons.append("No eligible pod lead")
    if missing:
        reasons.append(("No shortlisted coverage for: " if shortlisted else "No eligible coverage for: ") + ", ".join(missing))
    if not reasons:
        reasons.append((f"Mandatory skills cannot be covered together within a {count}-person pod using the top "
                        f"{LEAD_RECOMMENDATION_LIMIT} lead and top {CONTRIBUTOR_RECOMMENDATION_LIMIT} contributor scores") if shortlisted else
                       f"Mandatory skills cannot be covered together within a {count}-person pod")
    allocation = sum("guardrail" in c["exclusions"] for c in candidates)
    conflicts = sum(bool(re.search(r"leave:|travel:|ooo:|conflict:", c["exclusions"], re.I)) for c in candidates)
    return {"message": ". ".join(reasons) + ".", "eligible": len(eligible), "required_people": count,
            "missing_skills": missing, "allocation_exclusions": allocation, "date_conflicts": conflicts}

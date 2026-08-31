# Persona and Access Matrix

## Approved prototype personas

| Persona | Request scope | People scope | Special dashboard behavior |
|---|---|---|---|
| Operations Lead | All requests | All people | Full operational dashboard |
| Request Lead | All requests in current prototype | All people | Full operational dashboard |
| Pod Lead | Requests where the demo Pod Lead is recommended | Demo Pod Lead plus people referenced by scoped recommendations | Scoped request, fitment, team and availability data |
| POD Member | Requests where the signed-in demo member is recommended | Signed-in member only | Personal fitment preview, My Capacity, no team-wide insights |
| Executive | All requests in current prototype | All people | Full summary dashboard |
| System Administrator | All requests | All people | Full dashboard plus administration |

## Workspace access

Legend: `Full` = available; `Scoped` = available with persona-filtered content; `Locked` = remains visible in navigation but cannot be entered.

| Workspace | Operations Lead | Request Lead | Pod Lead | POD Member | Executive | System Administrator |
|---|---:|---:|---:|---:|---:|---:|
| Command Center | Full | Full | Scoped | Scoped | Full | Full |
| Requests | Full | Full | Scoped | Scoped | Full | Full |
| AI Fitment | Full | Full | Scoped | Scoped | Full | Full |
| Allocation Calendar | Full | Full | Locked | Locked | Full | Full |
| Team & Skills | Full | Full | Scoped | Own profile | Full | Full |
| My Availability | Full | Full | Scoped | Own information | Full | Full |
| Agent Execution | Full | Full | Locked | Locked | Full | Full |
| Reports | Full | Full | Locked | Locked | Full | Full |
| Administration | Full | Full | Locked | Locked | Full | Full |

## Persona-specific control visibility

| Control/section | Pod Lead | POD Member |
|---|---:|---:|
| Locked navigation items remain visible | Yes | Yes |
| New request | Current prototype permits scoped-role logic unless explicitly hidden | Hidden |
| Export requests | Current prototype follows screen scope | Hidden |
| Re-run recommendation | Available within scoped fitment | Hidden |
| Approve pod | Available within scoped fitment | Hidden |
| Team search and directory | Scoped | Hidden; own profile only |
| Upcoming Demand and dashboard audit section | Visible | Hidden |
| Priority staffing queue | Scoped queue | Replaced by My AI fitment preview |
| Capacity Watch | Scoped team capacity | Renamed My Capacity and shows self only |

## Implementation rule

Phase 2 must move these decisions into typed role-policy and selector functions. React components must consume policy results; individual components must not duplicate role-name comparisons.

This remains prototype authorization. Production authentication and server-enforced authorization are outside the parity migration.


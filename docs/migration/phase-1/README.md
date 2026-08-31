# Phase 1 — Migration Baseline and Blueprint

Status: **Complete**  
Captured: **2026-08-24**  
Application source: `C:\Users\smaikoti\Desktop\ai-pod-staffing`  
Pre-migration backup: `C:\Users\smaikoti\Desktop\ai-pod-staffing-html-backup`

## Purpose

This folder freezes the approved HTML prototype before it is rebuilt as React/TSX components. It is the acceptance reference for Phases 2–5. Phase 1 makes no application-runtime changes.

## Source-of-truth order

1. `public/prototype.html` — approved markup, visible copy, active CSS, layout and responsive rules.
2. `public/prototype-app.js` — current behavior, persona scoping, calculations, forms and interactions.
3. `lib/staffing-data.ts` — workbook reader, integrity checks and server-side view model.
4. `data/ai-pod-staffing-prototype.xlsx` — current prototype data source.
5. `app/api/staffing/route.ts` and `app/api/chat/route.ts` — current API boundaries.

The older CSS in `app/globals.css` is not the visual source of truth. The inactive `legacyPrototypeScript` inside `prototype.html` must not be migrated.

## Phase 1 artifacts

- [Screen and interaction inventory](screen-inventory.md)
- [Persona and access matrix](persona-access-matrix.md)
- [Component and route blueprint](component-blueprint.md)
- [Workbook and API data contract](data-contract.md)
- [Visual source and style tokens](visual-source.md)
- [Parity acceptance checklist](parity-checklist.md)
- `screenshots/` — 39 approved-state desktop, persona, overlay and mobile captures.

## Baseline coverage

- All nine workspaces were captured for Operations Lead.
- All four Administration tabs were captured.
- Command Center was captured for all six personas.
- All accessible scoped workspaces were captured for Pod Lead and POD Member.
- Request details, create request, human approval, quick allocation, person details, availability, notifications and Ask AI Pod overlays were captured.
- Mobile Command Center, Requests, navigation, create-request drawer and POD Member dashboard were captured at 390 × 844.

## Migration rule

No visible wording, icon path, color, spacing, dimension, persona rule or interaction may be changed merely because the implementation moves to React. Any intentional product change must be handled separately from migration parity.


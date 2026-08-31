# Visual Source and Style Tokens

## Approved visual source

The active `<style>` block in `public/prototype.html` is the migration reference. It must be extracted without reinterpretation before it is separated into component styles.

## Core tokens

| Token | Approved value |
|---|---|
| Background | `#f7f6f2` |
| Surface | `#ffffff` |
| Soft surface | `#fbfaf7` |
| Primary ink | `#161513` |
| Secondary ink | `#56514b` |
| Tertiary ink | `#77716b` |
| Border | `#ddd8d1` |
| Soft border | `#ebe7e1` |
| Oracle red | `#c74634` |
| Dark red | `#9f2d20` |
| Red surface | `#f9e9e5` |
| Teal | `#2b6f6d` |
| Teal surface | `#e5f1ef` |
| Blue | `#315d84` |
| Blue surface | `#e8f0f7` |
| Amber | `#8d5b00` |
| Amber surface | `#fff2d6` |
| Green | `#2f6b3f` |
| Green surface | `#e7f3e8` |
| Purple | `#66508c` |
| Purple surface | `#eee9f7` |
| Danger | `#b3261e` |
| Card radius | `14px` |
| Sidebar width | `252px` |
| Topbar height | `68px` |
| Card shadow | `0 1px 2px rgba(22,21,19,.06), 0 8px 24px rgba(22,21,19,.05)` |

## Typography

Preserve this exact stack during parity work:

```css
Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif
```

Do not introduce `next/font` during parity because a different font file or metric can alter line wrapping and dimensions.

## Responsive breakpoints

- `1100px`: multi-column content collapses; search hides; candidate reason grid reduces.
- `760px`: off-canvas sidebar, mobile menu, single-column cards/forms, reduced table columns and mobile chat/button positioning.

## Icon rule

The inline SVG path definitions in `prototype-app.js` are the approved navigation icons. Create a typed React `Icon` component using the same paths. Do not replace them with Lucide icons during parity work.

## Screenshot conventions

- Desktop screen captures: viewport `1440 × 900`.
- Overlay screenshots: viewport capture at `1440 × 900`.
- Mobile captures: viewport `390 × 844`.
- Screenshots are stored under `screenshots/` and must not be overwritten after Phase 2 begins; new comparison images should be stored separately.

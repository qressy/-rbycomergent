# Chattersift Color System

This document defines the Chattersift color system.

- The Django Tailwind and DaisyUI theme source lives in `chattersift/static/src/project.css`.
- The compiled stylesheet served by Django lives in `chattersift/static/css/project.css`.

## Prefixes By Surface

| Surface | Tailwind utilities | DaisyUI components |
|---------|--------------------|--------------------|
| Extension | `bg-primary`, `text-base-content` | `btn`, `alert`, `badge` |
| Django templates | `bg-primary`, `text-base-content` | `btn`, `alert`, `badge` |

## Semantic Colors

| Token | Tailwind utility example | Use for |
|-------|--------------------------|---------|
| `primary` | `bg-primary` | Main CTAs, links, active states |
| `secondary` | `bg-secondary` | Secondary actions |
| `accent` | `bg-accent` | Highlights, emphasis |
| `neutral` | `bg-neutral` | Dark surfaces, sidebars |
| `info` | `bg-info` | Informational messaging |
| `success` | `bg-success` | Positive states |
| `warning` | `bg-warning` | Caution states |
| `error` | `bg-error` | Errors, destructive states |

## Base Colors

| Token | Tailwind utility example | Use for |
|-------|--------------------------|---------|
| `base-100` | `bg-base-100` | Main background |
| `base-200` | `bg-base-200` | Secondary background |
| `base-300` | `bg-base-300` | Borders, tertiary surfaces |
| `base-content` | `text-base-content` | Primary text |

## Django Examples

```html
<section class="bg-base-100 text-base-content">
  <div class="card border border-base-300">
    <div class="card-body">
      <h2 class="card-title">Warmup status</h2>
      <p class="text-base-content/70">Mailbox health is improving.</p>
      <div class="flex gap-3">
        <button class="btn btn-primary">Continue</button>
        <button class="btn btn-ghost">Later</button>
      </div>
    </div>
  </div>
</section>
```

## Density & Sizing

The global scale is intentionally large — 37signals-style. `html { font-size: 18px }` bumps every rem in the system, and `.btn` / `.input` / `.select` / `.textarea` / `.card-body` carry explicit min-heights, font sizes, and padding to match. This is the **default** scale: landing, settings, auth, and prose pages all render at it.

Dense surfaces (the dashboard, future inspector panels, anything table-shaped) opt out via a single wrapper class on a parent element. Density flows down through CSS custom properties; you do not need to add `-xs` to every child.

### Density tokens

Defined at `:root` in `chattersift/static/src/project.css`. Default values reproduce the 37signals scale.

| Token | Default | `.density-compact` | Drives |
|-------|---------|--------------------|--------|
| `--ctrl-h` | `3rem` | `1.75rem` | Min-height of `.btn`, height of `.input`/`.select` |
| `--ctrl-fs` | `1.0625rem` | `0.8125rem` | Font-size of `.btn`/`.input`/`.select`/`.textarea` |
| `--ctrl-px` | `1.25rem` | `0.625rem` | Horizontal padding inside `.btn` |
| `--surface-fs` | `1.0625rem` | `0.9375rem` | Body text inside the surface |
| `--card-pad` | `2rem` | `1rem` | Padding of `.card-body` |

Custom hand-rolled controls (chips, popovers, inline toolbars) should read from the same tokens so they track whichever density they're rendered inside.

### The `.density-compact` wrapper

Putting `density-compact` on a parent re-points every token above to its compact value for that subtree. The dashboard shell at `chattersift/templates/dash_base.html` carries it on `<main id="dash-content">`, which is why everything under `/dash/` renders tight without per-template `-xs` discipline.

```html
<main id="dash-content" class="density-compact …">
  {# every monitor section inherits compact density #}
</main>
```

Use it on any region that needs to read as dense — a sidebar, a settings sub-table, an inspector panel. Outside such regions, leave the default scale alone.

### DaisyUI size modifiers as escape hatches

The bare overrides on `.btn` / `.input` / `.select` / `.textarea` are written with `:not(.btn-xs):not(.btn-sm):not(.btn-lg)` guards, so explicit DaisyUI size modifiers always win the cascade. Two consequences:

- Inside a `.density-compact` zone you can still write `btn-lg` for a deliberately loud CTA — it stays large.
- Outside a density zone you can still drop a one-off `btn-xs` for a compact control without inheriting the rest of the dense look.

Reach for `density-compact` when an entire region should be tight. Reach for `-xs` / `-sm` / `-lg` modifiers when one specific control needs to differ from its neighbours.

## Color Values Reference

| Name | OKLCH value | Approximate hex |
|------|-------------|-----------------|
| `base-100` | `oklch(100% 0 0)` | `#FFFFFF` |
| `base-200` | `oklch(97% 0.005 260)` | `#F9FAFB` |
| `base-300` | `oklch(93% 0.01 260)` | `#F3F4F6` |
| `base-content` | `oklch(25% 0.02 260)` | `#1F2937` |
| `primary` | `oklch(55% 0.22 250)` | `#3B82F6` |
| `secondary` | `oklch(55% 0.02 260)` | `#6B7280` |
| `accent` | `oklch(68% 0.16 55)` | `#C87830` |
| `neutral` | `oklch(35% 0.02 260)` | `#374151` |
| `info` | `oklch(62% 0.06 250)` | `#6B8DB5` |
| `success` | `oklch(70% 0.18 145)` | `#22C55E` |
| `warning` | `oklch(82% 0.18 85)` | `#EAB308` |
| `error` | `oklch(60% 0.22 25)` | `#EF4444` |

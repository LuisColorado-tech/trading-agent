---
name: page-design
description: Use ONLY when designing or updating HTML/CSS pages, landing pages, dashboards, or pricing tables for Agents Corp business units. Use for any UI/UX work: colors, typography, layout, responsive design, dark theme.
---

# Page Design Skill — Agents Corp

## Design System

### Colors (Dark Theme — Standard across all Agents Corp products)
```css
Background: #0d1117 (GitHub dark)
Text:       #c9d1d9
Headers:    #58a6ff (blue)
Accent:     #1f6feb (blue border)
Success:    #238636 / #3fb950 (green)
Warning:    #d29922 (gold)
Danger:     #f85149 (red)
Card bg:    #161b22
Border:     #30363d
Muted:      #8b949e
```

### Typography
```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif
Headers: 2em / 1.5em / 1.2em
Body: 1em
Code: 0.85em monospace
Muted/small: 0.85em with color #8b949e
```

### Component Patterns

**Cards:**
```css
.card { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:20px; margin:10px }
```

**Tables:**
```css
table { width:100%; border-collapse:collapse }
th,td { padding:8px 12px; text-align:left; border-bottom:1px solid #30363d }
th { color:#58a6ff }
```

**Buttons:**
```css
.btn { display:inline-block; background:#238636; color:white; padding:10px 25px; border-radius:6px; text-decoration:none; font-weight:bold; margin:5px }
.btn-outline { background:transparent; border:1px solid #58a6ff; color:#58a6ff }
.btn-gold { background:transparent; border:1px solid #d29922; color:#d29922 }
```

**Status tags:**
```css
.up { color:#3fb950 } .down { color:#f85149 }
```

**Responsive:**
```css
max-width: 800-1000px; margin: 0 auto; padding: 20px
Mobile: single column, stack cards vertically
```

### Pricing Table Pattern
Use flexbox: `.plans { display:flex; gap:15px; flex-wrap:wrap }`
Each plan: `.plan { flex:1; min-width:200px }`
Highlight recommended: `.plan.featured { border-color:#58a6ff; border-width:2px }`

### Page Template
```html
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Page Title</title>
<style>/* dark theme styles */</style></head><body>
<!-- content -->
</body></html>
```

### Self-Updating Dashboard Pattern
For real-time health dashboards: `<meta http-equiv="refresh" content="30">`

### Rules
1. ALWAYS dark theme (#0d1117 background)
2. NEVER use external CSS frameworks (no Bootstrap, Tailwind CDN)
3. All CSS inline in `<style>` tag — pages must work offline
4. Spanish-first content, English labels for tech terms
5. Mobile-responsive with flexbox, not media queries
6. Keep pages under 5KB (no images, no fonts, no JS frameworks)

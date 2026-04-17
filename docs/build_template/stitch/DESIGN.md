# Design System Document: The Executive Atelier

## 1. Overview & Creative North Star: "The Digital Curator"

This design system moves away from the rigid, sterile grids of traditional corporate software. Our Creative North Star is **"The Digital Curator."** We aim to transform a board meeting application into a high-end editorial experience that feels less like a database and more like a private digital lounge. 

The system achieves a "High-End Editorial" feel through **intentional asymmetry, expansive breathing room, and sophisticated layering.** We break the "template" look by treating the interface as a curated canvas where content is prioritized through tonal shifts rather than structural confinement. By overlapping elements—such as board member avatars slightly breaking the bounds of their containers—we create a sense of depth and life that feels premium and intentional.

---

## 2. Colors: Tonal Depth over Structural Lines

The color strategy is rooted in "Atmospheric Professionalism." We use a high-chroma `primary` blue for tactical actions, balanced by an expansive palette of sophisticated neutrals.

### The "No-Line" Rule
Designers are prohibited from using 1px solid borders to section off the UI. Boundaries must be defined solely through **background color shifts**. Use `surface_container_low` for a section background sitting atop a `surface` base. This creates a soft, architectural distinction that feels more modern than a "boxed-in" grid.

### Surface Hierarchy & Nesting
Treat the UI as a series of physical layers, similar to stacked sheets of fine paper or frosted glass.
*   **Base Layer:** `background` or `surface`.
*   **Sectional Layer:** `surface_container_low`.
*   **Content Layer (Cards):** `surface_container_lowest` (pure white).
*   **Active/Elevated Layer:** `surface_bright`.

### The "Glass & Gradient" Rule
To elevate the experience, floating menus and modal overlays must utilize **Glassmorphism**. Use `surface` or `surface_container` at 80% opacity with a `backdrop-blur` of 12px–20px. 
For main CTAs or high-level summary headers, use a subtle linear gradient from `primary` (#003d9b) to `primary_container` (#0052cc). This adds "soul" and a tactile, liquid quality to the most important actions.

---

## 3. Typography: Editorial Authority

We use a dual-font strategy to balance character with absolute legibility.

*   **Headlines (Manrope):** The use of Manrope for `display` and `headline` scales provides a contemporary, geometric structural feel. It signals authority and modernism.
*   **Body & Utility (Inter):** Inter is used for `title`, `body`, and `label` scales. Its high x-height and neutrality ensure that even complex board minutes or financial data remain effortless to read.

**Typography as Identity:** 
High contrast in scale is encouraged. Pair a `display-sm` headline with a `body-md` description to create an editorial layout that guides the eye. Avoid "middle-ground" sizing; go big or stay functional.

---

## 4. Elevation & Depth: Tonal Layering

Traditional shadows are often "muddy." In this system, depth is achieved through light and tone.

*   **The Layering Principle:** Instead of shadows, place a `surface_container_lowest` card inside a `surface_container_low` container. This creates a "natural lift" via contrast.
*   **Ambient Shadows:** For floating elements (like an active avatar or a dropdown), use an extra-diffused shadow: `box-shadow: 0 12px 32px rgba(25, 28, 29, 0.06)`. The shadow color is a tinted version of `on_surface`, mimicking natural light.
*   **The "Ghost Border" Fallback:** If a border is required for accessibility, use the `outline_variant` token at **15% opacity**. Never use 100% opaque borders.
*   **The Avatar Pop:** For the cartoon-style board member avatars, apply a `surface_tint` glow (8% opacity) on hover to make them feel "activated" within the space.

---

## 5. Components

### Buttons
*   **Primary:** Gradient of `primary` to `primary_container`. `xl` roundedness (1.5rem). Use `headline-sm` for text to give buttons a bold, confident presence.
*   **Secondary:** `surface_container_high` background with `on_surface` text. No border.
*   **Tertiary:** Transparent background, `primary` text. Use for low-emphasis actions like "Cancel" or "View Less."

### The Board Member Avatar (Signature Component)
*   **Style:** Circular (`full` roundedness) with a 2px `surface_container_lowest` gap between the image and a subtle `outline_variant` ring.
*   **States:** On hover, the avatar should scale by 1.1x and gain an ambient shadow. On click/active, add a 3px ring of `primary`.

### Cards & Lists
*   **Rule:** Forbid the use of divider lines. 
*   **Execution:** Separate list items using `body-md` spacing (0.875rem) and subtle background toggles between `surface_container_low` and `surface_container_lowest`. 
*   **Interactive Cards:** Use `lg` roundedness (1rem). Ensure content has at least 24px of internal padding to maintain the "Editorial" feel.

### Input Fields
*   **Style:** Minimalist. Use `surface_container_low` as the background with a `none` border. On focus, transition the background to `surface_container_lowest` and add a `primary` 2px bottom-indicator (not a full border).

---

## 6. Do's and Don'ts

### Do:
*   **Embrace Negative Space:** If a screen feels "empty," it’s likely working. Use space to separate high-level agenda items.
*   **Use Subtle Status Colors:** Use `secondary` (soft green) for "Quorum Met" and `tertiary` (amber) for "Pending Approval" using the `fixed_dim` variants to ensure they don't clash with the primary blue.
*   **Asymmetric Layouts:** Place a primary action button offset from the main grid to break the "standard software" look.

### Don't:
*   **Don't use Dark Grays for Text:** Always use `on_surface` or `on_surface_variant` to maintain the soft, professional tone. Avoid #000000.
*   **Don't Over-Round:** Stick to `lg` (1rem) for cards. Going too round (like `xl` or `full` on squares) makes the app feel "bubbly" rather than "executive."
*   **No Heavy Borders:** If you see a hard line, delete it and use a background color shift instead.
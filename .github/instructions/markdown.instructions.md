---
applyTo: "**/*.md"
description: Formatting conventions for generated Markdown so it renders well in the Clearance macOS app
---

- Use YAML frontmatter when document metadata is useful; omit it when there's nothing meaningful to put
  there — don't add empty frontmatter.
- Build a stable heading hierarchy so Clearance's outline and anchor navigation work well.
- Prefer GFM tables, task lists, and strikethrough where they improve readability over prose.
- Use relative links and local image paths so documents remain portable.
- Use fenced `mermaid` or `dot`/`graphviz` blocks for diagrams; only add a diagram when it clarifies
  something prose doesn't.
- Use `\( ... \)` for inline math and `$$ ... $$` for display math.
- Add language identifiers to fenced code blocks for syntax highlighting.
- Only emit features that benefit the document — no decorative structure for its own sake.

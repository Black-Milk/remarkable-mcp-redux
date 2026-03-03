---
name: remarkable-diagram
description: Converts hand-drawn reMarkable diagrams into Excalidraw drawings. Uses MCP tools to render .rm files to PDF, interprets the diagram structure, then recreates it as an interactive Excalidraw view and optionally saves as .excalidraw.md.
---

# reMarkable Diagram to Excalidraw Conversion

## When This Skill Activates

Claude uses this skill when:
- The user asks to convert a reMarkable diagram or drawing to Excalidraw
- The user wants to digitize a hand-drawn architecture diagram, flowchart, or sketch
- The user mentions a reMarkable page that contains shapes, boxes, or flow diagrams
- The user asks to "make that drawing editable" or "turn my sketch into a diagram"

## Prerequisites

Same as remarkable-transcribe:
- **reMarkable desktop app** synced locally
- **remarkable MCP server** registered in `.mcp.json`
- **cairo** system library via Homebrew

Additionally:
- **Excalidraw MCP tool** (create_view) for live preview rendering
- **Obsidian Excalidraw plugin** installed (if saving to an Obsidian vault)

## How It Works

### Pipeline
```
reMarkable cloud → Desktop app sync → Local .rm files (v6)
    → remarkable MCP tools (rmc → SVG → cairosvg → PDF)
    → Claude reads PDF → Interprets diagram structure
    → Excalidraw create_view (live preview)
    → Save as .excalidraw.md
```

## Step-by-Step Process

### 1. Check Status and Find the Document

Verify system is ready, then find the document:
```
remarkable_check_status()
remarkable_list_documents(search="diagram name")
remarkable_get_document_info(doc_id="<uuid>")
```

### 2. Render to PDF

Render the diagram page(s):
```
remarkable_render_pages(doc_id="<uuid>", page_indices=[0])
```
Or for multi-page diagrams:
```
remarkable_render_pages(doc_id="<uuid>", first_n=3)
```

### 3. Read and Interpret the Diagram

Read the PDF and identify:
- **Shapes**: rectangles, circles, diamonds, freeform boxes
- **Text labels**: inside shapes or standalone
- **Connections**: arrows, lines between shapes
- **Groupings**: visual clusters, containment relationships
- **Annotations**: callout text, notes outside the main diagram
- **Layout**: hierarchical (tree), flow (left-to-right), cycle, matrix, etc.

### 3. Create Live Excalidraw Preview

Use the `create_view` MCP tool to render the diagram with proper Excalidraw elements.

**Mapping rules from hand-drawn to Excalidraw:**

| Hand-drawn | Excalidraw element | Style |
|---|---|---|
| Rectangle/box | `rectangle` with `roundness: { type: 3 }` | Light fill color based on role |
| Circle/oval | `ellipse` | Light fill |
| Diamond | `diamond` | Light fill |
| Arrow/line between shapes | `arrow` with bindings | strokeWidth 2 |
| Text inside shape | `label` on the shape | fontSize 18-22 |
| Standalone text/title | `text` element | fontSize 20-28 |
| Annotation/callout | `ellipse` or `rectangle` with light yellow fill | fontSize 16 |
| Crossed-out item | Omit or render with strikethrough note | — |

**Color assignment by role:**
- Primary/main nodes → Light Blue `#a5d8ff`
- Success/output → Light Green `#b2f2bb`
- Warning/external → Light Orange `#ffd8a8`
- Special/processing → Light Purple `#d0bfff`
- Error/critical → Light Red `#ffc9c9`
- Notes/annotations → Light Yellow `#fff3bf`
- People/entities → Light Pink `#eebefa`
- Data/storage → Light Teal `#c3fae8`

### Avoiding Common Bugs

#### No duplicate text
The `create_view` MCP tool uses a `label` shorthand on shapes — this is ONLY for the preview tool. When saving the `.excalidraw.md` file, you must choose ONE text approach per shape:
- **Option A (preferred for saving):** Shape with NO label/boundElements + NO separate text element. Let the Excalidraw plugin handle text from the `## Text Elements` section alone.
- **Option B:** Use `label` in `create_view` for preview, then in the saved JSON omit both `boundElements` on the shape and separate `text` elements with `containerId`. Instead, just list the text in `## Text Elements`.

**NEVER** create a shape with `boundElements` pointing to a text element AND also list that same text in `## Text Elements` with a separate text element in the JSON. This causes double rendering.

#### Preventing element overlap — spacing rules
- **Minimum 40px vertical gap** between distinct sections (chart area → cards → notes)
- **Minimum 25px horizontal gap** between side-by-side cards/boxes
- **Labels outside shapes** (like axis labels) must be at least 15px away from any shape edge
- **Text elements must not share y-coordinates** with shape edges — offset by at least 10px
- Before finalizing, mentally walk through the layout checking for any element whose bounding box intersects another's

#### Text Elements section format
The `## Text Elements` section lists text for search/indexing. Rules:
- List each piece of text EXACTLY once
- Format: `[text content] ^[element_id]`
- For multi-line text, put each line on its own line before the `^id`
- Do NOT list text that only exists as a `label` shorthand in create_view — only list text that has a corresponding element in the saved JSON

### 4. Save as .excalidraw.md

After creating the live preview, save the diagram as an `.excalidraw.md` file.

**File format — simplified (let plugin handle text indexing):**

Write ONLY the Drawing section. The Excalidraw plugin auto-generates `## Text Elements` when it first opens and compresses the file. This avoids duplication bugs from manually maintaining text entries.

```markdown
---
excalidraw-plugin: parsed
tags: [excalidraw, remarkable]
source: remarkable/[Document Name]
---

==⚠  Switch to EXCALIDRAW VIEW in the MORE OPTIONS menu of this document. ⚠== You can decompress Drawing data with the command palette: 'Decompress current Excalidraw file'. For more info check in plugin settings under 'Saving'

# Excalidraw Data

## Text Elements

%%
## Drawing
\`\`\`json
{
  "type": "excalidraw",
  "version": 2,
  "source": "remarkable-tool",
  "elements": [
    ... Excalidraw element JSON array ...
  ],
  "appState": {
    "gridSize": null,
    "viewBackgroundColor": "#ffffff"
  },
  "files": {}
}
\`\`\`
%%
```

**Critical:** Leave `## Text Elements` empty. The plugin populates it on first load.

**In the JSON elements array**, use these text patterns:
- **Text inside a shape:** Use the `label` property directly on the shape element
- **Standalone text:** Use a `text` element
- **NEVER** use both `boundElements`/`containerId` bindings AND `label` — pick one approach

Save to the location the user specifies. Always ask if not obvious.

## Interpretation Guidelines

### Layout Detection
- **Tree/hierarchy**: Boxes connected vertically with branching → use top-down layout
- **Flow**: Boxes connected left-to-right → use horizontal layout
- **Cycle**: Boxes in a ring with arrows → use circular layout
- **Org chart**: Person names in boxes with reporting lines → use hierarchy
- **Mind map**: Central node with radiating branches → use radial layout
- **Freeform**: Mixed shapes, no clear pattern → preserve relative positions

### Text Interpretation
- Read all handwritten text in shapes and labels
- Preserve abbreviations unless clearly a spelling shorthand
- Crossed-out text should be omitted from the diagram
- If text is ambiguous, include best guess with a comment

### Connection Interpretation
- Solid lines → solid arrows/lines in Excalidraw
- Dashed lines → strokeStyle "dashed"
- Lines with arrowheads → endArrowhead "arrow"
- Lines without arrowheads → endArrowhead null
- Bidirectional → both startArrowhead and endArrowhead

### 6. Clean Up

After saving, remove temporary rendered PDFs:
```
remarkable_cleanup_renders()
```

## Important Notes

- Always show the user the live preview first before saving
- Ask the user to confirm the interpretation is correct before saving
- Complex diagrams may need iteration — save a draft and refine
- The Excalidraw MCP tool uses a specific element format — refer to the read_me output for exact JSON structure
- Keep diagrams clean and readable — don't try to perfectly replicate messy hand-drawn aesthetics
- Empty pages (no .rm file) are skipped and listed in `pages_failed`

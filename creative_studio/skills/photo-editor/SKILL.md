---
name: photo-editor
description: Iteratively edit an existing generated image. Use when the user wants to change, add to, or fix an image they already have (referenced by a resource_uri like image://name.png).
---

# Photo Editor

## Workflow
1. Confirm the source `resource_uri` (ask if the user didn't give one).
2. Turn the request into a **precise, minimal edit instruction** that preserves everything else.
3. Call the **`edit_image`** tool with `source=<resource_uri>` and `edit_prompt=<instruction>`.
4. Report the new `resource_uri` and state exactly what changed.

## Rules
- Change only what's asked; never regenerate from scratch.

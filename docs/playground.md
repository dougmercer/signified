---
hide:
  - navigation
  - toc
---
# Playground

Try Signified in your browser. Pick an example, edit it, and press **Run**
(or `Ctrl+Enter`, `Cmd+Enter` on macOS). The page downloads Python and
Signified when it opens, so **Run** takes a few seconds to become available.

<div class="signified-playground" data-signified-playground data-state="loading">
  <div class="signified-playground-toolbar">
    <label for="signified-playground-example" class="signified-playground-label">Example</label>
    <select id="signified-playground-example" data-playground-example></select>
    <span class="signified-playground-status" data-playground-status aria-live="polite">Loading Python…</span>
    <button type="button" data-playground-reset title="Undo your edits to this example">Reset</button>
    <button type="button" data-playground-share title="Copy a link to this code">Copy link</button>
    <button type="button" class="signified-playground-run" data-playground-run disabled>Run</button>
  </div>
  <div class="signified-playground-editor">
    <textarea data-playground-code aria-label="Code" spellcheck="false"></textarea>
  </div>
  <div class="signified-playground-output" data-playground-output role="log" aria-label="Output"></div>
</div>

<textarea hidden data-playground-example="calculations" data-title="Signals and calculations">
--8<-- "docs/playground/calculations.py"
</textarea>

<textarea hidden data-playground-example="computed" data-title="@computed functions">
--8<-- "docs/playground/computed.py"
</textarea>

<textarea hidden data-playground-example="effects" data-title="Effects">
--8<-- "docs/playground/effects.py"
</textarea>

<textarea hidden data-playground-example="batch" data-title="Batching writes">
--8<-- "docs/playground/batch.py"
</textarea>

<textarea hidden data-playground-example="binding" data-title="Switching sources with Binding">
--8<-- "docs/playground/binding.py"
</textarea>

<textarea hidden data-playground-example="lists" data-title="Lists and update()">
--8<-- "docs/playground/lists.py"
</textarea>

<textarea hidden data-playground-example="where" data-title="Choosing values with rx.where">
--8<-- "docs/playground/where.py"
</textarea>

<textarea hidden data-playground-example="method_chaining" data-title="Method chaining">
--8<-- "docs/playground/method_chaining.py"
</textarea>

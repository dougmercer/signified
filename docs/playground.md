---
hide:
  - navigation
---
# Playground

Run Python snippets directly in your browser with a Web Worker powered by Pyodide.

!!! note
    This page downloads Pyodide at runtime and attempts to install `signified` with `micropip`.

Use the example dropdown to load snippets, then press `Ctrl+Enter` (or `Cmd+Enter` on macOS) to run.

<div class="signified-playground" data-signified-playground>
  <label for="signified-playground-code" class="signified-playground-label-code">Code</label>
  <label class="signified-playground-label-output">Output</label>
  <div class="signified-playground-editor">
    <textarea id="signified-playground-code" data-playground-code spellcheck="false">from signified import Signal

x = Signal(2)
double = 2 * x

print("double:", double.value)
x.value = 5
print("double:", double.value)
</textarea>
  </div>
  <div class="signified-playground-output" data-playground-output aria-live="polite"></div>
  <div class="signified-playground-controls">
    <button type="button" class="md-button md-button--primary" data-playground-run disabled>Run</button>
    <button type="button" class="md-button" data-playground-reset>Reset</button>
    <button type="button" class="md-button" data-playground-clear>Clear</button>
    <span class="signified-playground-status" data-playground-status aria-live="polite">Loading interpreter...</span>
  </div>
  <div class="signified-playground-examples">
    <label for="signified-playground-example">Example</label>
    <select id="signified-playground-example" data-playground-example>
      <option value="basic">Basic Signal</option>
      <option value="decorator">Computed Decorator</option>
      <option value="collections">Collections and Mutation</option>
      <option value="where">Conditional where()</option>
      <option value="method-chain">Method Chaining</option>
    </select>
  </div>
</div>

<style>
.signified-playground {
  --playground-pane-height: 16rem;
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: auto var(--playground-pane-height) auto;
  grid-template-areas:
    "label-code  label-output"
    "editor      output"
    "controls    examples";
  column-gap: 0.75rem;
  row-gap: 0.5rem;
  margin-top: 1rem;
}

.signified-playground-label-code   { grid-area: label-code; }
.signified-playground-label-output { grid-area: label-output; }
.signified-playground-editor       { grid-area: editor; overflow: hidden; align-self: stretch; min-height: 0; }
.signified-playground-output       { grid-area: output; align-self: stretch; min-height: 0; }
.signified-playground-controls     { grid-area: controls; align-self: center; }
.signified-playground-examples     { grid-area: examples; align-self: center; }

.signified-playground-editor textarea {
  width: 100%;
  height: 100%;
  padding: 0.75rem;
  border: 1px solid var(--md-default-fg-color--lightest);
  border-radius: 0.4rem;
  box-sizing: border-box;
  font-family: var(--md-code-font-family);
  font-size: 0.75rem;
  line-height: 1.4;
  color: var(--md-code-fg-color);
  background: var(--md-code-bg-color);
  overflow-y: auto;
}

.signified-playground .CodeMirror {
  height: 100%;
  border: 1px solid var(--md-default-fg-color--lightest);
  border-radius: 0.4rem;
  box-sizing: border-box;
  font-family: var(--md-code-font-family);
  font-size: 0.75rem;
  line-height: 1.4;
}

.signified-playground-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.signified-playground-status {
  font-size: 0.75rem;
  color: var(--md-default-fg-color--light);
}

.signified-playground-status.error {
  color: var(--md-accent-fg-color);
}

.signified-playground-examples {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 0.25rem;
}

.signified-playground-examples label {
  white-space: nowrap;
}

.signified-playground-examples select {
  flex: 1 1 auto;
  width: auto;
  padding: 0.4rem 0.5rem;
  border: 1px solid var(--md-default-fg-color--lightest);
  border-radius: 0.4rem;
  font-size: 0.75rem;
  color: var(--md-default-fg-color);
  background: var(--md-default-bg-color);
}

.signified-playground-output {
  height: 100%;
  margin: 0;
  padding: 0.75rem;
  border: 1px solid var(--md-default-fg-color--lightest);
  border-radius: 0.4rem;
  box-sizing: border-box;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  overflow-y: auto;
  font-family: var(--md-code-font-family);
  font-size: 0.75rem;
  line-height: 1.4;
  color: var(--md-code-fg-color);
  background: var(--md-code-bg-color);
}

@media (max-width: 600px) {
  .signified-playground {
    grid-template-columns: 1fr;
    grid-template-rows: auto var(--playground-pane-height) auto auto var(--playground-pane-height) auto;
    grid-template-areas:
      "label-code"
      "editor"
      "controls"
      "label-output"
      "output"
      "examples";
  }
}
</style>

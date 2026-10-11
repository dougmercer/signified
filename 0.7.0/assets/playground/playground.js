(function () {
  if (window.__signifiedPlaygroundBootstrapped) {
    return;
  }
  window.__signifiedPlaygroundBootstrapped = true;

  // This script is docs/assets/playground/playground.js, so the site root is two levels up.
  const scriptUrl = document.currentScript.src;
  const siteUrl = new URL("../../", scriptUrl);
  const workerUrl = new URL("worker.js", scriptUrl);
  const CODEMIRROR_URL = "https://cdn.jsdelivr.net/npm/codemirror@5.65.16";
  // Stop replaces Run only when code runs this long, so quick runs don't flash it.
  const STOP_DELAY_MS = 250;
  // Past this much output, stop adding more so a runaway print loop can't freeze the page.
  const OUTPUT_LIMIT = 200000;
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform);

  const workers = new Set();
  const cleanups = [];
  // Bumped on every page change, so a setup still waiting on the network can tell it is stale.
  let generation = 0;

  // mike publishes each docs version in its own folder, with versions.json one
  // level up. Released docs install their own version from PyPI. The dev docs
  // are built from main, which may not match any release, so they get a notice.
  // Without versions.json (as under `mkdocs serve`), install the newest release.
  const DEV_VERSION = "dev";
  const findRequirement = async () => {
    const folder = siteUrl.pathname.split("/").filter(Boolean).pop();
    try {
      const response = await fetch(new URL("../versions.json", siteUrl));
      if (response.ok) {
        const versions = await response.json();
        const entry = versions.find(
          (item) => item.version === folder || (item.aliases || []).includes(folder),
        );
        if (entry) {
          return entry.version === DEV_VERSION ? null : `signified==${entry.version}`;
        }
      }
    } catch (error) {
      // Fall through to the newest release.
    }
    return "signified";
  };

  const showDevNotice = (root) => {
    const latestUrl = new URL("../latest/playground/", siteUrl);
    const notice = document.createElement("div");
    notice.className = "admonition info";
    notice.innerHTML = `
      <p class="admonition-title">The Playground runs released versions only</p>
      <p>It installs Signified from PyPI, so it is turned off in the development
      docs. <a href="${latestUrl}">Open the Playground for the latest release</a>.</p>`;
    root.hidden = true;
    root.before(notice);
    cleanups.push(() => {
      notice.remove();
      root.hidden = false;
    });
  };

  // CodeMirror is only needed here, so it loads with the Playground rather
  // than on every docs page. Without it, the plain textarea still works.
  let codeMirror = null;
  const loadScript = (src) =>
    new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.onload = resolve;
      script.onerror = reject;
      document.head.append(script);
    });
  const loadCodeMirror = () => {
    if (!codeMirror) {
      const stylesheet = document.createElement("link");
      stylesheet.rel = "stylesheet";
      stylesheet.href = `${CODEMIRROR_URL}/lib/codemirror.min.css`;
      document.head.append(stylesheet);
      codeMirror = loadScript(`${CODEMIRROR_URL}/lib/codemirror.min.js`)
        .then(() => loadScript(`${CODEMIRROR_URL}/mode/python/python.min.js`))
        .then(() => window.CodeMirror)
        .catch(() => null);
    }
    return codeMirror;
  };

  // The examples live in docs/playground/*.py and are included in the page as
  // hidden <textarea> elements, in the order they appear in the menu. Not
  // <script> elements: Material's instant navigation re-runs every <script> in
  // the new page as JavaScript.
  const readExamples = () =>
    Array.from(document.querySelectorAll("textarea[data-playground-example]"), (textarea) => ({
      name: textarea.dataset.playgroundExample,
      title: textarea.dataset.title,
      code: textarea.value.trim(),
    }));

  const toBase64Url = (text) => {
    let binary = "";
    for (const byte of new TextEncoder().encode(text)) {
      binary += String.fromCharCode(byte);
    }
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  };

  const fromBase64Url = (value) => {
    const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/"));
    return new TextDecoder().decode(Uint8Array.from(binary, (char) => char.charCodeAt(0)));
  };

  // A link names an unedited example (#example=effects) or carries the code (#code=...).
  const codeFromLink = (examples) => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const example = examples.find((item) => item.name === params.get("example"));
    if (example) {
      return example;
    }
    if (params.has("code")) {
      try {
        return { name: "shared", title: "Code from a link", code: fromBase64Url(params.get("code")) };
      } catch (error) {
        // Ignore a damaged link and show the first example.
      }
    }
    return null;
  };

  const initPlayground = async (token) => {
    const root = document.querySelector("[data-signified-playground]");
    if (!root || root.dataset.initialized === "true") {
      return;
    }
    root.dataset.initialized = "true";
    const isCurrent = () => token === generation && root.isConnected;

    const codeElement = root.querySelector("[data-playground-code]");
    const exampleSelect = root.querySelector("[data-playground-example]");
    const statusElement = root.querySelector("[data-playground-status]");
    const resetButton = root.querySelector("[data-playground-reset]");
    const shareButton = root.querySelector("[data-playground-share]");
    const runButton = root.querySelector("[data-playground-run]");
    const outputElement = root.querySelector("[data-playground-output]");

    const examples = readExamples();
    const linked = codeFromLink(examples);
    if (linked && !examples.includes(linked)) {
      examples.unshift(linked);
    }
    exampleSelect.replaceChildren(...examples.map((item) => new Option(item.title, item.name)));
    let current = linked || examples[0];
    exampleSelect.value = current.name;
    codeElement.value = current.code;

    const requirement = await findRequirement();
    if (!isCurrent()) {
      return;
    }
    if (requirement === null) {
      showDevNotice(root);
      return;
    }

    // State: loading, ready, running, or failed. CSS uses it for the signal line.
    let state = "loading";
    let environment = "";
    let worker = null;
    let stopTimer = null;
    let outputLength = 0;
    let pending = [];
    let frame = null;

    const setState = (next, status) => {
      state = next;
      root.dataset.state = next;
      statusElement.textContent = status;
      runButton.disabled = next !== "ready" && next !== "running";
    };

    const setRunLabel = (stopping) => {
      runButton.textContent = stopping ? "Stop" : "Run";
      runButton.dataset.action = stopping ? "stop" : "run";
      runButton.title = stopping ? "Stop the code and restart Python" : `Run (${isMac ? "Cmd" : "Ctrl"}+Enter)`;
    };

    // Output arrives a line at a time, so it is added once per frame.
    const flushOutput = () => {
      frame = null;
      for (const { text, stream } of pending) {
        const last = outputElement.lastElementChild;
        if (last && last.dataset.stream === stream) {
          last.textContent += text;
        } else {
          const span = document.createElement("span");
          span.dataset.stream = stream;
          span.textContent = text;
          outputElement.append(span);
        }
      }
      pending = [];
      outputElement.scrollTop = outputElement.scrollHeight;
    };

    const appendOutput = (text, stream) => {
      if (!text || outputLength > OUTPUT_LIMIT) {
        return;
      }
      outputLength += text.length;
      pending.push({ text: `${text}\n`, stream });
      if (outputLength > OUTPUT_LIMIT) {
        pending.push({ text: "Output stopped here because the code printed too much.\n", stream: "notice" });
      }
      if (frame === null) {
        frame = requestAnimationFrame(flushOutput);
      }
    };

    const clearOutput = (placeholder) => {
      pending = [];
      outputLength = 0;
      outputElement.replaceChildren();
      outputElement.dataset.placeholder = placeholder;
    };

    const finishRun = () => {
      clearTimeout(stopTimer);
      setRunLabel(false);
    };

    const handleMessage = (data) => {
      if (data.type === "status") {
        const what = requirement === "signified" ? "Signified" : requirement;
        setState("loading", data.phase === "python" ? "Loading Python…" : `Installing ${what}…`);
      } else if (data.type === "ready") {
        environment = `Signified ${data.signified} on Python ${data.python}`;
        setState("ready", environment);
      } else if (data.type === "failed") {
        if (data.phase === "python") {
          setState("failed", "Couldn't load Python");
          appendOutput(`Python didn't load: ${data.error}`, "stderr");
          appendOutput("Check your connection, then reload the page.", "notice");
        } else {
          setState("failed", "Couldn't install Signified");
          appendOutput(`Installing ${requirement} failed: ${data.error}`, "stderr");
          appendOutput("A new release can take a few minutes to reach PyPI. Reload the page to try again.", "notice");
        }
      } else if (data.type === "output") {
        appendOutput(data.text, data.stream);
      } else if (data.type === "done") {
        finishRun();
        appendOutput(data.result, "stdout");
        appendOutput(data.error, "stderr");
        setState("ready", environment);
      }
    };

    const startWorker = () => {
      const next = new Worker(workerUrl, { type: "module" });
      worker = next;
      workers.add(next);
      next.addEventListener("message", (event) => {
        if (worker === next) {
          handleMessage(event.data || {});
        }
      });
      next.addEventListener("error", (event) => {
        if (worker === next) {
          handleMessage({ type: "failed", phase: "python", error: event.message || "the worker stopped." });
        }
      });
      next.postMessage({ type: "init", requirement });
    };

    const run = () => {
      if (state !== "ready") {
        return;
      }
      clearOutput("The code ran without printing anything.");
      setState("running", "Running…");
      stopTimer = setTimeout(() => setRunLabel(true), STOP_DELAY_MS);
      worker.postMessage({ type: "run", code: getCode() });
    };

    // Python can't be interrupted here, so stopping means starting a new interpreter.
    const stop = () => {
      worker.terminate();
      workers.delete(worker);
      finishRun();
      appendOutput("Stopped.", "notice");
      setState("loading", "Restarting Python…");
      startWorker();
    };

    let editor = null;
    const getCode = () => (editor ? editor.getValue() : codeElement.value);
    const setCode = (value) => {
      if (editor) {
        editor.setValue(value);
        editor.focus();
      } else {
        codeElement.value = value;
      }
    };

    runButton.addEventListener("click", () => {
      if (runButton.dataset.action === "stop") {
        stop();
      } else {
        run();
      }
    });

    resetButton.addEventListener("click", () => setCode(current.code));

    exampleSelect.addEventListener("change", () => {
      current = examples.find((item) => item.name === exampleSelect.value) || current;
      setCode(current.code);
      clearOutput("Output appears here when you run the code.");
    });

    let shareTimer = null;
    shareButton.addEventListener("click", async () => {
      const code = getCode();
      const example = examples.find((item) => item.name !== "shared" && item.code === code);
      const url = new URL(window.location.href);
      url.hash = example ? `example=${example.name}` : `code=${toBase64Url(code)}`;
      window.history.replaceState(window.history.state, "", url);
      try {
        await navigator.clipboard.writeText(url.href);
        shareButton.textContent = "Link copied";
      } catch (error) {
        shareButton.textContent = "Link is in the address bar";
      }
      clearTimeout(shareTimer);
      shareTimer = setTimeout(() => {
        shareButton.textContent = "Copy link";
      }, 2000);
    });

    codeElement.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        run();
      }
    });

    setState("loading", "Loading Python…");
    setRunLabel(false);
    clearOutput("Output appears here when you run the code.");
    startWorker();

    const CodeMirror = await loadCodeMirror();
    if (!CodeMirror || !isCurrent()) {
      return;
    }
    editor = CodeMirror.fromTextArea(codeElement, {
      mode: "python",
      theme: "signified",
      lineNumbers: true,
      indentUnit: 4,
      tabSize: 4,
      screenReaderLabel: "Code",
      extraKeys: {
        // Indent with spaces: a tab mixed with spaces is an error in Python.
        Tab: (cm) =>
          cm.somethingSelected() ? cm.indentSelection("add") : cm.execCommand("insertSoftTab"),
        "Shift-Tab": "indentLess",
        "Ctrl-Enter": run,
        "Cmd-Enter": run,
      },
    });
    editor.setSize(null, "100%");
    cleanups.push(() => editor.toTextArea());
  };

  const onPageReady = () => {
    for (const worker of workers) {
      worker.terminate();
    }
    workers.clear();
    for (const cleanup of cleanups) {
      cleanup();
    }
    cleanups.length = 0;
    for (const root of document.querySelectorAll("[data-signified-playground]")) {
      root.dataset.initialized = "false";
    }
    generation += 1;
    initPlayground(generation);
  };

  // Material's instant navigation swaps pages without reloading, and announces each one on document$.
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(onPageReady);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", onPageReady, { once: true });
  } else {
    onPageReady();
  }
})();

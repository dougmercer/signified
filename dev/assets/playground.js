(function () {
  if (window.__signifiedPlaygroundBootstrapped) {
    return;
  }
  window.__signifiedPlaygroundBootstrapped = true;

  const scriptTag = Array.from(document.scripts).find((script) =>
    script.src.includes("assets/playground.js"),
  );
  const workerUrl = scriptTag
    ? new URL("signified-playground-worker.js", scriptTag.src).toString()
    : "assets/signified-playground-worker.js";
  const workers = new Set();
  const cleanups = [];
  const examples = {
    basic: `from signified import Signal

x = Signal(2)
double = 2 * x

print("double:", double.value)
x.value = 5
print("double:", double.value)`,
    decorator: `from signified import Signal, computed

values = Signal([1, 2, 3, 4])

@computed
def stats(nums):
    return {
        "sum": sum(nums),
        "mean": sum(nums) / len(nums),
    }

summary = stats(values)
print(summary.value)

values.value = [10, 20, 30]
print(summary.value)`,
    collections: `from signified import Signal

items = Signal({"theme": "dark", "count": 2})
theme = items["theme"]
count = items["count"]

print("theme:", theme.value)
print("count:", count.value)

items["theme"] = "light"
items["count"] = 9
print("theme:", theme.value)
print("count:", count.value)`,
    where: `from signified import Signal, computed

username = Signal(None)
is_logged_in = username.is_not(None)

@computed
def welcome(name):
    return f"Welcome back, {name}!"

message = is_logged_in.where(welcome(username), "Please log in")
print(message.value)

username.value = "admin"
print(message.value)`,
    "method-chain": `from signified import Signal

text = Signal("  Hello, World!  ")
processed = text.strip().lower().replace(",", "")

print(processed.value)
text.value = "  Goodbye, World!  "
print(processed.value)`,
  };

  const appendOutput = (outputElement, text) => {
    if (!text) {
      return;
    }
    if (outputElement.textContent) {
      outputElement.textContent += "\n";
    }
    outputElement.textContent += text;
    outputElement.scrollTop = outputElement.scrollHeight;
  };

  const updateStatus = (statusElement, text, isError) => {
    statusElement.textContent = text;
    statusElement.classList.toggle("error", Boolean(isError));
  };

  const cleanupWorkers = () => {
    for (const worker of workers) {
      worker.terminate();
    }
    workers.clear();
  };

  const cleanupPlaygroundState = () => {
    cleanupWorkers();
    for (const cleanup of cleanups) {
      cleanup();
    }
    cleanups.length = 0;
  };

  const currentColorScheme = () =>
    document.body?.getAttribute("data-md-color-scheme") ||
    document.documentElement?.getAttribute("data-md-color-scheme") ||
    "default";

  const currentEditorTheme = () =>
    currentColorScheme() === "slate" ? "material-darker" : "default";

  const initPlayground = () => {
    const root = document.querySelector("[data-signified-playground]");
    if (!root || root.dataset.initialized === "true") {
      return;
    }

    const codeElement = root.querySelector("[data-playground-code]");
    const runButton = root.querySelector("[data-playground-run]");
    const resetButton = root.querySelector("[data-playground-reset]");
    const clearButton = root.querySelector("[data-playground-clear]");
    const outputElement = root.querySelector("[data-playground-output]");
    const statusElement = root.querySelector("[data-playground-status]");
    const exampleSelect = root.querySelector("[data-playground-example]");

    if (
      !codeElement ||
      !runButton ||
      !resetButton ||
      !clearButton ||
      !outputElement ||
      !statusElement
    ) {
      return;
    }

    root.dataset.initialized = "true";
    runButton.disabled = true;

    let defaultCode = codeElement.value.trimEnd();
    let isReady = false;
    let editor = null;

    if (window.CodeMirror) {
      editor = window.CodeMirror.fromTextArea(codeElement, {
        mode: "python",
        lineNumbers: true,
        lineWrapping: false,
        indentUnit: 4,
        tabSize: 4,
        theme: currentEditorTheme(),
      });
      editor.setSize(null, "100%");

      const syncEditorTheme = () => {
        editor.setOption("theme", currentEditorTheme());
      };
      const observer = new MutationObserver(syncEditorTheme);
      if (document.body) {
        observer.observe(document.body, {
          attributes: true,
          attributeFilter: ["data-md-color-scheme"],
        });
      }
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-md-color-scheme"],
      });
      cleanups.push(() => {
        observer.disconnect();
        editor.toTextArea();
      });
    }

    const getCode = () => (editor ? editor.getValue() : codeElement.value);
    const setCode = (value) => {
      if (editor) {
        editor.setValue(value);
        editor.focus();
      } else {
        codeElement.value = value;
      }
    };

    const worker = new Worker(workerUrl);
    workers.add(worker);

    worker.addEventListener("message", (event) => {
      const data = event.data || {};

      if (data.type === "ready") {
        isReady = true;
        runButton.disabled = false;

        if (data.installation === "available") {
          updateStatus(statusElement, "Ready", false);
          return;
        }

        updateStatus(
          statusElement,
          "Ready (signified install failed, see output)",
          true,
        );
        appendOutput(
          outputElement,
          "[startup] signified could not be installed in this browser runtime.",
        );
        if (data.installationMessage) {
          appendOutput(outputElement, `[startup] ${data.installationMessage}`);
        }
        return;
      }

      if (data.type === "result") {
        if (data.stdout) {
          appendOutput(outputElement, data.stdout);
        }
        if (data.stderr) {
          appendOutput(outputElement, data.stderr);
        }
        if (data.result) {
          appendOutput(outputElement, data.result);
        }
        updateStatus(statusElement, "Ready", false);
        return;
      }

      if (data.type === "error") {
        if (data.stdout) {
          appendOutput(outputElement, data.stdout);
        }
        if (data.stderr) {
          appendOutput(outputElement, data.stderr);
        }
        appendOutput(outputElement, data.error || "Execution failed.");
        updateStatus(statusElement, "Execution error", true);
      }
    });

    worker.addEventListener("error", (event) => {
      appendOutput(outputElement, event.message || "Worker error.");
      updateStatus(statusElement, "Worker error", true);
    });

    runButton.addEventListener("click", () => {
      if (!isReady) return;
      updateStatus(statusElement, "Running...", false);
      worker.postMessage({ type: "run", code: getCode() });
    });

    resetButton.addEventListener("click", () => {
      setCode(defaultCode);
    });

    clearButton.addEventListener("click", () => {
      outputElement.textContent = "";
      updateStatus(statusElement, isReady ? "Ready" : "Loading interpreter...", false);
    });

    if (exampleSelect) {
      const loadExample = () => {
        const snippet = examples[exampleSelect.value];
        if (!snippet) {
          return;
        }
        defaultCode = snippet.trimEnd();
        setCode(defaultCode);
        outputElement.textContent = "";
        updateStatus(statusElement, isReady ? "Ready" : "Loading interpreter...", false);
      };
      exampleSelect.addEventListener("change", loadExample);
    }

    const runCode = () => runButton.click();
    if (editor) {
      editor.addKeyMap({
        "Ctrl-Enter": runCode,
        "Cmd-Enter": runCode,
      });
    } else {
      codeElement.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
          event.preventDefault();
          runCode();
        }
      });
    }

    worker.postMessage({ type: "init" });
  };

  const onPageReady = () => {
    cleanupPlaygroundState();
    for (const root of document.querySelectorAll("[data-signified-playground]")) {
      root.dataset.initialized = "false";
    }
    initPlayground();
  };

  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(onPageReady);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", onPageReady, { once: true });
  } else {
    onPageReady();
  }

  window.addEventListener("beforeunload", cleanupPlaygroundState);
})();

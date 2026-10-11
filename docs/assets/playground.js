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

price = Signal(10)
quantity = Signal(2)
total = price * quantity

print("total:", total.value)
quantity.value = 3
print("total:", total.value)`,
    decorator: `from signified import Signal, computed

@computed
def stats(numbers):
    return {"sum": sum(numbers), "mean": sum(numbers) / len(numbers)}

numbers = Signal([1, 2, 3, 4])
summary = stats(numbers)
print(summary.value)

numbers.value = [10, 20, 30]
print(summary.value)`,
    effect: `from signified import Signal, effect

@effect
def show(total):
    print(f"Total: \${total:.2f}")

price = Signal(10)
quantity = Signal(2)
watcher = show(price * quantity)  # runs right away

quantity.value = 3
price.value = 12.5

watcher.dispose()
price.value = 99  # no output after dispose`,
    batch: `from signified import Effect, Signal, batch

price = Signal(10)
quantity = Signal(2)
watcher = Effect(lambda: print("total:", price.value * quantity.value))

print("Without batch:")
price.value = 12
quantity.value = 3

print("With batch:")
with batch():
    price.value = 15
    quantity.value = 4
# The effect runs once, after the block.

watcher.dispose()`,
    binding: `from signified import Binding, Signal

frame = Signal(0)
x = Binding(0)    # a plain number for now
label_x = x + 10  # a label that sits to the right of the shape

x.value = 5
print("label_x:", label_x.value)

x.value = frame * 2  # now follow an animation
for f in [10, 20, 30]:
    frame.value = f
    print("label_x:", label_x.value)`,
    collections: `from signified import Signal, computed

numbers = Signal([1, 2, 3])
total = computed(sum)(numbers)
print("total:", total.value)

numbers[0] = 10  # item assignment sends an update
print("total:", total.value)

numbers.value.append(4)  # changing the raw list does not
print("total:", total.value)
numbers.update()  # so tell Signified about it
print("total:", total.value)`,
    where: `from signified import Signal, computed

@computed
def welcome(name):
    return f"Welcome back, {name}!"

username = Signal(None)
message = username.rx.is_not(None).rx.where(welcome(username), "Please log in")
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

// Pyodide 314+ only loads in module workers, so this is the .mjs build.
const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs";
// Tracebacks name the user's code with this, and show its source lines.
const FILENAME = "playground.py";

let pyodide = null;

const send = (message) => self.postMessage(message);

const errorText = (error) => (error && error.message ? error.message : String(error));

// Keep only the frames from the user's code. Pyodide's and Signified's own
// frames bury the line that caused the error.
const trimTraceback = (message) => {
  let keep = true;
  return message
    .split("\n")
    .filter((line) => {
      if (line.startsWith('  File "')) {
        keep = line.startsWith(`  File "${FILENAME}"`);
      } else if (!line.startsWith("    ")) {
        keep = true;
      }
      return keep;
    })
    .join("\n");
};

// micropip fails with a long traceback, but its exception message says what went wrong.
const exceptionMessage = (message) => {
  const match = message.match(/^\w+(?:Error|Exception): (.*)$/m);
  return match ? match[1] : message;
};

const formatResult = (value) => {
  if (value === undefined || value === null) {
    return "";
  }
  try {
    return value.toString();
  } catch (error) {
    return String(error);
  }
};

async function loadPython() {
  send({ type: "status", phase: "python" });
  const { loadPyodide } = await import(PYODIDE_URL);
  pyodide = await loadPyodide();
  // Output is sent line by line, so it shows up while the code runs.
  pyodide.setStdout({ batched: (text) => send({ type: "output", stream: "stdout", text }) });
  pyodide.setStderr({ batched: (text) => send({ type: "output", stream: "stderr", text }) });
}

async function install(requirement) {
  send({ type: "status", phase: "install" });
  await pyodide.loadPackage("micropip", { messageCallback: () => {} });
  await pyodide.pyimport("micropip").install(requirement);
  return {
    signified: pyodide.runPython('from importlib.metadata import version; version("signified")'),
    python: pyodide.runPython('import sys; f"{sys.version_info.major}.{sys.version_info.minor}"'),
  };
}

async function run(code) {
  // Each run gets a fresh namespace, so nothing carries over from the last one.
  const globals = pyodide.toPy({ __name__: "__main__" });
  try {
    const result = await pyodide.runPythonAsync(code, { globals, filename: FILENAME });
    send({ type: "done", result: formatResult(result) });
    if (result && typeof result.destroy === "function") {
      result.destroy();
    }
  } catch (error) {
    send({ type: "done", error: trimTraceback(errorText(error)) });
  } finally {
    globals.destroy();
  }
}

self.onmessage = async (event) => {
  const message = event.data || {};

  if (message.type === "init") {
    try {
      await loadPython();
    } catch (error) {
      send({ type: "failed", phase: "python", error: errorText(error) });
      return;
    }
    try {
      send({ type: "ready", ...(await install(message.requirement)) });
    } catch (error) {
      send({ type: "failed", phase: "install", error: exceptionMessage(errorText(error)) });
    }
    return;
  }

  if (message.type === "run") {
    await run(message.code || "");
  }
};

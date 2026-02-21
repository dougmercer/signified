const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/pyodide.js";

let pyodide = null;
let loadPromise = null;
let stdoutBuffer = [];
let stderrBuffer = [];
let installation = "pending";
let installationMessage = "";

const clearBuffers = () => {
  stdoutBuffer = [];
  stderrBuffer = [];
};

const joinBuffer = (buffer) => buffer.filter(Boolean).join("\n");

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

async function ensurePyodide() {
  if (pyodide) {
    return;
  }

  if (!loadPromise) {
    loadPromise = (async () => {
      importScripts(PYODIDE_URL);
      pyodide = await loadPyodide();

      pyodide.setStdout({
        batched(message) {
          stdoutBuffer.push(message);
        },
      });
      pyodide.setStderr({
        batched(message) {
          stderrBuffer.push(message);
        },
      });

      try {
        await pyodide.loadPackage("micropip");
        await pyodide.runPythonAsync(`
import micropip
await micropip.install("signified")
import signified
`);
        installation = "available";
      } catch (error) {
        installation = "failed";
        installationMessage = error && error.message ? error.message : String(error);
      }
    })();
  }

  await loadPromise;
}

self.onmessage = async (event) => {
  const message = event.data || {};

  if (message.type === "init") {
    try {
      await ensurePyodide();
      self.postMessage({
        type: "ready",
        installation,
        installationMessage,
      });
    } catch (error) {
      self.postMessage({
        type: "error",
        error: error && error.message ? error.message : String(error),
      });
    }
    return;
  }

  if (message.type !== "run") {
    return;
  }

  try {
    await ensurePyodide();
    clearBuffers();

    const result = await pyodide.runPythonAsync(message.code || "");
    const renderedResult = formatResult(result);

    if (result && typeof result.destroy === "function") {
      result.destroy();
    }

    self.postMessage({
      type: "result",
      stdout: joinBuffer(stdoutBuffer),
      stderr: joinBuffer(stderrBuffer),
      result: renderedResult,
    });
  } catch (error) {
    self.postMessage({
      type: "error",
      stdout: joinBuffer(stdoutBuffer),
      stderr: joinBuffer(stderrBuffer),
      error: error && error.message ? error.message : String(error),
    });
  }
};

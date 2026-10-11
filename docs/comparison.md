---
hide:
  - navigation
---

# Library comparison

Signified works much like the *signals* in many JavaScript frameworks: a
calculation follows the values it reads, recalculates only when needed, and
effects handle actions. This page shows how it lines up with other libraries,
so you can tell what carries over when moving code or ideas between them.

## Python libraries

In each row, `x` starts at `1` and `doubled` calculates twice its value.
Imports are omitted.

| Library | Create | Read / write | Calculate |
| --- | --- | --- | --- |
| Signified | `x = Signal(1)` | `x.value` / `x.value = 2` | `doubled = x * 2` |
| [reaktiv][reaktiv-computed] | `x = signal(1)` | `x()` / `x.set(2)` | `doubled = computed(lambda: x() * 2)` |
| [Param][param-expressions] | `x = rx(1)` | `x.rx.value` / `x.rx.value = 2` | `doubled = x * 2` |

**reaktiv** is the closest match. Like Signified, it follows the values a
function reads, caches results until an input changes, and runs effects
immediately. It reads by calling `x()` instead of using operators, compares
every value with `is`, prints effect errors instead of raising them, and offers
async helpers and locking for graphs shared across threads.

**Param** builds reactive expressions differently: `rx` records the operations
you apply and the values you pass in, rather than following reads inside a
function. Its watchers subscribe to named parameters. If you already use Param
parameters, its expressions connect directly to that model.

## JavaScript libraries

| Library | Create / read | Write | Calculate |
|---|---|---|---|
| [Angular][angular-signals] | `const x = signal(1)` / `x()` | `x.set(v)` | `computed(() => x() * 2)` |
| [Vue][vue-core] | `const x = ref(1)` / `x.value` | `x.value = v` | `computed(() => x.value * 2)` |
| [Svelte 5][svelte-derived] | `let x = $state(1)` / `x` | `x = v` | `let y = $derived(x * 2)` |
| [Preact Signals][preact-guide] | `const x = signal(1)` / `x.value` | `x.value = v` | `computed(() => x.value * 2)` |
| [Solid][solid-signal] | `const [x, setX] = createSignal(1)` / `x()` | `setX(v)` | `createMemo(() => x() * 2)` |
| [MobX][mobx-observable] | `const x = observable.box(1)` / `x.get()` | `runInAction(() => x.set(v))` | `computed(() => x.get() * 2)` |

All of these follow the values a calculation reads, as Signified does. The
frameworks also schedule effects around rendering, which standalone Python code
does not need.

## Calculations

| Library | Calculation runs | Counts as unchanged | Custom equality | Tracks changes inside objects |
|---|---|---|:---:|---|
| Signified | When read | Same built-in scalar value, otherwise same object | ✓ | No* |
| reaktiv | When read | Same object (`is`) | ✓ | No |
| Param `rx` | When read* | Inputs only, by parameter comparison | — | No |
| Angular | When read | `Object.is` | ✓ | No |
| Vue | When read | `Object.is` | ✗ | Yes (`shallowRef` opts out) |
| Svelte 5 | When read | `===` | ✗ | Yes (`$state.raw` opts out) |
| Preact | When read | `===` | ✗ | No |
| Solid | On creation and on each change | `===` | ✓ | No ([`createStore`][solid-store] opts in) |
| MobX | When read; cached only while observed | `Object.is` | ✓ | Yes (`observable.ref` opts out) |

- **Signified:** `signal[key] = value` and `signal.attr = value` notify, but
  changes made through `.value` need [`update()`](usage.md#collections-and-item-assignment).
- **Param:** building or inspecting an `rx` pipeline can run some steps early.
  Param does not compare results, so an unchanged result still notifies.

"Counts as unchanged" decides whether anything downstream updates. In every
library above except Param, a calculation that recalculates to an unchanged
result stops the update there.

## Effects

"Immediately" means before the write that triggered it returns, or when the
surrounding batch ends.

| Library | Effect | First run | Later runs | Group writes with | Stops when |
|---|---|---|---|---|---|
| Signified | `Effect` | Immediately | Immediately | `batch()` | You call `dispose()` or drop the reference |
| reaktiv | [`effect`][reaktiv-effect] | Immediately | Immediately | `batch()` | You call `dispose()` or drop the reference |
| Param | [watchers][param-watchers] | After the first change | Immediately | `batch_call_watchers` | You call `unwatch` |
| Angular | [`effect`][angular-effect-api] | During change detection* | During change detection* | Framework | Its owner is destroyed |
| Vue | [`watchEffect`][vue-watchers] | Immediately | Before the DOM updates | Framework | Its component unmounts |
| Svelte 5 | [`$effect`][svelte-effect] | After the DOM updates | After the DOM updates | Framework | Its component is destroyed |
| Preact | [`effect`][preact-guide] | Immediately | Immediately | `batch()` | You call the returned function |
| Solid | [`createEffect`][solid-effect] | After rendering | Immediately | `batch()` | Its owner is disposed |
| MobX | [`autorun`][mobx-reactions] | Immediately | Immediately | Actions | You call the returned function |

- **Angular:** effects created outside a component run as a microtask instead.
- Vue's `watch`, MobX's `reaction`, and Param's watchers wait for a change
  before their first run. Several frameworks offer options to change timing.

## Where Signified differs

- **Equality.** Built-in scalars such as `int`, `float`, and `str` compare by
  value; everything else compares by identity, and Signified never calls an
  object's `__eq__` unless you pass [`equal=`](usage.md#custom-equality).
  reaktiv uses `is` everywhere, and the JavaScript libraries use `===` or
  `Object.is`.
- **Nested reactive values stay as they are.** A signal holding another signal
  returns that signal, not its value. Read it with `unref`, `deep_unref`, or a
  `Binding`. Vue, by contrast, unwraps refs inside reactive objects for you.
- **`Binding`.** A binding is one stable handle whose source you can swap.
  Angular's [`linkedSignal`][angular-linked], Svelte's writable
  [`$derived`][svelte-derived], and Vue and MobX computed setters solve
  related problems, but each writes or overrides values rather than switching
  sources.
- **Operators.** Like Param, Python operators build calculations, so
  `price * quantity` is already reactive.
- **Errors.** A failed calculation saves its exception and raises it on each
  read until an input changes. When effects fail, the rest still run and the
  errors are raised together. reaktiv and MobX log effect errors instead, and
  Vue, Svelte, and Solid send them to framework error handlers.
- **Synchronous, one thread at a time.** Reads are tracked only while a
  function runs, never across `await`. Separate graphs can run on separate
  threads, but each graph is used from one thread at a time.

If you need every event in order, rather than the latest value, an event-stream
library such as [ReactiveX for Python][rxpy] is a better fit. Signals can skip
intermediate values that nothing read.

Other libraries' behavior was checked against their documentation and source on
September 19, 2026, using their default options.

[angular-signals]: https://angular.dev/guide/signals
[angular-linked]: https://angular.dev/guide/signals/linked-signal
[angular-effect-api]: https://angular.dev/api/core/effect
[vue-core]: https://vuejs.org/api/reactivity-core
[vue-watchers]: https://vuejs.org/guide/essentials/watchers
[svelte-derived]: https://svelte.dev/docs/svelte/$derived
[svelte-effect]: https://svelte.dev/docs/svelte/$effect
[preact-guide]: https://preactjs.com/guide/v10/signals/
[solid-signal]: https://docs.solidjs.com/reference/basic-reactivity/create-signal
[solid-effect]: https://docs.solidjs.com/reference/basic-reactivity/create-effect
[solid-store]: https://docs.solidjs.com/reference/store-utilities/create-store
[mobx-observable]: https://mobx.js.org/observable-state.html
[mobx-reactions]: https://mobx.js.org/reactions.html
[reaktiv-computed]: https://reaktiv.readthedocs.io/en/latest/api/compute-signal/
[reaktiv-effect]: https://reaktiv.readthedocs.io/en/latest/api/effect/
[param-expressions]: https://param.holoviz.org/en/docs/latest/user_guide/Reactive_Expressions.html
[param-watchers]: https://param.holoviz.org/en/docs/latest/user_guide/Dependencies_and_Watchers.html
[rxpy]: https://rxpy.readthedocs.io/en/latest/get_started.html

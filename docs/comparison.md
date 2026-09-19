---
hide:
  - navigation
---

# Library comparison

This page compares both the syntax and underlying assumptions/logic of several
other reactive programming libraries.

Signified's core model—tracked reads, cached derivations, and effects—has close
relatives in established reactive libraries. The differences that affect program
behavior are dependency discovery, evaluation timing, equality, mutation, and
effect scheduling. A similar API name does not imply the same contract.

## Python libraries

In each row, `x` starts at `1` and `doubled` calculates twice its value.
Imports are omitted.

| Library | Create | Read / write | Calculate |
| --- | --- | --- | --- |
| Signified | `x = Signal(1)` | `x.value` / `x.value = 2` | `doubled = x * 2` |
| [reaktiv](https://reaktiv.readthedocs.io/en/latest/) | `x = signal(1)` | `x()` / `x.set(2)` | `doubled = computed(lambda: x() * 2)` |
| [Param](https://param.holoviz.org/en/docs/latest/user_guide/Reactive_Expressions.html) | `x = rx(1)` | `x.rx.value` / `x.rx.value = 2` | `doubled = x * 2` |

Signified and reaktiv track the reactive values read during a calculation.
Param's reactive expressions record operations and their inputs. If you are
already using Param parameters, its expressions and bound functions connect
to that model.

## How to read the tables

This page compares the Python libraries **signified**, **reaktiv**, and **Param**
with **Angular signals**, **Vue 3 reactivity**, **Svelte 5 runes**, **Preact Signals
core**, **Solid**, and **MobX**. The JavaScript libraries provide useful semantic
reference points; their component runtimes add lifecycle and scheduling rules
that standalone Python code does not have. Svelte's legacy `$:` statements and
store API, and framework adapters around Preact Signals, are outside this scope.
Sources were checked on September 19, 2026; implementation observations below
link to specific revisions, including Param 2.4.2.

Each section defines its cases once, then maps APIs to those cases. **✓** means
the stated behavior applies, **✗** means it does not, **—** means the question is
inapplicable, and **?** means the sources used here do not establish the answer.
An asterisk points to a qualification immediately below the table. Matching
cells mean matching behavior on that dimension, not identical implementations.
Unless stated otherwise, comparisons use default options, successful synchronous
computations, and live owners in client-side framework code.

## API orientation

These are abbreviated idioms, with imports and component setup omitted. In each
row, `x` is the source and the final column derives twice its value.

| Library | Create / read | Write | Derive |
|---|---|---|---|
| [signified](compute-contract.md) (Python) | `x = Signal(1)` / `x.value` | `x.value = v` | `x * 2` or `Computed(lambda: x.value * 2)` |
| [reaktiv][reaktiv-computed] (Python) | `x = signal(1)` / `x()` | `x.set(v)` | `computed(lambda: x() * 2)` |
| [Param][param-expressions] (Python) | `x = rx(1)` / `x.rx.value` | `x.rx.value = v` | `x * 2` |
| [Angular][angular-signals] | `const x = signal(1)` / `x()` | `x.set(v)` | `computed(() => x() * 2)` |
| [Vue][vue-core] | `const x = ref(1)` / `x.value` | `x.value = v` | `computed(() => x.value * 2)` |
| [Svelte 5][svelte-derived] | `let x = $state(1)` / `x` | `x = v` | `let y = $derived(x * 2)` |
| [Preact Signals core][preact-guide] | `const x = signal(1)` / `x.value` | `x.value = v` | `computed(() => x.value * 2)` |
| [Solid][solid-signal] | `const [x, setX] = createSignal(1)` / `x()` | `setX(v)` | `createMemo(() => x() * 2)` |
| [MobX][mobx-observable] | `const x = observable.box(1)` / `x.get()` | `runInAction(() => x.set(v))` | `computed(() => x.get() * 2)` |

Signified and Param both overload Python operators, but build dependencies
differently. Reaktiv's current documentation prefers lowercase factories;
uppercase `Signal`, `Computed`, and `Effect` remain supported.

## What becomes a dependency?

| Rule | How dependencies are established |
|---|---|
| **Reads** | Track reactive accessors/properties read during execution, including synchronous helper calls. Each run replaces the previous dependency set with the reads it reached. |
| **References** | Record expression operands or explicitly bound/declared dependencies. Arbitrary reactive reads inside a called function do not automatically add dependencies. |

| Library / derivation | Dependency rule |
|---|---|
| [signified `Computed`](compute-contract.md) | Reads |
| [reaktiv `computed`][reaktiv-computed] | Reads |
| [Param `rx`][param-expressions] | References |
| [Angular `computed`][angular-signals] | Reads |
| [Vue `computed`][vue-computed] | Reads |
| [Svelte `$derived`][svelte-derived] | Reads |
| [Preact `computed`][preact-guide] | Reads |
| [Solid `createMemo`][solid-memo] | Reads |
| [MobX `computed`][mobx-tracking] | Reads |

Under **Reads**, `left.value if choose_left.value else right.value` in Signified
subscribes to the selector and the chosen input. Changing branches replaces the
input dependency. Capturing or returning a signal without reading it adds no
value dependency. Svelte's compiler syntax implements this same runtime rule
for synchronous `$derived` expressions.

Under **References**, Param's `rx` records a pipeline of operations.
`param.bind` returns a bound callable, while `@param.depends` supplies dependency
metadata. Neither alone supplies a cached, dynamically tracked `Computed`.
[Param dependencies][param-watchers].

Observers can deliberately use different rules for choosing triggers:

| Trigger selection | Observer APIs |
|---|---|
| Track reads in the side-effect callback | Signified `Effect`; reaktiv `effect`; Angular `effect`; Vue `watchEffect`; Svelte `$effect`; Preact `effect`; Solid `createEffect`; MobX `autorun` |
| Track a separate getter/data function; exclude side-effect callback reads | Vue `watch`; MobX `reaction` |
| Subscribe to specified parameters/references | Param watchers |

See the linked APIs in [Effects, batching, and lifetime](#effects-batching-and-lifetime)
for scheduling and ownership; trigger selection does not determine either.

## When does a derivation run?

These are three independent cases. A **read** includes demand from a downstream
computation, observer refresh, or renderer. **Unobserved** means no downstream
consumer is subscribed; ordinary application code can still hold and read the
derived value.

| Case | Meaning of ✓ | Meaning of ✗ |
|---|---|---|
| **Lazy start** | Creating the derivation does not run its callback; its first read does. | Creating the derivation runs its callback. |
| **Lazy refresh** | A source write alone does not run the callback; evaluation waits for demand. | Changed dependencies cause evaluation during update propagation, even without a downstream read. |
| **Unobserved cache** | Repeated unobserved reads with no changes reuse the result. | Repeated unobserved reads recompute. |

| Library / primitive | Lazy start | Lazy refresh | Unobserved cache |
|---|:---:|:---:|:---:|
| [signified `Computed`](compute-contract.md) | ✓ | ✓ | ✓ |
| [reaktiv `computed`][reaktiv-computed] | ✓ | ✓ | ✓ |
| [Param `rx`][param-rx-source] | Varies* | ✓ | ✓ |
| [Angular `computed`][angular-signals] | ✓ | ✓ | ✓ |
| [Vue `computed`][vue-computed] | ✓ | ✓ | ✓ |
| [Svelte `$derived`][svelte-derived] | ✓ | ✓ | ✓ |
| [Preact `computed`][preact-guide] | ✓ | ✓ | ✓ |
| [Solid `createMemo`][solid-memo] | ✗ | ✗ | ✓ |
| [MobX `computed`][mobx-computed] | ✓ | ✓ | ✗* |

- **Param:** constructing or inspecting an `rx` pipeline can evaluate steps
  before an explicit `.rx.value` read. The cache columns describe `rx` expression
  resolution, not a plain `param.bind` callable.
- **MobX:** the default cache is maintained while observed and suspended when
  unobserved. `keepAlive` changes the unobserved-cache cell to ✓.

Lazy refresh does not mean “wait until application code explicitly reads.” An
active effect can demand the value during the same source update. Batching can
defer that observer work; in Solid it can also defer memo recomputation.
[Preact][preact-guide], [Solid batching][solid-batch].

Keep derivations pure: their job is to calculate a value. Lazy evaluation means
unread intermediate states may never execute; suspension or changed dependencies
can introduce executions that application code did not explicitly request.
Use an effect for a required side effect, rather than relying on getter calls.
Vue, Solid, and MobX explicitly recommend pure derivations. Svelte additionally
disallows state changes inside derived expressions, and reaktiv rejects signal
writes during a computation. Signified documents purity as a caller obligation.
[Vue][vue-computed], [Solid][solid-memo], [MobX][mobx-computed],
[Svelte][svelte-derived], [reaktiv][reaktiv-signal].

## What counts as a change?

There are two separate decisions: whether a source write changes its value, and
whether a recomputed result changes what downstream consumers observe. For
example, changing `x` from `1` to `3` changes the source, but leaves `x % 2`
unchanged. Consumers that read only the parity can therefore skip work.

The named rules below compare values at a reactive node. Proxy conversion and
property-level observation are separate dimensions, covered in the next section.

| Equality rule | Values considered unchanged |
|---|---|
| **Scalar/identity** | Signified: same-type exact built-in `int`, `bool`, `str`, `bytes`, `complex`, `NoneType`, and `float` compare by value; float NaNs also match. Everything else compares by identity, without user `__eq__`. |
| **`is`** | Python object identity, including for scalar objects. Equal separately allocated numbers need not match. |
| **`Object.is`** | JavaScript primitive values or object identity; NaNs match, signed zeros differ. |
| **`===`** | JavaScript primitive values or object identity; NaNs differ, signed zeros match. |
| **Comparator** | Param parameter-event comparison; registered rules can compare supported containers by contents. |
| **None** | No final derived-result equality filter in the API being compared. |

**Custom derived equality** means an explicit comparator option on the derived
primitive. **Suppress equal output** means an observer that reads only the
derivation can skip its callback when the derived result is unchanged.

| Library | Source rule | Derived rule | Custom derived equality | Suppress equal output |
|---|---|---|:---:|:---:|
| [signified](compute-contract.md) | Scalar/identity | Scalar/identity | ✗ | ✓ |
| [reaktiv][reaktiv-signal] / [computed][reaktiv-computed] | `is` | `is` | ✓ | ✓ |
| [Param][param-comparator-source] / [`rx`][param-rx-source] | Comparator | None* | — | ✗* |
| [Angular][angular-signals] | `Object.is` | `Object.is` | ✓ | ✓ |
| [Vue][vue-equality-source] / [computed stability][vue-stability] | `Object.is` | `Object.is` | ✗ | ✓ |
| [Svelte][svelte-sources-source] / [derived][svelte-derived-source] | `===` | `===` | ✗ | ✓ |
| [Preact Signals core][preact-source] | `===` | `===` | ✗ | ✓ |
| [Solid][solid-signal] / [memo][solid-memo] | `===` | `===` | ✓ | ✓ |
| [MobX][mobx-observable] / [computed][mobx-computed] | `Object.is` | `Object.is` | ✓ | ✓ |

**Param:** in 2.4.2, `rx.watch` delegates to a bound watcher without adding a
final-result comparator. Parameter-event filtering is a separate stage.
**Vue:** the computed-output suppression entry assumes Vue 3.4 or later.
**Solid:** `equals: false` disables suppression. Angular, reaktiv, and Solid also
allow custom source equality; MobX offers structural and shallow comparers.

In Signified, unchanged computed outcomes suppress both downstream computations
and effects:

```python
from signified import Computed, Effect, Signal

x = Signal(1)
parity = Computed(lambda: x.value % 2)
seen = []
watcher = Effect(lambda: seen.append(parity.value))
x.value = 3
assert seen == [1]
x.value = 4
assert seen == [1, 0]
watcher.dispose()
```

An effect that also reads `x.value` has another reason to run. Signified's
explicit `Signal.update()` and `Computed.invalidate()` force notification from
that node. [Signified contract](compute-contract.md).

## Mutation, nesting, and writable derivations

| Observation rule | Which writes are observed? |
|---|---|
| **Value** | Assigning through the source API. Merely storing a container does not make mutations through its raw aliases observable. |
| **Deep** | Assigning through the source API and mutating supported nested objects through reactive proxies/properties. Conversion rules determine which objects are supported. |

| Library / source | Default observation | Alternative discussed here |
|---|---|---|
| [signified `Signal`](compute-contract.md) | Value* | Explicit mutation notification |
| [reaktiv `signal`][reaktiv-signal] | Value | — |
| [Param `rx`][param-expressions] | Value | — |
| [Angular `signal`][angular-signals] | Value | — |
| [Vue `ref` / `reactive`][vue-core] | Deep | Value: [`shallowRef`][vue-shallow] |
| [Svelte `$state`][svelte-state] | Deep | Value: `$state.raw` |
| [Preact `signal`][preact-guide] | Value | — |
| [Solid `createSignal`][solid-signal] | Value | Deep: [`createStore`][solid-store] |
| [MobX `observable`][mobx-observable] | Deep | Value: `observable.ref` |

**Signified:** item/attribute assignment through a `Signal` forwards the mutation
and notifies. Mutating through `.value` requires replacement or `update()` to
notify. This explicit forwarding does not observe raw aliases. Deep observation
also has boundaries: Svelte, for example, proxies arrays and simple objects,
rather than every possible class instance.

Signified stores exactly the object supplied. Nested reactive values remain
ordinary values until explicitly read:

```python
from signified import Binding, Computed, Signal

inner = Signal(1)
outer = Signal(inner)
assert outer.value is inner
assert Computed(lambda: inner).value is inner
assert Binding(inner).value == 1
```

Signified's `unref` crosses one boundary; [`deep_unref`](resolution.md) explicitly
traverses supported containers and tracks the values it reads. Vue instead has
context-dependent ref unwrapping, including different behavior for object
properties versus array and collection elements. These are distinct rules from
dependency discovery. [Signified contract](compute-contract.md),
[Vue ref unwrapping][vue-core].

Read-only access does not freeze the returned object. Signified's `Computed`,
for example, does not forward writes but can return a mutable dictionary.
Writable derivations need a separate classification; the following are distinct
cases, with example APIs rather than an exhaustive feature inventory.

| Write behavior | Meaning | Example APIs |
|---|---|---|
| **Setter** | Run a user-supplied setter that writes underlying state. | [Vue writable computed][vue-computed]; [MobX computed setter][mobx-computed] |
| **Override** | Replace the result temporarily; dependency changes restore the derivation. | [Svelte non-`const` `$derived`][svelte-derived], since 5.25 |
| **Derived default** | Maintain writable state with a default that follows source changes. | [Angular `linkedSignal`][angular-linked] |
| **Select source** | Replace which source a stable handle follows; do not write to the old source. | [Signified `Binding`](compute-contract.md) |

## Effects, batching, and lifetime

Scheduling labels describe **when the side-effect callback runs**. Dependency
collection can happen earlier, including when registering a lazy watcher.

| Timing | Execution point |
|---|---|
| **Sync** | During the triggering call, before it returns. For updates inside an explicit batch/action, this means the outermost flush. |
| **On change** | No initial side-effect callback; wait for a triggering change. |
| **Angular sync** | During Angular's synchronization/change-detection process. |
| **Microtask** | In the microtask queue, after the current synchronous work. |
| **Before DOM** | In Vue's watcher queue, after parent updates and before the owner's DOM update. |
| **After DOM** | In Svelte's microtask flush, after mounting or applying DOM updates. |
| **After render** | After Solid's current rendering phase. |

The first-callback column assumes creation outside an explicit batch/action.
Distinct APIs get separate rows when their timing differs.

| Library / observer | First callback | Later callbacks | Update grouping |
|---|---|---|---|
| [signified `Effect`](compute-contract.md) | Sync | Sync | `batch()` |
| [reaktiv `effect`][reaktiv-effect] | Sync | Sync | `batch()` |
| [Param watchers][param-watchers] | On change | Sync | `batch_call_watchers` |
| [Angular component `effect`][angular-effect-api] | Angular sync | Angular sync | Framework |
| [Angular root `effect`][angular-effect-api] | Microtask | Microtask | Framework |
| [Vue `watchEffect`][vue-watchers] | Sync | Before DOM | Framework |
| [Vue `watch`][vue-watchers] | On change | Before DOM | Framework |
| [Svelte `$effect`][svelte-effect] | After DOM | After DOM | Framework |
| [Preact core `effect`][preact-guide] | Sync | Sync | `batch()` |
| [Solid `createEffect`][solid-effect] | After render | Sync | `batch()` |
| [MobX `autorun`][mobx-reactions] | Sync | Sync | Action/transaction |
| [MobX `reaction`][mobx-reactions] | On change | Sync | Action/transaction |

Options can change these defaults: Vue offers `immediate`, `post`, and unbatched
`sync` modes; Svelte has `$effect.pre`; MobX offers `fireImmediately` and custom
schedulers. Signified's `batch()` also defers the initial callback of an effect
created inside it. Preact's core effect still starts immediately inside a batch.
Param's `batch_call_watchers` groups parameter events on one object; `queued`
controls how callbacks process nested events.

Ownership is independent of scheduling:

| Lifetime rule | What application code must do | APIs |
|---|---|---|
| **Retain handle** | Hold a strong reference while active; call `dispose()` to stop. | Signified `Effect`; reaktiv `effect` |
| **Owner scope** | Create in the intended scope; scope destruction stops the observer. Explicit stopping is also available. | Angular effects; Vue watchers created synchronously in setup; Svelte effects; Solid effects |
| **Explicit stop** | Invoke the disposer or unregister the watcher when its work is no longer needed. | Preact core effects; MobX reactions; Param parameter watchers (`unwatch`) |

Angular's default owner is its injection context. Vue watchers created later
asynchronously need manual stopping; Svelte's `$effect.root` also requires manual
cleanup. Cleanup hooks for reruns are separate from stopping the observer.
[Angular lifecycle][angular-effect-guide], [Vue][vue-watchers], [Svelte][svelte-effect].

Batching generally groups observer work; it should not be assumed to provide
database-style isolation or rollback. Signified, Preact Signals, and Solid allow
reads of updated derived state inside a batch. In Signified, a batch body that
raises still leaves writes applied and flushes pending effects. Independent
effect order is unspecified, and cascading writes can run an effect again in
the same flush. MobX actions are also transactions for reaction scheduling, not
an instruction to execute each reaction after every intermediate assignment.
[Signified](compute-contract.md), [Preact][preact-guide],
[Solid batching][solid-batch], [MobX actions][mobx-actions].

## Errors are part of the contract

Two questions need separate answers: **what does a failed derived read cache?**
and **who receives an observer's exception?** Equivalent successful values do
not imply equivalent failure behavior.

**Cache failed read** means the node stores the error and rethrows it on later
reads until refresh is required. The reporting rules describe failures of
already-active observers, not failure while constructing one.

| Reporting rule | What happens after an observer fails? |
|---|---|
| **Collect** | Continue healthy pending callbacks, then raise one failure directly or aggregate multiple failures. |
| **First** | Continue healthy pending callbacks, then raise the first failure. |
| **Log** | Report ordinary callback errors without propagating them to the original writer by default. |
| **App handler** | Framework-managed errors can be delivered to an application error handler. |
| **Owner handler** | An installed boundary/handler handles errors in its reactive or rendering subtree. |

| Library | Cache failed read | Observer reporting rule |
|---|:---:|---|
| [signified](compute-contract.md#errors-and-recovery) | ✓* | Collect |
| [reaktiv][reaktiv-source] / [effects][reaktiv-effect-source] | ✓* | Log |
| [Param `rx`][param-rx-source] | ✓ | ? |
| [Angular][angular-computed-source] | ✓ | ? |
| [Vue][vue-errors] | ? | App handler |
| [Svelte][svelte-errors] | ? | Owner handler |
| [Preact Signals core][preact-source] | ✓ | First |
| [Solid][solid-errors] | ? | Owner handler |
| [MobX][mobx-reactions] | ? | Log |

- **Signified:** caches ordinary `Exception`, not control-flow exceptions such
  as `KeyboardInterrupt`. A failed run retains the dependencies it reached;
  changed dependencies or `invalidate()` permit retry. A new failure and recovery
  each count as a changed outcome. Multiple flush failures form an `ExceptionGroup`.
- **Reaktiv:** the inspected implementation caches `BaseException`, including
  control-flow exceptions. Its synchronous effect runner prints tracebacks.
- **Third-party cache entries:** ✓ records the linked implementation's behavior,
  including Param 2.4.2 expression resolution. **? is not ✗**: it makes no claim
  about caching or retry behavior for that API.
- **Handlers:** Vue exposes `app.config.errorHandler`; Svelte has
  `<svelte:boundary>`; Solid has `catchError`; MobX reactions accept `onError`.
  A handler's scope matters: Svelte and Solid's scoped handlers do not cover
  arbitrary later async callbacks. Error reporting alone does not establish a
  failed getter's cache policy.

## Async and execution assumptions

Automatic dependency tracking usually covers the synchronous execution of a
tracked callback. Reads in a later task, timer, or continuation are not implied
dependencies. Vue explicitly limits `watchEffect` tracking to reads before the
first `await`; Angular likewise documents a synchronous tracking context.
Svelte provides a specific compiler-supported exception: visible `await` in
`$derived` can preserve tracking across suspension, whereas an `await` hidden
inside a called async function does not receive the same transformation.
[Vue][vue-watchers], [Angular][angular-signals],
[Svelte derived tracking][svelte-derived], [Svelte async expressions][svelte-await].

Async I/O support and concurrent graph access are separate capabilities.
Signified's graph is synchronous and single-threaded, and neither `batch()` nor
`untracked()` may span `await`. Reaktiv offers async facilities and opt-in
thread-safety configuration; those have their own rules. Param supports async
watcher execution through an async executor. Neither feature should be reduced
to a blanket “all computations are async/thread-safe” checkmark.
[Signified](compute-contract.md), [reaktiv advanced features][reaktiv-advanced],
[Param async watchers][param-watchers].

## Where Signified fits

Signified follows a recognizable signals contract: runtime read tracking,
dynamic dependencies, lazy cached derivations, equality-based suppression, and
separate effects. Angular, reaktiv, and Preact Signals provide particularly close
comparisons for that combination. Vue and Svelte add deep state tracking and UI
scheduling; Solid differs on initial memo evaluation; MobX makes observation
part of cache lifetime. Param offers a different Python model based on recorded
expressions, declared references, and parameter metadata.

Signified's particular choices are its fixed scalar/identity equality policy,
explicit handling of nested reactive values, replaceable-source `Binding`, and
synchronous effect/error contract. Those rules matter more when porting code
than whether two libraries both expose a function called `computed`.

For event sequences, [ReactiveX for Python][rxpy] is another useful comparison:
an Observable delivers notifications to subscribers and composes them with
stream operators. A cached current value can intentionally skip intermediate
states; preserving and processing individual events calls for a different
contract. Streams and signals can serve complementary roles in one application.

[angular-signals]: https://angular.dev/guide/signals
[angular-linked]: https://angular.dev/guide/signals/linked-signal
[angular-effect-api]: https://angular.dev/api/core/effect
[angular-effect-guide]: https://angular.dev/guide/signals/effect
[angular-computed-source]: https://github.com/angular/angular/blob/7569a02d2961155cc32b9491918bde8ae4c47616/packages/core/primitives/signals/src/computed.ts
[vue-core]: https://vuejs.org/api/reactivity-core
[vue-computed]: https://vuejs.org/guide/essentials/computed
[vue-watchers]: https://vuejs.org/guide/essentials/watchers
[vue-shallow]: https://vuejs.org/api/reactivity-advanced#shallowref
[vue-stability]: https://vuejs.org/guide/best-practices/performance#computed-stability
[vue-equality-source]: https://github.com/vuejs/core/blob/4ab865a848a1da3d10fb674f857e5fff13094644/packages/shared/src/general.ts
[vue-errors]: https://vuejs.org/api/application#app-config-errorhandler
[svelte-state]: https://svelte.dev/docs/svelte/$state
[svelte-derived]: https://svelte.dev/docs/svelte/$derived
[svelte-effect]: https://svelte.dev/docs/svelte/$effect
[svelte-await]: https://svelte.dev/docs/svelte/await-expressions
[svelte-errors]: https://svelte.dev/docs/svelte/svelte-boundary
[svelte-sources-source]: https://github.com/sveltejs/svelte/blob/636eaaaa6f064b55072e7d192bb76dc9d8c4516e/packages/svelte/src/internal/client/reactivity/sources.js
[svelte-derived-source]: https://github.com/sveltejs/svelte/blob/636eaaaa6f064b55072e7d192bb76dc9d8c4516e/packages/svelte/src/internal/client/reactivity/deriveds.js
[preact-guide]: https://preactjs.com/guide/v10/signals/
[preact-source]: https://github.com/preactjs/signals/blob/b0df09ae3bbc66eefa8027bbd862563203e4c7f4/packages/core/src/index.ts
[solid-signal]: https://docs.solidjs.com/reference/basic-reactivity/create-signal
[solid-memo]: https://docs.solidjs.com/reference/basic-reactivity/create-memo
[solid-effect]: https://docs.solidjs.com/reference/basic-reactivity/create-effect
[solid-store]: https://docs.solidjs.com/reference/store-utilities/create-store
[solid-batch]: https://docs.solidjs.com/reference/reactive-utilities/batch
[solid-errors]: https://docs.solidjs.com/reference/reactive-utilities/catch-error
[mobx-observable]: https://mobx.js.org/observable-state.html
[mobx-computed]: https://mobx.js.org/computeds.html
[mobx-tracking]: https://mobx.js.org/understanding-reactivity.html
[mobx-reactions]: https://mobx.js.org/reactions.html
[mobx-actions]: https://mobx.js.org/actions.html
[reaktiv-signal]: https://reaktiv.readthedocs.io/en/latest/api/signal/
[reaktiv-computed]: https://reaktiv.readthedocs.io/en/latest/api/compute-signal/
[reaktiv-effect]: https://reaktiv.readthedocs.io/en/latest/api/effect/
[reaktiv-advanced]: https://reaktiv.readthedocs.io/en/latest/advanced-features/
[reaktiv-source]: https://github.com/buiapp/reaktiv/blob/95bd929a5102b7690c83a4bdda8463c6a2b06ff0/src/reaktiv/signal.py
[reaktiv-effect-source]: https://github.com/buiapp/reaktiv/blob/95bd929a5102b7690c83a4bdda8463c6a2b06ff0/src/reaktiv/effect.py
[param-expressions]: https://param.holoviz.org/en/docs/latest/user_guide/Reactive_Expressions.html
[param-watchers]: https://param.holoviz.org/en/docs/latest/user_guide/Dependencies_and_Watchers.html
[param-comparator-source]: https://github.com/holoviz/param/blob/v2.4.2/param/parameterized.py
[param-rx-source]: https://github.com/holoviz/param/blob/v2.4.2/param/reactive.py
[rxpy]: https://rxpy.readthedocs.io/en/latest/get_started.html

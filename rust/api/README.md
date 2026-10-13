# signified-api (internal)

The C API that `signified._core` exports in the `signified._core._C_API` capsule: extension
modules create `signified.Computed` values evaluated by native kernels. It is internal and
undocumented outside `src/lib.rs`, and this crate is not published. The engine uses it, and
extensions that use the API copy `src/lib.rs`: key3d vendors it as `rust/src/signified_api.rs`.

`../api-example` is an extension that uses the API from outside signified, tested in CI.

Changing the API: only append fields to `CApi`, bump `VERSION`, keep the layout tests passing,
and update the vendored copies. Changing an existing function needs a new capsule name.

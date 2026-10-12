//! Same graphs, same operations, in signified's Rust API, reactive_graph,
//! sycamore-reactive and salsa (`signified_graphs.py` runs them on signified
//! from Python). See README.md.
//!
//! Workloads (N = 1000; layers: 10 deep x 100 wide):
//!   chain   source -> c1 -> ... -> cN (each +1); update the source, read cN
//!   fan     source -> N leaves (source + i) -> one sum; update, read the sum
//!   layers  each node = two nodes of the layer before; update, read a sum of the last layer
//!   cutoff  source -> zero (source * 0) -> chain of N; update, read the tail (nothing changes)
//!   create  build the N-node chain and read its tail once
//! Prints CSV: library,workload,microseconds per operation (best of 5 samples).

use std::hint::black_box;
use std::time::Instant;

const N: usize = 1000;
const W: usize = 100;
const D: usize = 10;

fn bench(lib: &str, workload: &str, mut op: impl FnMut()) {
    // Calibrate to ~100 ms per sample.
    let mut iters = 1usize;
    loop {
        let t = Instant::now();
        for _ in 0..iters {
            op();
        }
        if t.elapsed().as_secs_f64() > 0.02 {
            break;
        }
        iters *= 2;
    }
    iters *= 5;
    let mut best = f64::INFINITY;
    for _ in 0..5 {
        let t = Instant::now();
        for _ in 0..iters {
            op();
        }
        best = best.min(t.elapsed().as_secs_f64() / iters as f64);
    }
    println!("{lib},{workload},{:.3}", best * 1e6);
}

fn expected_fan(src: i64) -> i64 {
    N as i64 * src + (N as i64 * (N as i64 - 1)) / 2
}
fn expected_layers(src: i64) -> i64 {
    (1i64 << (D - 1)) * (W as i64 * src + (W as i64 * (W as i64 - 1)) / 2)
}

mod sg {
    use super::*;
    use signified::{Computed, Signal};

    fn chain_on(base: Computed<i64>) -> Computed<i64> {
        let mut prev = base;
        for _ in 1..N {
            let p = prev.clone();
            prev = Computed::new(move || p.get() + 1);
        }
        prev
    }

    pub fn run() {
        let lib = "signified (Rust)";
        {
            let src = Signal::new(0i64);
            let s = src.clone();
            let out = chain_on(Computed::new(move || s.get() + 1));
            src.set(7);
            assert_eq!(out.get(), 7 + N as i64);
            let mut v = 0;
            bench(lib, "chain", || {
                v += 1;
                src.set(v);
                black_box(out.get());
            });
        }
        {
            let src = Signal::new(0i64);
            let leaves: Vec<Computed<i64>> = (0..N)
                .map(|i| {
                    let s = src.clone();
                    Computed::new(move || s.get() + i as i64)
                })
                .collect();
            let sum = Computed::new(move || leaves.iter().map(|m| m.get()).sum::<i64>());
            src.set(7);
            assert_eq!(sum.get(), expected_fan(7));
            let mut v = 0;
            bench(lib, "fan", || {
                v += 1;
                src.set(v);
                black_box(sum.get());
            });
        }
        {
            let src = Signal::new(0i64);
            let mut layer: Vec<Computed<i64>> = (0..W)
                .map(|j| {
                    let s = src.clone();
                    Computed::new(move || s.get() + j as i64)
                })
                .collect();
            for _ in 1..D {
                let prev = layer.clone();
                layer = (0..W)
                    .map(|j| {
                        let (a, b) = (prev[j].clone(), prev[(j + 1) % W].clone());
                        Computed::new(move || a.get() + b.get())
                    })
                    .collect();
            }
            let last = layer;
            let sum = Computed::new(move || last.iter().map(|m| m.get()).sum::<i64>());
            src.set(7);
            assert_eq!(sum.get(), expected_layers(7));
            let mut v = 0;
            bench(lib, "layers", || {
                v += 1;
                src.set(v);
                black_box(sum.get());
            });
        }
        {
            let src = Signal::new(0i64);
            let s = src.clone();
            let zero = Computed::new(move || s.get() * 0);
            let out = chain_on(Computed::new(move || zero.get() + 1));
            src.set(7);
            assert_eq!(out.get(), N as i64);
            let mut v = 0;
            bench(lib, "cutoff", || {
                v += 1;
                src.set(v);
                black_box(out.get());
            });
        }
        bench(lib, "create", || {
            let src = Signal::new(1i64);
            let s = src.clone();
            let out = chain_on(Computed::new(move || s.get() + 1));
            black_box(out.get());
        });
    }
}

mod rg {
    use super::*;
    use reactive_graph::computed::Memo;
    use reactive_graph::owner::Owner;
    use reactive_graph::prelude::*;
    use reactive_graph::signal::RwSignal;

    fn chain_on(base: Memo<i64>) -> Memo<i64> {
        let mut prev = base;
        for _ in 1..N {
            let p = prev;
            prev = Memo::new(move |_| p.get() + 1);
        }
        prev
    }

    pub fn run() {
        let owner = Owner::new();
        owner.set();
        let lib = "reactive_graph";
        {
            let src = RwSignal::new(0i64);
            let out = chain_on(Memo::new(move |_| src.get() + 1));
            src.set(7);
            assert_eq!(out.get(), 7 + N as i64);
            let mut v = 0;
            bench(lib, "chain", || {
                v += 1;
                src.set(v);
                black_box(out.get());
            });
        }
        {
            let src = RwSignal::new(0i64);
            let leaves: Vec<Memo<i64>> = (0..N).map(|i| Memo::new(move |_| src.get() + i as i64)).collect();
            let sum = Memo::new(move |_| leaves.iter().map(|m| m.get()).sum::<i64>());
            src.set(7);
            assert_eq!(sum.get(), expected_fan(7));
            let mut v = 0;
            bench(lib, "fan", || {
                v += 1;
                src.set(v);
                black_box(sum.get());
            });
        }
        {
            let src = RwSignal::new(0i64);
            let mut layer: Vec<Memo<i64>> = (0..W).map(|j| Memo::new(move |_| src.get() + j as i64)).collect();
            for _ in 1..D {
                let prev = layer.clone();
                layer = (0..W)
                    .map(|j| {
                        let (a, b) = (prev[j], prev[(j + 1) % W]);
                        Memo::new(move |_| a.get() + b.get())
                    })
                    .collect();
            }
            let last = layer;
            let sum = Memo::new(move |_| last.iter().map(|m| m.get()).sum::<i64>());
            src.set(7);
            assert_eq!(sum.get(), expected_layers(7));
            let mut v = 0;
            bench(lib, "layers", || {
                v += 1;
                src.set(v);
                black_box(sum.get());
            });
        }
        {
            let src = RwSignal::new(0i64);
            let zero = Memo::new(move |_| src.get() * 0);
            let out = chain_on(Memo::new(move |_| zero.get() + 1));
            src.set(7);
            assert_eq!(out.get(), N as i64);
            let mut v = 0;
            bench(lib, "cutoff", || {
                v += 1;
                src.set(v);
                black_box(out.get());
            });
        }
        bench(lib, "create", || {
            let scope = Owner::new();
            scope.with(|| {
                let src = RwSignal::new(1i64);
                let out = chain_on(Memo::new(move |_| src.get() + 1));
                black_box(out.get());
            });
            drop(scope);
        });
    }
}

mod sy {
    use super::*;
    use sycamore_reactive::*;

    fn chain_on(base: ReadSignal<i64>) -> ReadSignal<i64> {
        let mut prev = base;
        for _ in 1..N {
            let p = prev;
            prev = create_selector(move || p.get() + 1);
        }
        prev
    }

    pub fn run() {
        let lib = "sycamore-reactive";
        let root = create_root(|| {
            {
                let src = create_signal(0i64);
                let out = chain_on(create_selector(move || src.get() + 1));
                src.set(7);
                assert_eq!(out.get(), 7 + N as i64);
                let mut v = 0;
                bench(lib, "chain", || {
                    v += 1;
                    src.set(v);
                    black_box(out.get());
                });
            }
            {
                let src = create_signal(0i64);
                let leaves: Vec<ReadSignal<i64>> =
                    (0..N).map(|i| create_selector(move || src.get() + i as i64)).collect();
                let sum = create_selector(move || leaves.iter().map(|m| m.get()).sum::<i64>());
                src.set(7);
                assert_eq!(sum.get(), expected_fan(7));
                let mut v = 0;
                bench(lib, "fan", || {
                    v += 1;
                    src.set(v);
                    black_box(sum.get());
                });
            }
            {
                let src = create_signal(0i64);
                let mut layer: Vec<ReadSignal<i64>> =
                    (0..W).map(|j| create_selector(move || src.get() + j as i64)).collect();
                for _ in 1..D {
                    let prev = layer.clone();
                    layer = (0..W)
                        .map(|j| {
                            let (a, b) = (prev[j], prev[(j + 1) % W]);
                            create_selector(move || a.get() + b.get())
                        })
                        .collect();
                }
                let last = layer;
                let sum = create_selector(move || last.iter().map(|m| m.get()).sum::<i64>());
                src.set(7);
                assert_eq!(sum.get(), expected_layers(7));
                let mut v = 0;
                bench(lib, "layers", || {
                    v += 1;
                    src.set(v);
                    black_box(sum.get());
                });
            }
            {
                let src = create_signal(0i64);
                let zero = create_selector(move || src.get() * 0);
                let out = chain_on(create_selector(move || zero.get() + 1));
                src.set(7);
                assert_eq!(out.get(), N as i64);
                let mut v = 0;
                bench(lib, "cutoff", || {
                    v += 1;
                    src.set(v);
                    black_box(out.get());
                });
            }
            bench(lib, "create", || {
                let scope = create_child_scope(|| {
                    let src = create_signal(1i64);
                    let out = chain_on(create_selector(move || src.get() + 1));
                    black_box(out.get());
                });
                scope.dispose();
            });
        });
        root.dispose();
    }
}

mod sa {
    use super::*;
    use salsa::Setter;

    #[salsa::input]
    struct Source {
        #[returns(copy)]
        value: i64,
    }

    #[salsa::interned]
    struct Node<'db> {
        #[returns(copy)]
        index: u32,
    }

    #[salsa::interned]
    struct Cell<'db> {
        #[returns(copy)]
        layer: u32,
        #[returns(copy)]
        index: u32,
    }

    #[salsa::tracked(returns(copy))]
    fn chain<'db>(db: &'db dyn salsa::Database, src: Source, node: Node<'db>) -> i64 {
        let i = node.index(db);
        if i == 0 {
            src.value(db) + 1
        } else {
            chain(db, src, Node::new(db, i - 1)) + 1
        }
    }

    #[salsa::tracked(returns(copy))]
    fn chain_out(db: &dyn salsa::Database, src: Source) -> i64 {
        chain(db, src, Node::new(db, N as u32 - 1))
    }

    #[salsa::tracked(returns(copy))]
    fn leaf<'db>(db: &'db dyn salsa::Database, src: Source, node: Node<'db>) -> i64 {
        src.value(db) + node.index(db) as i64
    }

    #[salsa::tracked(returns(copy))]
    fn fan_sum(db: &dyn salsa::Database, src: Source) -> i64 {
        (0..N as u32).map(|i| leaf(db, src, Node::new(db, i))).sum()
    }

    #[salsa::tracked(returns(copy))]
    fn cell<'db>(db: &'db dyn salsa::Database, src: Source, c: Cell<'db>) -> i64 {
        let (k, j) = (c.layer(db), c.index(db));
        if k == 0 {
            src.value(db) + j as i64
        } else {
            cell(db, src, Cell::new(db, k - 1, j)) + cell(db, src, Cell::new(db, k - 1, (j + 1) % W as u32))
        }
    }

    #[salsa::tracked(returns(copy))]
    fn layers_sum(db: &dyn salsa::Database, src: Source) -> i64 {
        (0..W as u32).map(|j| cell(db, src, Cell::new(db, D as u32 - 1, j))).sum()
    }

    #[salsa::tracked(returns(copy))]
    fn zero(db: &dyn salsa::Database, src: Source) -> i64 {
        src.value(db) * 0
    }

    #[salsa::tracked(returns(copy))]
    fn cut_chain<'db>(db: &'db dyn salsa::Database, src: Source, node: Node<'db>) -> i64 {
        let i = node.index(db);
        if i == 0 {
            zero(db, src) + 1
        } else {
            cut_chain(db, src, Node::new(db, i - 1)) + 1
        }
    }

    #[salsa::tracked(returns(copy))]
    fn cut_out(db: &dyn salsa::Database, src: Source) -> i64 {
        cut_chain(db, src, Node::new(db, N as u32 - 1))
    }

    fn updates(lib: &str, workload: &str, read: fn(&salsa::DatabaseImpl, Source) -> i64, check: fn(i64) -> i64) {
        let mut db = salsa::DatabaseImpl::new();
        let src = Source::new(&db, 0);
        read(&db, src);
        src.set_value(&mut db).to(7);
        assert_eq!(read(&db, src), check(7));
        let mut v = 0;
        bench(lib, workload, || {
            v += 1;
            src.set_value(&mut db).to(v);
            black_box(read(&db, src));
        });
    }

    pub fn run() {
        let lib = "salsa";
        updates(lib, "chain", |db, s| chain_out(db, s), |v| v + N as i64);
        updates(lib, "fan", |db, s| fan_sum(db, s), expected_fan);
        updates(lib, "layers", |db, s| layers_sum(db, s), expected_layers);
        updates(lib, "cutoff", |db, s| cut_out(db, s), |_| N as i64);
        bench(lib, "create", || {
            let db = salsa::DatabaseImpl::new();
            let src = Source::new(&db, 1);
            black_box(chain_out(&db, src));
        });
    }
}

fn main() {
    let which: Vec<String> = std::env::args().skip(1).collect();
    let all = which.is_empty();
    // Deep chains recurse on their first read: give them room.
    std::thread::Builder::new()
        .stack_size(512 << 20)
        .spawn(move || {
            if all || which.iter().any(|w| w == "signified") {
                sg::run();
            }
            if all || which.iter().any(|w| w == "reactive_graph") {
                rg::run();
            }
            if all || which.iter().any(|w| w == "sycamore") {
                sy::run();
            }
            if all || which.iter().any(|w| w == "salsa") {
                sa::run();
            }
        })
        .unwrap()
        .join()
        .unwrap();
}

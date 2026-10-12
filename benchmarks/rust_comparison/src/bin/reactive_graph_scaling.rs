//! How reactive_graph's chain update cost scales with chain length (is it quadratic?).
use std::hint::black_box;
use std::time::Instant;

use reactive_graph::computed::Memo;
use reactive_graph::owner::Owner;
use reactive_graph::prelude::*;
use reactive_graph::signal::RwSignal;

fn main() {
    std::thread::Builder::new().stack_size(512 << 20).spawn(|| {
        let owner = Owner::new();
        owner.set();
        for n in [50usize, 100, 200, 400, 800] {
            let src = RwSignal::new(0i64);
            let mut prev = Memo::new(move |_| src.get() + 1);
            for _ in 1..n {
                let p = prev;
                prev = Memo::new(move |_| p.get() + 1);
            }
            let out = prev;
            out.get();
            let iters = 20;
            let t = Instant::now();
            for v in 0..iters {
                src.set(v);
                black_box(out.get());
            }
            let us = t.elapsed().as_secs_f64() / iters as f64 * 1e6;
            println!("n={n:4}  {us:10.1} us/update  {:8.1} ns/node", us * 1000.0 / n as f64);
        }
    }).unwrap().join().unwrap();
}

//! Random graphs and random writes, checked against recomputing everything
//! from scratch.

use std::cell::{Cell, RefCell};
use std::rc::Rc;

use signified::{batch, Computed, Effect, Signal};

/// xorshift64*, so the test needs no dependencies and is reproducible.
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_f491_4f6c_dd1d)
    }

    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
}

/// How a computed combines earlier nodes (by index; signals come first).
#[derive(Clone)]
enum Formula {
    Sum(Vec<usize>),
    /// `if a > b { c } else { d }`: its dependencies change with the branch.
    Pick([usize; 4]),
    /// Collapses many inputs to a few values, so changes often stop here.
    Sign(usize),
}

fn evaluate(formula: &Formula, value: impl Fn(usize) -> i64) -> i64 {
    match formula {
        Formula::Sum(inputs) => inputs.iter().map(|&i| value(i)).sum(),
        Formula::Pick([a, b, c, d]) => {
            if value(*a) > value(*b) {
                value(*c)
            } else {
                value(*d)
            }
        }
        Formula::Sign(input) => value(*input).signum(),
    }
}

#[derive(Clone)]
enum Reactive {
    Signal(Signal<i64>),
    Computed(Computed<i64>),
}

impl Reactive {
    fn get(&self) -> i64 {
        match self {
            Reactive::Signal(signal) => signal.get(),
            Reactive::Computed(computed) => computed.get(),
        }
    }
}

fn run(seed: u64) {
    let mut rng = Rng(seed);
    let signals = 2 + rng.below(6);
    let computeds = 1 + rng.below(40);
    let mut values: Vec<i64> = (0..signals).map(|_| rng.below(5) as i64 - 2).collect();
    let mut formulas = Vec::new();
    let mut nodes: Vec<Reactive> = values
        .iter()
        .map(|&value| Reactive::Signal(Signal::new(value)))
        .collect();
    let evaluations = Rc::new(Cell::new(0_u32));
    for index in signals..signals + computeds {
        let formula = match rng.below(3) {
            0 => Formula::Sum((0..1 + rng.below(3)).map(|_| rng.below(index)).collect()),
            1 => Formula::Pick([
                rng.below(index),
                rng.below(index),
                rng.below(index),
                rng.below(index),
            ]),
            _ => Formula::Sign(rng.below(index)),
        };
        let inputs = nodes.clone();
        let (closure_formula, evaluations) = (formula.clone(), evaluations.clone());
        nodes.push(Reactive::Computed(Computed::new(move || {
            evaluations.set(evaluations.get() + 1);
            evaluate(&closure_formula, |i| inputs[i].get())
        })));
        formulas.push(formula);
    }

    // The model: every node's value, computed from the signals.
    let model = |values: &[i64]| {
        let mut all = values.to_vec();
        for formula in &formulas {
            let value = evaluate(formula, |i| all[i]);
            all.push(value);
        }
        all
    };

    // An effect watching one computed records what it saw.
    let watched = signals + rng.below(computeds);
    let seen = Rc::new(RefCell::new(Vec::new()));
    let _effect = Effect::new({
        let (node, seen) = (nodes[watched].clone(), seen.clone());
        move || seen.borrow_mut().push(node.get())
    });

    for _ in 0..200 {
        match rng.below(4) {
            0 | 1 => {
                let signal = rng.below(signals);
                values[signal] = rng.below(5) as i64 - 2;
                if let Reactive::Signal(node) = &nodes[signal] {
                    node.set(values[signal]);
                }
            }
            2 => batch(|| {
                for _ in 0..3 {
                    let signal = rng.below(signals);
                    values[signal] = rng.below(5) as i64 - 2;
                    if let Reactive::Signal(node) = &nodes[signal] {
                        node.set(values[signal]);
                    }
                }
            }),
            _ => {
                let expected = model(&values);
                let index = rng.below(nodes.len());
                assert_eq!(
                    nodes[index].get(),
                    expected[index],
                    "seed {seed}, node {index}"
                );
                // Nothing changed, so reading again evaluates nothing.
                let before = evaluations.get();
                assert_eq!(nodes[index].get(), expected[index]);
                assert_eq!(
                    evaluations.get(),
                    before,
                    "seed {seed}: a repeat read evaluated"
                );
            }
        }
        let expected = model(&values)[watched];
        assert_eq!(
            seen.borrow().last(),
            Some(&expected),
            "seed {seed}: effect is stale"
        );
        // The effect only runs when its value changed.
        let seen = seen.borrow();
        assert!(
            seen.windows(2).all(|pair| pair[0] != pair[1]),
            "seed {seed}: the effect ran without a change: {seen:?}"
        );
    }
    let expected = model(&values);
    for (index, node) in nodes.iter().enumerate() {
        assert_eq!(
            node.get(),
            expected[index],
            "seed {seed}, node {index} at the end"
        );
    }
}

#[test]
fn random_graphs_match_recomputing_from_scratch() {
    for seed in 1..=500_u64 {
        run(seed.wrapping_mul(0x9e37_79b9_7f4a_7c15));
    }
}

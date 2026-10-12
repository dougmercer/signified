//! The example from the README: `cargo run -p signified --example area`.

use signified::{Computed, Effect, Signal};

fn main() {
    let width = Signal::new(2.0);
    let height = Signal::new(3.0);
    let area = Computed::new({
        let (width, height) = (width.clone(), height.clone());
        move || width.get() * height.get()
    });
    let _log = Effect::new({
        let area = area.clone();
        move || println!("area is {}", area.get())
    }); // prints "area is 6"
    width.set(4.0); // prints "area is 12"
    height.set(3.0); // equal to the current value: prints nothing
}

//! How much native stack the current thread has left.
//!
//! `stacker` reads a thread's stack bounds from `pthread_getattr_np`. For the
//! main thread, musl reports only the part of the stack mapped so far (about
//! 128 KiB at startup) rather than the size it can grow to, which would make
//! every refresh look too deep. Under musl, the main thread's bound is worked
//! out from `RLIMIT_STACK` instead.

/// Free native stack below the current frame, if known.
pub(crate) fn remaining() -> Option<usize> {
    #[cfg(all(target_os = "linux", target_env = "musl"))]
    match musl::stack_end() {
        musl::StackEnd::Reported => {}
        musl::StackEnd::At(end) => {
            let here = 0u8;
            return Some((std::ptr::addr_of!(here) as usize).saturating_sub(end));
        }
        musl::StackEnd::Unknown => return None,
    }
    stacker::remaining_stack()
}

#[cfg(all(target_os = "linux", target_env = "musl"))]
mod musl {
    use std::mem::MaybeUninit;

    /// Where the current thread's stack ends.
    #[derive(Clone, Copy)]
    pub(super) enum StackEnd {
        /// Not the main thread; musl reports its bounds correctly.
        Reported,
        /// The lowest address the main thread's stack can grow to.
        At(usize),
        /// The main thread, with an unlimited or unreadable stack size.
        Unknown,
    }

    thread_local! {
        static STACK_END: StackEnd = unsafe { find_stack_end() };
    }

    pub(super) fn stack_end() -> StackEnd {
        STACK_END.with(|end| *end)
    }

    unsafe fn find_stack_end() -> StackEnd {
        if libc::gettid() != libc::getpid() {
            return StackEnd::Reported;
        }
        // For the main thread, musl reports the top of the stack and the size
        // mapped so far; the stack can grow down from that top to the limit.
        let mut attr = MaybeUninit::<libc::pthread_attr_t>::uninit();
        if libc::pthread_attr_init(attr.as_mut_ptr()) != 0 {
            return StackEnd::Unknown;
        }
        let mut attr = attr.assume_init();
        let mut low = std::ptr::null_mut();
        let mut mapped = 0;
        let found = libc::pthread_getattr_np(libc::pthread_self(), &mut attr) == 0
            && libc::pthread_attr_getstack(&attr, &mut low, &mut mapped) == 0;
        libc::pthread_attr_destroy(&mut attr);
        let mut limit = MaybeUninit::<libc::rlimit>::uninit();
        if !found || libc::getrlimit(libc::RLIMIT_STACK, limit.as_mut_ptr()) != 0 {
            return StackEnd::Unknown;
        }
        let size = limit.assume_init().rlim_cur;
        if size == libc::RLIM_INFINITY {
            return StackEnd::Unknown;
        }
        let top = low as usize + mapped;
        StackEnd::At(top.saturating_sub(size as usize))
    }
}

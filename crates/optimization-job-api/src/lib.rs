#![doc = include_str!("../README.md")]
//!
//! The [`legacy`] module keeps compatibility with the earlier `fcmaes.job/0.1`
//! format; its numerical semantics are unchanged.
#![warn(missing_docs)]
pub mod artifact;
pub mod legacy;
pub mod process;
pub mod result;
pub mod spec;
pub mod storage;
pub mod worker;
pub use spec::*;
/// The error of every fallible function in this crate. A [`Coded`] error
/// carries a stable code ([`error_code`]); any other error is reported as
/// `runner_error`.
pub type Error = Box<dyn std::error::Error + Send + Sync>;
/// A result with the crate's [`Error`].
pub type Result<T> = std::result::Result<T, Error>;

/// An error with a stable, machine-readable code. The runner prints the code
/// next to the message; the [guide](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md#errors) lists every code.
#[derive(Debug)]
pub struct Coded {
    /// The stable code, such as `invalid_job` or `attempt_active`.
    pub code: &'static str,
    /// The human-readable message.
    pub message: String,
}
impl std::fmt::Display for Coded {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for Coded {}
/// An [`Error`] carrying `code`.
pub fn coded(code: &'static str, message: impl Into<String>) -> Error {
    Box::new(Coded {
        code,
        message: message.into(),
    })
}
/// The code of `error`, `runner_error` if it has none.
pub fn error_code(error: &Error) -> &'static str {
    error
        .downcast_ref::<Coded>()
        .map_or("runner_error", |c| c.code)
}
/// True for error codes after which the identical command can succeed later
/// without any change: only `attempt_active` (wait for the processes of the
/// attempt to exit). Every other error needs a different request, a
/// re-registered worker or operator action.
pub fn retryable(code: &str) -> bool {
    code == "attempt_active"
}

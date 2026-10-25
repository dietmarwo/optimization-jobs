//! A stalled peer cannot hold the helper's input/upload lock indefinitely.
use std::{
    fs::File,
    io::{self, Read, Write},
    os::fd::{AsRawFd, FromRawFd},
    time::{Duration, Instant},
};
pub(super) struct Deadline {
    file: File,
    until: Instant,
}
impl Deadline {
    pub fn new(fd: i32) -> io::Result<Self> {
        let copy = unsafe { libc::dup(fd) };
        if copy < 0 {
            return Err(io::Error::last_os_error());
        }
        let file = unsafe { File::from_raw_fd(copy) };
        let flags = unsafe { libc::fcntl(copy, libc::F_GETFL) };
        if flags < 0 || unsafe { libc::fcntl(copy, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self {
            file,
            until: Instant::now() + Duration::from_secs(300),
        })
    }
    fn ready(&self, events: i16) -> io::Result<()> {
        let left = self.until.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "remote helper I/O deadline exceeded",
            ));
        }
        let mut descriptor = libc::pollfd {
            fd: self.file.as_raw_fd(),
            events,
            revents: 0,
        };
        let rc = unsafe { libc::poll(&mut descriptor, 1, left.as_millis().clamp(1, 1000) as i32) };
        if rc < 0 {
            let error = io::Error::last_os_error();
            if error.kind() != io::ErrorKind::Interrupted {
                return Err(error);
            }
        }
        Ok(())
    }
}
impl Read for Deadline {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        loop {
            if Instant::now() >= self.until {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "remote helper I/O deadline exceeded",
                ));
            }
            match self.file.read(buf) {
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => self.ready(libc::POLLIN)?,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => (),
                result => return result,
            }
        }
    }
}
impl Write for Deadline {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        loop {
            if Instant::now() >= self.until {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "remote helper I/O deadline exceeded",
                ));
            }
            match self.file.write(buf) {
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => self.ready(libc::POLLOUT)?,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => (),
                result => return result,
            }
        }
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

# Copyright 2026 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

import os
import select
import shlex
import stat
import threading
from typing import Optional


class JobServerClient:
    """
    Client for GNU Make Jobserver protocol using named pipes (FIFOs),
    as introduced in GNU Make 4.4 (--jobserver-auth=fifo:PATH).
    """

    def __init__(self, fifo_path: str):
        self.fifo_path = fifo_path
        self._fd: Optional[int] = None
        self._implicit_lock = threading.Lock()

    @classmethod
    def _parse_makeflags(cls, makeflags_str: str) -> Optional[str]:
        if not makeflags_str:
            return None
        try:
            tokens = shlex.split(makeflags_str)
        except ValueError:
            tokens = makeflags_str.split()

        for token in tokens:
            if token.startswith("--jobserver-auth="):
                val = token.removeprefix("--jobserver-auth=")
                if val.startswith("fifo:"):
                    return val.removeprefix("fifo:")
        return None

    @classmethod
    def from_settings(cls, settings=None) -> Optional["JobServerClient"]:
        """
        Auto-detect jobserver from settings or environment.
        Checks MAKEFLAGS and GNUMAKEFLAGS in settings, then in os.environ.
        """
        candidates = []
        if settings is not None:
            for var in ("MAKEFLAGS", "GNUMAKEFLAGS"):
                val = settings.get(var)
                if val:
                    candidates.append(val)

        for var in ("MAKEFLAGS", "GNUMAKEFLAGS"):
            val = os.environ.get(var)
            if val:
                candidates.append(val)

        for candidate in candidates:
            path = cls._parse_makeflags(candidate)
            if path:
                try:
                    st = os.stat(path)
                    if stat.S_ISFIFO(st.st_mode):
                        return cls(path)
                except OSError:
                    pass
        return None

    @classmethod
    def from_environ(cls, env=None) -> Optional["JobServerClient"]:
        """
        Auto-detect jobserver from environment mapping or os.environ.
        """
        target_env = os.environ if env is None else env
        for var in ("MAKEFLAGS", "GNUMAKEFLAGS"):
            val = target_env.get(var)
            if val:
                path = cls._parse_makeflags(val)
                if path:
                    try:
                        st = os.stat(path)
                        if stat.S_ISFIFO(st.st_mode):
                            return cls(path)
                    except OSError:
                        pass
        return None

    def open(self) -> bool:
        """
        Open the jobserver FIFO in non-blocking read/write mode.
        Returns True if successful, False otherwise.
        """
        if self._fd is not None:
            return True
        try:
            self._fd = os.open(self.fifo_path, os.O_RDWR | os.O_NONBLOCK)
            return True
        except OSError:
            self._fd = None
            return False

    def close(self) -> None:
        """
        Close the FIFO file descriptor if open.
        """
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            finally:
                self._fd = None

    def __enter__(self) -> "JobServerClient":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def acquire_nonblocking(self) -> Optional[bytes]:
        """
        Attempt to acquire a single token non-blockingly.
        Returns a 1-byte token if acquired, or None if no token is available.
        """
        if self._fd is None and not self.open():
            return None
        try:
            return os.read(self._fd, 1)
        except (BlockingIOError, InterruptedError):
            return None
        except OSError:
            self.close()
            return None

    def acquire(self) -> bytes:
        """
        Acquire a slot to run: either the process's implicit slot (returned as b"")
        or a token from the jobserver FIFO. Blocks until one is acquired.
        """
        while True:
            if self._implicit_lock.acquire(blocking=False):
                return b""

            token = self.acquire_nonblocking()
            if token is not None:
                return token

            if self._fd is None and not self.open():
                self._implicit_lock.acquire(blocking=True)
                return b""

            try:
                r, _, _ = select.select([self._fd], [], [], 0.005)
                if r:
                    token = self.acquire_nonblocking()
                    if token is not None:
                        return token
            except (OSError, ValueError):
                pass

    def release(self, token: bytes) -> bool:
        """
        Release a previously acquired token back to the jobserver.
        If token is b"" (implicit slot), releases the internal lock.
        Otherwise, writes the token byte back to the FIFO.
        """
        if token == b"":
            try:
                self._implicit_lock.release()
                return True
            except RuntimeError:
                return False
        if not token:
            return True
        if self._fd is None and not self.open():
            return False
        try:
            os.write(self._fd, token)
            return True
        except OSError:
            self.close()
            return False

# Copyright 2026 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

import os
import shutil
import tempfile

from portage.tests import TestCase
from portage.util.jobserver import JobServerClient


class JobServerClientTestCase(TestCase):
    def testParseMakeflags(self):
        parse = JobServerClient._parse_makeflags
        self.assertIsNone(parse(None))
        self.assertIsNone(parse(""))
        self.assertIsNone(parse("-j8 -l8"))
        self.assertIsNone(parse("--jobserver-auth=3,4"))
        self.assertIsNone(parse("--jobserver-fds=3,4"))

        self.assertEqual(
            parse("--jobserver-auth=fifo:/tmp/test_fifo"),
            "/tmp/test_fifo",
        )
        self.assertEqual(
            parse("-j4 --jobserver-auth=fifo:/tmp/test_fifo -l4"),
            "/tmp/test_fifo",
        )
        self.assertEqual(
            parse('--jobserver-auth="fifo:/tmp/test fifo"'),
            "/tmp/test fifo",
        )

    def testFromSettingsAndEnviron(self):
        tempdir = tempfile.mkdtemp()
        try:
            fifo_path = os.path.join(tempdir, "test.fifo")
            os.mkfifo(fifo_path)

            reg_path = os.path.join(tempdir, "regular.txt")
            with open(reg_path, "w") as f:
                f.write("not a fifo")

            # Valid FIFO in settings
            settings = {"MAKEFLAGS": f"--jobserver-auth=fifo:{fifo_path}"}
            client = JobServerClient.from_settings(settings)
            self.assertIsNotNone(client)
            self.assertEqual(client.fifo_path, fifo_path)

            # Valid FIFO in environment
            env = {"GNUMAKEFLAGS": f"--jobserver-auth=fifo:{fifo_path}"}
            client = JobServerClient.from_environ(env)
            self.assertIsNotNone(client)
            self.assertEqual(client.fifo_path, fifo_path)

            # Not a FIFO (regular file)
            settings_reg = {"MAKEFLAGS": f"--jobserver-auth=fifo:{reg_path}"}
            self.assertIsNone(JobServerClient.from_settings(settings_reg))

            # Non-existent file
            settings_nonexistent = {
                "MAKEFLAGS": f"--jobserver-auth=fifo:{fifo_path}.nonexistent"
            }
            self.assertIsNone(JobServerClient.from_settings(settings_nonexistent))
        finally:
            shutil.rmtree(tempdir)

    def testAcquireAndRelease(self):
        tempdir = tempfile.mkdtemp()
        try:
            fifo_path = os.path.join(tempdir, "test.fifo")
            os.mkfifo(fifo_path)

            client = JobServerClient(fifo_path)
            with client:
                # Initially empty FIFO: acquire() gets the implicit token b""
                t_implicit = client.acquire()
                self.assertEqual(t_implicit, b"")

                # Put two tokens into the FIFO
                os.write(client._fd, b"+-")

                # Next acquire() gets a token from the FIFO
                t1 = client.acquire()
                self.assertEqual(t1, b"+")
                t2 = client.acquire()
                self.assertEqual(t2, b"-")

                # Release implicit token
                self.assertTrue(client.release(t_implicit))

                # Now implicit slot is available again
                self.assertEqual(client.acquire(), b"")

                # Release FIFO tokens back
                self.assertTrue(client.release(t1))
                self.assertTrue(client.release(t2))

                # Read them back directly
                tokens_in_fifo = os.read(client._fd, 10)
                self.assertEqual(tokens_in_fifo, b"+-")
        finally:
            shutil.rmtree(tempdir)

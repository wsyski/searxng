# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring,disable=missing-class-docstring,invalid-name
"""Shared testing code."""

import sys
import os
import subprocess
import traceback
import pathlib
import shutil

from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from splinter import Browser

import tests as searx_tests
from tests.robot import test_webapp


class SearxRobotLayer:
    """Searx Robot Test Layer"""

    def setUp(self):
        os.setpgrp()  # create new process group, become its leader

        tests_path = pathlib.Path(searx_tests.__file__).resolve().parent

        # get program paths
        webapp = str(tests_path.parent / 'searx' / 'webapp.py')
        exe = 'python'

        # set robot settings path
        os.environ['SEARXNG_SETTINGS_PATH'] = str(tests_path / 'robot' / 'settings_robot.yml')

        # run the server
        self.server = subprocess.Popen(  # pylint: disable=consider-using-with
            [exe, webapp], stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        if hasattr(self.server.stdout, 'read1'):
            print(self.server.stdout.read1(1024).decode())

    def tearDown(self):
        os.kill(self.server.pid, 9)
        # remove previously set environment variable
        del os.environ['SEARXNG_SETTINGS_PATH']


def _driver_options():
    """Resolve the browser and the driver the build system actually installed.

    `gecko.driver` (manage) pins a geckodriver version and unpacks it into
    ${PY_ENV_BIN}, which manage prepends to PATH, so `which` finds it. Handing
    that path to selenium is the point of this function: left to itself
    (`service=None`) selenium invokes Selenium Manager, which probes the host for
    a browser independently of PATH. Where /usr/bin/firefox is a packaging
    wrapper rather than the browser - Ubuntu's snap shim is exactly that - the
    manager runs the wrapper, reads a version string off it, and then hands
    geckodriver the WRAPPER. geckodriver execs it, the wrapper exits 1, and the
    failure arrives as "Process unexpectedly closed with status 1", naming neither
    the cause nor the fix.

    Resolving `firefox` the same way keeps the two in step: whichever browser is
    first on PATH is the one actually under test, rather than a second, unrelated
    one found by a different search.
    """
    options = Options()
    binary = shutil.which('firefox')
    if binary:
        options.binary_location = binary
    return options, Service(executable_path=shutil.which('geckodriver'))


def run_robot_tests(tests):
    print('Running {0} tests'.format(len(tests)))

    for test in tests:
        options, service = _driver_options()
        print(f'browser: {options.binary_location} ({_version(options.binary_location)})')
        print(f'driver:  {service.path}')
        with Browser(
            'firefox',
            headless=True,
            options=options,
            service=service,
            profile_preferences={'intl.accept_languages': 'en'},
        ) as browser:
            test(browser)


def _version(binary):
    """The browser's own version string, so the log says what ran.

    Not an assertion: this suite's job is the webapp, and a browser version is
    only recorded here to make a host-specific failure legible afterwards.
    """
    try:
        out = subprocess.run([binary, '-v'], capture_output=True, text=True, timeout=30, check=False)
        return (out.stdout or out.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def main():
    test_layer = SearxRobotLayer()
    try:
        test_layer.setUp()
        run_robot_tests([getattr(test_webapp, x) for x in dir(test_webapp) if x.startswith('test_')])
    except Exception:  # pylint: disable=broad-except
        print('Error occurred: {0}'.format(traceback.format_exc()))
        sys.exit(1)
    finally:
        test_layer.tearDown()


if __name__ == '__main__':
    main()

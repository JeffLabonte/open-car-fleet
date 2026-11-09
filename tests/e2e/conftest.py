"""Shared helpers for the end-to-end Selenium suites."""

import os
from urllib.parse import urljoin

from selenium import webdriver


def base_url() -> str:
    """Return the base URL of the running application server."""
    return os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def e2e_url(path: str) -> str:
    """Build an absolute URL from a path."""
    return urljoin(base_url(), path)


def sign_in_with_test_session(
    driver: webdriver.Firefox,
    email: str,
    next_url: str = "/",
) -> None:
    """Sign the browser in using the DEBUG-only /set-test-session/ helper.

    The helper uses a same-origin form POST so the email is not exposed in the
    URL query string. Callers should wait for navigation to ``next_url``
    afterwards.
    """
    driver.get(e2e_url("/login/"))
    driver.execute_script(
        """
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = '/set-test-session/';
        const emailInput = document.createElement('input');
        emailInput.type = 'hidden';
        emailInput.name = 'email';
        emailInput.value = arguments[0];
        form.appendChild(emailInput);
        const nextInput = document.createElement('input');
        nextInput.type = 'hidden';
        nextInput.name = 'next';
        nextInput.value = arguments[1];
        form.appendChild(nextInput);
        document.body.appendChild(form);
        form.submit();
        """,
        email,
        next_url,
    )

import { Hanko } from '../vendor/hanko/hanko-frontend-sdk.js';
import { register } from '../vendor/hanko/hanko-elements.js';

const apiUrl = JSON.parse(document.getElementById('hanko-api-url').textContent);
const nextUrl = JSON.parse(document.getElementById('hanko-next-url').textContent);
const loggedOut = JSON.parse(document.getElementById('hanko-logged-out').textContent);
const authContainer = document.getElementById('hanko-auth-container');

if (!apiUrl) {
  const message = 'Missing HANKO_API_URL. Set it in .env and restart the server.';
  console.error(message);
  authContainer.textContent = message;
  throw new Error(message);
}

const hanko = new Hanko(apiUrl);

// If the user explicitly logged out, terminate the frontend Hanko session
// before any auto-login checks run.
if (loggedOut) {
  try {
    await hanko.logout();
  } catch (error) {
    console.warn('Unable to fully terminate Hanko session on logout.', error);
  }
}

/**
 * Validate a redirect URL supplied by an untrusted source (e.g. a JSON
 * response). Only same-origin relative paths are accepted so that assigning
 * the value to window.location cannot be abused as an open redirect or
 * javascript: URL sink.
 */
function isSafeRedirectUrl(value) {
  if (typeof value !== 'string') {
    return false;
  }
  const url = value.trim();
  if (!url) {
    return false;
  }
  // Reject protocol-relative URLs and any string that begins with a URL
  // scheme (e.g. http:, https:, javascript:, data:).
  if (/^\/\//.test(url) || /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(url)) {
    return false;
  }
  // Require a relative path.
  if (!url.startsWith('/')) {
    return false;
  }
  // Final same-origin sanity check.
  try {
    const parsed = new URL(url, window.location.origin);
    return parsed.origin === window.location.origin;
  } catch {
    return false;
  }
}

function showCallbackError() {
  const errorBox = document.getElementById('hanko-callback-error');
  if (errorBox) {
    errorBox.classList.remove('is-hidden');
  }
}

async function finishLogin() {
  try {
    const session = await hanko.validateSession();
    if (!session?.is_valid) {
      return false;
    }

    const sessionToken = hanko.getSessionToken();
    if (!sessionToken) {
      console.error('Hanko session is valid but no session token is available.');
      return false;
    }

    const user = await hanko.getCurrentUser();
    const payload = {
      id: user?.user_id || user?.id || '',
      email: user?.emails?.[0]?.address || user?.email || '',
      name: user?.name || user?.display_name || user?.emails?.[0]?.address || '',
      display_name: user?.display_name || user?.name || user?.emails?.[0]?.address || '',
      avatar_url: user?.avatar_url || user?.avatar || '',
      provider: 'hanko',
      session_token: sessionToken,
      next: nextUrl,
    };

    const csrfToken = document.cookie
      .split('; ')
      .find((row) => row.startsWith('csrftoken='))
      ?.split('=')[1] || '';

    const response = await fetch('/auth/hanko/callback/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': decodeURIComponent(csrfToken),
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      showCallbackError();
      throw new Error(`Login callback failed with status ${response.status}`);
    }

    const callbackPayload = await response.json().catch(() => ({}));

    const redirectTarget = isSafeRedirectUrl(callbackPayload.redirect_url)
      ? callbackPayload.redirect_url.trim()
      : isSafeRedirectUrl(nextUrl)
        ? nextUrl.trim()
        : '/';

    // Always resolve the redirect through URL so the value assigned to the
    // location sink is guaranteed to be a same-origin path. redirectTarget is
    // already validated as a same-origin relative path by isSafeRedirectUrl.
    window.location.href = new URL(redirectTarget, window.location.origin).href; // NOSONAR
    return true;
  } catch (error) {
    console.error('Hanko login callback failed.', error);
    showCallbackError();
    return false;
  }
}

try {
  const { hanko: elementsHanko } = await register(apiUrl);
  elementsHanko.onSessionCreated(async () => {
    await finishLogin();
  });

  const existingSession = await hanko.validateSession();
  if (existingSession?.is_valid && !loggedOut) {
    await finishLogin();
  }
} catch (error) {
  const message = 'Unable to load the Hanko login form. Please check your internet connection, disable ad blockers for this site, and verify HANKO_API_URL is correct.';
  console.error(message, error);
  authContainer.textContent = message;
  showCallbackError();
  throw error;
}

const retryButton = document.getElementById('hanko-retry-button');
if (retryButton) {
  retryButton.addEventListener('click', () => {
    const errorBox = document.getElementById('hanko-callback-error');
    if (errorBox) {
      errorBox.classList.add('is-hidden');
    }
    void finishLogin();
  });
}

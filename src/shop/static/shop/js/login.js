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
      throw new Error(`Login callback failed with status ${response.status}`);
    }

    window.location.href = nextUrl;
    return true;
  } catch (error) {
    console.error('Hanko login callback failed.', error);
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
  throw error;
}

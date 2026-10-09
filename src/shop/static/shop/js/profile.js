import { register } from './hanko/hanko-elements.js';

const apiUrl = JSON.parse(document.getElementById('hanko-api-url').textContent);
const profileContainer = document.getElementById('hanko-profile-container');

if (!apiUrl) {
  const message = 'Missing HANKO_API_URL. Set it in .env and restart the server.';
  console.error(message);
  profileContainer.textContent = message;
  throw new Error(message);
}

try {
  await register(apiUrl);
} catch (error) {
  const message = 'Unable to load the Hanko profile. Please check your internet connection, disable ad blockers for this site, and verify HANKO_API_URL is correct.';
  console.error(message, error);
  profileContainer.textContent = message;
  throw error;
}

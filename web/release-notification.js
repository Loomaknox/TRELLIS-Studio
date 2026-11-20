import {t} from './i18n.js';

const notice = document.getElementById('studioReleaseUpdate');
const storageKey = 'trellis.dismissedRelease';

function dismissedVersion() {
  try {
    return localStorage.getItem(storageKey);
  } catch {
    return null;
  }
}

if (notice) {
  async function checkRelease() {
    const response = await fetch('/api/release-status', {cache: 'no-store', credentials: 'same-origin'});
    if (!response.ok) return;
    const {update} = await response.json();
    if (!update || update.version === dismissedVersion()) return;

    const summary = notice.querySelector('summary');
    const heading = t('Studio {version} is available', {version: update.version});
    summary.setAttribute('aria-label', heading);
    document.getElementById('studioReleaseLabel').textContent = heading;
    document.getElementById('studioReleaseLink').href = update.url;
    document.getElementById('studioReleaseDismiss').onclick = () => {
      try {
        localStorage.setItem(storageKey, update.version);
      } catch {
        // This browser session can still dismiss the indicator.
      }
      notice.open = false;
      notice.hidden = true;
      document.querySelector('.topbar .brand')?.focus({preventScroll: true});
    };
    notice.addEventListener('keydown', event => {
      if (event.key !== 'Escape' || !notice.open) return;
      notice.open = false;
      summary.focus();
    });
    document.addEventListener('click', event => {
      if (notice.open && !notice.contains(event.target)) notice.open = false;
    });
    notice.hidden = false;
  }

  checkRelease().catch(() => {
    // Offline access to Studio does not depend on the release check.
  });
}

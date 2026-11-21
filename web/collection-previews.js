function loadReference(media) {
  const reference = media.querySelector(':scope > img[data-reference-url]');
  if (reference && !reference.hasAttribute('src')) reference.src = reference.dataset.referenceUrl;
}

function previewUrls(preview) {
  if (!preview?.textured_url || !preview?.clay_url) return null;
  try {
    const urls = [preview.textured_url, preview.clay_url].map(value => new URL(value, location.href));
    return urls.every(url => url.origin === location.origin && url.protocol === location.protocol)
      ? urls.map(url => url.href) : null;
  } catch {
    return null;
  }
}

export function createCollectionPreviews() {
  const entries = new Map();
  const observer = new IntersectionObserver(records => {
    for (const record of records) {
      if (!record.isIntersecting) continue;
      observer.unobserve(record.target);
      const entry = entries.get(record.target);
      if (entry && !entry.media.dataset.collectionPreview) void display(entry);
    }
  });

  function paintWipe(entry) {
    if (!entry.layer) return;
    const {media, hovered, focused, inputKind} = entry;
    const keyboard = focused && (!hovered || inputKind === 'keyboard');
    const wipe = keyboard ? entry.keyboardWipe : hovered ? entry.pointerWipe : 0;
    media.style.setProperty('--collection-preview-wipe', `${wipe}%`);
    media.classList.toggle('collection-preview-wiping', wipe > 0 && wipe < 100);
  }

  async function display(entry) {
    const {media, button, urls} = entry;
    const textured = new Image();
    const clay = new Image();
    textured.className = 'collection-preview-textured';
    clay.className = 'collection-preview-clay';
    textured.alt = '';
    clay.alt = '';
    media.dataset.collectionPreview = 'loading';
    media.setAttribute('aria-busy', 'true');
    try {
      [textured.src, clay.src] = urls;
      await Promise.all([textured.decode(), clay.decode()]);
      if (entries.get(media) !== entry) return;
      const layer = document.createElement('span');
      layer.className = 'collection-preview-render';
      layer.setAttribute('aria-hidden', 'true');
      const divider = document.createElement('span');
      divider.className = 'collection-preview-divider';
      layer.append(textured, clay, divider);
      entry.layer = layer;
      media.append(layer);
      media.dataset.collectionPreview = 'ready';
      button?.setAttribute('aria-keyshortcuts', 'ArrowLeft ArrowRight');
      paintWipe(entry);
    } catch {
      if (entries.get(media) !== entry) return;
      media.dataset.collectionPreview = 'fallback';
      loadReference(media);
    } finally {
      if (entries.get(media) === entry) media.removeAttribute('aria-busy');
    }
  }

  function remove(media) {
    const entry = entries.get(media);
    if (!entry) return;
    entries.delete(media);
    observer.unobserve(media);
    entry.listeners.abort();
    entry.button?.removeAttribute('aria-keyshortcuts');
    entry.layer?.remove();
    delete media.dataset.collectionPreview;
    media.removeAttribute('aria-busy');
    media.style.removeProperty('--collection-preview-wipe');
    media.classList.remove('collection-preview-wiping');
  }

  return {
    clear() {
      for (const media of entries.keys()) remove(media);
    },
    watch(media, preview) {
      const urls = previewUrls(preview);
      const previous = entries.get(media);
      if (!urls) {
        remove(media);
        loadReference(media);
        return;
      }
      if (previous?.urls[0] === urls[0] && previous.urls[1] === urls[1]) return;
      remove(media);
      const button = media.closest('button.card-open');
      const entry = {
        media, button, urls, listeners: new AbortController(),
        hovered: false, focused: button?.matches(':focus-visible') === true,
        pointerWipe: 0, keyboardWipe: 50,
      };
      entries.set(media, entry);
      const options = {signal: entry.listeners.signal};
      const move = event => {
        if (event.pointerType !== 'mouse') return;
        const rect = media.getBoundingClientRect();
        entry.hovered = true;
        entry.inputKind = 'pointer';
        entry.pointerWipe = rect.width ? Math.max(0, Math.min(100, 100 * (event.clientX - rect.left) / rect.width)) : 0;
        paintWipe(entry);
      };
      media.addEventListener('pointerenter', move, options);
      media.addEventListener('pointermove', move, options);
      media.addEventListener('pointerleave', () => {
        entry.hovered = false;
        entry.pointerWipe = 0;
        paintWipe(entry);
      }, options);
      button?.addEventListener('focus', () => {
        if (!button.matches(':focus-visible')) return;
        entry.focused = true;
        entry.inputKind = 'keyboard';
        entry.keyboardWipe = 50;
        paintWipe(entry);
      }, options);
      button?.addEventListener('keydown', event => {
        if (!entry.focused || !entry.layer || event.target !== button || button.closest('.turntable-playing')
            || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return;
        event.preventDefault();
        entry.inputKind = 'keyboard';
        entry.keyboardWipe = Math.max(0, Math.min(100, entry.keyboardWipe + (event.key === 'ArrowLeft' ? -10 : 10)));
        paintWipe(entry);
      }, options);
      button?.addEventListener('blur', () => {
        entry.focused = false;
        paintWipe(entry);
      }, options);
      observer.observe(media);
    },
  };
}

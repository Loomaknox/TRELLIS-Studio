import { language, localizeStatic, setLanguage } from './i18n.js';

document.documentElement.lang = language;
localizeStatic(document.documentElement);

const container = document.querySelector('[data-language-selector]');
if (container) {
  const select = document.createElement('select');
  select.className = 'studio-language-select';
  select.setAttribute('aria-label', language === 'fr' ? 'Langue' : 'Language');
  for (const [code, name] of [['en', 'English'], ['fr', 'Français']]) {
    const option = new Option(name, code);
    option.lang = code;
    select.add(option);
  }
  select.value = language;
  select.addEventListener('change', () => setLanguage(select.value));
  container.replaceChildren(select);
}

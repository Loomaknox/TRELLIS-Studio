import assert from 'node:assert/strict';
import {test} from 'node:test';

test('browser language, preference and parameter substitution', async () => {
  const {chooseLanguage} = await import('../web/i18n.js');
  assert.equal(chooseLanguage(null, 'fr-CA'), 'fr');
  assert.equal(chooseLanguage(null, 'es-ES'), 'en');
  assert.equal(chooseLanguage('en', 'fr-FR'), 'en');
  assert.equal(chooseLanguage('fr', 'en-GB'), 'fr');
  assert.equal(chooseLanguage('de', 'fr'), 'fr');

  globalThis.location = {search: '?lang=fr'};
  try {
    const {language, t, localizeStatic} = await import('../web/i18n.js?fr-test');
    assert.equal(language, 'fr');
    const faceMessages = [
      'Enhance face (TOPOS)',
      'Use a front-facing T- or A-pose. Rebuilds the face before native PBR texturing.',
      'Install the optional face reconstruction component.',
      'Install the local TRELLIS.2 shape encoder and 1024 material weights.',
      'Fitting the facial surface and eye sockets',
      'Insufficient native geometry at the projected eyelid.',
      'The facial reference does not cover visible material voxels.',
      'Frame faces',
    ];
    for (const message of faceMessages) assert.notEqual(t(message), message);
    assert.equal(t('Queued'), 'En attente');
    assert.equal(t('Multiview refinement'), 'Affinage multivue');
    assert.equal(t('Unavailable'), 'Indisponible');
    assert.notEqual(t('Rig profile could not be applied'), 'Rig profile could not be applied');
    assert.equal(t('{value} GiB VRAM free', {value:'10,5'}), 'VRAM libre 10,5 Gio');
    assert.equal(t('Reference for {name}', {name: '{unknown} <avatar>'}), 'Référence de {unknown} <avatar>');
    assert.equal(t('A server-specific diagnostic'), 'A server-specific diagnostic');
    assert.equal(t('Back', undefined, 'navigation'), 'Retour');

    const label = {nodeType: 3, textContent: '  My models\n '};
    const attributes = new Map([['placeholder', 'Search models…'], ['data-key', 'My models']]);
    const input = {
      nodeType: 1, tagName: 'INPUT', childNodes: [],
      getAttribute: name => attributes.get(name),
      setAttribute: (name, value) => attributes.set(name, value),
    };
    const optionLabel = {nodeType: 3, textContent: 'My models'};
    const option = {
      nodeType: 1, tagName: 'OPTION', childNodes: [optionLabel],
      getAttribute: () => null,
      hasAttribute: name => name === 'value' && option.savedValue !== undefined,
      get value() { return this.savedValue ?? optionLabel.textContent; },
      set value(value) { this.savedValue = value; },
    };
    optionLabel.parentElement = option;
    localizeStatic({
      nodeType: 1, tagName: 'TEMPLATE', getAttribute: () => null,
      content: {childNodes: [label, input, option]},
    });
    assert.equal(label.textContent, '  Mes modèles\n ');
    assert.notEqual(attributes.get('placeholder'), 'Search models…');
    assert.equal(attributes.get('data-key'), 'My models');
    assert.equal(optionLabel.textContent, 'Mes modèles');
    assert.equal(option.value, 'My models');

    globalThis.location.search = '?lang=en';
    const {language: english, t: translateEnglish} = await import('../web/i18n.js?en-test');
    assert.equal(english, 'en');
    for (const message of faceMessages) assert.equal(translateEnglish(message), message);
    assert.equal(translateEnglish('Queued'), 'Queued');
    assert.equal(translateEnglish('Multiview refinement'), 'Multiview refinement');
    assert.equal(translateEnglish('Reference for {name}', {name: 'Avatar'}), 'Reference for Avatar');
  } finally {
    delete globalThis.location;
  }
});

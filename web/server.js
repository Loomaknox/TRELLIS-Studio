import './language-selector.js';
import {t, formatLocale, translateStage} from './i18n.js';
import {
  request, getUser, element, avatar, nameOf, diskLimit, diskUsed, availableCredits, formatBytes, formatNumber,
} from './server-shell.js?v=3.4.0';

const byId = id => document.getElementById(id);
const main = byId('server-main');
const route = location.pathname.replace(/\/$/, '');
const socialNames = {linkedin: 'LinkedIn', github: 'GitHub', mastodon: 'Mastodon', instagram: 'Instagram', other: t('Other link')};
const socialKeys = Object.keys(socialNames);
const dateFormat = new Intl.DateTimeFormat(formatLocale, {dateStyle: 'short', timeStyle: 'short'});
const stateNames = {
  active: t('Active'), pending: t('Pending'), disabled: t('Disabled'), queued: t('Queued'), running: t('Running'),
  done: t('Completed'), error: t('Failed'), failed: t('Failed'), cancelled: t('Cancelled'), paused: t('Paused'),
};
const roleName = user => user.role === 'admin' ? t('Administrator') : t('User');
const isMfa = user => user.totp_enabled ?? user.mfa_enabled;
const withData = form => Object.fromEntries(new FormData(form));

function render(template) {
  main.replaceChildren(byId(`${template}-template`).content.cloneNode(true));
}

function notice(node, text = '', error = false) {
  node.textContent = text;
  node.hidden = !text;
  node.toggleAttribute('data-error', error);
  if (text && node.closest('dialog')?.open) node.scrollIntoView({block: 'nearest'});
}

async function perform(control, feedback, action) {
  if (control.disabled) return;
  control.disabled = true;
  notice(feedback);
  try { await action(); }
  catch (error) { notice(feedback, error.message, true); }
  finally { control.disabled = false; }
}

function bindForm(id, feedback, action) {
  const form = byId(id);
  form.addEventListener('submit', event => {
    event.preventDefault();
    const submit = event.submitter || form.querySelector('[type=submit]');
    perform(submit, byId(feedback), () => action(withData(form), form));
  });
  return form;
}

function checkPassword(data, key = 'password') {
  if (data[key] !== data.confirm_password) throw new Error(t('The passwords do not match.'));
  delete data.confirm_password;
}

function post(path, body = {}) {
  return request(path, {method: 'POST', body});
}

function patch(path, body) {
  return request(path, {method: 'PATCH', body});
}

function dateOf(value) {
  if (!value) return '—';
  const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? '—' : dateFormat.format(date);
}

function stateChip(state) {
  const badge = element('span', 'server-chip', stateNames[state] || state || '—');
  badge.dataset.state = state || '';
  return badge;
}

function progress(value, max, label) {
  const bar = element('progress');
  bar.max = max;
  bar.value = Math.min(value, max);
  bar.setAttribute('aria-label', label);
  return bar;
}

function metric(label, value, hint, bar) {
  const card = element('div', 'server-metric');
  card.append(element('span', '', label), element('strong', '', value));
  if (hint) card.append(element('small', '', hint));
  if (bar) card.append(bar);
  return card;
}

function activity(title, detail, side) {
  const row = element('div', 'server-activity-row');
  const description = element('div');
  description.append(element('strong', '', title), element('small', '', detail));
  row.append(description);
  if (side) row.append(side);
  return row;
}

function showList(container, rows, empty) {
  container.replaceChildren(...(rows.length ? rows : [element('p', 'server-empty', empty)]));
}

function button(label, action, className = 'server-secondary') {
  const control = element('button', className, label);
  control.type = 'button';
  control.addEventListener('click', () => action(control));
  return control;
}

function tabs(group, initial, changed) {
  const controls = [...byId(group).querySelectorAll('[role=tab]')].filter(control => !control.disabled);
  function activate(name, focus = false) {
    const current = controls.find(control => control.dataset.tab === name) || controls[0];
    for (const control of controls) {
      const selected = control === current;
      control.tabIndex = selected ? 0 : -1;
      control.setAttribute('aria-selected', String(selected));
      byId(control.getAttribute('aria-controls')).hidden = !selected;
    }
    if (focus) current.focus();
    changed?.(current.dataset.tab);
  }
  controls.forEach((control, index) => {
    control.addEventListener('click', () => activate(control.dataset.tab));
    control.addEventListener('keydown', event => {
      const offset = {ArrowRight: 1, ArrowLeft: -1}[event.key];
      let next = index;
      if (offset) next = (index + offset + controls.length) % controls.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = controls.length - 1;
      else return;
      event.preventDefault();
      activate(controls[next].dataset.tab, true);
    });
  });
  activate(initial);
  return activate;
}

function destination(user) {
  return user.password_change_required || user.mfa_setup_required ? '/server/account#security' : '/';
}

function loginPage() {
  render('auth');
  const login = byId('login-section');
  const register = byId('register-section');
  const feedback = byId('auth-notice');
  const changed = new URLSearchParams(location.search).get('changed');
  if (changed === 'password') notice(feedback, t('Password changed. Sign in with your new password.'));
  const toggle = (showRegistration, focus = true) => {
    login.hidden = showRegistration;
    register.hidden = !showRegistration;
    notice(feedback);
    if (focus) (showRegistration ? register : login).querySelector('input').focus();
  };
  byId('show-register').addEventListener('click', () => toggle(true));
  byId('show-login').addEventListener('click', () => toggle(false));
  bindForm('login-form', 'auth-notice', async data => {
    if (!data.code.trim()) delete data.code;
    try {
      const response = await post('/login', data);
      location.replace(destination(getUser(response)));
    } catch (error) {
      if (['mfa_required', 'totp_required', 'invalid_factor'].includes(error.code)) {
        byId('login-code-details').open = true;
        byId('login-form').elements.code.focus();
      }
      throw error;
    }
  });
  bindForm('register-form', 'auth-notice', async (data, form) => {
    checkPassword(data);
    await post('/register', data);
    form.reset();
    toggle(false);
    byId('login-form').elements.email.value = data.email;
    notice(feedback, t('Request received. You can sign in once an administrator activates your account.'));
  });
}

function setupPage() {
  render('setup');
  const token = new URLSearchParams(location.hash.slice(1)).get('token');
  if (location.hash) history.replaceState(null, '', location.pathname);
  const form = byId('setup-form');
  const feedback = byId('setup-notice');
  if (!token) {
    form.hidden = true;
    notice(feedback, t('Return to the installer to open a valid setup link.'), true);
    return;
  }
  bindForm('setup-form', 'setup-notice', async data => {
    checkPassword(data);
    await post('/setup', {...data, token});
    form.reset();
    form.hidden = true;
    notice(feedback, t('Administrator account created. Return to the installer to finish setting up the server.'));
  });
}

function connectNavigation(user) {
  byId('server-navigation').hidden = false;
  byId('server-network').hidden = true;
  byId('admin-link').hidden = user.role !== 'admin' || user.mfa_setup_required || user.password_change_required;
  const restricted = user.mfa_setup_required || user.password_change_required;
  byId('server-navigation').querySelector('a[href="/"]').hidden = restricted;
  byId('server-docs-link').hidden = restricted;
  if (route === '/server/account') byId('account-link').setAttribute('aria-current', 'page');
  if (route === '/server/admin') byId('admin-link').setAttribute('aria-current', 'page');
  const logout = byId('server-logout');
  logout.addEventListener('click', async () => {
    logout.disabled = true;
    try { await post('/logout'); }
    finally { location.replace('/server/login'); }
  });
}

function profileIdentity(user, stamp = '') {
  avatar(byId('profile-avatar'), user, stamp);
  byId('profile-name').textContent = nameOf(user);
  byId('profile-email').textContent = user.email;
  byId('profile-role').textContent = roleName(user);
}

function fill(form, data, keys) {
  for (const key of keys) form.elements[key].value = data[key] ?? '';
}

function usagePage(user) {
  const used = diskUsed(user);
  const limit = diskLimit(user);
  const admin = user.role === 'admin';
  const reserved = user.storage_reserved_bytes
    ? ` · ${t('{size} reserved', {size: formatBytes(user.storage_reserved_bytes)})}` : '';
  byId('usage-metrics').replaceChildren(
    metric(t('Storage used'), formatBytes(used), admin ? t('Unlimited quota') : `${t('of {size}', {size: formatBytes(limit)})}${reserved}`,
      limit > 0 ? progress(used, limit, t('Storage used')) : null),
    metric(t('Available credits'), admin ? t('Unlimited') : formatNumber(availableCredits(user)), t('New generations')),
    metric(t('Reserved credits'), admin ? '—' : formatNumber(user.credits_reserved || 0), t('Queued or running generations')),
  );
}

function usageLedger(data) {
  const labels = {reserve: t('Credit reserved'), reserved: t('Credit reserved'), debit: t('Generation completed'),
    charged: t('Generation completed'), release: t('Reservation released'), released: t('Reservation released'),
    grant: t('Credits granted'), adjust: t('Credit adjustment'), adjustment: t('Credit adjustment')};
  const entries = data.ledger || data.entries || [];
  return entries.map(entry => {
    const action = entry.kind || entry.action || entry.event;
    const amount = entry.delta ?? entry.amount;
    const suffix = typeof amount === 'number' && amount !== 0
      ? element('strong', '', `${amount > 0 ? '+' : ''}${formatNumber(amount)}`) : null;
    return activity(labels[action] || action || t('Credit activity'),
      [dateOf(entry.created_at || entry.created), entry.reason].filter(Boolean).join(' · '), suffix);
  });
}

function secureAccount(user) {
  const enrolled = isMfa(user);
  byId('mfa-summary').textContent = user.role === 'admin'
    ? (enrolled ? t('Two-factor authentication is required for administrators and cannot be disabled.')
                : t('Administrators must set up two-factor authentication before using Studio.'))
    : (enrolled ? t('Two-factor authentication is enabled. You can disable it below.')
                : t('Two-factor authentication is optional for your account. Use an authenticator app for extra protection.'));
  byId('mfa-action').textContent = enrolled ? t('Disable two-factor authentication') : t('Set up two-factor authentication');
  const start = byId('mfa-start-form');
  const locked = (enrolled && user.role === 'admin') || user.password_change_required;
  start.hidden = locked;
  byId('mfa-disable-code').hidden = !enrolled;
  start.elements.code.required = Boolean(enrolled);
  bindForm('password-form', 'password-notice', async (data, form) => {
    checkPassword(data, 'new_password');
    await post('/password', data);
    form.reset();
    location.replace('/server/login?changed=password');
  });
  bindForm('mfa-start-form', 'mfa-notice', async (data, form) => {
    if (enrolled) {
      if (!confirm(t('Disable two-factor authentication for your account?'))) return;
      await post('/mfa/disable', data);
      form.reset();
      location.replace('/server/login');
      return;
    }
    const setup = await post('/mfa/setup', {password: data.password});
    form.reset();
    byId('mfa-secret').textContent = setup.secret;
    const qr = byId('mfa-qr');
    qr.hidden = !/^data:image\/png;base64,[a-zA-Z0-9+/=]+$/.test(setup.qr_data_url || '');
    if (!qr.hidden) qr.src = setup.qr_data_url;
    else qr.removeAttribute('src');
    byId('mfa-qr-instruction').hidden = qr.hidden;
    byId('mfa-setup').hidden = false;
    byId('mfa-enable-form').elements.code.focus();
  });
  bindForm('mfa-enable-form', 'mfa-notice', async data => {
    const result = await post('/mfa/enable', data);
    byId('mfa-setup').hidden = true;
    start.hidden = true;
    byId('mfa-secret').textContent = '';
    byId('mfa-qr').removeAttribute('src');
    const recovery = byId('mfa-recovery');
    const list = element('ul', 'server-recovery-list');
    list.append(...(result.recovery_codes || []).map(code => {
      const item = element('li');
      item.append(element('code', '', code));
      return item;
    }));
    const message = element('p', '', t('Store these recovery codes in a safe place. Each code can be used once.'));
    const loginLink = element('a', 'server-primary', t('Sign in again'));
    loginLink.href = '/server/login';
    const actions = element('div', 'server-actions');
    actions.append(loginLink);
    recovery.replaceChildren(message, list, actions);
    recovery.hidden = false;
    notice(byId('mfa-notice'), t('Two-factor authentication enabled.'));
  });
}

function apiKeys(restricted) {
  byId('api-token-locked').hidden = !restricted;
  byId('api-token-controls').hidden = restricted;
  if (restricted) return () => {};

  const list = byId('api-token-list');
  const feedback = byId('api-token-notice');
  const secret = byId('api-token-secret');
  const reveal = byId('api-token-reveal');
  const hide = byId('api-token-hide');
  let latestList = 0;
  let revealedKey;
  byId('api-token-origin').textContent = location.origin;

  function clearKey() {
    revealedKey = undefined;
    secret.value = '';
    reveal.hidden = true;
  }

  async function loadKeys() {
    const revision = ++latestList;
    try {
      const {tokens} = await request('/tokens');
      if (revision !== latestList) return;
      const rows = tokens.map(key => {
        const revoke = button(t('Revoke'), control => perform(control, feedback, async () => {
          if (!confirm(t('Revoke “{label}”? Clients using this key will need a replacement key.', {label: key.label}))) return;
          await request(`/tokens/${encodeURIComponent(key.id)}`, {method: 'DELETE'});
          if (revealedKey === key.id) clearKey();
          notice(feedback, t('API key revoked.'));
          await loadKeys();
        }));
        revoke.setAttribute('aria-label', t('Revoke API key {label}', {label: key.label}));
        const detail = [`${key.prefix}…`, t('Created {date}', {date: dateOf(key.created)})];
        if (key.last_used) detail.push(t('Last used {date}', {date: dateOf(key.last_used)}));
        return activity(key.label, detail.join(' · '), revoke);
      });
      showList(list, rows, t('No API keys yet.'));
    } catch (error) {
      if (revision === latestList) notice(feedback, error.message, true);
    }
  }

  bindForm('api-token-form', 'api-token-notice', async (data, form) => {
    const label = data.label.trim();
    if (!label) throw new Error(t('Enter a name for the API key.'));
    const result = await post('/tokens', {label});
    form.reset();
    if (byId('panel-security').hidden) {
      notice(feedback, t('API key created. To get a new key, revoke this one and create another.'));
      return;
    }
    revealedKey = result.key.id;
    secret.value = result.token;
    reveal.hidden = false;
    byId('api-token-copy').focus();
    await loadKeys();
  });
  byId('api-token-copy').addEventListener('click', event => perform(event.currentTarget, feedback, async () => {
    try {
      await navigator.clipboard.writeText(secret.value);
      notice(feedback, t('API key copied.'));
    } catch {
      secret.focus();
      secret.select();
      notice(feedback, t('API key selected. Use your keyboard shortcut to copy it.'));
    }
  }));
  hide.addEventListener('click', () => {
    clearKey();
    byId('api-token-form').elements.label.focus();
  });
  window.addEventListener('pagehide', clearKey);
  return tab => {
    if (tab === 'security') loadKeys();
    else clearKey();
  };
}

function accountPage(user) {
  render('account');
  connectNavigation(user);
  profileIdentity(user);
  const restricted = user.password_change_required || user.mfa_setup_required;
  if (restricted) {
    main.querySelector('.server-page-heading a').hidden = true;
    for (const key of ['profile', 'usage']) {
      byId(`tab-${key}`).disabled = true;
      byId(`tab-${key}`).hidden = true;
      byId(`panel-${key}`).hidden = true;
    }
    notice(byId('account-required'), user.password_change_required
      ? t('Choose a new password to access Studio.')
      : t('Enable two-factor authentication to access Studio and Administration.'));
  }

  const profile = byId('profile-form');
  const profileKeys = ['first_name', 'last_name', 'email', 'bio', 'website'];
  fill(profile, user, profileKeys);
  fill(profile, user.social_links || {}, socialKeys);
  if (socialKeys.some(key => user.social_links?.[key])) byId('social-details').open = true;
  bindForm('profile-form', 'profile-notice', async data => {
    delete data.email;
    data.social_links = {};
    for (const key of socialKeys) {
      if (data[key].trim()) data.social_links[key] = data[key].trim();
      delete data[key];
    }
    user = getUser(await patch('/me', data));
    profileIdentity(user);
    fill(profile, user, profileKeys);
    notice(byId('profile-notice'), t('Profile saved.'));
  });

  const avatarForm = byId('avatar-form');
  const fileInput = avatarForm.elements.file;
  const avatarSave = byId('avatar-save');
  let preview;
  function discardPreview() {
    if (preview) URL.revokeObjectURL(preview);
    preview = undefined;
  }
  fileInput.addEventListener('change', () => {
    discardPreview();
    const file = fileInput.files[0];
    avatarSave.hidden = true;
    if (!file) { profileIdentity(user); return; }
    if (file.size > 2 * 1024 ** 2 || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      fileInput.value = '';
      profileIdentity(user);
      notice(byId('avatar-notice'), t('Choose a JPEG, PNG, or WebP image up to 2 MiB.'), true);
      return;
    }
    preview = URL.createObjectURL(file);
    const image = element('img');
    image.alt = '';
    image.src = preview;
    byId('profile-avatar').replaceChildren(image);
    avatarSave.hidden = false;
    notice(byId('avatar-notice'), t('New avatar preview.'));
  });
  window.addEventListener('pagehide', discardPreview);
  bindForm('avatar-form', 'avatar-notice', async (_data, form) => {
    if (!fileInput.files.length) return;
    user = getUser(await post('/profile/avatar', new FormData(form)));
    form.reset();
    avatarSave.hidden = true;
    discardPreview();
    profileIdentity(user, Date.now());
    notice(byId('avatar-notice'), t('Avatar saved.'));
  });

  secureAccount(user);
  const showApiKeys = apiKeys(restricted);
  async function loadUsage() {
    const ledger = byId('usage-ledger');
    const cleanup = byId('usage-cleanup');
    usagePage(user);
    try {
      const data = await request('/usage');
      if (data.user || data.usage) {
        user = {...user, ...getUser(data.user || data.usage)};
        usagePage(user);
      }
      const breakdown = data.breakdown;
      byId('usage-breakdown').hidden = !breakdown;
      if (breakdown) {
        const labels = {models: t('Models and references'), caches: t('Remesh caches'), exports: t('Exports'),
          trash: t('Trash'), other: t('Other files')};
        byId('usage-storage').replaceChildren(...Object.entries(labels).map(([key, label]) =>
          activity(label, '', element('strong', '', formatBytes(breakdown[key] ?? 0)))));
      }
      showList(ledger, usageLedger(data), t('No credit activity yet.'));
      const rows = [
        ...(data.trash || []).map(item => ({...item, type: 'trash', label: t('Trash')})),
        ...(data.exports || []).map(item => ({...item, type: 'exports', label: t('Export', null, 'serverFile')})),
        ...(data.uploads || []).map(item => ({...item, type: 'uploads', label: t('Upload')})),
      ].map(item => {
        const feedback = element('p', 'server-notice');
        feedback.setAttribute('role', 'status');
        feedback.hidden = true;
        const remove = button(t('Delete'), control => perform(control, feedback, async () => {
          if (!confirm(t('Permanently delete this item?'))) return;
          await request(`/${item.type}/${encodeURIComponent(item.id)}`, {method: 'DELETE'});
          await loadUsage();
        }));
        const wrapper = element('div');
        wrapper.append(activity(item.name || item.id, `${item.label} · ${formatBytes(item.bytes)}`, remove), feedback);
        return wrapper;
      });
      showList(cleanup, rows, t('No files available for cleanup.'));
    } catch (error) {
      showList(ledger, [], error.message);
      cleanup.replaceChildren();
    }
  }
  const activate = tabs('account-tabs', restricted ? 'security' : location.hash.slice(1), tab => {
    history.replaceState(null, '', `${location.pathname}${tab === 'profile' ? '' : `#${tab}`}`);
    if (tab === 'usage') loadUsage();
    showApiKeys(tab);
  });
  window.addEventListener('hashchange', () => activate(location.hash.slice(1)));
}

function adminPage(actor) {
  document.title = t('TRELLIS Studio · Administration');
  render('admin');
  connectNavigation(actor);
  const feedback = byId('admin-notice');
  const dialog = byId('user-dialog');
  const dialogNotice = byId('user-dialog-notice');
  const form = byId('user-form');
  const search = byId('user-search');
  const filter = byId('user-filter');
  const temporary = byId('user-temporary');
  let users = [];
  let selected = null;
  let selectedTab = 'users';
  let queuePaused = false;

  function drawUsers() {
    const query = search.value.trim().toLowerCase();
    const visible = users.filter(user => (filter.value === 'all' || user.status === filter.value)
      && `${nameOf(user)} ${user.email}`.toLowerCase().includes(query));
    const rows = visible.map(user => {
      const row = element('tr');
      row.setAttribute('role', 'row');
      const identity = element('div', 'server-user-cell');
      const icon = element('span', 'server-avatar');
      avatar(icon, user);
      const text = element('div');
      text.append(element('strong', '', nameOf(user)), element('small', '', user.email));
      identity.append(icon, text);
      const storage = element('div', 'server-storage');
      const used = diskUsed(user);
      const limit = diskLimit(user);
      storage.append(element('span', '', user.role === 'admin' ? t('Unlimited') : `${formatBytes(used)} / ${formatBytes(limit)}`));
      if (limit > 0) storage.append(progress(used, limit, t('Storage used')));
      const open = button(user.status === 'pending' ? t('Review', null, 'accountRequest') : t('Details'), () => editUser(user));
      open.setAttribute('aria-label', `${open.textContent} · ${nameOf(user)}`);
      const cells = [identity, element('span', 'server-chip', roleName(user)), stateChip(user.status), storage,
        element('span', '', user.role === 'admin' ? t('Unlimited') : formatNumber(availableCredits(user))), open];
      for (const [index, content] of cells.entries()) {
        const cell = element('td');
        cell.setAttribute('role', 'cell');
        const label = ['', t('Role'), t('Status'), t('Storage'), t('Credits')][index];
        if (label) cell.dataset.label = label;
        cell.append(content);
        row.append(cell);
      }
      return row;
    });
    byId('user-list').replaceChildren(...rows);
    byId('users-empty').hidden = !!rows.length;
    const pending = users.filter(user => user.status === 'pending').length;
    byId('pending-count').textContent = formatNumber(pending);
    byId('pending-count').hidden = !pending;
  }

  async function loadUsers() {
    const result = await request('/admin/users');
    users = Array.isArray(result) ? result : result.users || [];
    drawUsers();
  }

  async function loadMetrics() {
    const data = await request('/admin/status');
    const total = typeof data.users === 'number' ? data.users : users.length;
    const pending = data.pending_users ?? users.filter(user => user.status === 'pending').length;
    const active = data.active_jobs ?? 0;
    byId('admin-metrics').replaceChildren(
      metric(t('Accounts'), formatNumber(total), t(pending === 1 ? '{count} pending request' : '{count} pending requests',
        {count: formatNumber(pending)})),
      metric(t('Library data'), formatBytes(data.used_bytes), t('Storage used')),
      metric(t('Free space'), formatBytes(data.free_bytes), t('Server drive')),
      metric(t('Server queue'), data.paused ? t('Paused') : t('Open', null, 'serverQueue'), t(active === 1 ? '{count} active job' : '{count} active jobs',
        {count: formatNumber(active)})),
    );
  }

  async function loadQueue() {
    const result = await request('/admin/queue');
    queuePaused = !!result.paused;
    byId('queue-toggle').textContent = queuePaused ? t('Resume queue') : t('Pause queue');
    const jobs = result.items || result.jobs || [];
    const rows = jobs.map(job => {
      const side = element('div', 'server-activity-side');
      side.append(stateChip(job.state));
      if (job.state === 'queued' || job.state === 'running') {
        side.append(button(t('Cancel'), control => perform(control, feedback, async () => {
          if (!confirm(t('Cancel this job?'))) return;
          await post(`/admin/queue/${encodeURIComponent(job.user_id)}/${encodeURIComponent(job.id)}/cancel`);
          await loadQueue();
          await loadMetrics();
        })));
      }
      return activity(job.name || job.id, [job.user_name || job.email, translateStage(job.stage || ''),
        job.state === 'running' && Number.isFinite(job.progress) ? t('{value}%', {value: formatNumber(job.progress)}) : '']
        .filter(Boolean).join(' · '), side);
    });
    showList(byId('queue-list'), rows, t('The queue is empty.'));
  }

  async function loadAudit() {
    const result = await request('/admin/audit');
    const actions = {server_initialized: t('Server configured'), account_requested: t('Account requested'), account_created: t('Account created'), account_updated: t('Account updated'),
      activate: t('Account activated'), deactivate: t('Account disabled'), credits_adjusted: t('Credits adjusted'),
      quota_updated: t('Quota changed'), sessions_revoked: t('Sessions revoked'),
      password_reset: t('Password reset'), password_changed: t('Password changed'),
      totp_reset: t('Two-factor authentication reset'), totp_enabled: t('Two-factor authentication enabled'),
      totp_disabled: t('Two-factor authentication disabled'), login: t('Sign-in'), profile_updated: t('Profile updated')};
    const rows = (result.entries || result.events || []).map(entry => {
      const target = entry.subject_name || entry.target_name || entry.subject_email || entry.target_email;
      return activity([actions[entry.action] || entry.action || t('Administration'), target].filter(Boolean).join(' · '),
        [entry.actor_name || entry.actor_email, dateOf(entry.created_at || entry.created), entry.reason].filter(Boolean).join(' · '));
    });
    showList(byId('audit-list'), rows, t('No activity recorded.'));
  }

  function quotaControls() {
    const unlimited = form.elements.role.value === 'admin';
    byId('user-quota-fields').hidden = unlimited;
    byId('user-unlimited').hidden = !unlimited;
    form.elements.disk_gib.disabled = unlimited;
    form.elements.credits.disabled = unlimited || !!selected;
    byId('user-credit-section').hidden = !selected || selected.role === 'admin';
  }

  function showTemporary(value) {
    temporary.replaceChildren();
    temporary.hidden = !value;
    if (value) {
      temporary.append(element('h3', '', t('Temporary password')),
        element('p', '', t('Share this password with the user. They must change it at their next sign-in.')),
        element('code', '', value));
      temporary.scrollIntoView({block: 'nearest'});
    }
  }

  function inspectDetails(user) {
    const details = byId('user-inspect-details');
    details.replaceChildren();
    const rows = [
      [t('Last sign-in'), dateOf(user.last_login_at || user.last_login)],
      [t('Two-factor authentication'), isMfa(user) ? t('Enabled') : t('Disabled', null, 'authentication')],
      [t('Bio'), user.bio], [t('Website'), user.website],
      ...socialKeys.map(key => [socialNames[key], user.social_links?.[key]]),
    ];
    for (const [label, value] of rows) {
      if (!value) continue;
      const cell = element('dd');
      if (/^https?:\/\//i.test(value)) {
        const link = element('a', '', value);
        link.href = value;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        cell.append(link);
      } else cell.textContent = value;
      details.append(element('dt', '', label), cell);
    }
  }

  function editUser(user, keepTemporary = false) {
    selected = user;
    form.reset();
    byId('user-credit-form').reset();
    notice(dialogNotice);
    if (!keepTemporary) showTemporary();
    byId('user-dialog-title').textContent = user ? nameOf(user) : t('Create user');
    byId('user-dialog-subtitle').textContent = user ? `${stateNames[user.status]} · ${roleName(user)}` : t('Set access and the initial quotas.');
    const icon = byId('user-dialog-avatar');
    icon.hidden = !user;
    if (user) avatar(icon, user);
    fill(form, user || {}, ['first_name', 'last_name', 'email']);
    form.elements.role.value = user?.role || 'user';
    form.elements.role.disabled = !user || user.id === actor.id;
    form.elements.status.value = user?.status || 'active';
    form.elements.status.disabled = !user || user.id === actor.id;
    form.elements.disk_gib.value = diskLimit(user || {}) == null ? 10 : Number((diskLimit(user) / 1024 ** 3).toFixed(3));
    form.elements.credits.value = 0;
    form.elements.password.disabled = !!user;
    byId('user-password-field').hidden = !!user;
    byId('user-initial-credits').hidden = !!user;
    byId('user-activate').hidden = user?.status !== 'pending';
    byId('user-save').textContent = user ? t('Save changes') : t('Create account');
    byId('user-inspect').hidden = !user;
    byId('user-revoke').hidden = user?.id === actor.id;
    byId('user-reset-password').hidden = user?.id === actor.id;
    byId('user-reset-mfa').hidden = user?.id === actor.id || !user || !isMfa(user);
    if (user) {
      inspectDetails(user);
      byId('user-credit-summary').textContent = t('{available} available · {reserved} reserved', {
        available: formatNumber(availableCredits(user)), reserved: formatNumber(user.credits_reserved || 0),
      });
    }
    quotaControls();
    if (!dialog.open) dialog.showModal();
  }

  const adminUserPath = user => `/admin/users/${encodeURIComponent(user.id)}`;
  bindForm('user-form', 'user-dialog-notice', async data => {
    const edited = selected;
    const rawLimit = data.disk_gib;
    if (data.role === 'admin' || edited?.role === 'admin' && !data.role) data.disk_limit_bytes = null;
    else if (edited && Math.abs(Number(rawLimit) - diskLimit(edited) / 1024 ** 3) < .0005) {
      data.disk_limit_bytes = diskLimit(edited);
    } else data.disk_limit_bytes = Math.round(Number(rawLimit) * 1024 ** 3);
    delete data.disk_gib;
    if (edited && data.status === 'disabled' && edited.status !== 'disabled'
      && !confirm(t('Disable the account for {name}? Their active sessions will end.', {name: nameOf(edited)}))) return;
    if (!edited) {
      data.credits = Number(data.credits);
      if (!data.password) delete data.password;
    }
    const result = edited ? await patch(adminUserPath(edited), data) : await post('/admin/users', data);
    await loadUsers();
    await loadMetrics();
    const fresh = users.find(item => item.id === (getUser(result).id || edited?.id));
    if (fresh) editUser(fresh, true);
    if (result.temporary_password) showTemporary(result.temporary_password);
    notice(dialogNotice, edited ? t('User details updated.') : t('Account created.'));
  });
  bindForm('user-credit-form', 'user-dialog-notice', async data => {
    const edited = selected;
    data.amount = Number(data.amount);
    if (!data.amount) throw new Error(t('Enter the number of credits to add or remove.'));
    await post(`${adminUserPath(edited)}/credits`, data);
    await loadUsers();
    editUser(users.find(item => item.id === edited.id) || edited, true);
    notice(dialogNotice, t('Credit adjustment saved.'));
  });
  byId('admin-create').addEventListener('click', () => editUser(null));
  byId('user-dialog-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { showTemporary(); selected = null; });
  byId('user-activate').addEventListener('click', () => {
    form.elements.status.value = 'active';
    form.requestSubmit(byId('user-save'));
  });
  form.elements.role.addEventListener('change', quotaControls);
  byId('user-revoke').addEventListener('click', event => perform(event.currentTarget, dialogNotice, async () => {
    if (!confirm(t('Sign out {name} from all devices?', {name: nameOf(selected)}))) return;
    await request(`${adminUserPath(selected)}/sessions`, {method: 'DELETE'});
    notice(dialogNotice, t('Sessions revoked.'));
  }));
  byId('user-reset-password').addEventListener('click', event => perform(event.currentTarget, dialogNotice, async () => {
    if (!confirm(t('Reset the password for {name}?', {name: nameOf(selected)}))) return;
    const result = await post(`${adminUserPath(selected)}/reset-password`);
    showTemporary(result.temporary_password);
    notice(dialogNotice, t('Password reset.'));
  }));
  byId('user-reset-mfa').addEventListener('click', event => perform(event.currentTarget, dialogNotice, async () => {
    const edited = selected;
    if (!confirm(t('Reset two-factor authentication for {name}?', {name: nameOf(edited)}))) return;
    await post(`${adminUserPath(edited)}/reset-mfa`);
    await loadUsers();
    editUser(users.find(item => item.id === edited.id) || edited, true);
    notice(dialogNotice, t('Two-factor authentication reset.'));
  }));
  search.addEventListener('input', drawUsers);
  filter.addEventListener('change', drawUsers);
  byId('queue-toggle').addEventListener('click', event => perform(event.currentTarget, feedback, async () => {
    await patch('/admin/queue', {paused: !queuePaused});
    await Promise.all([loadQueue(), loadMetrics()]);
  }));
  const load = action => action().catch(error => notice(feedback, error.message, true));
  tabs('admin-tabs', 'users', tab => {
    selectedTab = tab;
    if (tab === 'queue') load(loadQueue);
    if (tab === 'audit') load(loadAudit);
  });
  load(async () => { await loadUsers(); await loadMetrics(); });
  setInterval(() => {
    if (!document.hidden && selectedTab === 'queue') load(loadQueue);
  }, 5000);
}

async function start() {
  if (route === '/server/setup') { setupPage(); return; }
  if (route === '/server/login') {
    loginPage();
    try { location.replace(destination(getUser(await request('/me')))); }
    catch (error) {
      if (error.status !== 401 && error.status !== 403) notice(byId('auth-notice'), error.message, true);
    }
    return;
  }
  const user = getUser(await request('/me'));
  if (route === '/server/admin' && user.role === 'admin' && !user.mfa_setup_required && !user.password_change_required) adminPage(user);
  else accountPage(user);
}

start().catch(error => {
  if (error.status === 401) location.replace('/server/login');
  else {
    const feedback = element('p', 'server-notice', error.message || t('The server is unavailable.'));
    feedback.dataset.error = '';
    feedback.setAttribute('role', 'alert');
    main.replaceChildren(feedback);
  }
});

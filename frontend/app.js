const state = { user: null, posts: [], view: 'feed', authMode: 'login', photoUrl: null, openComments: new Set() };
const $ = (selector) => document.querySelector(selector);
const postsEl = $('#posts');
const noticeEl = $('#notice');

const icons = {
  heart: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 4.7a5.5 5.5 0 0 0-7.8 0L12 5.8l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.5a5.5 5.5 0 0 0 0-7.8Z"/></svg>',
  comment: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 16a3 3 0 0 1-3 3H9l-5 3v-5a3 3 0 0 1-2-3V6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3z"/></svg>'
};

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

function initials(name) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase() || '').join('');
}

function dateLabel(value) {
  const date = new Date(value);
  const now = new Date();
  const dayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const previousDay = new Date(dayStart);
  previousDay.setDate(previousDay.getDate() - 1);
  const today = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const time = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(date);
  if (today.getTime() === dayStart.getTime()) return `сегодня, ${time}`;
  if (today.getTime() === previousDay.getTime()) return `вчера, ${time}`;
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' }).format(date);
}

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'Не удалось выполнить запрос');
  return data;
}

function showNotice(message) {
  noticeEl.textContent = message;
  noticeEl.hidden = false;
  clearTimeout(showNotice.timer);
  showNotice.timer = setTimeout(() => { noticeEl.hidden = true; }, 5000);
}

function showAuth(mode = 'login') {
  state.authMode = mode;
  const registration = mode === 'register';
  $('#auth-title').textContent = registration ? 'Присоединяйтесь к Кругу' : 'Войдите в Круг';
  $('#auth-description').textContent = registration ? 'Создайте аккаунт и поделитесь своей первой историей.' : 'Продолжайте общение, делитесь мыслями и находите близких по духу.';
  $('#name-field').hidden = !registration;
  $('#auth-name').required = registration;
  $('#auth-password').autocomplete = registration ? 'new-password' : 'current-password';
  $('#auth-submit').textContent = registration ? 'Создать аккаунт' : 'Войти';
  $('#auth-switch').textContent = registration ? 'Уже есть аккаунт? Войти' : 'Зарегистрироваться';
  $('#auth-error').hidden = true;
  $('#auth-modal').hidden = false;
  document.body.style.overflow = 'hidden';
  setTimeout(() => (registration ? $('#auth-name') : $('#auth-email')).focus(), 0);
}

function closeAuth() {
  $('#auth-modal').hidden = true;
  document.body.style.overflow = '';
  $('#auth-form').reset();
}

function renderUser() {
  const user = state.user;
  $('#user-mini').hidden = !user;
  $('#auth-trigger').hidden = Boolean(user);
  $('#logout-button').hidden = !user;
  $('#mobile-auth').textContent = user ? user.name : 'Войти';
  $('#composer-avatar').textContent = user ? initials(user.name) : 'Я';
  if (user) $('#user-mini').innerHTML = `<span class="avatar" style="width:32px;height:32px;font-size:11px">${escapeHtml(initials(user.name))}</span><span>${escapeHtml(user.name)}</span>`;
}

function renderPost(post) {
  const isOpen = state.openComments.has(post.id);
  const comments = post.comments.map((comment) => `<div class="comment"><span class="avatar">${escapeHtml(initials(comment.author.name))}</span><div class="comment-body"><strong>${escapeHtml(comment.author.name)}</strong>${escapeHtml(comment.text)}</div></div>`).join('');
  return `<article class="post surface" data-post-id="${post.id}">
    <div class="post-head"><span class="avatar">${escapeHtml(initials(post.author.name))}</span><div><div class="post-author">${escapeHtml(post.author.name)}</div><div class="post-time">${dateLabel(post.created_at)}</div></div></div>
    ${post.text ? `<p class="post-text">${escapeHtml(post.text)}</p>` : ''}
    ${post.image_url ? `<img class="post-image" src="${escapeHtml(post.image_url)}" alt="Фото к публикации" loading="lazy">` : ''}
    <div class="post-actions"><button class="action-button ${post.liked ? 'is-liked' : ''}" type="button" data-action="like" aria-label="${post.liked ? 'Убрать отметку Нравится' : 'Нравится'}">${icons.heart}<span>Нравится${post.likes_count ? ` · ${post.likes_count}` : ''}</span></button><button class="action-button" type="button" data-action="comments" aria-expanded="${isOpen}">${icons.comment}<span>Комментарии${post.comments.length ? ` · ${post.comments.length}` : ''}</span></button></div>
    <div class="comments" ${isOpen ? '' : 'hidden'}>${comments || '<p class="post-time">Комментариев пока нет. Начните разговор.</p>'}<form class="comment-form"><input name="text" maxlength="1000" placeholder="Написать комментарий..." aria-label="Текст комментария" required><button type="submit">Отправить</button></form></div>
  </article>`;
}

function renderPosts() {
  if (!state.posts.length) {
    const profile = state.view === 'profile';
    postsEl.innerHTML = `<div class="empty-state surface"><h2>${profile ? 'У вас пока нет публикаций' : 'Здесь пока тихо'}</h2><p>${profile ? 'Напишите первую историю — она появится здесь.' : 'Станьте первым, кто поделится историей в Круге.'}</p></div>`;
    return;
  }
  postsEl.innerHTML = state.posts.map(renderPost).join('');
}

async function loadPosts() {
  postsEl.innerHTML = '<div class="loading">Загружаем истории...</div>';
  try {
    const scope = state.view === 'profile' ? '?scope=mine' : '';
    state.posts = (await api(`/api/posts${scope}`)).posts;
    renderPosts();
  } catch (error) {
    postsEl.innerHTML = '<div class="empty-state surface"><h2>Не удалось загрузить ленту</h2><p>Проверьте подключение к серверу и попробуйте ещё раз.</p></div>';
    showNotice(error.message);
  }
}

async function setView(view) {
  if (view === 'profile' && !state.user) { showAuth(); return; }
  state.view = view;
  document.querySelectorAll('.nav-link').forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle('is-active', active);
    if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  });
  $('#feed-heading').textContent = view === 'profile' ? 'Мои публикации' : 'Лента';
  $('#feed-subtitle').textContent = view === 'profile' ? state.user.name : 'Истории людей рядом';
  $('.section-heading').hidden = view !== 'profile';
  await loadPosts();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function clearPhoto() {
  $('#post-image').value = '';
  $('#photo-label').textContent = 'Добавить фото';
  $('#photo-preview').hidden = true;
  if (state.photoUrl) URL.revokeObjectURL(state.photoUrl);
  state.photoUrl = null;
}

document.querySelectorAll('.nav-link').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
document.querySelectorAll('.brand').forEach((link) => link.addEventListener('click', (event) => { event.preventDefault(); setView('feed'); }));
$('.photo-button').addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); $('#post-image').click(); } });
$('#auth-trigger').addEventListener('click', () => showAuth());
$('#mobile-auth').addEventListener('click', () => state.user ? setView('profile') : showAuth());
$('#close-auth').addEventListener('click', closeAuth);
$('#auth-modal').addEventListener('click', (event) => { if (event.target.id === 'auth-modal') closeAuth(); });
document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !$('#auth-modal').hidden) closeAuth(); });
$('#auth-switch').addEventListener('click', () => showAuth(state.authMode === 'login' ? 'register' : 'login'));
$('#auth-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('#auth-submit');
  button.disabled = true;
  $('#auth-error').hidden = true;
  const payload = { email: $('#auth-email').value, password: $('#auth-password').value };
  if (state.authMode === 'register') payload.name = $('#auth-name').value;
  try {
    const data = await api(`/api/${state.authMode}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    state.user = data.user;
    closeAuth();
    renderUser();
    await loadPosts();
    showNotice(state.authMode === 'register' ? 'Добро пожаловать в Круг!' : 'Вы вошли в Круг.');
  } catch (error) {
    $('#auth-error').textContent = error.message;
    $('#auth-error').hidden = false;
  } finally { button.disabled = false; }
});
$('#logout-button').addEventListener('click', async () => {
  try {
    await api('/api/logout', { method: 'POST' });
    state.user = null;
    renderUser();
    await setView('feed');
  } catch (error) { showNotice(error.message); }
});
$('#post-text').addEventListener('focus', () => { if (!state.user) { $('#post-text').blur(); showAuth(); } });
$('#post-image').addEventListener('click', (event) => { if (!state.user) { event.preventDefault(); showAuth(); } });
$('#post-image').addEventListener('change', () => {
  const file = $('#post-image').files[0];
  if (!file) return;
  if (state.photoUrl) URL.revokeObjectURL(state.photoUrl);
  if (file.size > 5 * 1024 * 1024) { clearPhoto(); showNotice('Файл слишком большой (до 5 МБ)'); return; }
  state.photoUrl = URL.createObjectURL(file);
  $('#photo-preview-image').src = state.photoUrl;
  $('#photo-preview').hidden = false;
  $('#photo-label').textContent = 'Фото добавлено';
});
$('#remove-photo').addEventListener('click', clearPhoto);
$('#publish-button').addEventListener('click', async () => {
  if (!state.user) { showAuth(); return; }
  const text = $('#post-text').value.trim();
  const image = $('#post-image').files[0];
  if (!text && !image) { showNotice('Напишите текст или добавьте фото'); return; }
  const body = new FormData();
  body.append('text', text);
  if (image) body.append('image', image);
  const button = $('#publish-button');
  button.disabled = true;
  button.textContent = 'Публикуем...';
  try {
    await api('/api/posts', { method: 'POST', body });
    $('#post-text').value = '';
    clearPhoto();
    await loadPosts();
    showNotice('Публикация добавлена.');
  } catch (error) { showNotice(error.message); }
  finally { button.disabled = false; button.textContent = 'Опубликовать'; }
});
postsEl.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const id = Number(button.closest('[data-post-id]').dataset.postId);
  if (button.dataset.action === 'comments') {
    if (state.openComments.has(id)) state.openComments.delete(id); else state.openComments.add(id);
    renderPosts();
    return;
  }
  if (!state.user) { showAuth(); return; }
  button.disabled = true;
  try {
    const data = await api(`/api/posts/${id}/like`, { method: 'POST' });
    state.posts = state.posts.map((post) => post.id === id ? data.post : post);
    renderPosts();
  } catch (error) { showNotice(error.message); button.disabled = false; }
});
postsEl.addEventListener('submit', async (event) => {
  if (!event.target.matches('.comment-form')) return;
  event.preventDefault();
  if (!state.user) { showAuth(); return; }
  const form = event.target;
  const id = Number(form.closest('[data-post-id]').dataset.postId);
  const text = new FormData(form).get('text')?.trim();
  if (!text) return;
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    const data = await api(`/api/posts/${id}/comments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    state.posts = state.posts.map((post) => post.id === id ? data.post : post);
    state.openComments.add(id);
    renderPosts();
  } catch (error) { showNotice(error.message); button.disabled = false; }
});

(async () => {
  try { state.user = (await api('/api/me')).user; } catch (error) { showNotice(error.message); }
  renderUser();
  await loadPosts();
})();

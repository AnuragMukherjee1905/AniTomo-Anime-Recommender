// ── Data ──────────────────────────────────────────────────────────────────────

const GENRES = [
  'Action', 'Romance', 'Fantasy', 'Sci-Fi',
  'Slice of Life', 'Thriller', 'Mecha', 'Isekai',
  'Sports', 'Horror', 'Mystery', 'Comedy'
];

const MOODS = [
  { label: 'Epic',      icon: '⚔️' },
  { label: 'Cozy',      icon: '🍵' },
  { label: 'Dark',      icon: '🌑' },
  { label: 'Heartfelt', icon: '💙' },
  { label: 'Hyped',     icon: '⚡' },
  { label: 'Chill',     icon: '🌊' },
];

const BACKEND = "http://localhost:8000";

// ── State ─────────────────────────────────────────────────────────────────────

let activeGenres   = new Set();
let activeMood     = null;
let isLoading      = false;
let displayedAnime = [];

// ── Render ────────────────────────────────────────────────────────────────────

function renderGenres() {
  document.getElementById('genre-pills').innerHTML = GENRES.map(g => `
    <div class="pill ${activeGenres.has(g) ? 'active' : ''}"
         onclick="toggleGenre('${g}')">${g}</div>
  `).join('');
}

function renderMoods() {
  document.getElementById('mood-grid').innerHTML = MOODS.map(m => `
    <div class="mood-card ${activeMood === m.label ? 'active' : ''}"
         onclick="toggleMood('${m.label}')">
      <span class="mood-icon">${m.icon}</span>
      <span class="mood-label">${m.label}</span>
    </div>
  `).join('');
}

function renderCards() {
  const grid  = document.getElementById('cards-grid');
  const count = document.getElementById('cards-count');
  count.textContent = `${displayedAnime.length} result${displayedAnime.length !== 1 ? 's' : ''}`;

  if (displayedAnime.length === 0) {
    grid.innerHTML = `
      <div class="empty-state">
        &gt; NO RESULTS FOUND_<br>
        Try different filters or search terms.
      </div>`;
    return;
  }

  grid.innerHTML = displayedAnime.map(a => {
    const genre      = Array.isArray(a.genres) ? a.genres[0] : (a.genre || '');
    const badgeClass = getBadgeClass(genre);
    const score      = a.score || '?';
    const year       = a.year  || '';

    const posterHtml = a.image_url
      ? `<img class="card-poster" src="${a.image_url}" alt="${escapeHtml(a.title)}"
              loading="lazy"
              onerror="this.style.display='none';this.nextElementSibling.style.display='flex';" />
         <div class="card-poster-placeholder" style="display:none;">🎭</div>`
      : `<div class="card-poster-placeholder">🎭</div>`;

    return `
      <div class="anime-card" onclick="openModal(${JSON.stringify(a).replace(/"/g, '&quot;')})">
        ${posterHtml}
        <div class="card-body">
          <div class="card-title">${escapeHtml(a.title)}</div>
          <div class="card-meta">
            <span class="badge ${badgeClass}">${genre}</span>
            <span class="card-score">★ ${score}</span>
          </div>
          <div class="card-meta" style="margin-top:4px;font-size:0.55rem;opacity:0.6;">${year}</div>
        </div>
      </div>
    `;
  }).join('');
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getBadgeClass(genre) {
  const map = {
    'Action':'badge-action','Romance':'badge-romance',
    'Fantasy':'badge-fantasy','Sci-Fi':'badge-scifi',
    'Science Fiction':'badge-scifi','Slice of Life':'badge-slice',
    'Thriller':'badge-thriller','Horror':'badge-thriller',
    'Mystery':'badge-thriller','Comedy':'badge-slice',
    'Sports':'badge-action','Mecha':'badge-scifi','Isekai':'badge-fantasy',
  };
  return map[genre] || 'badge-fantasy';
}

function escapeHtml(str) {
  return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
                    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function escapeTitle(title) {
  return (title || '').replace(/'/g, "\\'");
}

// ── Interactions ──────────────────────────────────────────────────────────────

function toggleGenre(genre) {
  activeGenres.has(genre) ? activeGenres.delete(genre) : activeGenres.add(genre);
  renderGenres();
}

function toggleMood(mood) {
  activeMood = activeMood === mood ? null : mood;
  renderMoods();
}

// ── Modal ─────────────────────────────────────────────────────────────────────

function openModal(anime) {
  const genres = Array.isArray(anime.genres) ? anime.genres.join(', ') : (anime.genre || '');
  const synopsis = anime.synopsis || 'No synopsis available.';

  document.getElementById('modal-inner').innerHTML = `
    ${anime.image_url
      ? `<img class="modal-poster" src="${anime.image_url}" alt="${escapeHtml(anime.title)}"
              onerror="this.style.display='none';" />`
      : ''}
    <div class="modal-title">${escapeHtml(anime.title)}</div>
    <div class="modal-meta">
      <span class="highlight">★ ${anime.score || '?'}</span>
      <span>${anime.episodes ? anime.episodes + ' eps' : ''}</span>
      <span>${anime.year || ''}</span>
      <span>${genres}</span>
    </div>
    <div class="modal-synopsis">${escapeHtml(synopsis)}</div>
    <a class="modal-mal-link"
       href="https://myanimelist.net/anime/${anime.id}"
       target="_blank" rel="noopener">
      ▶ VIEW ON MAL
    </a>
  `;

  document.getElementById('modal-overlay').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
  document.body.style.overflow = '';
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

// ── API calls ─────────────────────────────────────────────────────────────────

async function handleRecommend() {
  if (isLoading) return;
  isLoading = true;

  const btn   = document.getElementById('rec-btn');
  const title = document.getElementById('cards-title');

  btn.querySelector('.btn-inner').innerHTML =
    `<span class="loading-dots"><span></span><span></span><span></span></span>`;
  title.textContent = 'SEARCHING DATABASE…';

  try {
    const res = await fetch(`${BACKEND}/recommend`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        genres: [...activeGenres],
        mood:   activeMood,
        top_n:  20,
      }),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    const data        = await res.json();
    displayedAnime    = data.results || [];
    title.textContent = activeMood
      ? `RESULTS // ${activeMood.toUpperCase()} MOOD`
      : 'RECOMMENDED FOR YOU';
  } catch (err) {
    console.error(err);
    displayedAnime    = [];
    title.textContent = 'ERROR — IS BACKEND RUNNING?';
  }

  btn.querySelector('.btn-inner').textContent = '▶ GET RECOMMENDATIONS';
  isLoading = false;
  renderCards();
}

async function handleSearch() {
  const query   = document.getElementById('search-input').value.trim();
  const titleEl = document.getElementById('cards-title');

  if (!query) { await loadTrending(); return; }

  titleEl.textContent = `SEARCHING "${query.toUpperCase()}"…`;

  try {
    const res  = await fetch(`${BACKEND}/search?q=${encodeURIComponent(query)}&limit=20`);
    if (!res.ok) throw new Error(`${res.status}`);
    const data        = await res.json();
    displayedAnime    = data.results || [];
    titleEl.textContent = `RESULTS // "${query.toUpperCase()}"`;
  } catch (err) {
    console.error(err);
    displayedAnime      = [];
    titleEl.textContent = 'SEARCH ERROR — IS BACKEND RUNNING?';
  }

  renderCards();
}

async function loadTrending() {
  document.getElementById('cards-title').textContent = 'LOADING…';
  try {
    const res  = await fetch(`${BACKEND}/trending?limit=20`);
    if (!res.ok) throw new Error(`${res.status}`);
    const data = await res.json();
    displayedAnime = data.results || [];
    document.getElementById('cards-title').textContent = 'TRENDING THIS SEASON';
  } catch (err) {
    console.error(err);
    displayedAnime = [];
    document.getElementById('cards-title').textContent = 'COULD NOT CONNECT — IS BACKEND RUNNING?';
  }
  renderCards();
}

// ── Event listeners ───────────────────────────────────────────────────────────

document.getElementById('search-btn').addEventListener('click', handleSearch);
document.getElementById('search-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') handleSearch();
});
document.getElementById('rec-btn').addEventListener('click', handleRecommend);

// ── Init ──────────────────────────────────────────────────────────────────────

renderGenres();
renderMoods();
loadTrending();

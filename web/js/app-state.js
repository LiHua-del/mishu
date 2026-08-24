(() => {
  'use strict';

  const {
    STORAGE_KEY, DEVICE_KEY, OLD_KEYS, GENRES, PLATFORMS, WORD_OPTIONS,
    SUBTAG_GROUPS
  } = window.MishuAppConfig;

  const now = () => new Date().toISOString();
  const deviceId = (() => {
    let value = localStorage.getItem(DEVICE_KEY);
    if (!value) {
      value = globalThis.crypto?.randomUUID?.() || `device-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      localStorage.setItem(DEVICE_KEY, value);
    }
    return value.slice(0, 120);
  })();

  const state = {
    audience: 'male', selectedGenres: [], selectedSubtags: [], subtagMatch: 'any',
    selectedPlatforms: [...PLATFORMS], wordRange: 'any', status: 'all', mode: 'mixed',
    aiEnabled: true, events: [], shownIds: [], bookCache: {}, batch: [], libraryTab: 'want',
    dialogBookId: '', sources: [], searchedAt: '', aiAvailable: false, aiModel: '',
    aiBatchSummary: '', aiLastError: '', isRefreshing: false, dialogOpenedAt: 0,
    filtersCollapsed: false, lastSuccessfulFilterKey: '',
    sync: {connected: false, cursor: 0, initialized: false, lastSyncedAt: '', sentEventIds: [], busy: false}
  };

  function validEventId(value) {
    return /^[A-Za-z0-9._:-]{12,100}$/.test(String(value || ''));
  }

  function legacyEventId(event, index) {
    const bookPart = String(event?.bookId || 'book').replace(/[^A-Za-z0-9._:-]/g, '').slice(0, 36) || 'book';
    const timePart = String(event?.timestamp || 'legacy').replace(/[^A-Za-z0-9]/g, '').slice(-22) || 'legacy';
    return `legacy-${timePart}-${bookPart}-${index}`.slice(0, 100);
  }

  function newEventId() {
    return globalThis.crypto?.randomUUID?.() || `event-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
  }

  function normalizeBook(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const title = String(raw.title || raw.bookTitle || '').trim();
    const cover = String(raw.cover || raw.coverUrl || '').trim();
    if (!title || !cover) return null;
    const genres = Array.isArray(raw.genres) ? raw.genres.map(String).filter(Boolean) : [];
    const contentTags = Array.isArray(raw.contentTags) ? raw.contentTags
      .filter(item => item && typeof item === 'object' && item.name)
      .map(item => ({name: String(item.name), confidence: Number(item.confidence || 0), source: String(item.source || ''), evidence: String(item.evidence || '')}))
      .slice(0, 18) : [];
    return {
      id: String(raw.id || 'book-' + title), title,
      author: String(raw.author || '未知作者').trim() || '未知作者',
      description: String(raw.description || raw.desc || '详情以原平台页面为准。').trim(),
      cover, url: String(raw.url || raw.link || '').trim(),
      platform: String(raw.platform || '实时平台').trim(), genres, contentTags,
      words: Number(raw.words || 0) || 0, status: String(raw.status || '待核实').trim(),
      popularityScore: Number(raw.popularityScore || 50) || 50,
      popularityText: String(raw.popularityText || '实时推荐').trim(),
      rank: Number(raw.rank || 0) || 0, trendScore: Number(raw.trendScore || 0) || 0,
      trendLabel: String(raw.trendLabel || '').trim(), rankChange: Number(raw.rankChange || 0) || 0,
      sourceType: String(raw.sourceType || ''), aiRank: Number(raw.aiRank || 0) || 0,
      aiReason: String(raw.aiReason || '').trim(), aiSummary: String(raw.aiSummary || '').trim()
    };
  }

  function loadState() {
    let raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) raw = OLD_KEYS.map(key => localStorage.getItem(key)).find(Boolean) || '{}';
    try {
      const saved = JSON.parse(raw);
      state.audience = ['male', 'female', 'all'].includes(saved.audience) ? saved.audience : 'male';
      state.selectedGenres = Array.isArray(saved.selectedGenres) ? saved.selectedGenres.filter(item => GENRES.includes(item)).slice(0, 3) : [];
      state.selectedSubtags = Array.isArray(saved.selectedSubtags) ? saved.selectedSubtags.filter(item => Object.values(SUBTAG_GROUPS).flat().includes(item)).slice(0, 3) : [];
      state.subtagMatch = saved.subtagMatch === 'all' ? 'all' : 'any';
      state.selectedPlatforms = Array.isArray(saved.selectedPlatforms) ? saved.selectedPlatforms.filter(item => PLATFORMS.includes(item)) : [...PLATFORMS];
      if (!state.selectedPlatforms.length) state.selectedPlatforms = [...PLATFORMS];
      state.wordRange = WORD_OPTIONS.some(item => item[0] === saved.wordRange) ? saved.wordRange : 'any';
      state.status = ['all', 'completed', 'ongoing'].includes(saved.status) ? saved.status : 'all';
      state.mode = ['popular', 'random', 'mixed'].includes(saved.mode) ? saved.mode : (saved.mode === 'explore' ? 'random' : 'mixed');
      state.aiEnabled = saved.aiEnabled !== false;
      state.events = Array.isArray(saved.events) ? saved.events.filter(event => event && event.bookId && event.action).slice(-1600).map((event, index) => ({
        ...event, eventId: validEventId(event.eventId) ? event.eventId : legacyEventId(event, index), timestamp: String(event.timestamp || now())
      })) : [];
      state.shownIds = Array.isArray(saved.shownIds) ? [...new Set(saved.shownIds.map(String))].slice(-500) : [];
      if (saved.bookCache && typeof saved.bookCache === 'object') {
        Object.values(saved.bookCache).forEach(rawBook => { const book = normalizeBook(rawBook); if (book) state.bookCache[book.id] = book; });
      }
      const savedSync = saved.sync && typeof saved.sync === 'object' ? saved.sync : {};
      state.sync.cursor = Math.max(0, Number(savedSync.cursor || 0) || 0);
      state.sync.initialized = savedSync.initialized === true;
      state.sync.lastSyncedAt = String(savedSync.lastSyncedAt || '');
      state.sync.sentEventIds = Array.isArray(savedSync.sentEventIds) ? savedSync.sentEventIds.filter(validEventId).slice(-1800) : [];
    } catch (_) {
      localStorage.removeItem(STORAGE_KEY);
    }
  }

  function saveState() {
    const books = Object.values(state.bookCache).slice(-600);
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      version: 4, audience: state.audience, selectedGenres: state.selectedGenres,
      selectedSubtags: state.selectedSubtags, subtagMatch: state.subtagMatch,
      selectedPlatforms: state.selectedPlatforms, wordRange: state.wordRange, status: state.status,
      mode: state.mode, aiEnabled: state.aiEnabled, events: state.events.slice(-1600),
      shownIds: state.shownIds.slice(-500), bookCache: Object.fromEntries(books.map(book => [book.id, book])),
      sync: {cursor: state.sync.cursor, initialized: state.sync.initialized, lastSyncedAt: state.sync.lastSyncedAt, sentEventIds: state.sync.sentEventIds.slice(-1800)}
    }));
  }

  function recordBooks(books) {
    books.forEach(book => { state.bookCache[book.id] = book; });
    saveState();
  }

  function rememberShown(bookIds) {
    const latest = [...new Set(bookIds.map(String).filter(Boolean))];
    const latestSet = new Set(latest);
    state.shownIds = state.shownIds.filter(bookId => !latestSet.has(bookId)).concat(latest).slice(-500);
  }

  window.MishuAppState = {
    STORAGE_KEY, state, deviceId, now, normalizeBook, loadState, saveState,
    recordBooks, rememberShown, validEventId, legacyEventId, newEventId
  };
})();

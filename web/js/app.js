(() => {
  'use strict';

  const {
    AUDIENCES, GENRES, PLATFORMS, WORD_OPTIONS, MODES, STATUS_OPTIONS,
    SUBTAG_GROUPS, DECISIONS, SYNC_ACTIONS, ACCENT_THEMES, COVER_PLACEHOLDER
  } = window.MishuAppConfig;
  const {
    STORAGE_KEY, state, deviceId, now, normalizeBook, loadState, saveState,
    recordBooks, rememberShown, validEventId, newEventId
  } = window.MishuAppState;
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const esc = value => String(value == null ? '' : value).replace(/[&<>'"]/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'}[char]));

  function bindCoverFallbacks(root = document) {
    root.querySelectorAll('img').forEach(image => {
      if (image.dataset.coverFallbackBound) return;
      image.dataset.coverFallbackBound = '1';
      image.addEventListener('error', () => {
        if (image.src.endsWith(COVER_PLACEHOLDER)) return;
        image.classList.add('cover-broken');
        image.src = COVER_PLACEHOLDER;
      });
    });
  }

  function applyAccentTheme(theme, announce = false) {
    const nextTheme = ACCENT_THEMES.has(theme) ? theme : 'coral';
    document.documentElement.dataset.accent = nextTheme;
    localStorage.setItem('mishu-accent', nextTheme);
    $$('[data-accent-theme]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.accentTheme === nextTheme)));
    if (announce) toast('主题色已更新');
  }

  function updateBrowserThemeColor() {
    const color = document.body.classList.contains('dark') ? '#1d1b19' : '#f4f2ee';
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', color);
  }

  function latestDecision(bookId) {
    for (let index = state.events.length - 1; index >= 0; index -= 1) {
      const event = state.events[index];
      if (event.bookId === bookId && DECISIONS.has(event.action)) return event.action === 'clear' ? '' : event.action;
    }
    return '';
  }

  function appendEvent(bookId, action, extra = {}) {
    const event = {eventId: newEventId(), bookId, action, timestamp: now(), ...extra};
    state.events.push(event);
    state.events = state.events.slice(-1600);
    saveState();
    fetch('/api/events', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({deviceId, events: [event]})
    }).catch(() => {});
    scheduleSync();
  }

  const {
      request: syncRequest,
      loadStatus: loadSyncStatus,
      syncNow,
      scheduleSync,
      createToken: createSyncToken,
      join: joinSync,
      disconnect: disconnectSync
    } = window.MishuSync.create({
      state, deviceId, $, normalizeBook, validEventId, now, saveState, toast,
      afterMerge: () => {
        renderBookGrid();
        renderLibrary();
        renderProfile();
        renderLearningState();
        updateFilterSummary();
      }
    });

  function setDecision(bookId, action) {
    const current = latestDecision(bookId);
    appendEvent(bookId, current === action ? 'clear' : action);
    renderBookGrid();
    renderLibrary();
    renderProfile();
    renderLearningState();
    if (state.dialogBookId === bookId) updateDialogButtons();
    if (action === 'dislike' && current !== action && state.dialogBookId === bookId) $('#dislikeReasons').hidden = false;
    if (action !== 'dislike' || current === action) $('#dislikeReasons').hidden = true;
    const labels = {want: '已放入想看', liked: '已记住：你喜欢这本', read: '已记为看过，只用于去重', dislike: '以后少推类似的', clear: '已取消'};
    toast(current === action ? labels.clear : labels[action]);
  }

  function preferenceModel() {
    return MishuPreferenceModel.build({
      books: Object.values(state.bookCache),
      events: state.events
    });
  }

  function preferenceWeights() {
    return MishuPreferenceModel.rankingWeights(preferenceModel(), currentTasteSignalCount());
  }

  function preferencePayload() {
    const weights = preferenceWeights();
    const output = {};
    [...weights.entries()].sort((left, right) => Math.abs(right[1]) - Math.abs(left[1])).slice(0, 36).forEach(([tag, weight]) => {
      output[tag] = Math.max(-12, Math.min(12, Number(weight.toFixed(2))));
    });
    return output;
  }

  function currentTasteSignalCount() {
    return Object.values(state.bookCache).filter(book => ['want', 'liked', 'dislike'].includes(latestDecision(book.id))).length;
  }

  function selectedPlatformLabel() {
    if (state.selectedPlatforms.length === PLATFORMS.length) return '全平台';
    if (state.selectedPlatforms.length <= 2) return state.selectedPlatforms.join('、');
    return `${state.selectedPlatforms.length} 个平台`;
  }

  function selectedAudienceLabel() {
    return AUDIENCES.find(item => item[0] === state.audience)?.[1] || '男频';
  }

  function updateFilterSummary() {
    const rawWordLabel = WORD_OPTIONS.find(item => item[0] === state.wordRange)?.[1] || '不限';
    const wordLabel = rawWordLabel === '不限' ? '篇幅不限' : rawWordLabel;
    const statusLabel = STATUS_OPTIONS.find(item => item[0] === state.status)?.[1] || STATUS_OPTIONS[0][1];
    const statusShortLabel = state.status === 'completed' ? '仅完结' : state.status === 'ongoing' ? '仅连载' : '状态不限';
    const modeLabel = MODES.find(item => item[0] === state.mode)?.[1] || '个性';
    const topics = state.selectedGenres.length ? state.selectedGenres.join('、') : '全题材';
    const details = state.selectedSubtags.length ? ` · ${state.selectedSubtags.join('、')}` : '';
    $('#refineSummary').textContent = [wordLabel, statusShortLabel, selectedPlatformLabel()].join(' · ');
    const hintParts = [selectedAudienceLabel(), modeLabel, selectedPlatformLabel(), `${topics}${details}`, state.wordRange !== 'any' ? rawWordLabel : '', state.status !== 'all' ? statusLabel : '', '6 本'].filter(Boolean);
    $('#discoverButtonHint').textContent = hintParts.join(' · ');
    $('#filterPanel').classList.toggle('compact', state.filtersCollapsed);
    $('#discoverPage').classList.toggle('has-batch', state.batch.length === 6);
    $('#discoverPage').classList.toggle('results-active', state.batch.length === 6 && state.filtersCollapsed);
    $('#resetFiltersButton').hidden = state.filtersCollapsed;
    $('#editFiltersButton').hidden = !state.filtersCollapsed;
    $('#filterPanelSummary').textContent = state.filtersCollapsed
      ? [selectedAudienceLabel(), modeLabel, `${topics}${details}`, wordLabel, statusShortLabel, selectedPlatformLabel()].join(' · ')
      : '先选频道和方式，其余按需补充';
    $('#resultFilterSummary').textContent = [selectedAudienceLabel(), modeLabel, `${topics}${details}`, wordLabel, statusShortLabel, selectedPlatformLabel()].join(' · ');
  }

  function renderFilters() {
    $('#audienceOptions').innerHTML = AUDIENCES.map(([value, label]) => `<button type="button" class="${state.audience === value ? 'active' : ''}" data-audience="${value}" aria-pressed="${state.audience === value}">${label}</button>`).join('');
    $('#genreOptions').innerHTML = GENRES.map(genre => `<button type="button" class="${state.selectedGenres.includes(genre) ? 'active' : ''}" data-genre="${esc(genre)}" aria-pressed="${state.selectedGenres.includes(genre)}">${esc(genre)}</button>`).join('');
    const allPlatformsSelected = state.selectedPlatforms.length === PLATFORMS.length;
    $('#platformOptions').innerHTML = `<button type="button" class="${allPlatformsSelected ? 'active' : ''}" data-platform-all aria-pressed="${allPlatformsSelected}">全部平台</button>` + PLATFORMS.map(platform => `<button type="button" class="${!allPlatformsSelected && state.selectedPlatforms.includes(platform) ? 'active' : ''}" data-platform="${esc(platform)}" aria-pressed="${!allPlatformsSelected && state.selectedPlatforms.includes(platform)}">${esc(platform)}</button>`).join('');
    const availableSubtags = [...new Set(state.selectedGenres.flatMap(genre => SUBTAG_GROUPS[genre] || []))];
    state.selectedSubtags = state.selectedSubtags.filter(tag => availableSubtags.includes(tag));
    $('#subtagGroup').hidden = availableSubtags.length === 0;
    $('#subtagOptions').innerHTML = availableSubtags.map(tag => `<button type="button" class="${state.selectedSubtags.includes(tag) ? 'active' : ''}" data-subtag="${esc(tag)}" aria-pressed="${state.selectedSubtags.includes(tag)}">${esc(tag)}</button>`).join('');
    $('#subtagMatchOptions').hidden = state.selectedSubtags.length < 2;
    $$('[data-subtag-match]').forEach(button => button.classList.toggle('active', button.dataset.subtagMatch === state.subtagMatch));
    $('#wordOptions').innerHTML = WORD_OPTIONS.map(([value, label]) => `<button type="button" class="${state.wordRange === value ? 'active' : ''}" data-words="${value}" aria-pressed="${state.wordRange === value}">${label}</button>`).join('');
    $('#modeOptions').innerHTML = MODES.map(([value, title]) => {
      return `<button type="button" class="${state.mode === value ? 'active' : ''}" data-mode="${value}" aria-pressed="${state.mode === value}">${title}</button>`;
    }).join('');
    const modeExplanation = state.mode === 'popular'
      ? '热门：优先公开榜单。'
      : state.mode === 'random'
        ? '随机：从合格候选中打散挑选。'
        : '';
    $('#modeHelp').hidden = !modeExplanation;
    $('#modeHelp').textContent = modeExplanation;
    $('#statusOptions').innerHTML = STATUS_OPTIONS.map(([value, label]) => `<button type="button" class="${state.status === value ? 'active' : ''}" data-status="${value}" aria-pressed="${state.status === value}">${label}</button>`).join('');
    updateFilterSummary();
    $$('[data-audience]').forEach(button => button.addEventListener('click', () => {
      state.audience = button.dataset.audience;
      saveState(); renderFilters();
    }));
    $$('[data-genre]').forEach(button => button.addEventListener('click', () => {
      const genre = button.dataset.genre;
      if (state.selectedGenres.includes(genre)) state.selectedGenres = state.selectedGenres.filter(item => item !== genre);
      else if (state.selectedGenres.length < 3) state.selectedGenres.push(genre);
      else return toast('一次最多选 3 个大类');
      saveState(); renderFilters();
    }));
    $$('[data-subtag]').forEach(button => button.addEventListener('click', () => {
      const tag = button.dataset.subtag;
      if (state.selectedSubtags.includes(tag)) state.selectedSubtags = state.selectedSubtags.filter(item => item !== tag);
      else if (state.selectedSubtags.length < 3) state.selectedSubtags.push(tag);
      else return toast('一次最多选 3 个细分偏好');
      saveState(); renderFilters();
    }));
    $$('[data-subtag-match]').forEach(button => button.addEventListener('click', () => {
      state.subtagMatch = button.dataset.subtagMatch === 'all' ? 'all' : 'any';
      saveState(); renderFilters();
    }));
    $$('[data-words]').forEach(button => button.addEventListener('click', () => {
      state.wordRange = button.dataset.words; saveState(); renderFilters();
    }));
    $('[data-platform-all]').addEventListener('click', () => {
      state.selectedPlatforms = [...PLATFORMS];
      saveState(); renderFilters();
    });
    $$('[data-platform]').forEach(button => button.addEventListener('click', () => {
      const platform = button.dataset.platform;
      if (state.selectedPlatforms.length === PLATFORMS.length) {
        state.selectedPlatforms = [platform];
        saveState(); renderFilters();
        return;
      }
      if (state.selectedPlatforms.includes(platform)) {
        if (state.selectedPlatforms.length === 1) return toast('至少保留一个来源');
        state.selectedPlatforms = state.selectedPlatforms.filter(item => item !== platform);
      } else {
        state.selectedPlatforms.push(platform);
      }
      saveState(); renderFilters();
    }));
    $$('[data-mode]').forEach(button => button.addEventListener('click', () => {
      state.mode = button.dataset.mode; saveState(); renderFilters(); renderLearningState();
    }));
    $$('[data-status]').forEach(button => button.addEventListener('click', () => {
      state.status = button.dataset.status; saveState(); renderFilters();
    }));
  }

  function bookFacts(book) {
    const facts = [];
    if (book.trendLabel) facts.push(book.trendLabel);
    const primaryTag = (book.contentTags || []).find(tag => Number(tag.confidence || 0) >= .65);
    if (primaryTag) facts.push(primaryTag.name);
    else if (book.genres[0]) facts.push(book.genres[0]);
    if (book.words) facts.push(`${book.words.toFixed(book.words % 1 ? 1 : 0)}万字`);
    if (book.status && book.status !== '待核实') facts.push(book.status);
    return facts.slice(0, 3);
  }

  function renderBookGrid() {
    const books = state.batch.map(id => state.bookCache[id]).filter(Boolean);
    $('#emptyState').hidden = books.length > 0;
    $('#batchFooter').hidden = books.length === 0;
    $('#bookGrid').innerHTML = books.map(book => {
      const decision = latestDecision(book.id);
      const classes = ['discovery-book', decision === 'want' ? 'selected' : '', ['read', 'liked'].includes(decision) ? 'seen' : '', decision === 'dislike' ? 'skipped' : ''].filter(Boolean).join(' ');
      return `<article class="${classes}" data-book-card="${esc(book.id)}">
        <span class="book-heat">${esc(book.popularityText)}</span>
        ${decision === 'liked' ? '<span class="book-state">喜欢</span>' : decision === 'read' ? '<span class="book-state neutral">看过</span>' : ''}
        <button class="cover-button" type="button" data-detail="${esc(book.id)}" aria-label="查看《${esc(book.title)}》详情"><img src="${esc(book.cover)}" alt="《${esc(book.title)}》封面" loading="lazy" referrerpolicy="no-referrer"></button>
        <h3>${esc(book.title)}</h3>
        <div class="book-byline">${esc(book.author)} · ${esc(book.platform)}</div>
        <div class="book-facts">${bookFacts(book).map(fact => `<span>${esc(fact)}</span>`).join('')}</div>
        <div class="quick-actions">
          <button class="want-button ${decision === 'want' ? 'active' : ''}" type="button" data-decision="want" data-book="${esc(book.id)}">${decision === 'want' ? '✓ 已想看' : '♡ 想看'}</button>
          <button class="skip-button" type="button" data-decision="dislike" data-book="${esc(book.id)}" aria-label="不想看">${decision === 'dislike' ? '↶' : '×'}</button>
        </div>
      </article>`;
    }).join('');
    $$('[data-detail]').forEach(button => button.addEventListener('click', () => openBookDialog(button.dataset.detail)));
    $$('[data-decision]').forEach(button => button.addEventListener('click', () => setDecision(button.dataset.book, button.dataset.decision)));
    bindCoverFallbacks($('#bookGrid'));
    const wanted = books.filter(book => latestDecision(book.id) === 'want').length;
    $('#selectionCount').textContent = String(wanted);
    $('#copySelectedButton').disabled = wanted === 0;
  }

  function aiPreferences() {
    // AI 不得把一次详情或复制放大成明确口味；只有重复证据或足够强的显式证据才传入。
    const weighted = [...preferenceModel().entries()]
      .filter(([, record]) => record.positiveBooks.size >= 2 || record.explicitWeight >= 1.5)
      .sort((left, right) => right[1].weight - left[1].weight)
      .slice(0, 10)
      .map(([tag]) => tag);
    const likedBooks = [];
    const dislikedBooks = [];
    Object.values(state.bookCache).forEach(book => {
      const decision = latestDecision(book.id);
      if ((decision === 'want' || decision === 'liked') && likedBooks.length < 12) likedBooks.push(book.title);
      if (decision === 'dislike' && dislikedBooks.length < 12) dislikedBooks.push(book.title);
    });
    return {positiveTags: weighted, likedBooks, dislikedBooks};
  }

  async function requestAiAnalysis(candidates) {
    if (!state.aiEnabled || !state.aiAvailable || candidates.length < 2) return null;
    const books = candidates.slice(0, 24).map(book => ({
      id: book.id, title: book.title, author: book.author, platform: book.platform,
      genres: book.genres, contentTags: book.contentTags, words: book.words, status: book.status,
      popularityText: book.popularityText, description: book.description
    }));
    try {
      const response = await fetch('/api/ai/enrich', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({deviceId, books, preferences: aiPreferences(), mode: state.mode})
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.message || 'AI 分析暂时不可用');
      state.aiLastError = '';
      return data;
    } catch (error) {
      state.aiLastError = error.message || 'AI 分析暂时不可用';
      return null;
    }
  }

  function applyAiAnalysis(candidates, analysis) {
    if (!analysis) return candidates;
    const reasons = analysis.reasons && typeof analysis.reasons === 'object' ? analysis.reasons : {};
    const summaries = analysis.summaries && typeof analysis.summaries === 'object' ? analysis.summaries : {};
    const byId = new Map(candidates.map(book => [book.id, book]));
    const ordered = [];
    (Array.isArray(analysis.rankedIds) ? analysis.rankedIds : []).forEach((bookId, index) => {
      const book = byId.get(String(bookId));
      if (!book || ordered.includes(book)) return;
      book.aiRank = index + 1;
      book.aiReason = String(reasons[book.id] || '').trim();
      book.aiSummary = String(summaries[book.id] || '').trim();
      ordered.push(book);
    });
    candidates.forEach(book => { if (!ordered.includes(book)) ordered.push(book); });
    state.aiBatchSummary = String(analysis.summary || '').trim();
    return ordered;
  }

  function renderAiInsight() {
    const node = $('#aiInsight');
    if (state.aiBatchSummary) {
      node.hidden = false;
      $('#aiInsightText').textContent = state.aiBatchSummary;
    } else {
      node.hidden = true;
      $('#aiInsightText').textContent = '';
    }
  }

  async function enhanceVisibleBatch(baselineBooks, rawPool, batchToken, batchMeta) {
    const candidates = rawPool.length >= 6 ? rawPool : baselineBooks;
    const analysis = await requestAiAnalysis(candidates);
    if (!analysis || state.batch.join('|') !== batchToken) return;
    // 用户已作出选择后，不再替换卡片，避免打断正在挑书的节奏。
    if (state.batch.some(bookId => latestDecision(bookId))) return;
    // AI 可以分析更大的候选池，但只能重排服务端已经校验好的当前六本，
    // 不能重新引入其他候选破坏频道、来源比例或去重结果。
    const visibleIds = new Set(baselineBooks.map(book => book.id));
    const ranked = applyAiAnalysis(candidates, analysis).filter(book => visibleIds.has(book.id));
    baselineBooks.forEach(book => {
      if (!ranked.some(item => item.id === book.id)) ranked.push(book);
    });
    if (ranked.length !== 6) return;
    recordBooks(ranked);
    state.batch = ranked.map(book => book.id);
    rememberShown(state.batch);
    saveState();
    renderBookGrid();
    renderAiInsight();
    $('#batchMeta').textContent = `${batchMeta} · AI 已补充`;
    $('#liveStatus').textContent = 'AI 已补充';
    $('#sourceNoteText').textContent += ' AI 已基于候选简介完成语义分析，并在当前六本内完成排序。';
  }

  function currentFilterKey() {
    return JSON.stringify({
      audience: state.audience,
      genres: state.selectedGenres, subtags: state.selectedSubtags, subtagMatch: state.subtagMatch,
      words: state.wordRange, status: state.status, platforms: state.selectedPlatforms, mode: state.mode
    });
  }

  async function requestCandidates(excludeIds, timeoutMs = 45000) {
    const payload = {
      audience: state.audience,
      genres: state.selectedGenres.join(','), subtags: state.selectedSubtags.join(','), subtagMatch: state.subtagMatch,
      words: state.wordRange, status: state.status, platforms: state.selectedPlatforms.join(','),
      mode: state.mode, exclude: excludeIds.join(','), current: state.batch.join(','), allowFallback: false,
      preferences: preferencePayload()
    };
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch('/api/discover', {
        method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'},
        body: JSON.stringify(payload), signal: controller.signal
      });
      const data = await response.json().catch(() => ({}));
      if (response.status === 401) showAuthGate(data.message || '登录已过期，请重新输入访问口令。');
      if (!response.ok || !data.ok) throw new Error(data.message || '实时书库未返回结果');
      return data;
    } catch (error) {
      if (error?.name === 'AbortError') throw new Error(`请求超过 ${Math.round(timeoutMs / 1000)} 秒，当前结果已保留。`);
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function renderLoadingGrid() {
    $('#bookGrid').innerHTML = Array.from({length: 6}, () => '<div class="book-skeleton"><i></i><b></b><small></small></div>').join('');
  }

  async function discoverNext() {
    if (state.isRefreshing) return;
    const button = $('#discoverButton');
    const nextButton = $('#nextBatchButton');
    const hadBatch = state.batch.length === 6;
    const filterKey = currentFilterKey();
    const isSameFilterRefresh = hadBatch && state.lastSuccessfulFilterKey === filterKey;
    const requestTimeout = isSameFilterRefresh ? 15000 : 45000;
    const statusTimers = [
      window.setTimeout(() => {
        if (state.isRefreshing) $('#liveStatus').textContent = '正在扩充候选';
      }, 4000),
      window.setTimeout(() => {
        if (state.isRefreshing) $('#liveStatus').textContent = '条件较细，仍在补齐';
      }, 10000)
    ];
    button.disabled = true;
    if (nextButton) nextButton.disabled = true;
    button.querySelector('strong').textContent = '正在生成推荐…';
    state.isRefreshing = true;
    if (!hadBatch) $('#discoverPage').classList.add('loading-results');
    $('#batchSection').classList.toggle('refreshing', hadBatch);
    if (!hadBatch) {
      renderLoadingGrid();
      $('#emptyState').hidden = true;
      $('#batchFooter').hidden = true;
    }
    $('#liveStatus').className = 'fresh-dot';
    $('#liveStatus').textContent = hadBatch ? '准备下一批' : '联网中';
    try {
      const data = await requestCandidates(state.shownIds.slice(-180), requestTimeout);
      const candidates = (data.results || []).map(normalizeBook).filter(Boolean);
      if (candidates.length !== 6) throw new Error('未取得完整的 6 本，当前结果已保留。');
      state.aiBatchSummary = '';
      state.aiLastError = '';
      const rankedCandidates = candidates;
      recordBooks(rankedCandidates);
      state.batch = rankedCandidates.map(book => book.id);
      rememberShown(state.batch);
      state.sources = Array.isArray(data.sources) ? data.sources : [];
      state.searchedAt = data.searchedAt || now();
      state.lastSuccessfulFilterKey = filterKey;
      state.filtersCollapsed = true;
      saveState();
      renderBookGrid();
      updateFilterSummary();
      renderAiInsight();
      const modeName = MODES.find(item => item[0] === state.mode)?.[1] || '推荐';
      const genreName = state.selectedSubtags.length ? state.selectedSubtags.join('、') : (state.selectedGenres.length ? state.selectedGenres.join('、') : '全站');
      const batchMeta = `${selectedAudienceLabel()} · ${genreName} · ${modeName} · 固定 6 本`;
      $('#batchMeta').textContent = batchMeta;
      $('#liveStatus').className = 'fresh-dot live';
      $('#liveStatus').textContent = '刚刚更新';
      $('#sourceNote').hidden = false;
      $('#sourceNote').open = false;
      const aiNote = state.aiEnabled && state.aiAvailable ? ' AI 正在补充分析。' : '';
      const recycleNote = data.recycleLevel === 1 ? ' 已轮换较早候选。' : data.recycleLevel > 1 ? ' 为补满 6 本，已复用较早候选。' : '';
      const refreshNote = data.backgroundRefresh ? ' 正在后台扩充候选。' : '';
      $('#sourceNoteText').textContent = `来源：${state.sources.join('、') || '公开实时书库'}。${recycleNote}${refreshNote}${aiNote}`;
      if (!hadBatch) $('#batchSection').scrollIntoView({behavior: 'smooth', block: 'start'});
      renderProfile();
      if (state.aiEnabled && state.aiAvailable) {
        const aiPool = (data.analysisCandidates || []).map(normalizeBook).filter(Boolean);
        const batchToken = state.batch.join('|');
        enhanceVisibleBatch(rankedCandidates, aiPool, batchToken, batchMeta);
      }
    } catch (error) {
      state.aiBatchSummary = '';
      renderAiInsight();
      if (!hadBatch) {
        state.batch = [];
        renderBookGrid();
        $('#emptyState').hidden = false;
        $('#emptyState').querySelector('strong').textContent = '未取得完整推荐结果';
        $('#emptyState').querySelector('p').textContent = error.message || '请稍后再试，或适当放宽篇幅和细分条件。';
      }
      $('#liveStatus').textContent = '稍后再试';
      toast(error.message || '实时发现暂时不可用');
    } finally {
      statusTimers.forEach(timer => window.clearTimeout(timer));
      state.isRefreshing = false;
      $('#discoverPage').classList.remove('loading-results');
      $('#batchSection').classList.remove('refreshing');
      button.disabled = false;
      if (nextButton) nextButton.disabled = false;
      button.querySelector('strong').textContent = '开始推荐';
    }
  }

  function openBookDialog(bookId) {
    const book = state.bookCache[bookId];
    if (!book) return;
    state.dialogBookId = bookId;
    $('#dialogCover').src = book.cover;
    $('#dialogCover').classList.remove('cover-broken');
    $('#dialogCover').alt = `《${book.title}》封面`;
    $('#dialogHeat').textContent = book.popularityText;
    $('#dialogTitle').textContent = book.title;
    $('#dialogAuthor').textContent = `${book.author} · ${book.platform}`;
    $('#dialogMeta').innerHTML = bookFacts(book).map(fact => `<span>${esc(fact)}</span>`).join('');
    $('#dialogDesc').textContent = book.description || '详情以原平台页面为准。';
    const strictTags = (book.contentTags || []).filter(tag => Number(tag.confidence || 0) >= .65 && tag.source !== '书名').slice(0, 3);
    const matchNotes = strictTags.map(tag => `${tag.name}：${tag.source}提到“${tag.evidence}”`);
    $('#dialogMatch').hidden = matchNotes.length === 0;
    $('#dialogMatchText').textContent = matchNotes.join('；');
    const aiText = [book.aiSummary, book.aiReason].filter(Boolean).join(' ');
    $('#dialogAi').hidden = !aiText;
    $('#dialogAiText').textContent = aiText;
    $('#dialogSourceLink').href = book.url || '#';
    $('#dislikeReasons').hidden = latestDecision(bookId) !== 'dislike';
    $('#readFeedback').hidden = !['read', 'liked'].includes(latestDecision(bookId));
    updateDialogButtons();
    state.dialogOpenedAt = Date.now();
    bindCoverFallbacks($('#bookDialog'));
    appendEvent(bookId, 'detail');
    $('#bookDialog').showModal();
  }

  function updateDialogButtons() {
    const decision = latestDecision(state.dialogBookId);
    [['#dialogWantButton', 'want'], ['#dialogReadButton', 'read'], ['#dialogDislikeButton', 'dislike']].forEach(([selector, action]) => {
      $(selector).classList.toggle('active', action === 'read' ? ['read', 'liked'].includes(decision) : decision === action);
    });
  }

  function booksByDecision(action) {
    return Object.values(state.bookCache).filter(book => action === 'read'
      ? ['read', 'liked'].includes(latestDecision(book.id))
      : latestDecision(book.id) === action);
  }

  function renderLibrary() {
    const counts = {want: booksByDecision('want').length, read: booksByDecision('read').length, dislike: booksByDecision('dislike').length};
    $('#wantCount').textContent = counts.want;
    $('#readCount').textContent = counts.read;
    $('#dislikeCount').textContent = counts.dislike;
    $$('[data-library-tab]').forEach(button => {
      const active = button.dataset.libraryTab === state.libraryTab;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', String(active));
    });
    const books = booksByDecision(state.libraryTab).reverse();
    if (!books.length) {
      $('#libraryList').innerHTML = `<div class="library-empty">${state.libraryTab === 'want' ? '暂无想看的书，可前往“发现”开始推荐。' : '暂无记录。'}</div>`;
      return;
    }
    $('#libraryList').innerHTML = books.map(book => `<article class="library-book">
      <img src="${esc(book.cover)}" alt="" loading="lazy" referrerpolicy="no-referrer">
      <div class="library-book-copy"><strong>${esc(book.title)}</strong><small>${esc(book.author)} · ${esc(book.genres[0] || book.platform)}</small></div>
      <div class="library-book-actions"><button type="button" data-copy-book="${esc(book.id)}">复制书名</button><button type="button" data-detail="${esc(book.id)}">详情</button></div>
    </article>`).join('');
    $$('[data-copy-book]').forEach(button => button.addEventListener('click', () => copyBook(button.dataset.copyBook)));
    $$('[data-detail]').forEach(button => button.addEventListener('click', () => openBookDialog(button.dataset.detail)));
    bindCoverFallbacks($('#libraryList'));
  }

  function renderProfile() {
    const currentDecisions = currentTasteSignalCount();
    const copied = state.events.filter(event => event.action === 'copy').length;
    const weakSignals = new Set(state.events.filter(event => ['detail', 'copy'].includes(event.action)).map(event => `${event.bookId}:${event.action}`)).size;
    const model = preferenceModel();
    $('#decisionCount').textContent = String(currentDecisions);
    const detailedBooks = new Set(state.events.filter(event => event.action === 'detail').map(event => event.bookId));
    $('#shownCount').textContent = String(detailedBooks.size);
    $('#copiedCount').textContent = String(copied);
    const confidence = currentDecisions >= 20 ? '相对稳定' : currentDecisions >= 8 ? '正在成形' : currentDecisions ? `${currentDecisions} 条线索` : weakSignals ? '弱线索' : '等待选择';
    $('#profileConfidence').textContent = currentDecisions >= 20
      ? '重复偏好权重更高，较早记录会逐步减弱。'
      : currentDecisions >= 8
        ? '已参与个性排序，同时保留少量探索。'
      : currentDecisions >= 3
          ? '正在确认重复出现的偏好，不会由一次选择定型。'
        : currentDecisions
            ? '当前只作弱参考。'
            : weakSignals
              ? '详情和复制只作弱参考；想看才会明显增强。'
              : '添加想看、喜欢或不想看后开始学习。';
    $('#tasteTitle').textContent = currentDecisions >= 20 ? '当前口味趋势' : currentDecisions >= 8 ? '偏好开始成形' : currentDecisions ? '正在了解你的口味' : weakSignals ? '正在观察你的兴趣' : '还没有口味线索';
    $('#profileConfidenceBadge').textContent = confidence;
    const positive = [...model.entries()].filter(([, record]) => record.weight > .04).sort((a, b) => b[1].weight - a[1].weight).slice(0, 6);
    const negative = [...model.entries()].filter(([, record]) => record.weight < -.25).sort((a, b) => a[1].weight - b[1].weight).slice(0, 5);
    $('#avoidCard').hidden = negative.length === 0;
    $('#avoidList').textContent = negative.length ? `${negative.map(([tag]) => tag).join('、')}。来自“不想看”，可在书单撤销。` : '';
    if (!positive.length) {
      $('#tasteList').innerHTML = '<div class="taste-empty">明确选择几本书后显示偏好。展示和“看过”不算喜欢。</div>';
      return;
    }
    $('#tasteList').innerHTML = positive.map(([tag, record]) => {
      const support = record.positiveBooks.size;
      const strength = Math.max(6, Math.min(100, Math.round(Math.abs(record.weight) / 8 * 100)));
      const label = support >= 4 && record.weight >= 3 ? '明显偏好' : support >= 2 ? '可能喜欢' : support === 1 ? '初步线索' : '弱线索';
      const evidenceTitle = support ? `来自 ${support} 本明确选择` : '来自查看详情或复制';
      return `<div class="taste-row" title="${evidenceTitle}"><span>${esc(tag)}</span><div class="taste-bar"><i style="width:${strength}%"></i></div><small>${label}</small></div>`;
    }).join('');
  }

  function renderLearningState() {
    const decisions = currentTasteSignalCount();
    const weakSignals = new Set(state.events.filter(event => ['detail', 'copy'].includes(event.action)).map(event => `${event.bookId}:${event.action}`)).size;
    $('#learningNote').textContent = decisions >= 8
      ? `已参考 ${decisions} 次明确选择，保留少量探索。`
      : decisions >= 3
        ? `已记录 ${decisions} 次明确选择，正在确认重复偏好。`
      : decisions
          ? `已记录 ${decisions} 次明确选择，当前只作弱参考。`
          : weakSignals
            ? '详情和复制仅作弱参考。'
            : '明确选择会改善个性推荐。';
    $('#welcomeNote').textContent = decisions >= 8 ? '根据近期选择持续优化' : '发现下一本';
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (_) {
      const area = document.createElement('textarea');
      area.value = text; area.style.position = 'fixed'; area.style.opacity = '0'; document.body.appendChild(area); area.select();
      const ok = document.execCommand('copy'); area.remove(); return ok;
    }
  }

  async function copyBook(bookId) {
    const book = state.bookCache[bookId];
    if (!book) return;
    if (await copyText(book.title)) {
      appendEvent(bookId, 'copy'); renderProfile(); toast(`已复制《${book.title}》，可去轻悦时光搜索`);
    } else toast('复制失败，请长按书名复制');
  }

  async function copySelected() {
    const books = state.batch.map(id => state.bookCache[id]).filter(book => book && latestDecision(book.id) === 'want');
    if (!books.length) return toast('先选几本想看的书');
    if (await copyText(books.map(book => book.title).join('\n'))) {
      books.forEach(book => appendEvent(book.id, 'copy'));
      renderProfile(); toast(`已复制 ${books.length} 个书名`);
    }
  }

  function showPage(pageId) {
    $$('.page').forEach(page => { page.hidden = page.id !== pageId; });
    $$('[data-nav]').forEach(button => {
      const active = button.dataset.nav === pageId;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    if (pageId === 'libraryPage') renderLibrary();
    if (pageId === 'profilePage') renderProfile();
    window.scrollTo({top: 0, behavior: 'smooth'});
  }

  function exportBackup() {
    const payload = localStorage.getItem(STORAGE_KEY) || '{}';
    const blob = new Blob([payload], {type: 'application/json'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `觅书记录-${new Date().toISOString().slice(0, 10)}.json`;
    link.click(); URL.revokeObjectURL(link.href); toast('备份已导出');
  }

  function importBackup(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const saved = JSON.parse(String(reader.result || ''));
        if (!saved || !Array.isArray(saved.events)) throw new Error('bad');
        localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
        location.reload();
      } catch (_) { toast('这不是有效的觅书备份'); }
    };
    reader.readAsText(file, 'utf-8');
  }

  function toast(message) {
    const node = $('#toast');
    node.textContent = message; node.classList.add('show');
    clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.remove('show'), 2300);
  }

  function closeInfoPopover() {
    const popover = $('#infoPopover');
    if (!popover) return;
    popover.hidden = true;
    $$('.info-tip[aria-expanded="true"]').forEach(button => button.setAttribute('aria-expanded', 'false'));
  }

  function bindInfoTips() {
    document.addEventListener('click', event => {
      const button = event.target.closest('.info-tip');
      if (!button) {
        if (!event.target.closest('#infoPopover')) closeInfoPopover();
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const popover = $('#infoPopover');
      const isOpen = button.getAttribute('aria-expanded') === 'true';
      closeInfoPopover();
      if (isOpen || !button.dataset.tip) return;
      const rect = button.getBoundingClientRect();
      popover.textContent = button.dataset.tip;
      popover.hidden = false;
      const width = Math.min(278, window.innerWidth - 24);
      popover.style.width = `${width}px`;
      popover.style.left = `${Math.max(12, Math.min(window.innerWidth - width - 12, rect.left + rect.width / 2 - width / 2))}px`;
      popover.style.top = `${Math.min(window.innerHeight - popover.offsetHeight - 12, rect.bottom + 9)}px`;
      button.setAttribute('aria-expanded', 'true');
    });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') closeInfoPopover(); });
    window.addEventListener('scroll', closeInfoPopover, {passive: true});
  }

  function updateAiConfigUi(data) {
    state.aiAvailable = Boolean(data && data.enabled);
    state.aiModel = String(data?.model || '');
    $('#aiApiUrl').value = String(data?.apiUrl || '');
    $('#aiModel').value = state.aiModel;
    $('#aiApiKey').value = '';
    $('#aiApiKey').placeholder = data?.hasKey ? '密钥已保存，留空表示不修改' : '首次配置时填写';
    $('#aiConfigBadge').textContent = state.aiAvailable ? (data?.source === 'built-in' ? '服务内置' : '已配置') : '未配置';
    $('#aiConfigBadge').classList.toggle('ready', state.aiAvailable);
    $('#aiStatus').textContent = state.aiAvailable
      ? `${data?.source === 'built-in' ? '服务内置模型' : '已连接'} ${state.aiModel}；三种模式都会按需增强真实候选`
      : '未配置模型时继续使用轻量本机口味';
  }

  async function loadAiConfig() {
    try {
      const response = await fetch(`/api/ai/config?deviceId=${encodeURIComponent(deviceId)}`, {headers: {Accept: 'application/json'}});
      const data = await response.json();
      updateAiConfigUi(data);
    } catch (_) {
      state.aiAvailable = false;
      $('#aiStatus').textContent = '暂时无法读取 AI 配置，仍可使用基础推荐';
    }
  }

  async function saveAndTestAi() {
    const button = $('#aiSaveButton');
    const payload = {
      deviceId,
      apiUrl: $('#aiApiUrl').value.trim(),
      model: $('#aiModel').value.trim(),
      apiKey: $('#aiApiKey').value.trim()
    };
    if (!payload.apiUrl || !payload.model) return toast('请填写 API 地址和模型名称');
    button.disabled = true;
    button.textContent = '正在保存…';
    try {
      let response = await fetch('/api/ai/config', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
      });
      let data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.message || 'AI 配置保存失败');
      $('#aiApiKey').value = '';
      button.textContent = '正在测试连接…';
      response = await fetch('/api/ai/test', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({deviceId})});
      data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.message || '配置已保存，但连接测试失败');
      await loadAiConfig();
      state.aiEnabled = true;
      $('#aiToggle').checked = true;
      saveState();
      toast(`AI 已连接：${data.model || payload.model}`);
    } catch (error) {
      await loadAiConfig();
      toast(error.message || 'AI 配置失败');
    } finally {
      button.disabled = false;
      button.textContent = '保存并测试';
    }
  }

  async function clearAiConfig() {
    if (!window.confirm('确定清除保存在 VPS 上的 AI 地址、模型和密钥吗？')) return;
    try {
      const response = await fetch('/api/ai/config', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({clear: true, deviceId})
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.message || '清除失败');
      await loadAiConfig();
      toast(data.enabled ? '已清除网页配置，服务器环境配置仍在生效' : 'AI 配置已清除');
    } catch (error) {
      toast(error.message || 'AI 配置清除失败');
    }
  }


  function bindEvents() {
    bindInfoTips();
    $('#discoverButton').addEventListener('click', discoverNext);
    $('#nextBatchButton').addEventListener('click', discoverNext);
    $('#copySelectedButton').addEventListener('click', copySelected);
    $('#editFiltersButton').addEventListener('click', () => {
      state.filtersCollapsed = false;
      updateFilterSummary();
      $('#filterPanel').scrollIntoView({behavior: 'smooth', block: 'start'});
    });
    $('#resultFilterButton').addEventListener('click', () => {
      state.filtersCollapsed = false;
      updateFilterSummary();
      window.scrollTo({top: 0, behavior: 'smooth'});
    });
    $('#resetFiltersButton').addEventListener('click', () => {
      state.audience = 'male'; state.selectedGenres = []; state.selectedSubtags = []; state.subtagMatch = 'any'; state.selectedPlatforms = [...PLATFORMS]; state.wordRange = 'any'; state.status = 'all'; state.mode = 'mixed'; state.filtersCollapsed = false; saveState(); renderFilters(); renderLearningState(); toast('已恢复默认筛选条件');
    });
    $$('[data-nav]').forEach(button => button.addEventListener('click', () => showPage(button.dataset.nav)));
    $$('[data-go]').forEach(button => button.addEventListener('click', () => showPage(button.dataset.go)));
    $$('[data-library-tab]').forEach(button => button.addEventListener('click', () => { state.libraryTab = button.dataset.libraryTab; renderLibrary(); }));
    $('#themeButton').addEventListener('click', () => {
      document.body.classList.toggle('dark'); localStorage.setItem('mishu-theme', document.body.classList.contains('dark') ? 'dark' : 'light');
      updateBrowserThemeColor();
    });
    $$('[data-accent-theme]').forEach(button => button.addEventListener('click', () => {
      applyAccentTheme(button.dataset.accentTheme, true);
      $('#palettePicker').removeAttribute('open');
    }));
    $('#palettePicker').addEventListener('toggle', event => {
      event.currentTarget.querySelector('summary')?.setAttribute('aria-expanded', String(event.currentTarget.open));
    });
    document.addEventListener('click', event => {
      const picker = $('#palettePicker');
      if (picker.open && !picker.contains(event.target)) picker.removeAttribute('open');
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') $('#palettePicker').removeAttribute('open');
    });
    const closeDialog = () => {
      if (state.dialogBookId && Date.now() - state.dialogOpenedAt >= 6500) appendEvent(state.dialogBookId, 'dwell');
      $('#bookDialog').close();
    };
    $('#dialogCloseButton').addEventListener('click', closeDialog);
    $('#bookDialog').addEventListener('click', event => { if (event.target === $('#bookDialog')) closeDialog(); });
    $('#dialogWantButton').addEventListener('click', () => setDecision(state.dialogBookId, 'want'));
    $('#dialogReadButton').addEventListener('click', () => {
      const decision = latestDecision(state.dialogBookId);
      if (['read', 'liked'].includes(decision)) {
        setDecision(state.dialogBookId, decision);
        $('#readFeedback').hidden = true;
      } else {
        setDecision(state.dialogBookId, 'read');
        $('#readFeedback').hidden = false;
      }
    });
    $('#dialogDislikeButton').addEventListener('click', () => setDecision(state.dialogBookId, 'dislike'));
    $$('[data-dislike-reason]').forEach(button => button.addEventListener('click', () => {
      if (!state.dialogBookId) return;
      if (button.dataset.dislikeReason === '看过') {
        setDecision(state.dialogBookId, 'read');
        $('#dislikeReasons').hidden = true;
        toast('已改为看过，以后不会重复推荐');
        return;
      }
      appendEvent(state.dialogBookId, 'dislike_reason', {reason: button.dataset.dislikeReason});
      $('#dislikeReasons').hidden = true;
      renderProfile();
      toast(`已记住：不太喜欢${button.dataset.dislikeReason}`);
    }));
    $$('[data-read-feedback]').forEach(button => button.addEventListener('click', () => {
      if (!state.dialogBookId) return;
      const action = button.dataset.readFeedback === 'liked' ? 'liked' : 'read';
      if (latestDecision(state.dialogBookId) !== action) setDecision(state.dialogBookId, action);
      $('#readFeedback').hidden = true;
      toast(action === 'liked' ? '已记住：你喜欢这本' : '已记录为看过，不计入口味');
    }));
    $('#dialogCopyButton').addEventListener('click', () => copyBook(state.dialogBookId));
    $('#dialogSourceLink').addEventListener('click', () => { if (state.dialogBookId) appendEvent(state.dialogBookId, 'source'); });
    $('#aiToggle').addEventListener('change', event => {
      state.aiEnabled = event.target.checked; saveState();
      toast(state.aiEnabled ? (state.aiAvailable ? 'AI 分析与重排已开启' : '已开启；请先填写下方 AI 配置') : '已改为基础排序');
    });
    $('#aiSaveButton').addEventListener('click', saveAndTestAi);
    $('#aiClearButton').addEventListener('click', clearAiConfig);
    $('#syncCreateButton').addEventListener('click', createSyncToken);
    $('#syncJoinButton').addEventListener('click', joinSync);
    $('#syncNowButton').addEventListener('click', () => syncNow());
    $('#copySyncTokenButton').addEventListener('click', () => copyText($('#syncJoinToken').value));
    $('#syncDisconnectButton').addEventListener('click', () => disconnectSync(false));
    $('#syncResetButton').addEventListener('click', () => disconnectSync(true));
    $('#exportButton').addEventListener('click', exportBackup);
    $('#importInput').addEventListener('change', event => { if (event.target.files[0]) importBackup(event.target.files[0]); event.target.value = ''; });
    $('#clearButton').addEventListener('click', () => {
      if (state.sync.connected) return toast('已开启同步，请先在“跨设备同步”中停用并清空，再清除本机记录');
      if (!window.confirm('确定清除书单、口味和已展示记录吗？')) return;
      state.events = []; state.shownIds = []; state.bookCache = {}; state.batch = []; state.filtersCollapsed = false; saveState(); renderBookGrid(); renderLibrary(); renderProfile(); renderLearningState(); updateFilterSummary(); toast('个人记录已清空');
    });
    $('#sourceHealthButton').addEventListener('click', loadSourceHealth);
    $('#authLoginButton').addEventListener('click', loginWithAccessCode);
    $('#accessCodeInput').addEventListener('keydown', event => { if (event.key === 'Enter') loginWithAccessCode(); });
  }

  function showAuthGate(message = '') {
    $('#authGate').hidden = false;
    $('#authMessage').textContent = message;
    window.setTimeout(() => $('#accessCodeInput').focus(), 50);
  }

  async function checkAuthentication() {
    try {
      const response = await fetch('/api/auth/status', {headers: {Accept: 'application/json'}});
      const data = await response.json();
      if (data.required && !data.authenticated) {
        showAuthGate();
        return false;
      }
      $('#authGate').hidden = true;
      return true;
    } catch (_) {
      showAuthGate('暂时无法连接服务，请稍后重试。');
      return false;
    }
  }

  async function loginWithAccessCode() {
    const button = $('#authLoginButton');
    const code = $('#accessCodeInput').value;
    if (!code) return showAuthGate('请输入访问口令。');
    button.disabled = true;
    button.textContent = '正在验证…';
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code})
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.message || '访问口令不正确。');
      $('#accessCodeInput').value = '';
      $('#authGate').hidden = true;
      await loadAiConfig();
      await loadSyncStatus();
      toast('已进入觅书');
    } catch (error) {
      showAuthGate(error.message || '验证失败，请重试。');
    } finally {
      button.disabled = false;
      button.textContent = '进入觅书';
    }
  }

  async function loadSourceHealth() {
    const node = $('#sourceHealthList');
    if (!node.hidden) { node.hidden = true; return; }
    node.hidden = false;
    node.innerHTML = '<p>正在读取来源状态…</p>';
    try {
      const response = await fetch('/api/source-health', {headers: {Accept: 'application/json'}});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.message || '暂时无法读取');
      const sources = Array.isArray(data.sources) ? data.sources : [];
      const labels = {ok: '正常', checking: '检查中', warning: '需留意', risk: '结构风险'};
      node.innerHTML = sources.length
        ? `<button class="source-health-check" id="sourceHealthCheckButton" type="button">检查公开来源</button>${sources.map(item => {
          const last = item.lastAttemptAt || item.lastSuccessAt;
          const detail = item.status === 'ok' ? `最近检查 ${last ? new Date(last).toLocaleString('zh-CN') : '暂无'}` : String(item.message || '等待检查');
          return `<div><span><strong>${esc(item.platform)} <em class="health-${esc(item.status)}">${esc(labels[item.status] || '未知')}</em></strong><small>${esc(detail)}</small></span><b>${Number(item.candidateCount || 0)} 本</b></div>`;
        }).join('')}`
        : '<p>还没有采集记录，首次推荐后会显示。</p>';
      $('#sourceHealthCheckButton')?.addEventListener('click', async event => {
        const button = event.currentTarget; button.disabled = true; button.textContent = '检查中…';
        try {
          await syncRequest('/api/source-health/check', {});
          toast('已开始检查，稍后重新打开即可看到结果');
          window.setTimeout(() => { if (!node.hidden) { node.hidden = true; loadSourceHealth(); } }, 4500);
        } catch (error) { toast(error.message || '检查暂时不可用'); }
        finally { button.disabled = false; button.textContent = '检查公开来源'; }
      });
    } catch (error) {
      node.innerHTML = `<p>${esc(error.message || '暂时无法读取来源状态')}</p>`;
    }
  }

  async function init() {
    loadState();
    if (localStorage.getItem('mishu-theme') === 'dark') document.body.classList.add('dark');
    applyAccentTheme(localStorage.getItem('mishu-accent') || document.documentElement.dataset.accent);
    updateBrowserThemeColor();
    renderFilters(); renderBookGrid(); renderLibrary(); renderProfile(); renderLearningState(); bindEvents();
    renderAiInsight();
    $('#aiToggle').checked = state.aiEnabled;
    if (await checkAuthentication()) {
      const [, syncStatus] = await Promise.all([loadAiConfig(), loadSyncStatus()]);
      if (syncStatus.connected && !syncStatus.unavailable) syncNow(true, syncStatus);
    }
    document.addEventListener('visibilitychange', () => { if (!document.hidden) syncNow(true); });
    window.setInterval(() => { if (!document.hidden) syncNow(true); }, 5 * 60 * 1000);
    if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('/sw.js?v=60').catch(() => {});
  }

  init();
})();

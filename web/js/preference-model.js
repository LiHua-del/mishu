(function attachPreferenceModel(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.MishuPreferenceModel = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function createPreferenceModel() {
  'use strict';

  const DECISIONS = new Set(['want', 'liked', 'read', 'dislike', 'clear']);
  const EXPLICIT_WEIGHTS = {liked: 6, want: 4, dislike: -5};
  const IMPLICIT_WEIGHTS = {copy: 1, source: .15, dwell: .2, detail: .1};
  const HALF_LIFE_DAYS = 150;

  function decayFor(event, nowMs) {
    const occurred = event ? new Date(event.timestamp || 0) : null;
    const days = occurred && !Number.isNaN(occurred.getTime())
      ? Math.max(0, (nowMs - occurred.getTime()) / 86400000)
      : 0;
    return Math.max(.25, Math.pow(.5, days / HALF_LIFE_DAYS));
  }

  function latestDecision(events, bookId) {
    for (let index = events.length - 1; index >= 0; index -= 1) {
      const event = events[index];
      if (event.bookId === bookId && DECISIONS.has(event.action)) return event.action === 'clear' ? '' : event.action;
    }
    return '';
  }

  function latestMatchingEvent(events, bookId, actions) {
    for (let index = events.length - 1; index >= 0; index -= 1) {
      const event = events[index];
      if (event.bookId === bookId && actions.includes(event.action)) return event;
    }
    return null;
  }

  function normalizeTagEntries(entries) {
    const merged = new Map();
    entries.forEach(([rawTag, rawStrength]) => {
      const tag = String(rawTag || '').trim();
      const strength = Number(rawStrength || 0);
      if (!tag || strength <= 0) return;
      merged.set(tag, Math.max(merged.get(tag) || 0, strength));
    });
    const strongest = [...merged.entries()].sort((left, right) => right[1] - left[1]).slice(0, 7);
    const total = strongest.reduce((sum, item) => sum + item[1], 0) || 1;
    return strongest.map(([tag, strength]) => [tag, strength / total]);
  }

  function contentEvidence(book) {
    return (book.contentTags || [])
      .filter(item => item && item.name && Number(item.confidence || 0) >= .65 && item.source !== '书名')
      .map(item => [
        item.name,
        Math.min(1, Number(item.confidence || 0)) * (item.source === '分类' ? 1 : .88)
      ]);
  }

  function tagEvidence(book) {
    const genres = [...new Set(book.genres || [])].map(tag => [tag, .55]);
    return normalizeTagEntries([...genres, ...contentEvidence(book)]);
  }

  function build({books = [], events = [], nowMs = Date.now()} = {}) {
    const model = new Map();
    const booksById = new Map(books.map(book => [book.id, book]));
    const add = (tag, value, bookId, kind) => {
      if (!tag || !Number.isFinite(value) || value === 0) return;
      if (!model.has(tag)) {
        model.set(tag, {
          weight: 0,
          explicitWeight: 0,
          implicitWeight: 0,
          positiveBooks: new Set(),
          negativeBooks: new Set(),
          implicitBooks: new Set()
        });
      }
      const record = model.get(tag);
      record.weight += value;
      if (kind === 'implicit') {
        record.implicitWeight += value;
        if (bookId) record.implicitBooks.add(bookId);
      }
      else record.explicitWeight += value;
      if (kind === 'positive' && bookId) record.positiveBooks.add(bookId);
      if (kind === 'negative' && bookId) record.negativeBooks.add(bookId);
    };

    books.forEach(book => {
      const decision = latestDecision(events, book.id);
      const event = latestMatchingEvent(events, book.id, ['want', 'liked', 'read', 'dislike', 'clear']);
      const value = (EXPLICIT_WEIGHTS[decision] || 0) * decayFor(event, nowMs);
      const kind = value > 0 ? 'positive' : value < 0 ? 'negative' : '';
      if (kind) tagEvidence(book).forEach(([tag, share]) => add(tag, value * share, book.id, kind));
    });

    const seenImplicit = new Set();
    // 同一本书的同类弱互动只计一次，但使用最近一次时间，避免反复点详情刷高权重。
    [...events].reverse().filter(event => Object.hasOwn(IMPLICIT_WEIGHTS, event.action)).forEach(event => {
      const key = `${event.bookId}:${event.action}`;
      if (seenImplicit.has(key)) return;
      seenImplicit.add(key);
      const book = booksById.get(event.bookId);
      if (!book) return;
      const value = IMPLICIT_WEIGHTS[event.action] * decayFor(event, nowMs);
      tagEvidence(book).forEach(([tag, share]) => add(tag, value * share, book.id, 'implicit'));
    });

    const reasonEvents = new Map();
    events.filter(event => event.action === 'dislike_reason').forEach(event => reasonEvents.set(event.bookId, event));
    reasonEvents.forEach((event, bookId) => {
      const book = booksById.get(bookId);
      if (!book || latestDecision(events, bookId) !== 'dislike' || event.reason === '看过') return;
      const value = -2.2 * decayFor(event, nowMs);
      let evidence = [];
      if (event.reason === '平台') evidence = [[`platform:${book.platform || ''}`, 1]];
      else if (event.reason === '题材') evidence = normalizeTagEntries([...new Set(book.genres || [])].map(tag => [tag, 1]));
      else if (event.reason === '设定') evidence = normalizeTagEntries(contentEvidence(book));
      evidence.forEach(([tag, share]) => add(tag, value * share, bookId, 'negative'));
    });

    return model;
  }

  function rankingWeights(model, explicitDecisionCount) {
    const maturity = .25 + .75 * Math.min(Math.max(Number(explicitDecisionCount || 0), 0) / 8, 1);
    const weights = new Map();
    model.forEach((record, tag) => {
      const explicitSupport = Math.max(record.positiveBooks.size, record.negativeBooks.size);
      const explicitConfidence = explicitSupport ? Math.min(1, .65 + .15 * Math.max(0, explicitSupport - 1)) : 0;
      const implicitConfidence = Math.min(.55, .25 + .08 * record.implicitBooks.size);
      const value = record.explicitWeight * maturity * explicitConfidence
        + record.implicitWeight * implicitConfidence;
      if (Math.abs(value) >= .005) weights.set(tag, value);
    });
    return weights;
  }

  return {build, rankingWeights, tagEvidence, latestDecision};
});

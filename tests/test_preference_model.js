'use strict';

const assert = require('node:assert/strict');
const {build, rankingWeights} = require('../web/js/preference-model.js');

const NOW = Date.parse('2026-08-24T12:00:00.000Z');
const event = (bookId, action, extra = {}) => ({bookId, action, timestamp: new Date(NOW).toISOString(), ...extra});
const book = (id, genres, tags) => ({
  id,
  platform: '番茄',
  genres,
  contentTags: tags.map(name => ({name, confidence: .9, source: '简介'}))
});
const sumWeights = model => [...model.values()].reduce((sum, record) => sum + record.weight, 0);

// 只展示不产生任何口味证据。
assert.equal(build({books: [book('a', ['都市'], ['系统'])], events: [], nowMs: NOW}).size, 0);

// 查看详情是微弱信号；加入想看是明确正向，但一本书的总分必须在标签之间分摊。
const oneBook = book('a', ['都市'], ['系统', '重生', '明星']);
const detailOnly = build({books: [oneBook], events: [event('a', 'detail')], nowMs: NOW});
assert.ok(Math.abs(sumWeights(detailOnly) - .1) < 1e-9);
assert.ok([...rankingWeights(detailOnly, 0).values()].some(weight => weight > 0));
const wanted = build({books: [oneBook], events: [event('a', 'detail'), event('a', 'want')], nowMs: NOW});
assert.ok(Math.abs(sumWeights(wanted) - 4.1) < 1e-9);
assert.ok(Math.max(...[...wanted.values()].map(record => record.weight)) < 4.1);

// “喜欢”强于“想看”；“看过”只去重，不自动推断喜欢。
const liked = build({books: [oneBook], events: [event('a', 'liked')], nowMs: NOW});
assert.ok(Math.abs(sumWeights(liked) - 6) < 1e-9);
assert.equal(build({books: [oneBook], events: [event('a', 'read')], nowMs: NOW}).size, 0);

// 只有多本明确选择都出现的共同特征，才会逐渐成为稳定偏好。
const twoBooks = [
  book('a', ['都市'], ['系统', '重生']),
  book('b', ['都市'], ['系统', '娱乐圈'])
];
const repeated = build({books: twoBooks, events: [event('a', 'want'), event('b', 'want')], nowMs: NOW});
assert.equal(repeated.get('都市').positiveBooks.size, 2);
assert.equal(repeated.get('系统').positiveBooks.size, 2);
assert.equal(repeated.get('重生').positiveBooks.size, 1);
assert.ok(repeated.get('系统').weight > repeated.get('重生').weight);

// 样本少时个性权重会被压低，避免一次选择把后续推荐锁死。
const earlyRanking = rankingWeights(wanted, 1);
const matureRanking = rankingWeights(wanted, 8);
assert.ok([...earlyRanking.values()].reduce((sum, value) => sum + value, 0)
  < [...matureRanking.values()].reduce((sum, value) => sum + value, 0));

// 不喜欢的平台原因只影响该平台，不把来源混入普通内容偏好。
const disliked = build({
  books: [oneBook],
  events: [event('a', 'dislike'), event('a', 'dislike_reason', {reason: '平台'})],
  nowMs: NOW
});
assert.ok(disliked.get('platform:番茄').weight < -2);
assert.equal(disliked.get('platform:番茄').negativeBooks.size, 1);

console.log('preference-model: 7 scenarios passed');

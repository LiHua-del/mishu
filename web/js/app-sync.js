(() => {
  'use strict';

  function create(options) {
    const {
      state, deviceId, $, normalizeBook, validEventId, now, saveState, toast, afterMerge
    } = options;
    const {SYNC_ACTIONS} = window.MishuAppConfig;

    function defaultDeviceName() {
      return /iPhone|iPad|iPod/i.test(navigator.userAgent) ? 'iPhone / iPad'
        : /Android/i.test(navigator.userAgent) ? 'Android 设备' : '浏览器设备';
    }

    async function request(path, payload = {}, timeoutMs = 15000) {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetch(path, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({...payload, deviceId, deviceName: defaultDeviceName()}),
          signal: controller.signal
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) throw new Error(data.message || '同步服务暂时不可用');
        return data;
      } catch (error) {
        if (error?.name === 'AbortError') throw new Error('同步请求超时，请稍后重试');
        throw error;
      } finally {
        window.clearTimeout(timer);
      }
    }

    function renderStatus(data = {}) {
      state.sync.connected = Boolean(data.connected);
      const badge = $('#syncBadge');
      const statusLine = $('#syncStatusLine');
      const manage = $('#syncManage');
      const tokenInput = $('#syncJoinToken');
      const joinButton = $('#syncJoinButton');
      const copyButton = $('#copySyncTokenButton');
      const createButton = $('#syncCreateButton');
      const tokenHint = $('#syncTokenHint');
      if (!badge || !statusLine || !manage || !tokenInput || !joinButton || !copyButton || !createButton || !tokenHint) return;
      badge.textContent = state.sync.connected ? '已连接' : '未连接';
      badge.classList.toggle('ready', state.sync.connected);
      statusLine.hidden = !state.sync.connected;
      manage.hidden = !state.sync.connected;
      joinButton.hidden = state.sync.connected;
      copyButton.hidden = !state.sync.connected || !tokenInput.value;
      tokenInput.readOnly = state.sync.connected;
      tokenInput.placeholder = state.sync.connected ? '点击“生成同步令牌”后，可复制给新设备' : '粘贴 mishu-sync- 开头的令牌';
      createButton.textContent = state.sync.connected ? '生成新的同步令牌' : '创建并生成同步令牌';
      tokenHint.dataset.tip = state.sync.connected
        ? '需要添加设备时生成新令牌并复制；生成新令牌后，旧令牌失效。'
        : '粘贴令牌连接；本机有书单再生成令牌分享给自己的其他设备。';
      if (!state.sync.connected) {
        state.sync.initialized = false;
        state.sync.cursor = 0;
        state.sync.sentEventIds = [];
      }
      const text = $('#syncStatusText');
      if (text) {
        const devices = Number(data.deviceCount || 0);
        const time = state.sync.lastSyncedAt ? ` · 上次同步 ${new Date(state.sync.lastSyncedAt).toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})}` : '';
        text.textContent = state.sync.connected ? `${devices || 1} 台设备已连接${time}` : '尚未连接';
      }
      saveState();
    }

    async function loadStatus() {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch('/api/sync/status', {headers: {Accept: 'application/json'}, signal: controller.signal});
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) throw new Error(data.message || '同步状态读取失败');
        renderStatus(data);
        return data;
      } catch (_) {
        // 网络波动不等于同步已断开，保留本机的游标和待发送记录。
        return {connected: state.sync.connected, unavailable: true};
      } finally {
        window.clearTimeout(timer);
      }
    }

    function syncEvents() {
      return state.events.filter(event => SYNC_ACTIONS.has(event.action) && validEventId(event.eventId));
    }

    function mergeData(data) {
      const known = new Set(state.events.map(event => event.eventId).filter(validEventId));
      const incomingBooks = Array.isArray(data.books) ? data.books.map(normalizeBook).filter(Boolean) : [];
      incomingBooks.forEach(book => { state.bookCache[book.id] = book; });
      let changed = incomingBooks.length > 0;
      const incoming = Array.isArray(data.events) ? data.events : [];
      incoming.forEach(event => {
        const eventId = String(event?.eventId || '');
        if (!validEventId(eventId) || known.has(eventId) || !event.bookId || !SYNC_ACTIONS.has(event.action)) return;
        state.events.push({
          eventId, bookId: String(event.bookId), action: String(event.action),
          timestamp: String(event.timestamp || event.receivedAt || now()),
          ...(event.reason ? {reason: String(event.reason)} : {})
        });
        known.add(eventId);
        changed = true;
      });
      state.events = state.events.slice(-1600);
      state.sync.sentEventIds = [...new Set([
        ...state.sync.sentEventIds,
        ...incoming.map(event => String(event?.eventId || '')).filter(validEventId)
      ])].slice(-1800);
      return changed;
    }

    async function syncNow(silent = false, knownStatus = null) {
      if (state.sync.busy) return;
      const status = knownStatus || await loadStatus();
      if (status.unavailable || !status.connected) return;
      state.sync.busy = true;
      const button = $('#syncNowButton');
      if (button) { button.disabled = true; button.textContent = '同步中…'; }
      try {
        const sent = new Set(state.sync.sentEventIds);
        const outbound = syncEvents().filter(event => !sent.has(event.eventId));
        for (let offset = 0; offset < outbound.length; offset += 120) {
          const events = outbound.slice(offset, offset + 120);
          const ids = new Set(events.map(event => event.bookId));
          const books = [...ids].map(id => state.bookCache[id]).filter(Boolean);
          await request('/api/sync/push', {events, books});
          events.forEach(event => sent.add(event.eventId));
        }
        state.sync.sentEventIds = [...sent].slice(-1800);
        let hasMore = true;
        let rounds = 0;
        let changed = false;
        while (hasMore && rounds < 20) {
          const data = await request('/api/sync/pull', {cursor: state.sync.cursor});
          state.sync.cursor = Math.max(state.sync.cursor, Number(data.nextCursor || 0) || 0);
          changed = mergeData(data) || changed;
          hasMore = Boolean(data.hasMore);
          rounds += 1;
        }
        state.sync.initialized = true;
        state.sync.lastSyncedAt = now();
        saveState();
        renderStatus(status);
        if (changed) afterMerge();
        if (!silent) toast('已同步书单与口味记录');
      } catch (error) {
        if (!silent) toast(error.message || '同步失败，请稍后重试');
      } finally {
        state.sync.busy = false;
        if (button) { button.disabled = false; button.textContent = '立即同步'; }
      }
    }

    function scheduleSync() {
      clearTimeout(scheduleSync.timer);
      if (!state.sync.connected) return;
      scheduleSync.timer = window.setTimeout(() => syncNow(true), 1300);
    }

    async function createToken() {
      const button = $('#syncCreateButton');
      if (button) { button.disabled = true; button.textContent = '正在生成…'; }
      try {
        const data = await request('/api/sync/token');
        $('#syncJoinToken').value = String(data.token || '');
        renderStatus(data.status || {connected: true});
        $('#copySyncTokenButton').hidden = !data.token;
        await syncNow(true, data.status || {connected: true});
        toast('连接令牌已生成，请只发送给自己的设备');
      } catch (error) {
        toast(error.message || '令牌生成失败');
      } finally {
        if (button) { button.disabled = false; button.textContent = state.sync.connected ? '生成新的同步令牌' : '创建并生成同步令牌'; }
      }
    }

    async function join() {
      const token = $('#syncJoinToken').value.trim();
      if (!token) return toast('请先粘贴同步令牌');
      const button = $('#syncJoinButton');
      button.disabled = true;
      button.textContent = '连接中…';
      try {
        const data = await request('/api/sync/join', {token});
        $('#syncJoinToken').value = '';
        state.sync.cursor = 0;
        state.sync.initialized = false;
        state.sync.sentEventIds = [];
        renderStatus(data.status || {connected: true});
        await syncNow(true, data.status || {connected: true});
        toast('已连接，并合并书单与口味记录');
      } catch (error) {
        toast(error.message || '连接失败');
      } finally {
        button.disabled = false;
        button.textContent = '连接';
      }
    }

    async function disconnect(reset = false) {
      const prompt = reset
        ? '停用同步会断开所有设备，并清除服务器上的同步记录。确定继续吗？'
        : '只断开这台设备；其他设备和同步记录不会受影响。确定继续吗？';
      if (!window.confirm(prompt)) return;
      try {
        await request(reset ? '/api/sync/reset' : '/api/sync/disconnect');
        $('#syncJoinToken').value = '';
        $('#copySyncTokenButton').hidden = true;
        renderStatus({connected: false});
        toast(reset ? '同步已停用并清空' : '这台设备已断开同步');
      } catch (error) {
        toast(error.message || '操作失败');
      }
    }

    return {request, loadStatus, syncNow, scheduleSync, createToken, join, disconnect};
  }

  window.MishuSync = {create};
})();

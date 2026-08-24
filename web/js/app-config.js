(() => {
  'use strict';

  window.MishuAppConfig = Object.freeze({
    STORAGE_KEY: 'mishu-state-v8',
    DEVICE_KEY: 'mishu-device-id',
    OLD_KEYS: ['mishu-state-v7', 'mishu-state-v6', 'mishu-state-v5', 'mishu-state-v4', 'mishu-state-v3', 'mishu-state-v2', 'mishu-state-v1'],
    AUDIENCES: [['male', '男频'], ['female', '女频'], ['all', '不限']],
    GENRES: ['玄幻', '都市', '仙侠', '科幻', '悬疑灵异', '历史', '游戏', '言情', 'N次元', '现实'],
    PLATFORMS: ['起点', '番茄', '书旗', '七猫', 'QQ阅读'],
    WORD_OPTIONS: [
      ['any', '不限'], ['under30', '30万以下'], ['30to50', '30–50万'],
      ['50to100', '50–100万'], ['100to200', '100–200万'], ['over200', '200万以上']
    ],
    MODES: [
      ['popular', '热门', '优先参考平台榜单'],
      ['random', '随机', '在合格候选中打散'],
      ['mixed', '个性', '根据你的明确选择排序']
    ],
    STATUS_OPTIONS: [
      ['all', '连载、完结都可以'],
      ['completed', '只看完结'],
      ['ongoing', '只看连载']
    ],
    SUBTAG_GROUPS: {
      '都市': ['重生', '娱乐圈', '明星', '神豪', '商战', '校园', '医术', '直播', '都市异能', '系统'],
      '玄幻': ['高武', '东方玄幻', '御兽', '无敌流', '宗门', '诸天', '系统', '重生'],
      '仙侠': ['凡人流', '剑修', '宗门', '无敌流', '诸天', '系统', '重生'],
      '科幻': ['末世', '星际', '机甲', '系统', '重生'],
      '悬疑灵异': ['推理破案', '诡异复苏', '盗墓', '无限流', '系统'],
      '历史': ['历史穿越', '三国', '种田经营', '战争争霸', '重生'],
      '游戏': ['电竞', '网游', '模拟器', '系统'],
      '言情': ['重生', '娱乐圈', '明星', '豪门', '甜宠', '先婚后爱', '校园'],
      'N次元': ['综漫', '同人', '无限流', '系统'],
      '现实': ['职场', '年代', '种田经营']
    },
    DECISIONS: new Set(['want', 'liked', 'read', 'dislike', 'clear']),
    SYNC_ACTIONS: new Set(['want', 'liked', 'read', 'dislike', 'clear', 'dislike_reason', 'detail', 'copy', 'source', 'dwell']),
    ACCENT_THEMES: new Set(['coral', 'amber', 'sage', 'blue', 'plum']),
    COVER_PLACEHOLDER: '/icons/cover-placeholder.svg'
  });
})();

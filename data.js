/**
 * 开奖数据统一加载器（快乐8 / 双色球 / 大乐透）
 *
 * 加载顺序（自动合并，按期号取最新）：
 *   1. 同源静态文件 data/kl8.json | data/ssq.json | data/dlt.json
 *      —— 由 tools/fetch_data.py 或 GitHub Actions 每日刷新，抓的是官方接口
 *   2. 浏览器本地缓存（localStorage），断网时兜底
 *   3. 在线接口（体彩官方对浏览器开放跨域；福彩官方不开放，只靠静态文件）
 *
 * 统一数据格式：{ period, date, nums: [...], extra: [...] }
 *   kl8 -> nums 20 个；ssq -> nums 6 红 + extra [蓝]；dlt -> nums 5 前区 + extra [2 后区]
 */
(function (global) {
  'use strict';

  var CACHE_PREFIX = 'lottery_cache_v2_';

  function timeoutFetch(url, ms) {
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = null;
    var opts = { cache: 'no-store' };
    if (ctrl) {
      opts.signal = ctrl.signal;
      timer = setTimeout(function () { ctrl.abort(); }, ms || 12000);
    }
    return fetch(url, opts).then(function (res) {
      if (timer) clearTimeout(timer);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    }, function (err) {
      if (timer) clearTimeout(timer);
      throw err;
    });
  }

  function num(v, lo, hi) {
    var n = parseInt(v, 10);
    return (!isNaN(n) && n >= lo && n <= hi) ? n : null;
  }

  /* ---------------- 在线源解析 ---------------- */

  var KL_KEYS = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
    'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
    'seventeen', 'eighteen', 'nineteen', 'twenty'];

  function parseHuiniao(list, game) {
    var out = [];
    (list || []).forEach(function (item) {
      var period = String(item.code || item.qihao || item.issue || '');
      if (!period) return;
      var date = String(item.day || item.date || item.open_time || '').slice(0, 10);
      var nums = [], extra = [];
      if (game === 'kl8') {
        nums = KL_KEYS.map(function (k) { return num(item[k], 1, 80); })
          .filter(function (n) { return n !== null; });
      } else if (game === 'ssq') {
        nums = ['one', 'two', 'three', 'four', 'five', 'six']
          .map(function (k) { return num(item[k], 1, 33); })
          .filter(function (n) { return n !== null; });
        var b = num(item.seven, 1, 16);
        extra = b === null ? [] : [b];
      } else if (game === 'dlt') {
        nums = ['one', 'two', 'three', 'four', 'five']
          .map(function (k) { return num(item[k], 1, 35); })
          .filter(function (n) { return n !== null; });
        extra = ['six', 'seven'].map(function (k) { return num(item[k], 1, 12); })
          .filter(function (n) { return n !== null; });
      }
      var need = game === 'kl8' ? 15 : (game === 'ssq' ? 6 : 5);
      if (nums.length < need) return;
      out.push({
        period: period, date: date,
        nums: nums.slice().sort(function (a, b) { return a - b; }),
        extra: extra.slice().sort(function (a, b) { return a - b; })
      });
    });
    return out;
  }

  function parseSportteryDlt(json) {
    var rows = ((json || {}).value || {}).list || [];
    var out = [];
    rows.forEach(function (r) {
      var period = String(r.lotteryDrawNum || '');
      if (!period) return;
      var parts = String(r.lotteryDrawResult || '').trim().split(/\s+/);
      var nums = parts.slice(0, 5).map(function (x) { return num(x, 1, 35); })
        .filter(function (n) { return n !== null; });
      var extra = parts.slice(5, 7).map(function (x) { return num(x, 1, 12); })
        .filter(function (n) { return n !== null; });
      if (nums.length < 5) return;
      out.push({
        period: period,
        date: String(r.lotteryDrawTime || '').slice(0, 10),
        nums: nums.sort(function (a, b) { return a - b; }),
        extra: extra.sort(function (a, b) { return a - b; })
      });
    });
    return out;
  }

  var LIVE = {
    kl8: [{
      name: 'huiniao',
      url: 'https://api.huiniao.top/interface/home/lotteryHistory?type=klb&page=1&limit=100',
      parse: function (j) {
        var d = j.data || {};
        var list = ((d.data || {}).list) || [];
        var rows = parseHuiniao(list, 'kl8');
        if (d.last) rows = rows.concat(parseHuiniao([d.last], 'kl8'));
        return rows;
      }
    }],
    ssq: [{
      name: 'huiniao',
      url: 'https://api.huiniao.top/interface/home/lotteryHistory?type=ssq&page=1&limit=100',
      parse: function (j) {
        var d = j.data || {};
        var list = ((d.data || {}).list) || [];
        var rows = parseHuiniao(list, 'ssq');
        if (d.last) rows = rows.concat(parseHuiniao([d.last], 'ssq'));
        return rows;
      }
    }],
    dlt: [{
      name: 'sporttery',
      url: 'https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85&provinceId=0&pageSize=100&isVerify=1&pageNo=1',
      parse: parseSportteryDlt
    }, {
      name: 'huiniao',
      url: 'https://api.huiniao.top/interface/home/lotteryHistory?type=dlt&page=1&limit=100',
      parse: function (j) {
        var d = j.data || {};
        var list = ((d.data || {}).list) || [];
        var rows = parseHuiniao(list, 'dlt');
        if (d.last) rows = rows.concat(parseHuiniao([d.last], 'dlt'));
        return rows;
      }
    }]
  };

  /* ---------------- 合并工具 ---------------- */

  function periodKey(p) {
    var digits = String(p).replace(/\D/g, '');
    return digits;
  }

  function newer(a, b) {
    var ka = periodKey(a), kb = periodKey(b);
    if (ka.length !== kb.length) return ka.length - kb.length;
    return ka.localeCompare(kb);
  }

  function mergeDraws(bucket, rows, preferNew) {
    (rows || []).forEach(function (d) {
      if (!d || !d.period || !d.nums || !d.nums.length) return;
      var k = periodKey(d.period);
      if (!k) return;
      var exist = bucket[k];
      if (!exist || preferNew || !exist.date) bucket[k] = d;
    });
  }

  function sortDesc(draws) {
    return draws.slice().sort(function (a, b) {
      return newer(b.period, a.period) > 0 ? 1 : -1;
    });
  }

  function readCache(game) {
    try {
      var raw = localStorage.getItem(CACHE_PREFIX + game);
      if (!raw) return null;
      var obj = JSON.parse(raw);
      return (obj && Array.isArray(obj.draws)) ? obj : null;
    } catch (e) { return null; }
  }

  function writeCache(game, payload) {
    try {
      localStorage.setItem(CACHE_PREFIX + game, JSON.stringify({
        updated: payload.updated,
        latest: payload.latest,
        latestDate: payload.latestDate,
        draws: payload.draws
      }));
    } catch (e) { /* 配额满了就算了 */ }
  }

  /* ---------------- 主入口 ---------------- */

  function loadLocalScript(game) {
    // 用 <script> 加载 data/<game>.js：同源、可缓存、并且直接双击打开 html（file://）
    // 也能读到数据，不受 fetch 跨域限制
    return new Promise(function (resolve) {
      var el = document.createElement('script');
      var done = false;
      var finish = function (val) { if (!done) { done = true; resolve(val); } };
      el.src = 'data/' + game + '.js?t=' + Date.now();
      el.async = true;
      el.onload = function () {
        var store = global.__LOTTERY_DATA__ || {};
        finish(store[game] || null);
      };
      el.onerror = function () { finish(null); };
      setTimeout(function () { finish(null); }, 6000);
      document.head.appendChild(el);
    });
  }

  function load(game, options) {
    options = options || {};
    var bucket = {};
    var meta = { updated: '', latest: '', latestDate: '', sources: [] };
    var cache = readCache(game);
    if (cache) mergeDraws(bucket, cache.draws, false);
    if (cache && cache.updated) meta.updated = cache.updated;

    function applyLocal(json) {
      var draws = Array.isArray(json) ? json : (json.draws || []);
      mergeDraws(bucket, draws, true);
      meta.sources.push({
        name: 'local', ok: true,
        latest: (json.latest || (draws[0] && draws[0].period) || '')
      });
      if (json.updated) meta.updated = json.updated;
      if (json.latest) meta.latest = json.latest;
      if (json.latestDate) meta.latestDate = json.latestDate;
    }

    var localTask = loadLocalScript(game).then(function (payload) {
      if (payload) { applyLocal(payload); return true; }
      // 兜底：直接取 json（部分环境没有 js 版本时）
      var localUrl = 'data/' + game + '.json' + (options.fresh ? ('?t=' + Date.now()) : '');
      return timeoutFetch(localUrl, 8000).then(function (json) {
        applyLocal(json);
        return true;
      }).catch(function () {
        meta.sources.push({ name: 'local', ok: false });
        return false;
      });
    });

    return localTask.then(function () {
      var lives = LIVE[game] || [];
      var chain = Promise.resolve();
      lives.forEach(function (src) {
        chain = chain.then(function () {
          return timeoutFetch(src.url, 12000).then(function (json) {
            var rows = src.parse(json);
            mergeDraws(bucket, rows, false);
            meta.sources.push({
              name: src.name, ok: true,
              latest: rows.length ? rows[0].period : ''
            });
          }).catch(function () {
            meta.sources.push({ name: src.name, ok: false });
          });
        });
      });
      return chain;
    }).then(function () {
      var draws = sortDesc(Object.keys(bucket).map(function (k) { return bucket[k]; }));
      if (!draws.length) throw new Error('没有可用的开奖数据');
      var payload = {
        draws: draws,
        latest: draws[0].period,
        latestDate: draws[0].date || meta.latestDate,
        updated: meta.updated || new Date().toISOString(),
        sources: meta.sources
      };
      writeCache(game, payload);
      return payload;
    });
  }

  global.LotteryData = {
    load: load,
    refresh: function (game) { return load(game, { fresh: true }); },
    clearCache: function (game) {
      try { localStorage.removeItem(CACHE_PREFIX + game); } catch (e) { /* ignore */ }
    }
  };
})(window);

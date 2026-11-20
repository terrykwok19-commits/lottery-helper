/* ============================================================
   mobile.js —— 手机端运行时补丁

   只做 CSS 算不出来的那件事：
   分布图左侧「期号列 + 分区统计列」要一起吸在左边，但分区统计的
   吸附位置必须等于期号列的真实宽度（各页字号不同、期数不同都会变），
   所以实测一次写进 --dist-pw，CSS 用 left: var(--dist-pw) 取值。

   桌面端不做任何处理（媒体查询里才生效）。
   ============================================================ */
(function () {
  'use strict';

  var MQ = window.matchMedia('(max-width: 768px)');
  var rafId = 0;

  function measure() {
    rafId = 0;
    if (!MQ.matches) return;                       // 桌面交给各页原本的样式

    var mains = document.querySelectorAll('.dist-main');
    for (var i = 0; i < mains.length; i++) {
      var main = mains[i];
      var per = main.querySelector('.dist-period-col');
      if (!per) continue;
      var w = Math.round(per.getBoundingClientRect().width);
      if (w > 0) main.style.setProperty('--dist-pw', w + 'px');
    }
  }

  function schedule() {
    if (rafId) return;                             // 同一帧内只算一次
    rafId = window.requestAnimationFrame(measure);
  }

  function init() {
    schedule();
    // 分布表是切换标签 / 改期数时动态生成的，DOM 一变就重量
    if (window.MutationObserver) {
      new MutationObserver(schedule).observe(document.body, {
        childList: true,
        subtree: true
      });
    }
    window.addEventListener('resize', schedule);
    window.addEventListener('orientationchange', schedule);
    if (MQ.addEventListener) MQ.addEventListener('change', schedule);
    else if (MQ.addListener) MQ.addListener(schedule);
    // 字体加载完成后列宽会变，兜两次
    setTimeout(schedule, 800);
    setTimeout(schedule, 2500);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

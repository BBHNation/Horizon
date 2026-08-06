(function () {
  'use strict';

  function scoreTier(score, maximum) {
    var normalized = score / maximum * 10;
    if (normalized >= 9) return 'high';
    if (normalized >= 7) return 'good';
    if (normalized >= 5) return 'mid';
    return 'low';
  }

  /** Turn legacy star scores into compact, readable badges. */
  function processScoreBadges() {
    var scoreRe = /⭐️\s*(\d+(?:\.\d+)?)\/10/;
    var targets = document.querySelectorAll(
      '.main-content h2, .main-content h3, .main-content li'
    );
    targets.forEach(function (el) {
      var match = el.innerHTML.match(scoreRe);
      if (!match) return;
      var score = parseFloat(match[1]);
      el.innerHTML = el.innerHTML.replace(
        scoreRe,
        '<span class="score-badge" data-tier="' + scoreTier(score, 10) + '">' +
          match[1] + '</span>'
      );
    });
  }

  /** Highlight each Startup Radar opportunity and its score. */
  function processRadarScores() {
    var scoreRe = /\s+—\s+(\d+(?:\.\d+)?)\/100\s*$/;
    document.querySelectorAll('.main-content h3').forEach(function (heading) {
      var match = heading.innerHTML.match(scoreRe);
      if (!match) return;
      var score = parseFloat(match[1]);
      heading.classList.add('opportunity-heading');
      heading.innerHTML = heading.innerHTML.replace(
        scoreRe,
        ' <span class="radar-score" data-tier="' + scoreTier(score, 100) + '">' +
          match[1] + '</span>'
      );
    });
  }

  function directHeading(main, label) {
    return Array.from(main.querySelectorAll(':scope > h2')).find(function (heading) {
      return heading.textContent.trim() === label;
    });
  }

  function followingList(heading) {
    var node = heading && heading.nextElementSibling;
    while (node && !/^H[1-3]$/.test(node.tagName)) {
      if (node.tagName === 'UL') return node;
      node = node.nextElementSibling;
    }
    return null;
  }

  /** Replace the same-weight intro metadata with a compact report dashboard. */
  function buildReportOverview(main) {
    var quotes = Array.from(main.querySelectorAll(':scope > blockquote')).slice(0, 3);
    if (!quotes.length) return null;

    var overviewText = quotes.map(function (quote) {
      return quote.textContent.trim();
    }).join(' ');
    var fetched = overviewText.match(/本次抓取\s*(\d+)\s*条/);
    var added = overviewText.match(/新增\s*(\d+)\s*条/);
    var analyzed = overviewText.match(/完成\s*(\d+)\s*条/);
    var opportunityCount = main.querySelectorAll('h3.opportunity-heading').length;
    if (!fetched && !analyzed) return null;

    var section = document.createElement('section');
    section.className = 'radar-overview';
    section.setAttribute('aria-label', '本期雷达概览');
    section.innerHTML =
      '<div class="radar-overview__intro">' +
        '<p class="radar-kicker">TODAY\'S RADAR</p>' +
        '<p class="radar-overview__lead">先看结论，再决定哪些机会值得展开。</p>' +
      '</div>' +
      '<div class="radar-metrics">' +
        '<div><strong>' + (fetched ? fetched[1] : '—') + '</strong><span>抓取材料</span></div>' +
        '<div><strong>' + (added ? added[1] : '—') + '</strong><span>新增信号</span></div>' +
        '<div><strong>' + (analyzed ? analyzed[1] : '—') + '</strong><span>深度分析</span></div>' +
        '<div class="is-accent"><strong>' + opportunityCount + '</strong><span>推荐机会</span></div>' +
      '</div>';

    var method = document.createElement('details');
    method.className = 'radar-method';
    method.innerHTML = '<summary>本期样本与选材方法</summary><div class="radar-method__body"></div>';
    var methodBody = method.querySelector('.radar-method__body');
    quotes.forEach(function (quote) {
      Array.from(quote.children).forEach(function (child) {
        methodBody.appendChild(child.cloneNode(true));
      });
      quote.remove();
    });
    section.appendChild(method);

    var actions = main.querySelector(':scope > .page-actions');
    if (actions) actions.insertAdjacentElement('afterend', section);
    else main.insertAdjacentElement('afterbegin', section);
    return section;
  }

  /** Add a small, thumb-friendly table of contents for long reports. */
  function buildRadarNavigation(main, overview) {
    var highlights = directHeading(main, '今天最值得关注');
    var opportunities = directHeading(main, '今日创业机会');
    var skipped = directHeading(main, '今日不建议追');
    if (!highlights || !opportunities) return;

    highlights.id = 'radar-highlights';
    opportunities.id = 'radar-opportunities';
    if (skipped) skipped.id = 'radar-skipped';

    var nav = document.createElement('nav');
    nav.className = 'radar-jump-nav';
    nav.setAttribute('aria-label', '日报内容导航');
    nav.innerHTML =
      '<a href="#radar-highlights"><span>01</span>关键信号</a>' +
      '<a href="#radar-opportunities"><span>02</span>创业机会</a>' +
      (skipped ? '<a href="#radar-skipped"><span>03</span>暂不建议</a>' : '');
    (overview || main.querySelector(':scope > .page-actions')).insertAdjacentElement('afterend', nav);
  }

  /** Keep the three strongest signals visible and fold the secondary signals. */
  function enhanceSignals(main) {
    var heading = directHeading(main, '今天最值得关注');
    var list = followingList(heading);
    if (!list) return;

    list.classList.add('signal-list');
    var items = Array.from(list.children);
    items.slice(0, 3).forEach(function (item, index) {
      item.classList.add('signal-card');
      item.setAttribute('data-rank', String(index + 1).padStart(2, '0'));
    });
    if (items.length <= 3) return;

    var disclosure = document.createElement('details');
    disclosure.className = 'more-signals';
    disclosure.innerHTML =
      '<summary>展开另外 ' + (items.length - 3) + ' 条观察信号</summary>' +
      '<ul class="signal-list signal-list--secondary"></ul>';
    var secondary = disclosure.querySelector('ul');
    items.slice(3).forEach(function (item) { secondary.appendChild(item); });
    list.insertAdjacentElement('afterend', disclosure);
  }

  function fieldName(item) {
    var strong = item.querySelector(':scope > strong');
    return strong ? strong.textContent.replace(/[：:]\s*$/, '').trim() : '';
  }

  /** Turn each flat 13-row opportunity into a scan-first card with optional depth. */
  function enhanceOpportunities(main) {
    var headings = Array.from(main.querySelectorAll(':scope > h3.opportunity-heading'));
    var primaryFields = {
      '目标用户': 'is-audience',
      '当前痛点': 'is-pain',
      '为什么是现在': 'is-timing',
      '7 天 MVP': 'is-mvp',
      '第一批用户在哪里': 'is-users'
    };

    headings.forEach(function (heading, cardIndex) {
      var list = followingList(heading);
      if (!list) return;

      var card = document.createElement('article');
      card.className = 'opportunity-card';
      card.setAttribute('aria-labelledby', 'opportunity-' + (cardIndex + 1));
      heading.id = 'opportunity-' + (cardIndex + 1);
      heading.innerHTML = heading.innerHTML.replace(
        /^\s*(\d+)\.\s*/,
        '<span class="opportunity-rank" aria-label="机会 $1">$1</span>'
      );
      heading.insertAdjacentElement('beforebegin', card);
      card.appendChild(heading);

      var summaryList = document.createElement('ul');
      summaryList.className = 'opportunity-summary';
      var detailList = document.createElement('ul');
      detailList.className = 'opportunity-detail-list';

      Array.from(list.children).forEach(function (item) {
        var name = fieldName(item);
        if (primaryFields[name]) {
          item.classList.add(primaryFields[name]);
          summaryList.appendChild(item);
        } else {
          detailList.appendChild(item);
        }
      });
      list.remove();
      card.appendChild(summaryList);

      if (detailList.children.length) {
        var detail = document.createElement('details');
        detail.className = 'opportunity-detail';
        detail.innerHTML =
          '<summary><span>展开完整分析</span><small>' +
            detailList.children.length + ' 项：方案、商业、风险与证据</small></summary>';
        detail.appendChild(detailList);
        card.appendChild(detail);
      }
    });
  }

  /** The rejection list is useful context, but should not dominate the article. */
  function enhanceSkipped(main) {
    var heading = directHeading(main, '今日不建议追');
    var list = followingList(heading);
    if (!heading || !list) return;

    var disclosure = document.createElement('details');
    disclosure.className = 'skip-disclosure';
    disclosure.id = heading.id || 'radar-skipped';
    disclosure.innerHTML =
      '<summary><span><strong>今日不建议追</strong>' + list.children.length +
        ' 个方向</span><small>展开查看排除理由，避免被热点带偏</small></summary>';
    list.classList.add('skip-list');
    disclosure.appendChild(list);
    heading.replaceWith(disclosure);
  }

  function enhanceRadarReport() {
    var main = document.querySelector('.main-content');
    if (!main || !directHeading(main, '今日创业机会')) return;
    main.classList.add('radar-report');
    var overview = buildReportOverview(main);
    buildRadarNavigation(main, overview);
    enhanceSignals(main);
    enhanceOpportunities(main);
    enhanceSkipped(main);
  }

  function enhanceNewsReport() {
    var main = document.querySelector('.main-content');
    var data = main && main.querySelector(':scope > .news-overview-data');
    if (!main || !data) return;
    main.classList.add('news-report');

    var dashboard = document.createElement('section');
    dashboard.className = 'news-dashboard';
    dashboard.setAttribute('aria-label', '今日新闻概述');
    dashboard.innerHTML =
      '<div class="news-dashboard__heading">' +
        '<p class="radar-kicker">TODAY IN CONTEXT</p>' +
        '<h2>先看全局，再展开事件</h2>' +
      '</div>' +
      '<div class="news-metrics">' +
        '<div><strong>' + data.dataset.fetched + '</strong><span>抓取材料</span></div>' +
        '<div><strong>' + data.dataset.selected + '</strong><span>平衡选材</span></div>' +
        '<div><strong>' + data.dataset.publishers + '</strong><span>独立发布者</span></div>' +
        '<div class="is-accent"><strong>' + data.dataset.corroborated + '/' +
          data.dataset.events + '</strong><span>多源印证 / 总事件</span></div>' +
      '</div>';
    var narrative = document.createElement('div');
    narrative.className = 'news-dashboard__narrative';
    Array.from(data.children).forEach(function (child) {
      narrative.appendChild(child);
    });
    dashboard.appendChild(narrative);
    data.replaceWith(dashboard);

    var events = Array.from(main.querySelectorAll('.news-event'));
    if (!events.length) return;
    var categories = Array.from(new Set(events.map(function (event) {
      return event.dataset.category;
    })));
    var controls = document.createElement('div');
    controls.className = 'news-controls';
    controls.setAttribute('aria-label', '筛选新闻领域');
    var corroboratedCount = events.filter(function (event) {
      return event.dataset.evidence === 'corroborated';
    }).length;
    var primaryCount = events.filter(function (event) {
      return event.dataset.evidence === 'primary';
    }).length;
    var singleCount = events.filter(function (event) {
      return event.dataset.evidence === 'single_source';
    }).length;
    controls.innerHTML = '<button type="button" class="is-active" data-filter="all">全部 <span>' +
      events.length + '</span></button>' +
      '<button type="button" data-evidence-filter="corroborated">多源印证 <span>' +
        corroboratedCount + '</span></button>' +
      '<button type="button" data-evidence-filter="primary">官方/一手 <span>' +
        primaryCount + '</span></button>' +
      '<button type="button" data-evidence-filter="single_source">单源观察 <span>' +
        singleCount + '</span></button>' + categories.map(function (category) {
        var count = events.filter(function (event) {
          return event.dataset.category === category;
        }).length;
        return '<button type="button" data-filter="' + category + '">' + category +
          ' <span>' + count + '</span></button>';
      }).join('');

    var eventHeading = directHeading(main, '今日事件');
    if (eventHeading) eventHeading.insertAdjacentElement('afterend', controls);
    controls.addEventListener('click', function (event) {
      var button = event.target.closest('button[data-filter], button[data-evidence-filter]');
      if (!button) return;
      controls.querySelectorAll('button').forEach(function (item) {
        item.classList.toggle('is-active', item === button);
      });
      events.forEach(function (card) {
        if (button.dataset.evidenceFilter) {
          card.hidden = card.dataset.evidence !== button.dataset.evidenceFilter;
        } else {
          card.hidden = button.dataset.filter !== 'all' &&
            card.dataset.category !== button.dataset.filter;
        }
      });
    });

    events.forEach(function (card, index) {
      var heading = card.querySelector('h3');
      var detail = card.querySelector('.news-event__detail');
      var source = card.querySelector('.news-event__sources');
      if (heading) {
        heading.setAttribute('tabindex', '0');
        heading.setAttribute('role', 'button');
        heading.setAttribute('aria-controls', 'event-detail-' + (index + 1));
      }
      if (detail) detail.id = 'event-detail-' + (index + 1);
      function toggleDetail() {
        if (!detail) return;
        detail.open = !detail.open;
        if (detail.open) detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
      if (heading) {
        heading.addEventListener('click', toggleDetail);
        heading.addEventListener('keydown', function (keyboardEvent) {
          if (keyboardEvent.key === 'Enter' || keyboardEvent.key === ' ') {
            keyboardEvent.preventDefault();
            toggleDetail();
          }
        });
      }
      [detail, source].forEach(function (disclosure) {
        if (!disclosure) return;
        disclosure.addEventListener('toggle', function () {
          card.classList.toggle('is-expanded', Boolean(
            (detail && detail.open) || (source && source.open)
          ));
        });
      });
    });
  }

  /** Add semantic classes without changing the report Markdown. */
  function markSemanticElements() {
    document.querySelectorAll('.main-content p').forEach(function (paragraph) {
      var text = paragraph.textContent.trim();
      if (/^(Tags|标签)\s*:/.test(text)) {
        paragraph.classList.add('tag-line');
      } else if (/^(rss|reddit|github|hackernews|hn|telegram)\s*·/i.test(text)) {
        paragraph.classList.add('source-line');
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    processScoreBadges();
    processRadarScores();
    markSemanticElements();
    enhanceNewsReport();
    enhanceRadarReport();
  });
})();

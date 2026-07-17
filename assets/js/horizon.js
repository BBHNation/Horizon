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
  });
})();

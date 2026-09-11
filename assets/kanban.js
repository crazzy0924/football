/* ═══════════════════════════════════════════════════════
   足球系统 · 看板组件 (kanban.js)
   依赖: assets/vendor/sortable.min.js (可选; 缺失时自动降级为只读看板)
   用法:
     DSHKanban.mount(el, {
       columns: [{ id, title, color, cards: [{ id, title, meta:[]|'', tags:[{text,kind}] }] }],
       sortable: true,                     // 是否允许拖拽
       onMove: function(cardId, from, to){} // 拖拽落位回调
     })
   ═══════════════════════════════════════════════════════ */
(function (root) {
  "use strict";

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function cardsHtml(cards) {
    if (!cards || !cards.length) return '<div class="kb-empty">暂无</div>';
    return cards.map(function (c) {
      var meta = c.meta
        ? '<div class="kb-card-meta">' +
          (Array.isArray(c.meta) ? c.meta : [c.meta]).map(function (m) {
            return "<span>" + esc(m) + "</span>";
          }).join("") + "</div>"
        : "";
      var tags = c.tags && c.tags.length
        ? '<div class="kb-card-tags">' + c.tags.map(function (t) {
            var kind = t.kind ? " kb-" + esc(t.kind) : "";
            return '<span class="kb-tag' + kind + '">' + esc(t.text || t) + "</span>";
          }).join("") + "</div>"
        : "";
      return '<div class="kb-card" data-card-id="' + esc(c.id != null ? c.id : c.title) + '">' +
        '<div class="kb-card-title">' + esc(c.title || "") + "</div>" + meta + tags + "</div>";
    }).join("");
  }

  function columnHtml(col) {
    var dot = col.color ? ' style="background:' + esc(col.color) + '"' : "";
    return '<div class="kb-col" data-col-id="' + esc(col.id) + '">' +
      '<div class="kb-col-head"><span class="kb-col-dot"' + dot + "></span>" +
      '<span class="kb-col-title">' + esc(col.title || "") + "</span>" +
      '<span class="kb-col-count">' + ((col.cards || []).length) + "</span></div>" +
      '<div class="kb-col-body">' + cardsHtml(col.cards) + "</div></div>";
  }

  function syncCounts(boardEl) {
    var cols = boardEl.querySelectorAll(".kb-col");
    for (var i = 0; i < cols.length; i++) {
      var n = cols[i].querySelectorAll(".kb-card").length;
      var badge = cols[i].querySelector(".kb-col-count");
      if (badge) badge.textContent = String(n);
      var body = cols[i].querySelector(".kb-col-body");
      var empty = body && body.querySelector(".kb-empty");
      if (body && n > 0 && empty) empty.remove();
      if (body && n === 0 && !empty) body.insertAdjacentHTML("beforeend", '<div class="kb-empty">暂无</div>');
    }
  }

  var api = {
    mount: function (el, opts) {
      if (!el) throw new Error("DSHKanban.mount: 缺少容器");
      opts = opts || {};
      var cols = opts.columns || [];
      el.classList.add("kb-board");
      el.innerHTML = cols.map(columnHtml).join("");

      var canDrag = opts.sortable !== false && typeof root.Sortable === "function";
      if (canDrag) {
        var bodies = el.querySelectorAll(".kb-col-body");
        for (var i = 0; i < bodies.length; i++) {
          root.Sortable.create(bodies[i], {
            group: "kb-" + (opts.group || "default"),
            animation: 150,
            ghostClass: "kb-ghost",
            dragClass: "kb-drag",
            draggable: ".kb-card",
            onEnd: function (evt) {
              syncCounts(el);
              if (typeof opts.onMove === "function") {
                var card = evt.item.getAttribute("data-card-id");
                var from = evt.from.closest(".kb-col").getAttribute("data-col-id");
                var to = evt.to.closest(".kb-col").getAttribute("data-col-id");
                opts.onMove(card, from, to, evt);
              }
            },
          });
        }
      }
      syncCounts(el);
      return api;
    },
    esc: esc,
    _syncCounts: syncCounts,
  };

  root.DSHKanban = api;
})(typeof window !== "undefined" ? window : this);

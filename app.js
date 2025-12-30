/*
 * Dynamic Learning Experience (DLE)
 * Theme + widgets adapted from example/appsec-theme.js patterns.
 */

// Global Error Catching Net
window.onerror = function (message, source, lineno, colno, error) {
  const msg = `Global Error: ${message} at ${source}:${lineno}:${colno}`;
  console.error('[Ironclad]', msg, error);
  if (window.Notifications && window.Notifications.error) {
    window.Notifications.error(msg);
  } else {
    alert(msg); // Fallback for catastrophic early failures
  }
  return false;
};

window.onunhandledrejection = function (event) {
  const msg = `Unhandled Rejection: ${event.reason}`;
  console.error('[Ironclad]', msg);
  if (window.Notifications && window.Notifications.error) {
    window.Notifications.error(msg);
  }
};

const DLE = (() => {
  const state = {
    interactiveTotal: 0,
    completed: 0,
    quizzesTotal: 0,
    quizzesCorrect: 0
  };

  function setAccentColor(accent) {
    // Disabled to enforce "Hybrid Luxury" global theme
    // if (!accent) return;
    // document.documentElement.style.setProperty('--color-primary', accent);
    // document.documentElement.style.setProperty('--accent-color', accent);
  }

  function resetState() {
    state.interactiveTotal = 0;
    state.completed = 0;
    state.quizzesTotal = 0;
    state.quizzesCorrect = 0;
  }

  function updateProgressUI() {
    recalcInteractiveTotals();
    const statsGrid = document.getElementById('stats-grid');
    if (statsGrid) {
      statsGrid.innerHTML = `
        <div class="stat-box">
          <div class="stat-label">Interactive</div>
          <div class="stat-value">${state.completed}/${state.interactiveTotal}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">Quiz correct</div>
          <div class="stat-value">${state.quizzesCorrect}/${state.quizzesTotal}</div>
        </div>
      `;
    }

    const progressEl = document.getElementById('lesson-progress');
    if (progressEl) {
      progressEl.textContent = `${state.completed}/${state.interactiveTotal || 0}`;
    }

    if (document.getElementById('toc-sheet-list')) {
      updateToc();
    }

    const sections = Array.from(document.querySelectorAll('section.card:not([data-toc-skip])'));
    if (sections.length) {
      const scroller = getPrimaryScroller();
      updateSectionProgress(sections, scroller);
    }

    if (window.EdgePanel && typeof window.EdgePanel.updateProgress === 'function') {
      window.EdgePanel.updateProgress({
        completed: state.completed,
        total: state.interactiveTotal
      });
      if (typeof window.EdgePanel.updatePanelLayout === 'function') {
        window.EdgePanel.updatePanelLayout();
      }
    }
  }

  function recalcInteractiveTotals() {
    try {
      const interactiveNodes = document.querySelectorAll('[data-interactive="true"]');
      state.interactiveTotal = interactiveNodes.length;
      const completedNodes = document.querySelectorAll('[data-interactive="true"][data-completed="true"]');
      state.completed = completedNodes.length;
    } catch (e) {
      console.warn('[Progress] Recalc failed', e);
    }
  }

  function attachInteractiveFallback() {
    const interactiveNodes = document.querySelectorAll('[data-interactive="true"]');
    interactiveNodes.forEach((node) => {
      if (node.dataset.hookAttached) return;
      node.dataset.hookAttached = 'true';
      node.addEventListener('click', () => {
        if (node.dataset.completed === 'true') return;
        node.dataset.completed = 'true';
        updateProgressUI();
      }, { once: true });
    });
  }

  function createCompletionTracker(options = {}) {
    try {
      let completed = false;

      return (isCorrect, element) => {
        try {
          if (completed) return;
          completed = true;

          if (element && element.dataset) {
            element.dataset.completed = 'true';
          }

          state.completed += 1;
          if (options.quiz && isCorrect) {
            state.quizzesCorrect += 1;
          }
          updateProgressUI();
        } catch (e) {
          console.error('[Tracker] Callback failed:', e);
        }
      };
    } catch (e) {
      console.error('[Tracker] Creation failed:', e);
      return () => { }; // No-op fallback
    }
  }

  function createElement(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text) el.textContent = text;
    return el;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function renderCallout(kind, text) {
    const callout = createElement('div', `callout callout-${kind || 'info'}`);
    callout.innerHTML = escapeHtml(text || '');
    return callout;
  }

  function renderBlock(block, container) {
    try {
      if (!block) return;

      // Handle shorthand normalization
      const normalized = window.DLEWidgets.normalize(block);
      if (!normalized) return;
      const interactiveTypes = ['flipcard', 'quiz', 'fill_blank', 'translation', 'collapsible', 'swipe'];

      let rootNode = null;
      const isInteractive = interactiveTypes.includes(normalized.type);
      const tracker = isInteractive ? createCompletionTracker({ quiz: normalized.type === 'quiz' }) : null;

      const node = window.DLEWidgets.render(normalized, {
        onComplete: (val, element) => {
          if (!tracker) return;
          try {
            tracker(val, element || rootNode);
          } catch (e) {
            console.error('[App] Tracker callback failed:', e);
          }
        }
      });

      rootNode = node;

      if (node) {
        if (isInteractive) {
          node.dataset.interactive = 'true';
        }
        container.appendChild(node);
      }

      // Recursively render subsections as sibling cards
      if (normalized.subsections && Array.isArray(normalized.subsections)) {
        normalized.subsections.forEach(sub => {
          renderBlock(sub, container);
        });
      }
    } catch (e) {
      const msg = `Failed to render ${block?.type || 'unknown'}: ${e.message}`;
      console.error(`[App] ${msg}`, e);

      if (window.Notifications && window.Notifications.error) {
        window.Notifications.error(msg);
      }

      // Add error placeholder in the UI
      try {
        const errorBox = createElement('div', 'callout callout-danger');
        errorBox.innerHTML = `⚠️ ${escapeHtml(msg)}`;
        container.appendChild(errorBox);
      } catch (fallbackErr) {
        console.error('[App] Could not even render error box:', fallbackErr);
      }
    }
  }

  function getLessonData() {
    try {
      const raw = sessionStorage.getItem('lesson_json');
      if (!raw) {
        console.warn('[App] No lesson JSON in sessionStorage');
        return { lesson: null, error: 'No lesson JSON found in sessionStorage.' };
      }
      return { lesson: JSON.parse(raw), error: null };
    } catch (e) {
      console.error('[App] Failed to get lesson data:', e);
      if (window.Notifications && window.Notifications.error) {
        window.Notifications.error(`Failed to load lesson: ${e.message}`);
      }
      return { lesson: null, error: e.message };
    }
  }

  function updateToc() {
    try {
      const toc = document.getElementById('toc-sheet-list');
      if (!toc) return;

      toc.innerHTML = '';
      const sections = document.querySelectorAll('section.card:not([data-toc-skip])');

      const tocTitle = 'Table of Contents';
      const tocIntro = '';
      const tocTitleEl = document.getElementById('toc-sheet-title');
      const tocIntroEl = document.getElementById('toc-sheet-intro');
      if (tocTitleEl) tocTitleEl.textContent = tocTitle;
      if (tocIntroEl) tocIntroEl.textContent = tocIntro;

      sections.forEach((section, idx) => {
        const header = section.querySelector('.card-header');
        if (!header) return;

        // Extract normalization info from the card's dataset
        const autoNum = section.dataset.autoNumber || '';
        const level = autoNum ? autoNum.split('.').length : 1;

        const sectionLink = createElement('button', 'toc-link toc-section-link');
        sectionLink.type = 'button';
        const headerText = header.textContent.trim();
        sectionLink.textContent = autoNum && !headerText.startsWith(autoNum)
          ? `${autoNum} - ${headerText}`
          : headerText;
        sectionLink.style.paddingLeft = `${(level - 1) * 1}rem`;
        if (level > 1) {
          sectionLink.style.fontSize = '0.95rem';
          sectionLink.style.opacity = '0.9';
        }
        sectionLink.dataset.sectionIndex = idx;

        sectionLink.addEventListener('click', (e) => {
          e.preventDefault();
          section.scrollIntoView({ behavior: 'smooth', block: 'start' });
          closeTocSheet();
        });

        const sectionStatus = section.dataset.sectionStatus || '';
        sectionLink.classList.toggle('toc-item-done', sectionStatus === 'complete');
        sectionLink.classList.toggle('toc-item-skipped', sectionStatus === 'skipped');

        const interactiveNodes = section.querySelectorAll('[data-interactive="true"]');
        if (interactiveNodes.length > 0) {
          const completedNodes = section.querySelectorAll('[data-interactive="true"][data-completed="true"]');
          if (completedNodes.length === interactiveNodes.length) {
            sectionLink.classList.add('toc-item-complete');
          }
        }
        if (sectionStatus) {
          sectionLink.classList.remove('toc-item-complete');
        }
        toc.appendChild(sectionLink);

        // Add internal headings within this section as sub-links
        const headings = section.querySelectorAll('.card-body h2, .card-body h3');
        headings.forEach(h => {
          const subLink = createElement('button', 'toc-link toc-sub-link');
          subLink.type = 'button';
          subLink.textContent = h.textContent;
          subLink.style.paddingLeft = `${level * 1.25}rem`;
          subLink.style.fontSize = '0.85rem';
          subLink.style.opacity = '0.8';
          subLink.dataset.sectionIndex = idx;
          subLink.addEventListener('click', (e) => {
            e.preventDefault();
            h.scrollIntoView({ behavior: 'smooth', block: 'start' });
            closeTocSheet();
          });
          toc.appendChild(subLink);
        });
      });
    } catch (e) {
      console.error('[App] updateToc failed:', e);
      // Non-critical, don't notify user
    }
  }

  function openTocSheet() {
    const sheet = document.getElementById('toc-sheet');
    const backdrop = document.getElementById('toc-backdrop');
    if (!sheet || !backdrop) return;
    sheet.classList.add('open');
    sheet.setAttribute('aria-hidden', 'false');
    backdrop.hidden = false;
  }

  function closeTocSheet() {
    const sheet = document.getElementById('toc-sheet');
    const backdrop = document.getElementById('toc-backdrop');
    if (!sheet || !backdrop) return;
    sheet.classList.remove('open');
    sheet.setAttribute('aria-hidden', 'true');
    backdrop.hidden = true;
  }

  function initTocSheet() {
    const toggle = document.getElementById('toc-toggle');
    const closeBtn = document.getElementById('toc-close');
    const backdrop = document.getElementById('toc-backdrop');

    toggle?.addEventListener('click', () => {
      const sheet = document.getElementById('toc-sheet');
      if (sheet?.classList.contains('open')) {
        closeTocSheet();
      } else {
        openTocSheet();
      }
    });
    closeBtn?.addEventListener('click', () => closeTocSheet());
    backdrop?.addEventListener('click', () => closeTocSheet());

    const seen = sessionStorage.getItem('toc_seen');
    if (!seen) {
      openTocSheet();
      sessionStorage.setItem('toc_seen', 'true');
    }
  }

  const SectionTimer = {
    sections: [],
    activeIndex: -1,
    activeStart: null,
    tickHandle: null,
    storageKey: null,
    paused: false,
    pauseBtn: null,
    pill: null,
    panel: null,
    overlay: null,
    list: null,
    init(sectionNodes = [], lessonRaw = '') {
      if (!sectionNodes.length) return;
      this.activeIndex = -1;
      this.activeStart = null;
      this.sections = sectionNodes.map((section, idx) => {
        const header = section.querySelector('.card-header');
        const tracker = section.querySelector('[data-section-tracker="true"]');
        const skipBtn = section.querySelector('[data-section-action="skip"]');
        const finishBtn = section.querySelector('[data-section-action="finish"]');
        const autoNum = section.dataset.autoNumber || '';
        const headerText = (header?.textContent || `Section ${idx + 1}`)
          .replace(/\s+/g, ' ')
          .trim();
        return {
          element: section,
          title: autoNum && !headerText.startsWith(autoNum)
            ? `${autoNum} - ${headerText}`
            : headerText,
          key: autoNum || `${idx + 1}`,
          elapsedMs: 0,
          status: 'pending',
          tracker,
          skipBtn,
          finishBtn,
          row: null,
          durationEl: null,
          statusEl: null
        };
      });
      this.buildUI();
      this.bindActions();
      this.restoreState(lessonRaw);
      this.startTick();
      this.setActiveSection(0);
    },
    buildUI() {
      if (this.pill || !document.body) return;
      const pill = document.createElement('button');
      pill.type = 'button';
      pill.className = 'section-timer-pill';
      pill.setAttribute('aria-label', 'Open section time tracker');
      pill.setAttribute('aria-expanded', 'false');
      pill.innerHTML = `
        <span class="section-timer-label">Section Time</span>
        <span class="section-timer-value">0s</span>
      `;

      const overlay = document.createElement('div');
      overlay.className = 'section-timer-overlay';
      overlay.hidden = true;

      const panel = document.createElement('aside');
      panel.className = 'section-timer-panel';
      panel.setAttribute('aria-hidden', 'true');
      panel.setAttribute('aria-label', 'Section time tracker');

      const header = document.createElement('div');
      header.className = 'section-timer-panel-header';

      const title = document.createElement('div');
      title.className = 'section-timer-title';
      title.textContent = 'Section Time Tracker';

      const closeBtn = document.createElement('button');
      closeBtn.type = 'button';
      closeBtn.className = 'section-timer-control section-timer-close';
      closeBtn.setAttribute('aria-label', 'Close section time tracker');
      closeBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M6 6l12 12" />
          <path d="M18 6l-12 12" />
        </svg>
      `;

      const pauseBtn = document.createElement('button');
      pauseBtn.type = 'button';
      pauseBtn.className = 'section-timer-control section-timer-pause';
      pauseBtn.setAttribute('aria-label', 'Pause section timer');
      pauseBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="6" y="4" width="4" height="16" rx="1" />
          <rect x="14" y="4" width="4" height="16" rx="1" />
        </svg>
      `;

      const resetBtn = document.createElement('button');
      resetBtn.type = 'button';
      resetBtn.className = 'section-timer-control section-timer-reset';
      resetBtn.setAttribute('aria-label', 'Reset section progress');
      resetBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M21 12a9 9 0 1 1-2.64-6.36" />
          <path d="M21 3v6h-6" />
        </svg>
      `;

      header.appendChild(title);
      header.appendChild(pauseBtn);
      header.appendChild(resetBtn);
      header.appendChild(closeBtn);

      const list = document.createElement('div');
      list.className = 'section-timer-list';

      this.sections.forEach((section, idx) => {
        const row = document.createElement('button');
        row.className = 'section-timer-row';
        row.type = 'button';
        row.dataset.sectionIndex = idx.toString();
        row.setAttribute('aria-label', `Jump to ${section.title}`);

        const rowTitle = document.createElement('div');
        rowTitle.className = 'section-timer-row-title';
        rowTitle.textContent = section.title;

        const meta = document.createElement('div');
        meta.className = 'section-timer-row-meta';

        const duration = document.createElement('span');
        duration.className = 'section-timer-duration';
        duration.textContent = '0s';

        const status = document.createElement('span');
        status.className = 'section-timer-status status-pending';
        status.textContent = 'Active';

        meta.appendChild(duration);
        meta.appendChild(status);
        row.appendChild(rowTitle);
        row.appendChild(meta);
        list.appendChild(row);

        section.row = row;
        section.durationEl = duration;
        section.statusEl = status;
      });

      panel.appendChild(header);
      panel.appendChild(list);

      pill.addEventListener('click', () => this.togglePanel());
      closeBtn.addEventListener('click', () => this.closePanel());
      pauseBtn.addEventListener('click', () => this.togglePause());
      resetBtn.addEventListener('click', () => this.resetAll());
      overlay.addEventListener('click', () => this.closePanel());

      document.body.appendChild(pill);
      document.body.appendChild(overlay);
      document.body.appendChild(panel);

      this.pill = pill;
      this.panel = panel;
      this.overlay = overlay;
      this.list = list;
      this.pauseBtn = pauseBtn;
    },
    resetAll() {
      this.flushActiveTime();
      this.sections.forEach((section) => {
        section.elapsedMs = 0;
        section.status = 'pending';
        section.element.dataset.sectionStatus = '';
        section.element.classList.remove('card-status-complete', 'card-status-skipped');
        if (section.tracker) {
          section.tracker.dataset.completed = 'false';
          section.tracker.removeAttribute('data-completed');
        }
        if (section.skipBtn) section.skipBtn.disabled = false;
        if (section.finishBtn) section.finishBtn.disabled = false;
      });
      this.activeStart = Date.now();
      updateProgressUI();
      updateToc();
      this.updatePill();
      this.updateList();
      this.saveState();
    },
    async resolveStorageKey(lessonRaw = '') {
      if (!lessonRaw) return null;
      try {
        if (!window.crypto?.subtle) return null;
        const encoder = new TextEncoder();
        const data = encoder.encode(lessonRaw);
        const hashBuffer = await window.crypto.subtle.digest('SHA-1', data);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        const hashHex = hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
        this.storageKey = `dle-section-timer:${hashHex}`;
        return this.storageKey;
      } catch (e) {
        console.warn('[SectionTimer] Failed to compute SHA-1:', e);
        return null;
      }
    },
    async restoreState(lessonRaw = '') {
      const key = await this.resolveStorageKey(lessonRaw);
      if (!key) return;
      try {
        const stored = localStorage.getItem(key);
        if (!stored) return;
        const parsed = JSON.parse(stored);
        if (!parsed || typeof parsed !== 'object') return;
        const sectionData = parsed.sections || {};
        this.sections.forEach((section, idx) => {
          const saved = sectionData[section.key];
          if (!saved) return;
          section.elapsedMs = Math.max(0, Number(saved.elapsedMs) || 0);
          if (saved.status === 'complete' || saved.status === 'skipped') {
            section.status = saved.status;
            section.element.dataset.sectionStatus = saved.status;
            section.element.classList.remove('card-status-complete', 'card-status-skipped');
            section.element.classList.add(saved.status === 'complete' ? 'card-status-complete' : 'card-status-skipped');
            if (section.tracker) {
              section.tracker.dataset.completed = 'true';
            }
            if (section.skipBtn) section.skipBtn.disabled = true;
            if (section.finishBtn) section.finishBtn.disabled = true;
          }
          if (section.row) {
            section.row.dataset.sectionIndex = idx.toString();
          }
        });
        if (this.activeIndex >= 0 && this.sections[this.activeIndex]?.status !== 'pending') {
          this.activeStart = null;
        }
        updateProgressUI();
        updateToc();
        this.updatePill();
        this.updateList();
      } catch (e) {
        console.warn('[SectionTimer] Failed to restore state:', e);
      }
    },
    saveState() {
      if (!this.storageKey) return;
      try {
        const payload = {
          updatedAt: Date.now(),
          sections: this.sections.reduce((acc, section, idx) => {
            let elapsedMs = section.elapsedMs;
            if (idx === this.activeIndex && this.activeStart && section.status === 'pending') {
              elapsedMs += Date.now() - this.activeStart;
            }
            acc[section.key] = {
              elapsedMs,
              status: section.status
            };
            return acc;
          }, {})
        };
        localStorage.setItem(this.storageKey, JSON.stringify(payload));
      } catch (e) {
        console.warn('[SectionTimer] Failed to save state:', e);
      }
    },
    bindActions() {
      this.sections.forEach((section, idx) => {
        section.element.dataset.sectionKey = section.key;
        section.skipBtn?.addEventListener('click', () => this.markSection(idx, 'skipped'));
        section.finishBtn?.addEventListener('click', () => this.markSection(idx, 'complete', section.finishBtn));
        section.row?.addEventListener('click', () => {
          this.scrollToSection(section.element);
          this.setActiveSection(idx);
          this.closePanel();
        });
      });
      window.addEventListener('pagehide', () => {
        this.flushActiveTime();
        this.saveState();
      });
    },
    scrollToSection(target) {
      if (!target) return;
      const scroller = getPrimaryScroller();
      if (scroller && scroller !== window) {
        const scrollerRect = scroller.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const offset = targetRect.top - scrollerRect.top + scroller.scrollTop;
        scroller.scrollTo({ top: Math.max(0, offset - 12), behavior: 'smooth' });
        return;
      }
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },
    startTick() {
      if (this.tickHandle) return;
      if (this.paused) return;
      this.tickHandle = setInterval(() => {
        this.updatePill();
        this.updateList();
        this.saveState();
      }, 1000);
    },
    stopTick() {
      if (!this.tickHandle) return;
      clearInterval(this.tickHandle);
      this.tickHandle = null;
    },
    togglePause() {
      if (this.paused) {
        this.paused = false;
        this.setActiveSection(this.activeIndex);
        this.startTick();
        this.updatePauseButton();
        return;
      }
      this.flushActiveTime();
      this.paused = true;
      this.activeStart = null;
      this.stopTick();
      this.updatePill();
      this.updateList();
      this.saveState();
      this.updatePauseButton();
    },
    updatePauseButton() {
      if (!this.pauseBtn) return;
      if (this.paused) {
        this.pauseBtn.setAttribute('aria-label', 'Resume section timer');
        this.pauseBtn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <polygon points="6 4 20 12 6 20 6 4" />
          </svg>
        `;
      } else {
        this.pauseBtn.setAttribute('aria-label', 'Pause section timer');
        this.pauseBtn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="6" y="4" width="4" height="16" rx="1" />
            <rect x="14" y="4" width="4" height="16" rx="1" />
          </svg>
        `;
      }
    },
    setActiveSection(index) {
      if (index === this.activeIndex) return;
      this.flushActiveTime();
      this.activeIndex = index;
      const section = this.sections[index];
      if (!section) {
        this.activeStart = null;
        return;
      }
      if (!this.paused && section.status === 'pending') {
        this.activeStart = Date.now();
      } else {
        this.activeStart = null;
      }
      this.updatePill();
      this.updateList();
    },
    flushActiveTime() {
      if (this.activeIndex < 0 || !this.activeStart) return;
      const section = this.sections[this.activeIndex];
      if (!section || section.status !== 'pending') {
        this.activeStart = null;
        return;
      }
      section.elapsedMs += Date.now() - this.activeStart;
      this.activeStart = null;
    },
    markSection(index, status, finishButton = null) {
      const section = this.sections[index];
      if (!section || section.status !== 'pending') return;

      if (this.activeIndex === index) {
        this.flushActiveTime();
      }

      section.status = status;
      section.element.dataset.sectionStatus = status;
      section.element.classList.remove('card-status-complete', 'card-status-skipped');
      section.element.classList.add(status === 'complete' ? 'card-status-complete' : 'card-status-skipped');

      if (section.tracker) {
        section.tracker.dataset.completed = 'true';
      }

      if (section.skipBtn) section.skipBtn.disabled = true;
      if (section.finishBtn) section.finishBtn.disabled = true;

      updateProgressUI();
      updateToc();
      this.updatePill();
      this.updateList();
      this.saveState();

      if (status === 'complete') {
        CelebrationManager.celebrateSection({
          sectionEl: section.element,
          finishButton: finishButton || section.finishBtn,
          timerPill: this.pill
        });
      } else if (status === 'skipped') {
        CelebrationManager.reactToSkip({
          skipButton: section.skipBtn,
          timerPill: this.pill
        });
      }
    },
    updatePill() {
      if (!this.pill) return;
      const label = this.pill.querySelector('.section-timer-label');
      const value = this.pill.querySelector('.section-timer-value');
      const section = this.sections[this.activeIndex];
      if (!section || !value || !label) return;

      label.textContent = section.key ? `Section ${section.key}` : 'Section Time';
      const seconds = this.getSectionSeconds(this.activeIndex, true);
      value.textContent = this.formatDuration(seconds);
      this.pill.classList.toggle('is-running', section.status === 'pending');
    },
    updateList() {
      this.sections.forEach((section, idx) => {
        if (!section.durationEl || !section.statusEl) return;
        const seconds = this.getSectionSeconds(idx, true);
        section.durationEl.textContent = this.formatDuration(seconds);
        if (section.row) {
          const isActive = idx === this.activeIndex;
          const isPast = idx < this.activeIndex && section.status === 'pending';
          section.row.classList.toggle('is-active', isActive);
          section.row.classList.toggle('is-past', isPast);
          section.row.classList.toggle('status-pending', section.status === 'pending');
          section.row.classList.toggle('status-complete', section.status === 'complete');
          section.row.classList.toggle('status-skipped', section.status === 'skipped');
          section.row.setAttribute('aria-current', isActive ? 'true' : 'false');
        }

        const status = section.status;
        section.statusEl.classList.remove('status-pending', 'status-complete', 'status-skipped');
        section.statusEl.classList.add(`status-${status}`);
        section.statusEl.textContent = status === 'pending'
          ? (idx === this.activeIndex ? 'Active' : 'Pending')
          : status === 'complete'
            ? 'Done'
            : 'Skipped';
      });
    },
    getSectionSeconds(index, includeActive = false) {
      const section = this.sections[index];
      if (!section) return 0;
      let elapsedMs = section.elapsedMs;
      if (includeActive && index === this.activeIndex && this.activeStart && section.status === 'pending') {
        elapsedMs += Date.now() - this.activeStart;
      }
      return Math.max(0, Math.round(elapsedMs / 1000));
    },
    formatDuration(seconds) {
      const minutes = Math.floor(seconds / 60);
      const secs = Math.max(0, seconds % 60);
      return `${minutes}:${String(secs).padStart(2, '0')}`;
    },
    openPanel() {
      if (!this.panel || !this.overlay || !this.pill) return;
      this.panel.classList.add('open');
      this.panel.setAttribute('aria-hidden', 'false');
      this.overlay.hidden = false;
      this.pill.setAttribute('aria-expanded', 'true');
    },
    closePanel() {
      if (!this.panel || !this.overlay || !this.pill) return;
      this.panel.classList.remove('open');
      this.panel.setAttribute('aria-hidden', 'true');
      this.overlay.hidden = true;
      this.pill.setAttribute('aria-expanded', 'false');
    },
    togglePanel() {
      if (!this.panel?.classList.contains('open')) {
        this.openPanel();
      } else {
        this.closePanel();
      }
    }
  };

  const CelebrationManager = {
    storageKey: 'dle-celebration-settings',
    effectsEnabled: true,
    soundEnabled: true,
    audioCtx: null,
    confetti: {
      container: null,
      frame: null,
      timer: null,
      items: []
    },
    init() {
      try {
        const saved = JSON.parse(localStorage.getItem(this.storageKey) || '{}');
        if (typeof saved.effectsEnabled === 'boolean') {
          this.effectsEnabled = saved.effectsEnabled;
        }
        if (typeof saved.soundEnabled === 'boolean') {
          this.soundEnabled = saved.soundEnabled;
        }
      } catch (e) {
        console.warn('[Celebration] Unable to load preferences', e);
      }
      this.updateUIState();
    },
    persist() {
      try {
        localStorage.setItem(this.storageKey, JSON.stringify({
          effectsEnabled: this.effectsEnabled,
          soundEnabled: this.soundEnabled
        }));
      } catch (e) {
        console.warn('[Celebration] Unable to persist preferences', e);
      }
    },
    toggleSound() {
      this.soundEnabled = !this.soundEnabled;
      this.persist();
      this.updateUIState();
    },
    toggleEffects() {
      this.effectsEnabled = !this.effectsEnabled;
      this.persist();
      this.updateUIState();
    },
    updateUIState() {
      if (window.EdgePanel && typeof window.EdgePanel.refreshUtilityStates === 'function') {
        window.EdgePanel.refreshUtilityStates();
      }
    },
    celebrateSection({ sectionEl, finishButton, timerPill, intensity = 'finish' }) {
      const runEffects = this.effectsEnabled;
      const runSound = this.soundEnabled && intensity !== 'skip';
      if (!runEffects && !runSound) return;
      if (runEffects) {
        if (finishButton && intensity === 'finish') this.sparkleButton(finishButton);
        if (sectionEl) this.flashEdges(sectionEl);
        if (intensity === 'finish') this.launchConfetti();
        if (timerPill) this.animateTimerPill(timerPill, { mode: intensity });
      } else if (timerPill) {
        this.animateTimerPill(timerPill, { mode: intensity });
      }
      if (runSound && intensity === 'finish') {
        this.playSound();
      }
    },
    reactToSkip({ skipButton, timerPill }) {
      if (skipButton) this.showSkipFrown(skipButton);
      if (timerPill) this.animateTimerPill(timerPill, { mode: 'skip' });
    },
    sparkleButton(button) {
      if (!button) return;
      button.classList.remove('finish-sparkle');
      // force reflow to restart animation
      void button.offsetWidth;
      button.classList.add('finish-sparkle');
      const clear = () => button.classList.remove('finish-sparkle');
      button.addEventListener('animationend', clear, { once: true });
    },
    flashEdges(sectionEl) {
      if (!sectionEl) return;
      const existing = sectionEl.querySelector('.card-edge-glow');
      existing?.remove();

      const glow = document.createElement('div');
      glow.className = 'card-edge-glow';
      ['bottom', 'right', 'top', 'left'].forEach((edge) => {
        const line = document.createElement('span');
        line.className = `edge-glow-line edge-glow-${edge}`;
        glow.appendChild(line);
      });
      sectionEl.appendChild(glow);

      const cleanup = () => glow.remove();
      glow.addEventListener('animationend', cleanup, { once: true });
      setTimeout(cleanup, 1400);
    },
    launchConfetti() {
      if (!this.effectsEnabled || !document.body) return;
      this.stopConfetti();

      const random = Math.random;
      const cos = Math.cos;
      const sin = Math.sin;
      const PI = Math.PI;
      const PI2 = PI * 2;
      const confetti = this.confetti;

      const particles = 40;
      const spread = 40;
      const sizeMin = 3;
      const sizeMax = 12 - sizeMin;
      const eccentricity = 10;
      const deviation = 100;
      const dxThetaMin = -0.1;
      const dxThetaMax = -dxThetaMin - dxThetaMin;
      const dyMin = 0.13;
      const dyMax = 0.18;
      const dThetaMin = 0.4;
      const dThetaMax = 0.7 - dThetaMin;

      const colorThemes = [
        function () { return color(200 * random() | 0, 200 * random() | 0, 200 * random() | 0); },
        function () { const black = 200 * random() | 0; return color(200, black, black); },
        function () { const black = 200 * random() | 0; return color(black, 200, black); },
        function () { const black = 200 * random() | 0; return color(black, black, 200); },
        function () { return color(200, 100, 200 * random() | 0); },
        function () { return color(200 * random() | 0, 200, 200); },
        function () { const black = 256 * random() | 0; return color(black, black, black); },
        function () { return colorThemes[random() < 0.5 ? 1 : 2](); },
        function () { return colorThemes[random() < 0.5 ? 3 : 5](); },
        function () { return colorThemes[random() < 0.5 ? 2 : 4](); }
      ];

      function color(r, g, b) { return `rgb(${r},${g},${b})`; }
      function interpolation(a, b, t) { return (1 - cos(PI * t)) / 2 * (b - a) + a; }

      const radius = 1 / eccentricity;
      const radius2 = radius + radius;

      function createPoisson() {
        const domain = [radius, 1 - radius];
        let measure = Math.max(0, 1 - radius2);
        const spline = [0, 1];
        let safety = 999;
        while (measure && safety-- > 0) {
          const dart = measure * random();
          let i = 0;
          let l = 0;
          let interval, a, b, c, d;

          for (i = 0, l = domain.length, measure = 0; i < l; i += 2) {
            a = domain[i];
            b = domain[i + 1];
            interval = b - a;
            if (dart < measure + interval) {
              spline.push(dart + a - measure);
              break;
            }
            measure += interval;
          }

          c = dart - radius;
          d = dart + radius;

          for (i = domain.length - 1; i > 0; i -= 2) {
            l = i - 1;
            a = domain[l];
            b = domain[i];
            if (a >= c && a < d) {
              if (b > d) domain[l] = d;
              else domain.splice(l, 2);
            } else if (a < c && b > c) {
              if (b <= d) domain[i] = c;
              else domain.splice(i, 0, c, d);
            }
          }

          for (i = 0, l = domain.length, measure = 0; i < l; i += 2) {
            measure += domain[i + 1] - domain[i];
          }
          measure = Math.max(0, measure);
          if (domain.length < 2) break;
        }
        if (safety <= 0) {
          // Fallback to evenly spaced spline to avoid infinite loops
          return [0, 0.25, 0.5, 0.75, 1];
        }
        return spline.sort();
      }

      const container = document.createElement('div');
      container.style.position = 'fixed';
      container.style.top = '0';
      container.style.left = '0';
      container.style.width = '100%';
      container.style.height = '0';
      container.style.overflow = 'visible';
      container.style.zIndex = '9999';
      container.style.pointerEvents = 'none';

      function Confetto(theme) {
        this.frame = 0;
        this.outer = document.createElement('div');
        this.inner = document.createElement('div');
        this.outer.appendChild(this.inner);

        const outerStyle = this.outer.style;
        const innerStyle = this.inner.style;
        outerStyle.position = 'absolute';
        outerStyle.width = `${(sizeMin + sizeMax * random())}px`;
        outerStyle.height = `${(sizeMin + sizeMax * random())}px`;
        innerStyle.width = '100%';
        innerStyle.height = '100%';
        innerStyle.backgroundColor = theme();

        outerStyle.perspective = '50px';
        outerStyle.transform = `rotate(${360 * random()}deg)`;
        this.axis = `rotate3D(${cos(360 * random())},${cos(360 * random())},0,`;
        this.theta = 360 * random();
        this.dTheta = dThetaMin + dThetaMax * random();
        innerStyle.transform = `${this.axis}${this.theta}deg)`;

        this.x = window.innerWidth * random();
        this.y = -deviation;
        this.dx = sin(dxThetaMin + dxThetaMax * random());
        this.dy = dyMin + dyMax * random();
        outerStyle.left = `${this.x}px`;
        outerStyle.top = `${this.y}px`;

        this.splineX = createPoisson();
        this.splineY = [];
        for (let i = 1, l = this.splineX.length - 1; i < l; ++i) {
          this.splineY[i] = deviation * random();
        }
        this.splineY[0] = this.splineY[this.splineX.length - 1] = deviation * random();

        this.update = function (height, delta) {
          this.frame += delta;
          this.x += this.dx * delta;
          this.y += this.dy * delta;
          this.theta += this.dTheta * delta;

          let phi = (this.frame % 7777) / 7777;
          let i = 0;
          let j = 1;
          while (phi >= this.splineX[j]) i = j++;
          const rho = interpolation(this.splineY[i], this.splineY[j], (phi - this.splineX[i]) / (this.splineX[j] - this.splineX[i]));
          phi *= PI2;

          outerStyle.left = `${this.x + rho * cos(phi)}px`;
          outerStyle.top = `${this.y + rho * sin(phi)}px`;
          innerStyle.transform = `${this.axis}${this.theta}deg)`;
          return this.y > height + deviation;
        };
      }

      function poof() {
        if (confetti.frame) return;

        document.body.appendChild(container);
        confetti.container = container;

        const theme = colorThemes[0];
        let count = 0;
        (function addConfetto() {
          const confetto = new Confetto(theme);
          confetti.items.push(confetto);
          container.appendChild(confetto.outer);
          count += 1;
          if (count >= particles) {
            confetti.timer = null;
            return;
          }
          confetti.timer = setTimeout(addConfetto, spread * random());
        })();

        let prev;
        const loop = (timestamp) => {
          const delta = prev ? timestamp - prev : 0;
          prev = timestamp;
          const height = window.innerHeight;

          for (let i = confetti.items.length - 1; i >= 0; --i) {
            if (confetti.items[i].update(height, delta)) {
              container.removeChild(confetti.items[i].outer);
              confetti.items.splice(i, 1);
            }
          }

          if (confetti.timer || confetti.items.length) {
            confetti.frame = requestAnimationFrame(loop);
            return;
          }

          if (container.parentNode) {
            container.parentNode.removeChild(container);
          }
          confetti.frame = null;
          confetti.container = null;
        };

        confetti.frame = requestAnimationFrame(loop);
      }

      poof();
    },

    stopConfetti() {
      const confetti = this.confetti;
      if (confetti.timer) {
        clearTimeout(confetti.timer);
        confetti.timer = null;
      }
      if (confetti.frame) {
        cancelAnimationFrame(confetti.frame);
        confetti.frame = null;
      }
      confetti.items.forEach((item) => {
        if (item?.outer?.parentNode) item.outer.parentNode.removeChild(item.outer);
      });
      confetti.items = [];
      if (confetti.container?.parentNode) {
        confetti.container.parentNode.removeChild(confetti.container);
      }
      confetti.container = null;
    },
    animateTimerPill(pill, { mode = 'finish' } = {}) {
      if (!pill) return;
      const strong = mode === 'finish';
      pill.classList.remove('timer-pill-solidify', 'timer-pill-solidify-strong', 'timer-pill-muted');
      void pill.offsetWidth;
      pill.classList.add(strong ? 'timer-pill-solidify-strong' : 'timer-pill-solidify');
      pill.addEventListener('animationend', () => {
        pill.classList.remove('timer-pill-solidify', 'timer-pill-solidify-strong');
      }, { once: true });
    },
    showSkipFrown(button) {
      if (!button) return;
      const existing = button.querySelector('.skip-frown');
      existing?.remove();
      const icon = document.createElement('span');
      icon.className = 'skip-frown';
      icon.textContent = '🙁';
      button.appendChild(icon);
      icon.addEventListener('animationend', () => icon.remove(), { once: true });
    },
    playSound() {
      if (!this.soundEnabled) return;
      try {
        if (!this.audioCtx) {
          this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (this.audioCtx.state === 'suspended') {
          this.audioCtx.resume();
        }
        const now = this.audioCtx.currentTime;
        const masterGain = this.audioCtx.createGain();
        masterGain.gain.setValueAtTime(1, now);
        masterGain.connect(this.audioCtx.destination);

        const chimeNotes = [523.25, 659.25, 783.99, 1046.5]; // C major lift
        const padGain = this.audioCtx.createGain();
        padGain.gain.setValueAtTime(0.0001, now);
        padGain.gain.exponentialRampToValueAtTime(0.18, now + 0.14);
        padGain.gain.exponentialRampToValueAtTime(0.0001, now + 3.6);
        const pad = this.audioCtx.createOscillator();
        pad.type = 'sine';
        pad.frequency.setValueAtTime(220, now);
        pad.connect(padGain).connect(masterGain);
        pad.start(now);
        pad.stop(now + 3.8);

        chimeNotes.forEach((freq, idx) => {
          const start = now + idx * 0.16;
          const osc = this.audioCtx.createOscillator();
          const gain = this.audioCtx.createGain();
          osc.type = 'sine';
          osc.frequency.setValueAtTime(freq, start);
          osc.detune.setValueAtTime(6, start);
          gain.gain.setValueAtTime(0.0001, start);
          gain.gain.linearRampToValueAtTime(0.32, start + 0.06);
          gain.gain.exponentialRampToValueAtTime(0.0001, start + 1.35);
          osc.connect(gain).connect(masterGain);
          osc.start(start);
          osc.stop(start + 1.2);
        });
      } catch (e) {
        console.warn('[Celebration] Unable to play sound', e);
      }
    }
  };

  window.CelebrationManager = CelebrationManager;

  function getPrimaryScroller() {
    const scroller = document.querySelector('.viewer-main');
    if (!scroller) return window;
    const styles = window.getComputedStyle(scroller);
    const canScroll = scroller.scrollHeight > scroller.clientHeight + 1;
    const allowScroll = ['auto', 'scroll'].includes(styles.overflowY);
    return canScroll && allowScroll ? scroller : window;
  }

  function updateSectionProgress(sections, scroller = window) {
    const total = sections.length;
    if (total === 0) return;

    const scrollerRect = scroller === window ? null : scroller.getBoundingClientRect();
    const anchor = (scrollerRect ? scrollerRect.top : 0) + 140;
    let index = 0;
    let fallbackIndex = 0;

    sections.forEach((sec, i) => {
      const rect = sec.getBoundingClientRect();
      if (rect.top <= anchor) {
        fallbackIndex = i;
      }
      if (rect.top <= anchor && rect.bottom > anchor && index === 0) {
        index = i;
      }
    });

    if (index === 0 && fallbackIndex !== 0) {
      index = fallbackIndex;
    }

    const atBottom = scroller === window
      ? (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2)
      : (scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2);
    if (atBottom) {
      index = sections.length - 1;
    }

    const sectionProgress = document.getElementById('section-progress');
    if (sectionProgress) {
      sectionProgress.textContent = `Section ${index + 1} of ${total}`;
    }

    const bar = document.getElementById('section-progress-bar');
    if (bar) {
      const pct = ((index + 1) / total) * 100;
      bar.style.width = `${pct}%`;
    }

    const tocLinks = document.querySelectorAll('.toc-section-link, .toc-sub-link');
    tocLinks.forEach((link) => {
      const idx = Number(link.dataset.sectionIndex || -1);
      if (idx === -1) return;
      link.classList.toggle('toc-item-active', idx === index);
      link.classList.toggle('toc-item-past', idx < index);
    });

    if (window.EdgePanel && typeof window.EdgePanel.updateSectionProgress === 'function') {
      window.EdgePanel.updateSectionProgress(index + 1, total);
    }

    if (SectionTimer && typeof SectionTimer.setActiveSection === 'function') {
      SectionTimer.setActiveSection(index);
    }
  }

  let activeSearchHighlight = null;

  function clearSearchHighlight() {
    if (activeSearchHighlight) {
      activeSearchHighlight.classList.remove('search-hit');
      activeSearchHighlight = null;
    }
  }

  function searchLesson(term) {
    clearSearchHighlight();
    if (!term) return { found: false };
    const query = term.trim().toLowerCase();
    if (!query) return { found: false };

    const buckets = document.querySelectorAll('.card-header, .card-body, .viewer-title, .stats-card');
    for (const node of buckets) {
      const text = node.textContent || '';
      if (text.toLowerCase().includes(query)) {
        node.classList.add('search-hit');
        node.scrollIntoView({ behavior: 'smooth', block: 'center' });
        activeSearchHighlight = node;
        return { found: true, element: node };
      }
    }

    return { found: false };
  }

  function initViewer() {
    try {
      const main = document.getElementById('lesson-content');
      if (!main) return;

      // Reset UI
      main.innerHTML = '';
      resetState();

      const lessonResult = getLessonData();
      const lesson = lessonResult.lesson;
      const lessonRaw = sessionStorage.getItem('lesson_json') || '';
      if (!lesson || !lesson.blocks) {
        const errorTarget = document.getElementById('lesson-error');
        renderErrorState(
          errorTarget,
          'Lesson missing',
          lessonResult.error || 'No lesson JSON found. Please return to the editor.'
        );
        return;
      }

      const validation = validateLesson(lesson);
      const validationErrors = validation.errors.concat(validation.unknowns);
      if (validationErrors.length) {
        const errorTarget = document.getElementById('lesson-error');
        renderErrorState(errorTarget, 'Lesson invalid', validationErrors.join(' '));
        return;
      }

      setAccentColor(lesson.theme?.accent);
      document.title = lesson.title || 'DLE Lesson';

      const titleEl = document.getElementById('lesson-title');
      if (titleEl) {
        const titleTextEl = titleEl.querySelector('.viewer-title-text');
        if (titleTextEl) {
          titleTextEl.textContent = lesson.title || 'Lesson';
        } else {
          titleEl.textContent = lesson.title || 'Lesson';
        }
      }

      // Recursive numbering logic
      function applyNumbering(blocks, parentNum = '') {
        let count = 0;
        const interactiveTypes = ['flipcard', 'quiz', 'fill_blank', 'translation', 'collapsible'];

        blocks.forEach((b) => {
          const normalized = window.DLEWidgets.normalize(b);
          if (!normalized) return;

          // Global interactive counting
          if (interactiveTypes.includes(normalized.type)) {
            state.interactiveTotal++;
            if (normalized.type === 'quiz') state.quizzesTotal++;
          }

          if (normalized.type === 'section') {
            count++;
            const currentNum = parentNum ? `${parentNum}.${count}` : `${count}`;
            b._autoNumber = currentNum;
            normalized._autoNumber = currentNum;

            // Internal headings numbering and interactive counting
            let subCount = 0;
            if (normalized.items) {
              normalized.items.forEach(item => {
                const normItem = window.DLEWidgets.normalize(item);
                if (interactiveTypes.includes(normItem.type)) {
                  state.interactiveTotal++;
                  if (normItem.type === 'quiz') state.quizzesTotal++;
                }

                if (normItem.type === 'heading') {
                  subCount++;
                  item._autoNumber = `${currentNum}.${subCount}`;
                }
              });
            }

            // Recursive subsections numbering
            if (normalized.subsections) {
              applyNumbering(normalized.subsections, currentNum);
            }
          }
        });
      }

      applyNumbering(lesson.blocks);

      lesson.blocks.forEach((block) => {
        renderBlock(block, main);
      });

      TranslationSettings.refreshFromDocument();

      const sections = Array.from(document.querySelectorAll('section.card:not([data-toc-skip])'));
      SectionTimer.init(sections, lessonRaw);
      updateProgressUI();
      attachInteractiveFallback();

      // Initialize viewer utilities
      try {
        updateToc();
        initTocSheet();
        CollapsibleCards.init();
        applyTableScroll();
      } catch (err) {
        console.error('[App] Viewer utility initialization failed:', err);
      }

      const scroller = getPrimaryScroller();
      updateSectionProgress(sections, scroller);
      const scrollTarget = scroller === window ? window : scroller;
      scrollTarget.addEventListener('scroll', () => updateSectionProgress(sections, scroller));

      if (window.EdgePanel && typeof window.EdgePanel.bindActions === 'function') {
        const scroller = getPrimaryScroller();
        window.EdgePanel.bindActions({
          openToc: () => openTocSheet(),
          scrollTop: () => {
            if (scroller && scroller !== window) {
              scroller.scrollTo({ top: 0, behavior: 'smooth' });
            } else {
              window.scrollTo({ top: 0, behavior: 'smooth' });
            }
          },
          scrollBottom: () => {
            if (scroller && scroller !== window) {
              scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
            } else {
              window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
            }
          },
          search: (term) => searchLesson(term)
        });
      }
    } catch (e) {
      const msg = `Viewer initialization failed: ${e.message}`;
      console.error('[App]', msg, e);

      if (window.Notifications && window.Notifications.error) {
        window.Notifications.error(msg);
      }
    }
  }

  function validateLesson(lesson) {
    const errors = [];
    const unknowns = [];

    const supportedWidgetTypes = new Set([
      'paragraph',
      'heading',
      'list',
      'callout',
      'quiz',
      'flipcard',
      'fill_blank',
      'collapsible',
      'translation',
      'section',
      'table',
      'comparison',
      'codeviewer',
      'treeview',
      'swipe',
      'freeText',
      'stepFlow',
      'asciiDiagram',
      'checklist',
      'console'
    ]);

    const supportedBlockTypes = new Set(['section', 'quiz']);

    const shorthandKeys = new Set([
      'p',
      'section',
      'ul',
      'ol',
      'info',
      'tip',
      'warn',
      'err',
      'success',
      'tr',
      'ex',
      'flip',
      'blank',
      'quiz',
      'table',
      'compare',
      'codeviewer',
      'treeview',
      'swipe',
      'freeText',
      'stepFlow',
      'asciiDiagram',
      'checklist',
      'console'
    ]);

    const getNonMetaKeys = (obj) => Object.keys(obj).filter((key) => !key.startsWith('_'));

    const recordUnknown = (label, path, extra = '') => {
      const suffix = extra ? ` ${extra}` : '';
      unknowns.push(`${label} at ${path}.${suffix}`.trim());
    };

    const validateChecklistTree = (tree, path, depth = 1) => {
      if (!Array.isArray(tree)) {
        errors.push(`Checklist at ${path} must include a tree array.`);
        return;
      }
      if (depth > 3) {
        errors.push(`Checklist at ${path} exceeds max depth 3. Edit this JSON block during repair to reduce checklist nesting to max depth 3.`);
        return;
      }
      tree.forEach((node, idx) => {
        const nodePath = `${path}.tree[${idx}]`;
        if (typeof node === 'string') return;
        if (Array.isArray(node)) {
          const title = node[0];
          const children = node[1];
          if (typeof title !== 'string' || !title.trim()) {
            errors.push(`Checklist group at ${nodePath} must include a title.`);
          }
          validateChecklistTree(children, nodePath, depth + 1);
          return;
        }
        errors.push(`Checklist node at ${nodePath} must be a string or group.`);
      });
    };

    const validateStepFlow = (flow, path, depth = 0) => {
      if (!Array.isArray(flow)) {
        errors.push(`StepFlow at ${path} must include a flow array.`);
        return;
      }
      if (depth > 5) {
        errors.push(`StepFlow at ${path} exceeds max branching depth 5. Edit this JSON block during repair to reduce stepFlow branching to max depth 5.`);
        return;
      }
      flow.forEach((node, idx) => {
        const nodePath = `${path}.flow[${idx}]`;
        if (typeof node === 'string') return;
        if (Array.isArray(node)) {
          let choices = null;
          if (Array.isArray(node[0])) {
            choices = node;
          } else {
            const question = node[0];
            if (question !== undefined && typeof question !== 'string') {
              errors.push(`StepFlow branch question at ${nodePath} must be a string.`);
            }
            choices = node[1];
          }
          if (!Array.isArray(choices) || choices.length === 0) {
            errors.push(`StepFlow branch at ${nodePath} must include choices.`);
            return;
          }
          choices.forEach((choice, cIdx) => {
            const choicePath = Array.isArray(node[0]) ? `${nodePath}[${cIdx}]` : `${nodePath}[1][${cIdx}]`;
            if (!Array.isArray(choice)) {
              errors.push(`StepFlow choice at ${choicePath} must be an array.`);
              return;
            }
            const label = choice[0];
            const steps = choice[1];
            if (typeof label !== 'string' || !label.trim()) {
              errors.push(`StepFlow choice label missing at ${choicePath}.`);
            }
            if (!Array.isArray(steps)) {
              errors.push(`StepFlow choice steps missing at ${choicePath}.`);
              return;
            }
            validateStepFlow(steps, choicePath, depth + 1);
          });
          return;
        }
        errors.push(`StepFlow node at ${nodePath} must be a string or branch node.`);
      });
    };

    const validateWidget = (normalized, raw, path) => {
      if (!normalized || !normalized.type) {
        const rawKeys = raw && typeof raw === 'object' && !Array.isArray(raw) ? getNonMetaKeys(raw) : [];
        if (rawKeys.length === 1 && !shorthandKeys.has(rawKeys[0])) {
          recordUnknown(`Unknown widget key "${rawKeys[0]}"`, path);
        } else {
          recordUnknown('Unrecognized widget', path);
        }
        errors.push(`Widget at ${path} could not be resolved to a valid type.`);
        return;
      }

      if (!supportedWidgetTypes.has(normalized.type)) {
        recordUnknown(`Unknown widget type "${normalized.type}"`, path);
        errors.push(`Widget at ${path} uses unsupported type "${normalized.type}".`);
        return;
      }

      if (raw && typeof raw === 'object' && !Array.isArray(raw) && !raw.type) {
        const rawKeys = getNonMetaKeys(raw);
        if (
          rawKeys.length > 1
          && normalized.type !== 'section'
          && normalized.type !== 'quiz'
        ) {
          errors.push(`Widget at ${path} must use exactly one key (found: ${rawKeys.join(', ')}).`);
        }
      }

      switch (normalized.type) {
        case 'paragraph':
          if (typeof normalized.text !== 'string') {
            errors.push(`Paragraph at ${path} must be a string.`);
          }
          break;
        case 'callout':
          if (typeof normalized.text !== 'string') {
            errors.push(`Callout at ${path} must be a string.`);
          }
          break;
        case 'flipcard':
          if (typeof normalized.front !== 'string' || typeof normalized.back !== 'string') {
            errors.push(`Flipcard at ${path} must include front and back strings.`);
          }
          break;
        case 'translation': {
          const primary = normalized.original;
          const secondary = normalized.translated;
          if (typeof primary !== 'string' || typeof secondary !== 'string') {
            errors.push(`Translation at ${path} must include two strings.`);
          }
          break;
        }
        case 'fill_blank':
          if (typeof normalized.sentence !== 'string') {
            errors.push(`Fill-blank at ${path} must include a prompt sentence.`);
          } else if (!normalized.sentence.includes('___')) {
            errors.push(`Fill-blank at ${path} must include "___" in the prompt.`);
          }
          if (typeof normalized.answer !== 'string') {
            errors.push(`Fill-blank at ${path} must include a correct answer string.`);
          }
          if (typeof normalized.hint !== 'string') {
            errors.push(`Fill-blank at ${path} must include a hint string.`);
          }
          if (typeof normalized.explanation !== 'string') {
            errors.push(`Fill-blank at ${path} must include an explanation string.`);
          }
          break;
        case 'list':
          if (!Array.isArray(normalized.items)) {
            errors.push(`List at ${path} must include an array of items.`);
          }
          break;
        case 'quiz': {
          const questions = normalized.questions;
          if (!Array.isArray(questions) || questions.length === 0) {
            errors.push(`Quiz at ${path} must include a non-empty questions array.`);
            break;
          }
          questions.forEach((question, qIdx) => {
            const qText = question?.q ?? question?.question ?? question?.prompt ?? question?.text;
            const choices = question?.c ?? question?.choices ?? question?.options ?? question?.answers;
            const answer = question?.a ?? question?.answer ?? question?.correct ?? question?.correctIndex;
            const explanation = question?.e ?? question?.explanation ?? question?.why ?? question?.reason;
            const qPath = `${path}.questions[${qIdx}]`;

            if (typeof qText !== 'string' || !qText.trim()) {
              errors.push(`Quiz question text missing at ${qPath}.`);
            }
            if (!Array.isArray(choices) || choices.length < 2) {
              errors.push(`Quiz choices missing or too short at ${qPath}.`);
            }
            if (typeof answer !== 'number' || !Number.isInteger(answer)) {
              errors.push(`Quiz answer index must be an integer at ${qPath}.`);
            } else if (Array.isArray(choices) && (answer < 0 || answer >= choices.length)) {
              errors.push(`Quiz answer index out of range at ${qPath}.`);
            }
            if (typeof explanation !== 'string') {
              errors.push(`Quiz explanation missing at ${qPath}.`);
            }
          });
          break;
        }
        case 'swipe': {
          const title = normalized.title || normalized.instructions;
          if (typeof title !== 'string' || !title.trim()) {
            errors.push(`Swipe widget at ${path} must include a title.`);
          }
          const labels = normalized.labels || normalized.buckets;
          if (!Array.isArray(labels) || labels.length < 2) {
            errors.push(`Swipe widget at ${path} must include two bucket labels.`);
          }
          const cards = normalized.cards;
          if (!Array.isArray(cards) || cards.length === 0) {
            errors.push(`Swipe widget at ${path} must include a non-empty cards array.`);
            break;
          }
          cards.forEach((card, idx) => {
            const cPath = `${path}.cards[${idx}]`;
            const text = card?.text ?? card?.front ?? card?.prompt ?? card?.card ?? card?.[0];
            const correctIndex = card?.correctIndex ?? card?.correct ?? card?.answer ?? card?.bucket ?? card?.[1];
            const feedback = card?.feedback ?? card?.explanation ?? card?.reason ?? card?.[2];
            if (typeof text !== 'string' || !text.trim()) {
              errors.push(`Swipe card text missing at ${cPath}.`);
            }
            if (typeof correctIndex !== 'number' || !Number.isInteger(correctIndex) || (correctIndex !== 0 && correctIndex !== 1)) {
              errors.push(`Swipe card correct index must be 0 or 1 at ${cPath}.`);
            }
            if (typeof feedback !== 'string' || !feedback.trim()) {
              errors.push(`Swipe card feedback missing at ${cPath}.`);
            }
          });
          break;
        }
        case 'freeText':
          if (typeof normalized.prompt !== 'string') {
            errors.push(`FreeText at ${path} must include a prompt string.`);
          }
          if (normalized.seedLocked !== undefined && typeof normalized.seedLocked !== 'string') {
            errors.push(`FreeText seedLocked at ${path} must be a string.`);
          }
          if (typeof normalized.text !== 'string') {
            errors.push(`FreeText at ${path} must include a text string.`);
          }
          if (normalized.lang !== undefined && typeof normalized.lang !== 'string') {
            errors.push(`FreeText language at ${path} must be a string.`);
          }
          if (normalized.wordlistCsv !== undefined && typeof normalized.wordlistCsv !== 'string') {
            errors.push(`FreeText wordlist at ${path} must be a string.`);
          }
          if (normalized.mode !== undefined && !['single', 'multi'].includes(normalized.mode)) {
            errors.push(`FreeText mode at ${path} must be "single" or "multi".`);
          }
          if (normalized.singleLine !== undefined && typeof normalized.singleLine !== 'boolean') {
            errors.push(`FreeText singleLine at ${path} must be a boolean.`);
          }
          break;
        case 'stepFlow':
          if (typeof normalized.lead !== 'string') {
            errors.push(`StepFlow at ${path} must include a lead string.`);
          }
          validateStepFlow(normalized.flow, path);
          break;
        case 'asciiDiagram':
          if (typeof normalized.lead !== 'string') {
            errors.push(`AsciiDiagram at ${path} must include a lead string.`);
          }
          if (typeof normalized.diagram !== 'string' || !normalized.diagram.trim()) {
            errors.push(`AsciiDiagram at ${path} must include diagram text.`);
          }
          break;
        case 'checklist':
          if (typeof normalized.lead !== 'string') {
            errors.push(`Checklist at ${path} must include a lead string.`);
          }
          validateChecklistTree(normalized.tree, path);
          break;
        case 'console': {
          if (typeof normalized.lead !== 'string') {
            errors.push(`Console at ${path} must include a lead string.`);
          }
          const mode = normalized.mode;
          if (mode !== 0 && mode !== 1) {
            errors.push(`Console at ${path} must use mode 0 or 1.`);
          }
          if (!Array.isArray(normalized.rulesOrScript)) {
            errors.push(`Console at ${path} must include rules or script array.`);
            break;
          }
          if (mode === 1) {
            normalized.rulesOrScript.forEach((rule, idx) => {
              const rulePath = `${path}.rulesOrScript[${idx}]`;
              if (!Array.isArray(rule) || rule.length < 3) {
                errors.push(`Console rule at ${rulePath} must include [pattern, level, output].`);
                return;
              }
              if (typeof rule[0] !== 'string') {
                errors.push(`Console rule pattern at ${rulePath} must be a string.`);
              }
              if (!['ok', 'err', 'warn'].includes(rule[1])) {
                errors.push(`Console rule level at ${rulePath} must be ok, warn, or err.`);
              }
              if (typeof rule[2] !== 'string') {
                errors.push(`Console rule output at ${rulePath} must be a string.`);
              }
            });
          }
          if (mode === 0) {
            normalized.rulesOrScript.forEach((entry, idx) => {
              const entryPath = `${path}.rulesOrScript[${idx}]`;
              if (!Array.isArray(entry) || entry.length < 3) {
                errors.push(`Console demo entry at ${entryPath} must include [command, runMs, output].`);
                return;
              }
              if (typeof entry[0] !== 'string') {
                errors.push(`Console demo command at ${entryPath} must be a string.`);
              }
              if (typeof entry[1] !== 'number') {
                errors.push(`Console demo runMs at ${entryPath} must be a number.`);
              }
              if (typeof entry[2] !== 'string') {
                errors.push(`Console demo output at ${entryPath} must be a string.`);
              }
            });
          }
          if (normalized.guided !== undefined) {
            if (!Array.isArray(normalized.guided)) {
              errors.push(`Console guided panel at ${path} must be an array.`);
            } else {
              normalized.guided.forEach((entry, idx) => {
                const gPath = `${path}.guided[${idx}]`;
                if (!Array.isArray(entry) || entry.length < 2) {
                  errors.push(`Console guided step at ${gPath} must include [task, solution].`);
                  return;
                }
                if (typeof entry[0] !== 'string') {
                  errors.push(`Console guided task at ${gPath} must be a string.`);
                }
                if (typeof entry[1] !== 'string') {
                  errors.push(`Console guided solution at ${gPath} must be a string.`);
                }
              });
            }
          }
          break;
        }
        case 'section':
          if (typeof normalized.title !== 'string' || !normalized.title.trim()) {
            errors.push(`Section at ${path} is missing a title.`);
          } else if (/^\s*\d+(\.\d+)*[\)\.\-:]*\s+/.test(normalized.title)) {
            errors.push(`Section title at ${path} should not include numbering. Remove the leading number.`);
          }
          if (!Array.isArray(normalized.items)) {
            errors.push(`Section at ${path} must include an items array.`);
          }
          break;
        case 'heading':
          if (typeof normalized.text !== 'string' || !normalized.text.trim()) {
            errors.push(`Heading at ${path} must include text.`);
          }
          break;
        case 'table':
          if (!Array.isArray(normalized.rows) || normalized.rows.length === 0) {
            errors.push(`Table at ${path} must include rows.`);
          }
          break;
        case 'comparison':
          if (!Array.isArray(normalized.items) || normalized.items.length === 0) {
            errors.push(`Comparison at ${path} must include items.`);
          }
          break;
        case 'collapsible':
          if (typeof normalized.title !== 'string' || !normalized.title.trim()) {
            errors.push(`Collapsible at ${path} must include a title.`);
          }
          if (typeof normalized.content !== 'string' || !normalized.content.trim()) {
            errors.push(`Collapsible at ${path} must include content text.`);
          }
          break;
        default:
          break;
      }
    };

    const validateBlock = (block, path, { allowTypes, requireSection } = {}) => {
      if (!block) {
        errors.push(`Block at ${path} is empty.`);
        return;
      }

      const normalized = window.DLEWidgets.normalize(block);
      if (!normalized || !normalized.type) {
        const rawKeys = block && typeof block === 'object' && !Array.isArray(block) ? getNonMetaKeys(block) : [];
        if (rawKeys.length === 1 && !shorthandKeys.has(rawKeys[0])) {
          recordUnknown(`Unknown block key "${rawKeys[0]}"`, path);
        } else {
          recordUnknown('Unrecognized block', path);
        }
        errors.push(`Block at ${path} could not be resolved to a valid type.`);
        return;
      }

      if (!supportedWidgetTypes.has(normalized.type)) {
        recordUnknown(`Unknown block type "${normalized.type}"`, path);
        errors.push(`Block at ${path} uses unsupported type "${normalized.type}".`);
        return;
      }

      if (allowTypes && !allowTypes.has(normalized.type)) {
        errors.push(`Block at ${path} must be one of: ${Array.from(allowTypes).join(', ')}.`);
      }
      if (requireSection && normalized.type !== 'section') {
        errors.push(`Subsection at ${path} must be a section.`);
      }

      if (normalized.type === 'section') {
        validateWidget(normalized, block, path);
        const items = normalized.items || [];
        if (Array.isArray(items)) {
          items.forEach((item, itemIdx) => {
            const itemPath = `${path}.items[${itemIdx}]`;
            const itemNormalized = window.DLEWidgets.normalize(item);
            validateWidget(itemNormalized, item, itemPath);
          });
        }

        if (Array.isArray(normalized.subsections)) {
          normalized.subsections.forEach((sub, subIdx) => {
            const subPath = `${path}.subsections[${subIdx}]`;
            validateBlock(sub, subPath, { requireSection: true });
          });
        }
        return;
      }

      validateWidget(normalized, block, path);
    };

    if (!lesson || typeof lesson !== 'object') {
      errors.push('Lesson JSON must be an object.');
      return { errors, unknowns };
    }

    if (typeof lesson.title !== 'string' || !lesson.title.trim()) {
      errors.push('Lesson title is required and must be a string.');
    }

    if (!Array.isArray(lesson.blocks)) {
      errors.push('Lesson blocks must be an array.');
      return { errors, unknowns };
    }

    lesson.blocks.forEach((block, index) => {
      const path = `blocks[${index}]`;
      validateBlock(block, path, { allowTypes: supportedBlockTypes });
    });

    return { errors, unknowns };
  }

  const JSON_REPAIR_LIMITS = {
    maxTextLength: 800,
    maxListItems: 40,
    maxTableRows: 30,
    maxNestingDepth: 3
  };
  const REPAIR_CONFIRM_KEY = 'dle-repair-confirm';
  const EDITOR_STATE_KEY = 'dle-editor-state';

  function getRepairConfirmSetting() {
    const stored = localStorage.getItem(REPAIR_CONFIRM_KEY);
    if (stored == null) return true;
    return stored === 'true';
  }

  function setRepairConfirmSetting(value) {
    localStorage.setItem(REPAIR_CONFIRM_KEY, value ? 'true' : 'false');
  }

  function formatJsonBlock(value) {
    if (value === undefined) return '(no change)';
    if (value === null) return '(removed)';
    if (typeof value === 'string') return value;
    try {
      return JSON.stringify(value, null, 2);
    } catch (_) {
      return String(value);
    }
  }

  function createRepairLogger(container, statusEl) {
    const entries = [];
    const maxEntries = 120;

    const renderEntry = (entry) => {
      if (!container) return;
      const row = document.createElement('div');
      row.className = `repair-log-entry ${entry.type}`;
      row.tabIndex = 0;

      const msg = document.createElement('span');
      msg.className = 'repair-log-message';
      msg.textContent = entry.message;
      row.appendChild(msg);

      if (entry.details?.before !== undefined || entry.details?.after !== undefined) {
        const popup = document.createElement('div');
        popup.className = 'repair-change-popup';
        popup.innerHTML = `
          <h4>Before</h4>
          <pre class="repair-change-pre"></pre>
          <h4>After</h4>
          <pre class="repair-change-pre"></pre>
        `;
        const preBlocks = popup.querySelectorAll('.repair-change-pre');
        if (preBlocks[0]) preBlocks[0].textContent = formatJsonBlock(entry.details.before);
        if (preBlocks[1]) preBlocks[1].textContent = formatJsonBlock(entry.details.after);
        row.appendChild(popup);

        const togglePopup = () => popup.classList.toggle('show');
        row.addEventListener('click', togglePopup);
        row.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            togglePopup();
          }
        });
      }

      container.appendChild(row);
    };

    const clear = () => {
      entries.length = 0;
      if (container) {
        container.innerHTML = '<div class="repair-log-empty">Run Repair JSON to see fixes here.</div>';
      }
      if (statusEl) statusEl.textContent = 'No repairs yet';
    };

    const log = (message, type = 'info', details = null) => {
      if (!container) return;
      const entry = { message, type, at: new Date().toISOString(), details };
      if (details) entry.details = details;
      entries.push(entry);
      if (entries.length > maxEntries) entries.shift();

      if (container.querySelector('.repair-log-empty')) {
        container.innerHTML = '';
      }
      renderEntry(entry);
      container.scrollTop = container.scrollHeight;

      if (statusEl) {
        const time = new Date(entry.at).toLocaleTimeString('en-US', { hour12: false });
        statusEl.textContent = `${entries.length} entries - last run ${time}`;
      }
    };

    const loadEntries = (items = []) => {
      clear();
      if (!Array.isArray(items) || !items.length) return;
      if (container) container.innerHTML = '';
      items.slice(-maxEntries).forEach((entry) => {
        entries.push(entry);
        renderEntry(entry);
      });
      if (statusEl && entries.length) {
        const time = new Date(entries[entries.length - 1].at).toLocaleTimeString('en-US', { hour12: false });
        statusEl.textContent = `${entries.length} entries - last run ${time}`;
      }
    };

    return { clear, log, entries, loadEntries };
  }

  function findLineNumber(text, snippet) {
    if (!text || !snippet) return null;
    const index = text.indexOf(snippet);
    if (index === -1) return null;
    return text.slice(0, index).split('\n').length;
  }

  function getSnippetFromItem(item) {
    if (item == null) return null;
    if (typeof item === 'string') {
      const trimmed = item.trim();
      if (!trimmed) return null;
      return `"p": "${trimmed.slice(0, 28)}"`;
    }
    if (typeof item !== 'object') return null;
    if (item.section) return `"section": "${String(item.section).slice(0, 28)}"`;
    if (item.p) return `"p": "${String(item.p).slice(0, 28)}"`;
    if (item.info) return `"info": "${String(item.info).slice(0, 28)}"`;
    if (item.tip) return `"tip": "${String(item.tip).slice(0, 28)}"`;
    if (item.warn) return `"warn": "${String(item.warn).slice(0, 28)}"`;
    if (item.err) return `"err": "${String(item.err).slice(0, 28)}"`;
    if (item.success) return `"success": "${String(item.success).slice(0, 28)}"`;
    if (item.tr) return `"tr":`;
    if (item.blank) return `"blank":`;
    if (item.quiz) return `"quiz":`;
    if (item.table) return `"table":`;
    if (item.compare) return `"compare":`;
    return null;
  }

  function describeItemLabel(item) {
    if (item == null) return 'Item';
    if (typeof item === 'string') return `Paragraph "${item.slice(0, 36)}"`;
    if (typeof item !== 'object') return 'Item';
    if (item.section) return `Section "${item.section}"`;
    if (item.p) return `Paragraph "${String(item.p).slice(0, 36)}"`;
    if (item.info) return `Info "${String(item.info).slice(0, 36)}"`;
    if (item.tip) return `Tip "${String(item.tip).slice(0, 36)}"`;
    if (item.warn) return `Warning "${String(item.warn).slice(0, 36)}"`;
    if (item.err) return `Error "${String(item.err).slice(0, 36)}"`;
    if (item.success) return `Success "${String(item.success).slice(0, 36)}"`;
    if (item.tr) return 'Translation pair';
    if (item.blank) return 'Fill-blank';
    if (item.quiz) return 'Quiz';
    if (item.table) return 'Table';
    if (item.compare) return 'Comparison';
    return 'Widget';
  }

  function formatLocation({ path, item, sourceText }) {
    const snippet = getSnippetFromItem(item);
    const line = findLineNumber(sourceText, snippet);
    const label = describeItemLabel(item);
    const lineText = line ? `line ${line}` : 'line unknown';
    return { label, lineText, path };
  }

  async function confirmRemovalIfNeeded(context, payload) {
    if (typeof context.confirmRemoval !== 'function') return { action: 'remove' };
    const decision = await context.confirmRemoval(payload);
    if (!decision || typeof decision !== 'object') return { action: 'remove' };
    return decision;
  }

  function handleUserReplacement(decision, log, location, before) {
    if (decision?.action !== 'replace') return null;
    log(
      `User edited ${location.label} and it is now valid (${location.lineText}).`,
      'info',
      { before, after: decision.value }
    );
    return decision.value;
  }

  function extractPairFromKeys(obj, keyPairs) {
    for (const [leftKey, rightKey] of keyPairs) {
      if (obj[leftKey] !== undefined && obj[rightKey] !== undefined) {
        return [obj[leftKey], obj[rightKey], `${leftKey}/${rightKey}`];
      }
    }
    return null;
  }

  function normalizeInteractiveAliases(item, path, log, context) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return null;

    const translationSource = item.translation || item.translate;
    if (translationSource) {
      if (Array.isArray(translationSource) && translationSource.length >= 2) {
        return { mapped: { tr: [translationSource[0], translationSource[1]] }, note: 'translation array' };
      }
      if (typeof translationSource === 'object') {
        const pair = extractPairFromKeys(translationSource, [
          ['original', 'translated'],
          ['source', 'target'],
          ['left', 'right'],
          ['from', 'to']
        ]);
        if (pair) {
          return { mapped: { tr: [pair[0], pair[1]] }, note: `translation ${pair[2]}` };
        }
      }
    }

    const translationPair = extractPairFromKeys(item, [
      ['original', 'translated'],
      ['source', 'target'],
      ['left', 'right'],
      ['from', 'to']
    ]);
    if (translationPair) {
      return { mapped: { tr: [translationPair[0], translationPair[1]] }, note: `translation ${translationPair[2]}` };
    }

    const sentence = item.sentence ?? item.prompt ?? item.text ?? item.statement ?? null;
    const answer = item.answer ?? item.correct ?? item.solution ?? item.response ?? null;
    const hint = item.hint ?? item.tip ?? item.clue ?? '';
    const explanation = item.explanation ?? item.reason ?? item.why ?? '';
    if (sentence && answer && String(sentence).includes('___')) {
      return { mapped: { blank: [sentence, answer, hint, explanation] }, note: 'fill-blank keys' };
    }

    const front = item.front ?? item.prompt ?? item.question ?? item.term ?? item.word ?? null;
    const back = item.back ?? item.answer ?? item.definition ?? item.meaning ?? null;
    if (front && back) {
      const payload = [front, back];
      const frontHint = item.frontHint ?? item.hint ?? item.clue ?? null;
      const backHint = item.backHint ?? item.revealHint ?? null;
      if (frontHint) payload.push(frontHint);
      if (backHint) payload.push(backHint);
      return { mapped: { flip: payload }, note: 'flipcard keys' };
    }

    const question = item.question ?? item.q ?? item.prompt ?? item.text ?? null;
    const options = item.options ?? item.choices ?? item.c ?? item.answers ?? null;
    const correct = item.answer ?? item.correct ?? item.a ?? item.correctIndex ?? null;
    const explanationAlt = item.explanation ?? item.why ?? item.reason ?? null;
    if (question || options || correct || explanationAlt) {
      return {
        mapped: {
          quiz: {
            title: item.title || 'Quiz',
            questions: [{
              q: question,
              c: options,
              a: correct,
              e: explanationAlt
            }]
          }
        },
        note: 'quiz keys'
      };
    }

    return null;
  }

  function isQuizQuestionLike(item) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return false;
    const hasQuestion = item.question ?? item.q ?? item.prompt ?? item.text;
    const hasOptions = item.options ?? item.choices ?? item.c ?? item.answers;
    return Boolean(hasQuestion || hasOptions);
  }

  function attachSectionRemovalNote(payload, context) {
    if (!context?.currentSection) return payload;
    const { title, kept, remaining } = context.currentSection;
    if (kept === 0 && remaining === 1) {
      const note = ` Removing this will remove the entire section "${title}".`;
      return { ...payload, message: `${payload.message || ''}${note}`.trim() };
    }
    return payload;
  }

  function stripCodeFences(text, log) {
    const match = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
    if (match) {
      log('Removed markdown code fences around JSON.', 'info');
      return match[1].trim();
    }
    return text;
  }

  function stripNonJsonWrapper(text, log) {
    const first = text.search(/[{\[]/);
    const last = Math.max(text.lastIndexOf('}'), text.lastIndexOf(']'));
    if (first === -1 || last === -1) return text;
    if (first > 0 || last < text.length - 1) {
      log('Trimmed leading/trailing non-JSON text.', 'info');
      return text.slice(first, last + 1);
    }
    return text;
  }

  function stripJsonComments(text, log) {
    let result = '';
    let inString = false;
    let quote = '';
    let escaped = false;
    let removed = false;

    for (let i = 0; i < text.length; i++) {
      const char = text[i];
      const next = text[i + 1];

      if (inString) {
        result += char;
        if (escaped) {
          escaped = false;
        } else if (char === '\\') {
          escaped = true;
        } else if (char === quote) {
          inString = false;
        }
        continue;
      }

      if (char === '"' || char === '\'') {
        inString = true;
        quote = char;
        result += char;
        continue;
      }

      if (char === '/' && next === '/') {
        removed = true;
        i += 1;
        while (i < text.length && text[i] !== '\n') i += 1;
        result += '\n';
        continue;
      }

      if (char === '/' && next === '*') {
        removed = true;
        i += 2;
        while (i < text.length && !(text[i] === '*' && text[i + 1] === '/')) i += 1;
        i += 1;
        continue;
      }

      result += char;
    }

    if (removed) log('Stripped JSON comments.', 'info');
    return result;
  }

  function stripTrailingCommas(text, log) {
    const updated = text.replace(/,\s*([}\]])/g, '$1');
    if (updated !== text) log('Removed trailing commas.', 'info');
    return updated;
  }

  function quoteUnquotedKeys(text, log) {
    const isIdStart = (char) => /[A-Za-z_]/.test(char);
    const isId = (char) => /[A-Za-z0-9_]/.test(char);
    let result = '';
    let inString = false;
    let quote = '';
    let escaped = false;
    let changed = false;

    for (let i = 0; i < text.length; i++) {
      const char = text[i];

      if (inString) {
        result += char;
        if (escaped) {
          escaped = false;
        } else if (char === '\\') {
          escaped = true;
        } else if (char === quote) {
          inString = false;
        }
        continue;
      }

      if (char === '"' || char === '\'') {
        inString = true;
        quote = char;
        result += char;
        continue;
      }

      if (char === '{' || char === ',') {
        result += char;
        i += 1;
        while (i < text.length && /\s/.test(text[i])) {
          result += text[i];
          i += 1;
        }

        if (i < text.length && isIdStart(text[i])) {
          const keyStart = i;
          i += 1;
          while (i < text.length && isId(text[i])) i += 1;
          const key = text.slice(keyStart, i);

          let j = i;
          while (j < text.length && /\s/.test(text[j])) j += 1;

          if (text[j] === ':') {
            result += `"${key}"`;
            result += text.slice(i, j);
            result += ':';
            i = j;
            changed = true;
            continue;
          }

          result += key;
          i -= 1;
          continue;
        }

        i -= 1;
        continue;
      }

      result += char;
    }

    if (changed) log('Quoted unquoted object keys.', 'info');
    return result;
  }

  function normalizeSingleQuotes(text, log) {
    let result = '';
    let inSingle = false;
    let inDouble = false;
    let escaped = false;
    let changed = false;

    for (let i = 0; i < text.length; i++) {
      const char = text[i];

      if (inDouble) {
        result += char;
        if (escaped) {
          escaped = false;
        } else if (char === '\\') {
          escaped = true;
        } else if (char === '"') {
          inDouble = false;
        }
        continue;
      }

      if (inSingle) {
        if (escaped) {
          result += char;
          escaped = false;
          continue;
        }
        if (char === '\\') {
          result += char;
          escaped = true;
          continue;
        }
        if (char === '\'') {
          result += '"';
          inSingle = false;
          changed = true;
          continue;
        }
        if (char === '"') {
          result += '\\"';
          changed = true;
          continue;
        }
        result += char;
        continue;
      }

      if (char === '"') {
        inDouble = true;
        result += char;
        continue;
      }

      if (char === '\'') {
        inSingle = true;
        result += '"';
        changed = true;
        continue;
      }

      result += char;
    }

    if (changed) log('Converted single-quoted strings to double quotes.', 'info');
    return result;
  }

  function truncateText(text, limit) {
    if (text.length <= limit) return text;
    const remainder = text.slice(limit);
    const whitespaceIndex = remainder.search(/\s/);
    const cutoff = whitespaceIndex === -1 ? limit : limit + whitespaceIndex;
    return `${text.slice(0, cutoff)}...`;
  }

  function stripHtmlTags(text) {
    return text.replace(/<[^>]*>/g, '');
  }

  function sanitizeText(value, path, log, context, limit = JSON_REPAIR_LIMITS.maxTextLength) {
    if (value == null) return '';
    let text = String(value);
    const originalText = text;
    const withoutHtml = stripHtmlTags(text);
    if (withoutHtml !== text) {
      const line = findLineNumber(context.sourceText, text.slice(0, 18));
      log(
        `Removed HTML tags from text (${line ? `line ${line}` : 'line unknown'}).`,
        'warning',
        { before: originalText, after: withoutHtml }
      );
      text = withoutHtml;
    }

    text = text.trim();

    if (text.length > limit) {
      const severe = text.length > limit * 2;
      const before = text;
      text = truncateText(text, limit);
      const line = findLineNumber(context.sourceText, text.slice(0, 18));
      log(
        `Truncated text to ${limit} characters (${line ? `line ${line}` : 'line unknown'}).`,
        severe ? 'warning' : 'info',
        { before, after: text }
      );
      if (severe) context.needsRegeneration = true;
    }
    return text;
  }

  function normalizeTranslationEntry(value, path, log, context) {
    if (value == null) return '';
    const raw = typeof value === 'string' ? value : String(value);
    const match = raw.match(/^\s*([A-Za-z]{2,3})\s*[:\-]\s*(.*)$/);
    if (!match) {
      return sanitizeText(raw, path, log, context);
    }
    const code = match[1].toUpperCase();
    const text = sanitizeText(match[2], path, log, context);
    return `${code}: ${text}`;
  }

  function normalizeBlankWidget(blank, path, log, context, parentItem) {
    let entries = null;
    if (Array.isArray(blank)) {
      entries = blank.slice(0);
    } else if (blank && typeof blank === 'object') {
      entries = [blank.sentence, blank.answer, blank.hint, blank.explanation];
    }

    if (!entries || entries.length < 4) {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(`Fill-blank is missing required entries (${location.label}, ${location.lineText}).`, 'warning');
      return null;
    }

    const cleaned = entries.slice(0, 4).map((entry, idx) => sanitizeText(entry, `${path}[${idx}]`, log, context));
    if (!cleaned[0].includes('___')) {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(`Fill-blank is missing the "___" placeholder (${location.label}, ${location.lineText}).`, 'warning');
      return null;
    }
    return cleaned;
  }

  function normalizeListItems(items, path, log, context, parentItem) {
    const list = Array.isArray(items) ? items : [items];
    const cleaned = list
      .map((item, idx) => sanitizeText(item, `${path}[${idx}]`, log, context))
      .filter((item) => item.trim() !== '');

    if (cleaned.length > JSON_REPAIR_LIMITS.maxListItems) {
      const severe = cleaned.length > JSON_REPAIR_LIMITS.maxListItems * 2;
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(
        `Trimmed list to ${JSON_REPAIR_LIMITS.maxListItems} items (${location.label}, ${location.lineText}).`,
        'warning',
        { before: list, after: cleaned }
      );
      cleaned.length = JSON_REPAIR_LIMITS.maxListItems;
      if (severe) context.needsRegeneration = true;
    }

    return cleaned;
  }

  function normalizeTableRows(rows, path, log, context, parentItem) {
    if (!Array.isArray(rows)) return null;
    const cleaned = rows
      .map((row, rowIdx) => {
        if (!Array.isArray(row)) return null;
        return row.map((cell, cellIdx) => {
          if (typeof cell === 'string' || typeof cell === 'number' || typeof cell === 'boolean') {
            return sanitizeText(cell, `${path}[${rowIdx}][${cellIdx}]`, log, context);
          }
          return cell;
        });
      })
      .filter(Boolean);

    if (cleaned.length > JSON_REPAIR_LIMITS.maxTableRows) {
      const severe = cleaned.length > JSON_REPAIR_LIMITS.maxTableRows * 2;
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(
        `Trimmed table to ${JSON_REPAIR_LIMITS.maxTableRows} rows (${location.label}, ${location.lineText}).`,
        'warning',
        { before: rows, after: cleaned }
      );
      cleaned.length = JSON_REPAIR_LIMITS.maxTableRows;
      if (severe) context.needsRegeneration = true;
    }

    if (cleaned.length < 2) {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(`Table has no body rows (${location.label}, ${location.lineText}).`, 'warning', { before: rows, after: null });
      return null;
    }
    return cleaned;
  }

  function normalizeQuizWidget(quiz, path, log, context, parentItem) {
    if (!quiz || typeof quiz !== 'object') {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(`Quiz data is not valid (${location.label}, ${location.lineText}).`, 'warning');
      return null;
    }

    let title = sanitizeText(quiz.title || 'Quiz', `${path}.title`, log, context);
    if (!title) {
      title = 'Quiz';
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(
        `Quiz is missing a title (${location.label}, ${location.lineText}).`,
        'warning',
        { before: quiz, after: { ...quiz, title } }
      );
    }

    let questionsSource = quiz.questions;
    if (!Array.isArray(questionsSource)) {
      const singleQuestion = quiz.q ?? quiz.question ?? quiz.prompt ?? quiz.text ?? null;
      const singleChoices = quiz.c ?? quiz.choices ?? quiz.options ?? quiz.answers ?? null;
      const singleAnswer = quiz.a ?? quiz.answer ?? quiz.correct ?? quiz.correctIndex ?? null;
      const singleExplanation = quiz.e ?? quiz.explanation ?? quiz.why ?? quiz.reason ?? null;
      if (singleQuestion || singleChoices || singleAnswer || singleExplanation) {
        questionsSource = [{
          q: singleQuestion,
          c: singleChoices,
          a: singleAnswer,
          e: singleExplanation
        }];
        const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
        log(`Mapped quiz keys (question/options/answer) into questions[] (${location.label}, ${location.lineText}).`, 'info', { before: quiz, after: { ...quiz, questions: questionsSource } });
      }
    }

    if (!Array.isArray(questionsSource)) {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(`Quiz is missing questions (${location.label}, ${location.lineText}).`, 'warning');
      return null;
    }

    const cleanedQuestions = questionsSource.map((question, idx) => {
      const qText = question?.q ?? question?.question ?? question?.prompt ?? question?.text;
      const choices = question?.c ?? question?.choices ?? question?.options ?? question?.answers;
      const answer = question?.a ?? question?.answer ?? question?.correct ?? question?.correctIndex;
      const explanation = question?.e ?? question?.explanation ?? question?.why ?? question?.reason;
      const qPath = `${path}.questions[${idx}]`;

      const keyHints = [];
      if (question?.question || question?.prompt || question?.text) keyHints.push('question');
      if (question?.options || question?.answers) keyHints.push('options');
      if (question?.answer || question?.correctIndex) keyHints.push('answer');
      if (question?.why || question?.reason) keyHints.push('explanation');
      if (keyHints.length) {
        const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
        log(`Normalized quiz question keys (${keyHints.join(', ')}) (${location.label}, ${location.lineText}).`, 'info', { before: question, after: { q: qText, c: choices, a: answer, e: explanation } });
      }

      const cleanQ = sanitizeText(qText, `${qPath}.q`, log, context);
      const cleanChoices = normalizeListItems(choices, `${qPath}.c`, log, context, parentItem);
      let cleanExplanation = sanitizeText(explanation, `${qPath}.e`, log, context);
      if (!cleanExplanation) {
        context.needsRegeneration = true;
        cleanExplanation = '';
        const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
        log(`Quiz explanation missing; left empty (${location.label}, ${location.lineText}).`, 'warning', { before: question, after: { ...question, e: cleanExplanation } });
      }

      if (!cleanQ || cleanChoices.length < 2) {
        context.needsRegeneration = true;
        const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
        log(`Dropped an invalid quiz question (${location.label}, ${location.lineText}).`, 'warning', { before: question, after: null });
        return null;
      }

      let answerIndex = Number.isInteger(answer) ? answer : 0;
      if (!Number.isInteger(answer) && typeof answer === 'string') {
        const matchIndex = cleanChoices.findIndex((choice) => choice.trim().toLowerCase() === answer.trim().toLowerCase());
        if (matchIndex >= 0) {
          answerIndex = matchIndex;
          const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
          log(`Matched quiz answer text to choice index (${location.label}, ${location.lineText}).`, 'info', { before: question, after: { ...question, a: answerIndex } });
        }
      }
      if (!Number.isInteger(answer)) {
        context.needsRegeneration = true;
        log(`Quiz answer index missing at ${qPath}, defaulted to 0.`, 'warning');
      } else if (answerIndex < 0 || answerIndex >= cleanChoices.length) {
        context.needsRegeneration = true;
        answerIndex = 0;
        log(`Quiz answer index out of range at ${qPath}, defaulted to 0.`, 'warning');
      }

      return {
        q: cleanQ,
        c: cleanChoices,
        a: answerIndex,
        e: cleanExplanation
      };
    }).filter(Boolean);

    if (cleanedQuestions.length === 0) {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(`Quiz has no valid questions (${location.label}, ${location.lineText}).`, 'warning');
      return null;
    }

    return { title, questions: cleanedQuestions };
  }

  function normalizeSwipeWidget(swipe, path, log, context, parentItem) {
    let title = '';
    let labels = null;
    let cards = null;

    if (Array.isArray(swipe)) {
      title = swipe[0];
      labels = swipe[1];
      cards = swipe[2];
    } else if (swipe && typeof swipe === 'object') {
      title = swipe.title ?? swipe.instructions ?? swipe.prompt ?? '';
      labels = swipe.labels ?? swipe.buckets ?? swipe.bucketLabels;
      cards = swipe.cards;
    }

    title = sanitizeText(title || 'Swipe Drill', `${path}[0]`, log, context);
    if (!title) {
      title = 'Swipe Drill';
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(`Swipe widget title missing (${location.label}, ${location.lineText}).`, 'warning');
    }

    let cleanedLabels = Array.isArray(labels) ? labels : [];
    cleanedLabels = cleanedLabels.slice(0, 2).map((label, idx) => sanitizeText(label, `${path}[1][${idx}]`, log, context)).filter(Boolean);
    if (cleanedLabels.length < 2) {
      context.needsRegeneration = true;
      cleanedLabels = ['Left', 'Right'];
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(`Swipe widget labels missing; defaulted to Left/Right (${location.label}, ${location.lineText}).`, 'warning');
    }

    if (!Array.isArray(cards)) {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(`Swipe widget cards missing (${location.label}, ${location.lineText}).`, 'warning');
      return null;
    }

    const cleanedCards = cards.map((card, idx) => {
      let text = '';
      let correctIndex = 0;
      let feedback = '';

      if (Array.isArray(card)) {
        text = card[0];
        correctIndex = card[1];
        feedback = card[2];
      } else if (card && typeof card === 'object') {
        text = card.text ?? card.front ?? card.prompt ?? card.card;
        correctIndex = card.correct ?? card.answer ?? card.bucket ?? card.correctIndex;
        feedback = card.feedback ?? card.explanation ?? card.reason;
      } else {
        text = card;
      }

      text = sanitizeText(text, `${path}[2][${idx}][0]`, log, context);
      feedback = sanitizeText(feedback, `${path}[2][${idx}][2]`, log, context);

      let normalizedIndex = Number.isInteger(correctIndex) ? correctIndex : 0;
      if (!Number.isInteger(correctIndex) || (normalizedIndex !== 0 && normalizedIndex !== 1)) {
        context.needsRegeneration = true;
        normalizedIndex = 0;
        const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
        log(`Swipe card correct index invalid; defaulted to 0 (${location.label}, ${location.lineText}).`, 'warning', { before: card, after: [text, normalizedIndex, feedback] });
      }

      if (!text || !feedback) {
        context.needsRegeneration = true;
        const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
        log(`Swipe card missing text/feedback (${location.label}, ${location.lineText}).`, 'warning', { before: card, after: null });
        return null;
      }

      return [text, normalizedIndex, feedback];
    }).filter(Boolean);

    if (cleanedCards.length > JSON_REPAIR_LIMITS.maxListItems) {
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(
        `Trimmed swipe cards to ${JSON_REPAIR_LIMITS.maxListItems} items (${location.label}, ${location.lineText}).`,
        'warning',
        { before: cards, after: cleanedCards }
      );
      cleanedCards.length = JSON_REPAIR_LIMITS.maxListItems;
      context.needsRegeneration = true;
    }

    if (!cleanedCards.length) {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: parentItem, sourceText: context.sourceText });
      log(`Swipe widget has no valid cards (${location.label}, ${location.lineText}).`, 'warning');
      return null;
    }

    return [title, cleanedLabels, cleanedCards];
  }

  function sanitizeUntrimmedText(value, path, log, context, limit = JSON_REPAIR_LIMITS.maxTextLength) {
    if (value == null) return '';
    let text = String(value);
    if (text.length > limit) {
      const severe = text.length > limit * 2;
      const before = text;
      text = truncateText(text, limit);
      const line = findLineNumber(context.sourceText, text.slice(0, 18));
      log(
        `Truncated text to ${limit} characters (${line ? `line ${line}` : 'line unknown'}).`,
        severe ? 'warning' : 'info',
        { before, after: text }
      );
      if (severe) context.needsRegeneration = true;
    }
    return text;
  }

  function normalizeFreeTextWidget(freeText, path, log, context) {
    if (!Array.isArray(freeText)) return null;
    const prompt = sanitizeText(freeText[0], `${path}[0]`, log, context);
    const seedLocked = sanitizeUntrimmedText(freeText[1], `${path}[1]`, log, context);
    const text = sanitizeUntrimmedText(freeText[2], `${path}[2]`, log, context);
    const lang = freeText[3] ? sanitizeText(freeText[3], `${path}[3]`, log, context) : '';
    const wordlist = freeText[4] ? sanitizeText(freeText[4], `${path}[4]`, log, context) : '';
    const mode = freeText[5] ? sanitizeText(freeText[5], `${path}[5]`, log, context) : '';
    const payload = [prompt, seedLocked, text];
    let normalizedLang = lang;
    let normalizedWordlist = wordlist;
    if (mode) {
      if (!normalizedLang) normalizedLang = 'en';
      if (normalizedWordlist === '') normalizedWordlist = '';
    }
    if (normalizedWordlist && !normalizedLang) {
      normalizedLang = 'en';
    }
    if (normalizedLang) payload.push(normalizedLang);
    if (normalizedWordlist || mode) payload.push(normalizedWordlist || '');
    if (mode) payload.push(mode);
    return payload;
  }

  function normalizeStepFlowWidget(flow, path, log, context, depth = 0) {
    if (!Array.isArray(flow)) return null;
    if (depth > 5) {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: flow, sourceText: context.sourceText });
      log(`StepFlow branching exceeds depth 5 (${location.label}, ${location.lineText}).`, 'warning');
      return flow;
    }
    return flow.map((node, idx) => {
      const nodePath = `${path}[${idx}]`;
      if (typeof node === 'string') {
        return sanitizeText(node, nodePath, log, context);
      }
      if (Array.isArray(node)) {
        const isChoiceList = Array.isArray(node[0]);
        const rawChoices = isChoiceList ? node : (Array.isArray(node[1]) ? node[1] : []);
        const cleanedChoices = rawChoices.map((choice, cIdx) => {
          const choicePath = isChoiceList ? `${nodePath}[${cIdx}]` : `${nodePath}[1][${cIdx}]`;
          if (!Array.isArray(choice)) return null;
          const label = sanitizeText(choice[0], `${choicePath}[0]`, log, context);
          const steps = normalizeStepFlowWidget(choice[1], `${choicePath}[1]`, log, context, depth + 1) || [];
          return [label, steps];
        }).filter(Boolean);
        if (isChoiceList) {
          return cleanedChoices;
        }
        const question = sanitizeText(node[0], `${nodePath}[0]`, log, context);
        return [question, cleanedChoices];
      }
      return sanitizeText(String(node), nodePath, log, context);
    });
  }

  function normalizeAsciiDiagramWidget(diagram, path, log, context) {
    if (!Array.isArray(diagram)) return null;
    const lead = sanitizeText(diagram[0], `${path}[0]`, log, context);
    const content = sanitizeUntrimmedText(diagram[1], `${path}[1]`, log, context);
    return [lead, content];
  }

  function normalizeChecklistTree(tree, path, log, context, depth = 1) {
    if (!Array.isArray(tree)) return null;
    if (depth > 3) {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: tree, sourceText: context.sourceText });
      log(`Checklist nesting exceeds depth 3 (${location.label}, ${location.lineText}).`, 'warning');
      return tree;
    }
    return tree.map((node, idx) => {
      const nodePath = `${path}[${idx}]`;
      if (typeof node === 'string') {
        return sanitizeText(node, nodePath, log, context);
      }
      if (Array.isArray(node)) {
        const title = sanitizeText(node[0], `${nodePath}[0]`, log, context);
        const children = normalizeChecklistTree(node[1], `${nodePath}[1]`, log, context, depth + 1) || [];
        return [title, children];
      }
      return sanitizeText(String(node), nodePath, log, context);
    });
  }

  function normalizeConsoleWidget(consoleWidget, path, log, context) {
    if (!Array.isArray(consoleWidget)) return null;
    const lead = sanitizeText(consoleWidget[0], `${path}[0]`, log, context);
    const mode = Number(consoleWidget[1]) === 1 ? 1 : 0;
    const rulesOrScript = Array.isArray(consoleWidget[2]) ? consoleWidget[2] : [];
    const guided = Array.isArray(consoleWidget[3]) ? consoleWidget[3] : null;
    const cleanOutput = (value, fieldPath) => sanitizeUntrimmedText(value, fieldPath, log, context);

    let cleanedRulesOrScript = [];
    if (mode === 1) {
      cleanedRulesOrScript = rulesOrScript.map((rule, idx) => {
        if (!Array.isArray(rule)) return null;
        const rulePath = `${path}[2][${idx}]`;
        const pattern = sanitizeText(rule[0], `${rulePath}[0]`, log, context);
        const level = sanitizeText(rule[1], `${rulePath}[1]`, log, context);
        const output = cleanOutput(rule[2], `${rulePath}[2]`);
        return [pattern, level, output];
      }).filter(Boolean);
    } else {
      cleanedRulesOrScript = rulesOrScript.map((entry, idx) => {
        if (!Array.isArray(entry)) return null;
        const entryPath = `${path}[2][${idx}]`;
        const command = sanitizeText(entry[0], `${entryPath}[0]`, log, context);
        const runMs = Number(entry[1]) || 0;
        const output = cleanOutput(entry[2], `${entryPath}[2]`);
        return [command, runMs, output];
      }).filter(Boolean);
    }

    let cleanedGuided = null;
    if (guided) {
      if (mode === 0) {
        log(`Console guided steps are not allowed in demo mode (${path}). Removed during repair.`, 'error');
      } else {
        cleanedGuided = guided.map((entry, idx) => {
          if (!Array.isArray(entry)) return null;
          const gPath = `${path}[3][${idx}]`;
          const task = sanitizeText(entry[0], `${gPath}[0]`, log, context);
          const solution = sanitizeText(entry[1], `${gPath}[1]`, log, context);
          return [task, solution];
        }).filter(Boolean);
      }
    }

    const payload = [lead, mode, cleanedRulesOrScript]; 
    if (cleanedGuided) payload.push(cleanedGuided);
    return payload;
  }

  async function normalizeWidgetItem(item, path, log, context) {
    const shorthandKeys = new Set([
      'p',
      'section',
      'ul',
      'ol',
      'info',
      'tip',
      'warn',
      'err',
      'success',
      'tr',
      'ex',
      'flip',
      'blank',
      'quiz',
      'swipe',
      'table',
      'compare',
      'codeviewer',
      'treeview',
      'freeText',
      'stepFlow',
      'asciiDiagram',
      'checklist',
      'console'
    ]);

    if (typeof item === 'string') {
      const text = sanitizeText(item, path, log, context);
      if (!text) return [];
      const location = formatLocation({ path, item, sourceText: context.sourceText });
      log(`Converted text into a paragraph (${location.label}, ${location.lineText}).`, 'info', { before: item, after: { p: text } });
      return [{ p: text }];
    }

    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item, sourceText: context.sourceText });
      log(`Removed unsupported widget (${location.label}, ${location.lineText}).`, 'warning', { before: item, after: null });
      return [];
    }

    if (item.toc !== undefined || item.tableOfContents !== undefined || item.type === 'toc') {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item, sourceText: context.sourceText });
      log(`Table of contents widget is no longer supported (${location.label}, ${location.lineText}). Removed during repair.`, 'warning', { before: item, after: null });
      return [];
    }

    const alias = normalizeInteractiveAliases(item, path, log, context);
    if (alias?.mapped) {
      const location = formatLocation({ path, item, sourceText: context.sourceText });
      log(`Mapped ${alias.note} (${location.label}, ${location.lineText}).`, 'info', { before: item, after: alias.mapped });
      return normalizeWidgetItem(alias.mapped, path, log, context);
    }

    const rawKeys = Object.keys(item).filter((key) => !key.startsWith('_'));
    const shorthandHits = rawKeys.filter((key) => shorthandKeys.has(key));
    if (!item.type && shorthandHits.length > 1) {
      const location = formatLocation({ path, item, sourceText: context.sourceText });
      log(`Split a multi-key widget into ${shorthandHits.length} items (${location.label}, ${location.lineText}).`, 'info', { before: item, after: shorthandHits.map((key) => ({ [key]: item[key] })) });
      const splitItems = [];
      for (const key of shorthandHits) {
        const nextItems = await normalizeWidgetItem({ [key]: item[key] }, `${path}.${key}`, log, context);
        splitItems.push(...nextItems);
      }
      return splitItems;
    }

    if (item.p !== undefined) {
      const text = sanitizeText(item.p, `${path}.p`, log, context);
      if (!text) return [];
      return [{ p: text }];
    }

    if (item.info !== undefined || item.tip !== undefined || item.warn !== undefined || item.err !== undefined || item.success !== undefined) {
      const key = item.info !== undefined ? 'info'
        : item.tip !== undefined ? 'tip'
          : item.warn !== undefined ? 'warn'
            : item.err !== undefined ? 'err'
              : 'success';
      const text = sanitizeText(item[key], `${path}.${key}`, log, context);
      if (!text) return [];
      return [{ [key]: text }];
    }

    if (item.ul !== undefined || item.ol !== undefined) {
      const key = item.ul !== undefined ? 'ul' : 'ol';
      const list = normalizeListItems(item[key], `${path}.${key}`, log, context, item);
      if (!list.length) {
        context.needsRegeneration = true;
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        const decision = await confirmRemovalIfNeeded(context, attachSectionRemovalNote({
          title: 'Remove empty list?',
          message: `This ${location.label} has no usable items. Remove it?`,
          before: item,
          after: null,
          kind: 'item'
        }, context));
        const replacement = handleUserReplacement(decision, log, location, item);
        if (replacement) return [replacement];
        log(`Removed empty list (${location.label}, ${location.lineText}).`, 'warning', { before: item, after: null });
        return [];
      }
      return [{ [key]: list }];
    }

    if (item.tr !== undefined || item.ex !== undefined) {
      const pair = item.tr ?? item.ex;
      if (!Array.isArray(pair) || pair.length < 2) {
        context.needsRegeneration = true;
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        const decision = await confirmRemovalIfNeeded(context, attachSectionRemovalNote({
          title: 'Remove translation?',
          message: `This ${location.label} is missing language pairs. Remove it?`,
          before: item,
          after: null,
          kind: 'item'
        }, context));
        const replacement = handleUserReplacement(decision, log, location, item);
        if (replacement) return [replacement];
        log(`Removed invalid translation (${location.label}, ${location.lineText}).`, 'warning', { before: item, after: null });
        return [];
      }
      const primary = normalizeTranslationEntry(pair[0], `${path}.tr[0]`, log, context);
      const secondary = normalizeTranslationEntry(pair[1], `${path}.tr[1]`, log, context);
      if (!primary || !secondary) return [];
      return [{ tr: [primary, secondary] }];
    }

    if (item.flip !== undefined) {
      const flip = Array.isArray(item.flip) ? item.flip : [item.flip];
      const front = sanitizeText(flip[0], `${path}.flip[0]`, log, context);
      const back = sanitizeText(flip[1], `${path}.flip[1]`, log, context);
      if (!front || !back) {
        context.needsRegeneration = true;
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        const decision = await confirmRemovalIfNeeded(context, attachSectionRemovalNote({
          title: 'Remove flipcard?',
          message: `This ${location.label} is missing a front or back. Remove it?`,
          before: item,
          after: null,
          kind: 'item'
        }, context));
        const replacement = handleUserReplacement(decision, log, location, item);
        if (replacement) return [replacement];
        log(`Removed invalid flipcard (${location.label}, ${location.lineText}).`, 'warning', { before: item, after: null });
        return [];
      }
      const frontHint = flip[2] ? sanitizeText(flip[2], `${path}.flip[2]`, log, context) : undefined;
      const backHint = flip[3] ? sanitizeText(flip[3], `${path}.flip[3]`, log, context) : undefined;
      const payload = [front, back];
      if (frontHint) payload.push(frontHint);
      if (backHint) payload.push(backHint);
      return [{ flip: payload }];
    }

    if (item.blank !== undefined) {
      const blank = normalizeBlankWidget(item.blank, `${path}.blank`, log, context, item);
      if (!blank) {
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        const decision = await confirmRemovalIfNeeded(context, attachSectionRemovalNote({
          title: 'Remove fill-blank?',
          message: `This ${location.label} is missing required entries. Remove it?`,
          before: item,
          after: null,
          kind: 'item'
        }, context));
        const replacement = handleUserReplacement(decision, log, location, item);
        if (replacement) return [replacement];
        log(`Removed invalid fill-blank (${location.label}, ${location.lineText}).`, 'warning', { before: item, after: null });
        return [];
      }
      return [{ blank }];
    }

    if (item.quiz !== undefined) {
      const quiz = normalizeQuizWidget(item.quiz, `${path}.quiz`, log, context, item);
      if (!quiz) {
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        const decision = await confirmRemovalIfNeeded(context, attachSectionRemovalNote({
          title: 'Remove quiz?',
          message: `This ${location.label} is missing valid questions. Remove it?`,
          before: item,
          after: null,
          kind: 'item'
        }, context));
        const replacement = handleUserReplacement(decision, log, location, item);
        if (replacement) return [replacement];
        log(`Removed invalid quiz (${location.label}, ${location.lineText}).`, 'warning', { before: item, after: null });
        return [];
      }
      return [{ quiz }];
    }

    if (item.swipe !== undefined) {
      const swipe = normalizeSwipeWidget(item.swipe, `${path}.swipe`, log, context, item);
      if (!swipe) {
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        const decision = await confirmRemovalIfNeeded(context, attachSectionRemovalNote({
          title: 'Remove swipe widget?',
          message: `This ${location.label} is missing valid cards or labels. Remove it?`,
          before: item,
          after: null,
          kind: 'item'
        }, context));
        const replacement = handleUserReplacement(decision, log, location, item);
        if (replacement) return [replacement];
        log(`Removed invalid swipe widget (${location.label}, ${location.lineText}).`, 'warning', { before: item, after: null });
        return [];
      }
      return [{ swipe }];
    }

    if (item.table !== undefined) {
      const rows = normalizeTableRows(item.table, `${path}.table`, log, context, item);
      if (!rows) {
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        const decision = await confirmRemovalIfNeeded(context, attachSectionRemovalNote({
          title: 'Remove table?',
          message: `This ${location.label} does not have enough rows. Remove it?`,
          before: item,
          after: null,
          kind: 'item'
        }, context));
        const replacement = handleUserReplacement(decision, log, location, item);
        if (replacement) return [replacement];
        log(`Removed invalid table (${location.label}, ${location.lineText}).`, 'warning', { before: item, after: null });
        return [];
      }
      return [{ table: rows }];
    }

    if (item.compare !== undefined) {
      const rows = normalizeTableRows(item.compare, `${path}.compare`, log, context, item);
      if (!rows) {
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        const decision = await confirmRemovalIfNeeded(context, attachSectionRemovalNote({
          title: 'Remove comparison?',
          message: `This ${location.label} does not have enough rows. Remove it?`,
          before: item,
          after: null,
          kind: 'item'
        }, context));
        const replacement = handleUserReplacement(decision, log, location, item);
        if (replacement) return [replacement];
        log(`Removed invalid comparison (${location.label}, ${location.lineText}).`, 'warning', { before: item, after: null });
        return [];
      }
      return [{ compare: rows }];
    }

    if (item.freeText !== undefined) {
      const freeText = normalizeFreeTextWidget(item.freeText, `${path}.freeText`, log, context);
      if (!freeText) {
        context.needsRegeneration = true;
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        log(`FreeText widget missing required fields (${location.label}, ${location.lineText}).`, 'warning');
        return [];
      }
      return [{ freeText }];
    }

    if (item.stepFlow !== undefined) {
      const lead = Array.isArray(item.stepFlow) ? sanitizeText(item.stepFlow[0], `${path}.stepFlow[0]`, log, context) : '';
      const flowSource = Array.isArray(item.stepFlow) ? item.stepFlow[1] : item.stepFlow;
      const flow = normalizeStepFlowWidget(flowSource, `${path}.stepFlow`, log, context);
      if (!flow) {
        context.needsRegeneration = true;
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        log(`StepFlow widget missing flow (${location.label}, ${location.lineText}).`, 'warning');
        return [];
      }
      return [{ stepFlow: [lead, flow] }];
    }

    if (item.asciiDiagram !== undefined) {
      const diagram = normalizeAsciiDiagramWidget(item.asciiDiagram, `${path}.asciiDiagram`, log, context);
      if (!diagram) {
        context.needsRegeneration = true;
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        log(`AsciiDiagram widget missing diagram (${location.label}, ${location.lineText}).`, 'warning');
        return [];
      }
      return [{ asciiDiagram: diagram }];
    }

    if (item.checklist !== undefined) {
      const lead = Array.isArray(item.checklist) ? sanitizeText(item.checklist[0], `${path}.checklist[0]`, log, context) : '';
      const treeSource = Array.isArray(item.checklist) ? item.checklist[1] : item.checklist;
      const tree = normalizeChecklistTree(treeSource, `${path}.checklist`, log, context);
      if (!tree) {
        context.needsRegeneration = true;
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        log(`Checklist widget missing tree (${location.label}, ${location.lineText}).`, 'warning');
        return [];
      }
      return [{ checklist: [lead, tree] }];
    }

    if (item.console !== undefined) {
      const consoleWidget = normalizeConsoleWidget(item.console, `${path}.console`, log, context);
      if (!consoleWidget) {
        context.needsRegeneration = true;
        const location = formatLocation({ path, item, sourceText: context.sourceText });
        log(`Console widget missing configuration (${location.label}, ${location.lineText}).`, 'warning');
        return [];
      }
      return [{ console: consoleWidget }];
    }

    if (item.codeviewer !== undefined || item.treeview !== undefined || item.type) {
      return [item];
    }

    context.needsRegeneration = true;
    {
      const location = formatLocation({ path, item, sourceText: context.sourceText });
      const rawKeys = item && typeof item === 'object' ? Object.keys(item).filter((key) => !key.startsWith('_')) : [];
      const keyLabel = rawKeys.length ? `keys ${rawKeys.join(', ')}` : 'unknown keys';
      const decision = await confirmRemovalIfNeeded(context, attachSectionRemovalNote({
        title: 'Remove unknown widget?',
        message: `This ${location.label} is not supported. Remove it?`,
        before: item,
        after: null,
        kind: 'item'
      }, context));
      const replacement = handleUserReplacement(decision, log, location, item);
      if (replacement) return [replacement];
      log(`Removed an unknown widget (${keyLabel}, ${location.lineText}).`, 'warning', { before: item, after: null });
    }
    return [];
  }

  async function normalizeSectionBlock(section, path, depth, log, context) {
    if (!section || typeof section !== 'object') {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: section, sourceText: context.sourceText });
      log(`Removed empty section (${location.label}, ${location.lineText}).`, 'warning', { before: section, after: null });
      return null;
    }

    let title = section.section ?? section.title ?? '';
    title = sanitizeText(title, `${path}.section`, log, context);
    title = title.replace(/^\s*\d+(\.\d+)*[\)\.\-:]*\s*/, '').trim();
    if (!title) {
      title = 'Untitled section';
      context.needsRegeneration = true;
      log(`Section title missing at ${path}; inserted placeholder.`, 'warning');
    }

    const rawItems = Array.isArray(section.items) ? section.items : [];
    if (!Array.isArray(section.items)) {
      const location = formatLocation({ path, item: section, sourceText: context.sourceText });
      log(`Section is missing items; defaulted to empty (${location.label}, ${location.lineText}).`, 'warning');
      context.needsRegeneration = true;
    }

    const sectionInfo = { title, kept: 0, remaining: rawItems.length };
    context.currentSection = sectionInfo;
    const items = [];
    for (let idx = 0; idx < rawItems.length; idx += 1) {
      sectionInfo.remaining = rawItems.length - idx;
      sectionInfo.kept = items.length;
      const itemPath = `${path}.items[${idx}]`;
      const current = rawItems[idx];

      if (isQuizQuestionLike(current) && !current.quiz) {
        const grouped = [];
        let cursor = idx;
        while (cursor < rawItems.length && isQuizQuestionLike(rawItems[cursor]) && !rawItems[cursor].quiz) {
          grouped.push(rawItems[cursor]);
          cursor += 1;
        }
        idx = cursor - 1;
        const bundled = { quiz: { title: 'Quiz', questions: grouped } };
        const location = formatLocation({ path: itemPath, item: current, sourceText: context.sourceText });
        log(`Grouped ${grouped.length} quiz questions into one quiz (${location.label}, ${location.lineText}).`, 'info', { before: grouped, after: bundled });
        const bundledItems = await normalizeWidgetItem(bundled, itemPath, log, context);
        items.push(...bundledItems);
        continue;
      }

      const nextItems = await normalizeWidgetItem(current, itemPath, log, context);
      items.push(...nextItems);
    }
    context.currentSection = null;

    if (items.length === 0) {
      context.needsRegeneration = true;
      const location = formatLocation({ path, item: section, sourceText: context.sourceText });
      log(`Section removed because it has no items (${location.label}, ${location.lineText}).`, 'warning', { before: section, after: null });
      return null;
    }

    let subsections = [];
    if (Array.isArray(section.subsections)) {
      if (depth >= JSON_REPAIR_LIMITS.maxNestingDepth) {
        context.needsRegeneration = true;
        const location = formatLocation({ path, item: section, sourceText: context.sourceText });
        log(`Truncated subsections due to depth limit (${location.label}, ${location.lineText}).`, 'warning');
      } else {
        const normalizedSubs = [];
        for (let idx = 0; idx < section.subsections.length; idx += 1) {
          const normalized = await normalizeSectionBlock(section.subsections[idx], `${path}.subsections[${idx}]`, depth + 1, log, context);
          if (normalized) normalizedSubs.push(normalized);
        }
        subsections = normalizedSubs;
      }
    } else if (section.subsections) {
      const location = formatLocation({ path, item: section, sourceText: context.sourceText });
      log(`Section had invalid subsections; removed (${location.label}, ${location.lineText}).`, 'warning');
      context.needsRegeneration = true;
    }

    const cleaned = {
      section: title,
      items
    };
    if (subsections.length) cleaned.subsections = subsections;
    if (section.id) cleaned.id = section.id;
    Object.keys(section).forEach((key) => {
      if (key.startsWith('_')) cleaned[key] = section[key];
    });
    return cleaned;
  }

  async function normalizeBlocks(blocks, log, context) {
    const normalizedBlocks = [];
    for (let idx = 0; idx < blocks.length; idx += 1) {
      const block = blocks[idx];
      const path = `blocks[${idx}]`;
      if (block == null) {
        context.needsRegeneration = true;
        const location = formatLocation({ path, item: block, sourceText: context.sourceText });
        const decision = await confirmRemovalIfNeeded(context, {
          title: 'Remove empty block?',
          message: 'This block is empty. Remove it?',
          before: block,
          after: null,
          kind: 'block'
        });
        if (decision.action === 'replace') {
          log(`User edited ${location.label} and it is now valid (${location.lineText}).`, 'info', { before: block, after: decision.value });
          normalizedBlocks.push(decision.value);
          continue;
        }
        log(`Removed empty block (${location.label}, ${location.lineText}).`, 'warning', { before: block, after: null });
        continue;
      }

      if (typeof block === 'string') {
        const section = await normalizeSectionBlock({ section: 'Untitled section', items: [block] }, path, 0, log, context);
        if (section) normalizedBlocks.push(section);
        const location = formatLocation({ path, item: block, sourceText: context.sourceText });
        log(`Wrapped text into a new section (${location.label}, ${location.lineText}).`, 'info', { before: block, after: section });
        continue;
      }

      const normalized = window.DLEWidgets?.normalize?.(block);
      if (normalized?.type === 'section' || block.section !== undefined) {
        const section = await normalizeSectionBlock(block, path, 0, log, context);
        if (section) normalizedBlocks.push(section);
        continue;
      }

      if (normalized?.type === 'quiz' || block.quiz !== undefined) {
        const quiz = normalized?.type === 'quiz' ? normalizeQuizWidget(block.quiz ?? block, `${path}.quiz`, log, context, block) : normalizeQuizWidget(block.quiz, `${path}.quiz`, log, context, block);
        if (quiz) {
          const wrapped = {
            section: 'Quiz',
            items: [{ quiz }]
          };
          normalizedBlocks.push(wrapped);
          const location = formatLocation({ path, item: block, sourceText: context.sourceText });
          log(`Wrapped quiz into a section (${location.label}, ${location.lineText}).`, 'info', { before: block, after: wrapped });
        }
        continue;
      }

      const wrappedSection = await normalizeSectionBlock({ section: 'Untitled section', items: [block] }, path, 0, log, context);
      if (wrappedSection) {
        normalizedBlocks.push(wrappedSection);
        const location = formatLocation({ path, item: block, sourceText: context.sourceText });
        log(`Wrapped widget into a section (${location.label}, ${location.lineText}).`, 'info', { before: block, after: wrappedSection });
      }
    }

    return normalizedBlocks;
  }

  async function repairLessonJson(rawText, log, options = {}) {
    const context = {
      needsRegeneration: false,
      sourceText: rawText,
      confirmRemoval: options.confirmRemoval
    };
    let cleaned = rawText || '';
    if (options.recordHistory) options.recordHistory('Original', cleaned);
    cleaned = stripCodeFences(cleaned, log);
    cleaned = stripNonJsonWrapper(cleaned, log);
    cleaned = stripJsonComments(cleaned, log);
    cleaned = stripTrailingCommas(cleaned, log);
    cleaned = quoteUnquotedKeys(cleaned, log);
    cleaned = normalizeSingleQuotes(cleaned, log);
    if (options.recordHistory) options.recordHistory('Pre-cleaned', cleaned);

    let parsed = null;
    try {
      parsed = JSON.parse(cleaned);
    } catch (error) {
      log(`JSON parse failed after repair: ${error.message}`, 'error');
      return { success: false, error: 'JSON could not be repaired. Please provide a valid lesson JSON.' };
    }

    let lesson = parsed;
    if (Array.isArray(lesson)) {
      lesson = { title: 'Untitled lesson', blocks: lesson };
      context.needsRegeneration = true;
      log('Wrapped top-level array into lesson object.', 'warning');
    }

    if (!lesson || typeof lesson !== 'object') {
      log('Lesson JSON must be an object.', 'error');
      return { success: false, error: 'JSON could not be repaired. Please provide a valid lesson JSON.' };
    }

    let title = sanitizeText(lesson.title ?? 'Untitled lesson', 'title', log, context);
    if (!title) {
      title = 'Untitled lesson';
      context.needsRegeneration = true;
      log('Lesson title missing; inserted placeholder.', 'warning');
    }

    let blocks = lesson.blocks;
    if (!blocks) {
      log('Lesson blocks missing; regeneration required.', 'error');
      return { success: false, error: 'JSON could not be repaired. Please provide a valid lesson JSON.' };
    }
    if (!Array.isArray(blocks)) {
      if (typeof blocks === 'object') {
        blocks = [blocks];
        log('Wrapped lesson blocks object into array.', 'warning');
      } else {
        log('Lesson blocks must be an array.', 'error');
        return { success: false, error: 'JSON could not be repaired. Please provide a valid lesson JSON.' };
      }
    }

    const cleanedBlocks = await normalizeBlocks(blocks, log, context);
    const repairedLesson = {
      ...lesson,
      title,
      blocks: cleanedBlocks
    };
    if (options.recordHistory) options.recordHistory('Normalized', JSON.stringify(repairedLesson, null, 2));

    const validation = validateLesson(repairedLesson);
    if (validation.errors.length) {
      log(`Validation still reports ${validation.errors.length} error(s).`, 'warning');
      context.needsRegeneration = true;
    } else {
      log('Repair completed with no schema validation errors.', 'success');
    }

    if (options.recordHistory) {
      options.recordHistory('Repaired', JSON.stringify(repairedLesson, null, 2));
    }

    return {
      success: true,
      json: JSON.stringify(repairedLesson, null, 2),
      data: repairedLesson,
      needsRegeneration: context.needsRegeneration,
      validation
    };
  }

  function validateCandidateBlock(candidate, kind) {
    if (!candidate || typeof candidate !== 'object') {
      return ['Block must be valid JSON object.'];
    }
    if (kind === 'item') {
      const lesson = {
        title: 'Temp',
        blocks: [{ section: 'Temp', items: [candidate] }]
      };
      const validation = validateLesson(lesson);
      return validation.errors.filter((error) => error.includes('items[0]'));
    }
    const lesson = { title: 'Temp', blocks: [candidate] };
    const validation = validateLesson(lesson);
    return validation.errors;
  }

  function createRepairConfirmModal() {
    const overlay = document.createElement('div');
    overlay.className = 'repair-confirm-overlay';
    overlay.innerHTML = `
      <div class="repair-confirm-panel" role="dialog" aria-modal="true" aria-label="Confirm repair change">
        <h3>Confirm repair change</h3>
        <p class="repair-confirm-message"></p>
        <h4>Before</h4>
        <textarea class="repair-confirm-editor" spellcheck="false" wrap="off" readonly></textarea>
        <div class="repair-confirm-validation"></div>
        <div class="repair-confirm-actions">
          <button class="btn btn-secondary" type="button" data-action="ai" disabled title="Will be available in future">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2v4"/><path d="M12 18v4"/><path d="M2 12h4"/><path d="M18 12h4"/><circle cx="12" cy="12" r="4"/></svg>
            <span>Fix with AI</span>
          </button>
          <button class="btn btn-secondary" type="button" data-action="edit">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 20h9"/><path d="M16.5 3.5l4 4L7 21H3v-4L16.5 3.5z"/></svg>
            <span>Edit</span>
          </button>
          <button class="btn btn-primary" type="button" data-action="confirm">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 6h18"/><path d="M8 6v14"/><path d="M16 6v14"/><path d="M5 6l1-2h12l1 2"/><path d="M10 11l4 4m0-4l-4 4"/></svg>
            <span>Remove</span>
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const messageEl = overlay.querySelector('.repair-confirm-message');
    const editor = overlay.querySelector('.repair-confirm-editor');
    const validationEl = overlay.querySelector('.repair-confirm-validation');
    const confirmBtn = overlay.querySelector('[data-action="confirm"]');
    const editBtn = overlay.querySelector('[data-action="edit"]');

    const close = () => {
      overlay.classList.remove('open');
    };

    return (payload) => new Promise((resolve) => {
      if (!getRepairConfirmSetting()) {
        resolve({ action: 'remove' });
        return;
      }
      const { title, message, before, after } = payload || {};
      overlay.querySelector('h3').textContent = title || 'Confirm repair change';
      if (messageEl) messageEl.textContent = message || 'Do you want to apply this change?';
      if (editor) {
        editor.value = formatJsonBlock(before);
        editor.readOnly = true;
      }
      if (validationEl) validationEl.textContent = '';
      if (editBtn) editBtn.querySelector('span').textContent = 'Edit';
      // TODO: integrate Gemini API for AI-assisted repair suggestions.

      overlay.classList.add('open');

      let editing = false;
      const onConfirm = () => {
        cleanup();
        resolve({ action: 'remove' });
      };
      const onEdit = () => {
        if (!editor) return;
        if (!editing) {
          editing = true;
          editor.readOnly = false;
          editBtn.querySelector('span').textContent = 'Save';
          editor.focus();
          return;
        }
        try {
          const parsed = JSON.parse(editor.value || '');
          const errors = validateCandidateBlock(parsed, payload?.kind || 'item');
          if (errors.length) {
            if (validationEl) {
              validationEl.textContent = `Still invalid: ${errors[0]}`;
            }
            return;
          }
          cleanup();
          resolve({ action: 'replace', value: parsed });
        } catch (error) {
          if (validationEl) validationEl.textContent = `Invalid JSON: ${error.message}`;
        }
      };
      const onKeydown = (event) => {
        if (event.key === 'Escape') {
          cleanup();
          resolve({ action: 'remove' });
        }
      };
      const cleanup = () => {
        confirmBtn?.removeEventListener('click', onConfirm);
        editBtn?.removeEventListener('click', onEdit);
        overlay.removeEventListener('keydown', onKeydown);
        close();
      };

      confirmBtn?.addEventListener('click', onConfirm);
      editBtn?.addEventListener('click', onEdit);
      overlay.addEventListener('keydown', onKeydown);
      overlay.tabIndex = -1;
      overlay.focus();
    });
  }

  function createAppendValidationModal() {
    const overlay = document.createElement('div');
    overlay.className = 'repair-confirm-overlay';
    overlay.innerHTML = `
      <div class="repair-confirm-panel append-confirm-panel" role="dialog" aria-modal="true" aria-label="Append validation error">
        <h3>Append validation error</h3>
        <p class="repair-confirm-message"></p>
        <textarea class="repair-confirm-editor" spellcheck="false" wrap="off" readonly></textarea>
        <div class="repair-confirm-validation"></div>
        <div class="repair-confirm-actions">
          <button class="btn btn-secondary" type="button" data-action="edit">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 20h9"/><path d="M16.5 3.5l4 4L7 21H3v-4L16.5 3.5z"/></svg>
            <span>Edit</span>
          </button>
          <button class="btn btn-secondary" type="button" data-action="clear">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 6h18"/><path d="M8 6v14"/><path d="M16 6v14"/><path d="M5 6l1-2h12l1 2"/></svg>
            <span>Clear</span>
          </button>
          <button class="btn btn-primary" type="button" data-action="cancel">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M18 6L6 18"/><path d="M6 6l12 12"/></svg>
            <span>Close</span>
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const messageEl = overlay.querySelector('.repair-confirm-message');
    const editor = overlay.querySelector('.repair-confirm-editor');
    const validationEl = overlay.querySelector('.repair-confirm-validation');
    const editBtn = overlay.querySelector('[data-action="edit"]');
    const clearBtn = overlay.querySelector('[data-action="clear"]');
    const cancelBtn = overlay.querySelector('[data-action="cancel"]');

    const close = () => {
      overlay.classList.remove('open');
    };

    return (payload) => new Promise((resolve) => {
      const { message, jsonText, errors } = payload || {};
      if (messageEl) messageEl.textContent = message || 'Choose how to proceed with the invalid append payload.';
      if (editor) editor.value = jsonText || '';
      if (validationEl) {
        if (Array.isArray(errors) && errors.length) {
          validationEl.textContent = errors[0];
        } else {
          validationEl.textContent = '';
        }
      }

      overlay.classList.add('open');

      const onEdit = () => {
        cleanup();
        resolve({ action: 'edit' });
      };
      const onClear = () => {
        cleanup();
        resolve({ action: 'clear' });
      };
      const onCancel = () => {
        cleanup();
        resolve({ action: 'cancel' });
      };
      const onKeydown = (event) => {
        if (event.key === 'Escape') {
          cleanup();
          resolve({ action: 'cancel' });
        }
      };
      const cleanup = () => {
        editBtn?.removeEventListener('click', onEdit);
        clearBtn?.removeEventListener('click', onClear);
        cancelBtn?.removeEventListener('click', onCancel);
        overlay.removeEventListener('keydown', onKeydown);
        close();
      };

      editBtn?.addEventListener('click', onEdit);
      clearBtn?.addEventListener('click', onClear);
      cancelBtn?.addEventListener('click', onCancel);
      overlay.addEventListener('keydown', onKeydown);
      overlay.tabIndex = -1;
      overlay.focus();
    });
  }

  function extractErrorPath(error) {
    const match = error.match(/at ([^\s]+)(?:\s|$)/);
    if (!match) return '';
    return match[1].replace(/[.,]$/, '');
  }

  function getByPath(root, pathString) {
    if (!pathString) return null;
    const normalized = pathString.replace(/\[(\d+)\]/g, '.$1');
    const parts = normalized.split('.').filter(Boolean).map((part) => (part.match(/^\d+$/) ? Number(part) : part));
    let target = root;
    for (const part of parts) {
      if (target == null) return null;
      target = target[part];
    }
    return target;
  }

  function cleanValidationMessage(error) {
    return error
      .replace(/at [^\s]+/g, '')
      .replace(/^Block\s+/i, '')
      .replace(/^Widget\s+/i, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function formatValidationErrors(errors, sourceText) {
    let parsed = null;
    try {
      parsed = JSON.parse(sourceText || '{}');
    } catch (_) {
      parsed = null;
    }

    const friendly = [];
    const errorPaths = [];

    errors.forEach((error) => {
      const path = extractErrorPath(error);
      const normalizedPath = path ? path.replace(/\[(\d+)\]/g, '.$1') : '';
      if (normalizedPath) errorPaths.push({ path: normalizedPath, message: error });
      if (!parsed || !path) {
        friendly.push(error);
        return;
      }
      const item = getByPath(parsed, path);
      const location = formatLocation({ path, item, sourceText });
      const cleaned = cleanValidationMessage(error).replace(/\.$/, '');
      const keys = item && typeof item === 'object' && !Array.isArray(item)
        ? Object.keys(item).filter((key) => !key.startsWith('_'))
        : [];
      const keyNote = keys.length ? ` Keys: ${keys.join(', ')}.` : '';
      friendly.push(`Issue in ${location.label} (${location.lineText}): ${cleaned}.${keyNote}`);
    });

    return { friendly, errorPaths };
  }

  function showValidationErrors(container, errors, sourceText = '') {
    if (!container) return;
    container.innerHTML = '';

    if (!errors.length) {
      const ok = renderCallout('success', 'JSON looks valid.');
      container.appendChild(ok);
      return;
    }

    const formatted = formatValidationErrors(errors, sourceText);
    const list = document.createElement('ul');
    formatted.friendly.forEach((error) => {
      const li = document.createElement('li');
      li.textContent = error;
      list.appendChild(li);
    });

    const callout = renderCallout('danger', 'Please fix the errors below:');
    callout.appendChild(list);
    container.appendChild(callout);
  }

  function showUnknownIssues(container, unknowns) {
    if (!container) return;
    container.innerHTML = '';

    if (!unknowns.length) {
      return;
    }

    const list = document.createElement('ul');
    unknowns.forEach((unknown) => {
      const li = document.createElement('li');
      li.textContent = unknown;
      list.appendChild(li);
    });

    const callout = renderCallout('warning', 'Unidentified blocks/widgets detected:');
    callout.appendChild(list);
    container.appendChild(callout);
  }

  function renderErrorState(container, title, detail) {
    if (!container) return;
    container.innerHTML = '';

    const card = document.createElement('section');
    card.className = 'card';

    const header = createElement('div', 'card-header', title || 'Lesson error');
    const body = createElement('div', 'card-body');

    const message = createElement('p', null, 'We could not load the lesson JSON.');
    const detailBox = renderCallout('danger', detail || 'Unknown error');
    const link = createElement('a', 'btn btn-primary btn-compact', 'Back to editor');
    link.href = 'index.html';

    body.appendChild(message);
    body.appendChild(detailBox);
    body.appendChild(link);

    card.appendChild(header);
    card.appendChild(body);
    container.appendChild(card);
  }

  function initEditor() {
    const errorBox = document.getElementById('json-error');
    const unknownBox = document.getElementById('json-unknown');
    const loadBtn = document.getElementById('load-sample');
    const loadBasicBtn = document.getElementById('load-basic-structure');
    const validateBtn = document.getElementById('validate-json');
    const renderBtn = document.getElementById('render-lesson');
    const repairBtn = document.getElementById('repair-json');
    const forgetBtn = document.getElementById('forget-json');
    const appendBtn = document.getElementById('append-json');
    const clearAppendBtn = document.getElementById('clear-append');
    const copyOriginalBtn = document.getElementById('copy-original-json');
    const repairLogEl = document.getElementById('repair-log');
    const repairStatusEl = document.getElementById('repair-console-status');
    const repairTimelineTrack = document.getElementById('repair-timeline-track');

    // Create main JSON editor
    window.DLEWidgets?.CodeViewer?.create('json-editor-view', {
      code: '',
      editable: true,
      textareaId: 'json-input'
    });

    // Create append JSON editor
    window.DLEWidgets?.CodeViewer?.create('append-editor-view', {
      code: '',
      editable: true,
      textareaId: 'append-input'
    });

    const input = document.getElementById('json-input');
    const appendInput = document.getElementById('append-input');
    if (!input) return;
    const repairLogger = createRepairLogger(repairLogEl, repairStatusEl);
    let originalJson = '';
    const confirmRemoval = createRepairConfirmModal();
    const confirmAppendValidation = createAppendValidationModal();
    const repairHistory = [];
    let repairHistoryIndex = -1;
    let lastRepairedJson = '';
    let stateSaveTimeout = null;
    const createBasicLessonTemplate = (title) => ({
      title: title || 'Lesson Title',
      blocks: []
    });

    const renderRepairTimeline = () => {
      if (!repairTimelineTrack) return;
      repairTimelineTrack.classList.toggle('is-empty', repairHistory.length === 0);
      repairTimelineTrack.innerHTML = '';
      if (repairHistory.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'repair-timeline-empty';
        empty.textContent = 'No history yet.';
        repairTimelineTrack.appendChild(empty);
        return;
      }
      repairHistory.forEach((entry, idx) => {
        const labelText = String(entry.label || '');
        const hasNumberPrefix = /^\s*\d+/.test(labelText);
        const stepText = hasNumberPrefix ? '' : String(idx + 1);
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'repair-timeline-btn';
        if (idx === repairHistoryIndex) btn.classList.add('active');
        btn.innerHTML = `
          ${stepText ? `<span class="repair-timeline-step">${stepText}</span>` : ''}
          <span class="repair-timeline-label">${labelText}</span>
        `;
        btn.addEventListener('click', () => {
          repairHistoryIndex = idx;
          input.value = entry.json;
          input.dispatchEvent(new Event('input'));
          try {
            const lesson = JSON.parse(entry.json);
            const validation = validateLesson(lesson);
            showValidationErrors(errorBox, validation.errors, entry.json);
            showUnknownIssues(unknownBox, validation.unknowns);
          } catch (error) {
            showValidationErrors(errorBox, [`Invalid JSON: ${error.message}`], entry.json);
            showUnknownIssues(unknownBox, []);
          }
          updateTree();
          renderRepairTimeline();
        });
        repairTimelineTrack.appendChild(btn);
      });
    };

    const recordHistory = (label, jsonText) => {
      if (typeof jsonText !== 'string') return;
      repairHistory.push({ label, json: jsonText });
      repairHistoryIndex = repairHistory.length - 1;
      renderRepairTimeline();
    };

    const saveEditorState = () => {
      clearTimeout(stateSaveTimeout);
      stateSaveTimeout = setTimeout(() => {
        try {
          const payload = {
            json: input.value || '',
            append: appendInput?.value || '',
            originalJson,
            repairHistory,
            repairHistoryIndex,
            repairLog: repairLogger.entries,
            lastRepairedJson
          };
          sessionStorage.setItem(EDITOR_STATE_KEY, JSON.stringify(payload));
        } catch (e) {
          console.warn('[EditorState] Failed to save state', e);
        }
      }, 200);
    };

    const loadEditorState = () => {
      const raw = sessionStorage.getItem(EDITOR_STATE_KEY);
      if (!raw) return false;
      try {
        const state = JSON.parse(raw);
        if (typeof state.json === 'string') input.value = state.json;
        if (appendInput && typeof state.append === 'string') appendInput.value = state.append;
        if (typeof state.originalJson === 'string') originalJson = state.originalJson;
        if (Array.isArray(state.repairHistory)) {
          repairHistory.length = 0;
          repairHistory.push(...state.repairHistory);
        }
        if (typeof state.repairHistoryIndex === 'number') repairHistoryIndex = state.repairHistoryIndex;
        if (Array.isArray(state.repairLog)) repairLogger.loadEntries(state.repairLog);
        if (typeof state.lastRepairedJson === 'string') lastRepairedJson = state.lastRepairedJson;
        return true;
      } catch (e) {
        console.warn('[EditorState] Failed to load state', e);
        return false;
      }
    };

    // Auto-update tree when JSON changes
    function updateTree() {
      try {
        const validation = window.validateJSON(input.value || '{}');
        if (validation.valid) {
          const scan = validateLesson(validation.data);
          const formatted = formatValidationErrors(scan.errors, input.value);
          window.generateTreePreview(validation.data, { errorPaths: formatted.errorPaths });
          const blockCount = validation.data.blocks ? validation.data.blocks.length : 0;
          const statsEl = document.getElementById('tree-stats');
          if (statsEl) statsEl.textContent = `${blockCount} block${blockCount !== 1 ? 's' : ''}`;
          showUnknownIssues(unknownBox, scan.unknowns);
        } else {
          showUnknownIssues(unknownBox, []);
        }
      } catch (e) {
        console.log('Tree update skipped:', e);
      }
    }

    // Update tree on input changes (debounced)
    let treeUpdateTimeout;
    const updateRepairButtonState = () => {
      if (!repairBtn) return;
      const hasJson = Boolean((input.value || '').trim());
      const changed = input.value !== lastRepairedJson;
      repairBtn.disabled = !hasJson || !changed;
    };

    input.addEventListener('input', () => {
      clearTimeout(treeUpdateTimeout);
      treeUpdateTimeout = setTimeout(updateTree, 500);
      updateRepairButtonState();
      saveEditorState();
    });

    appendInput?.addEventListener('input', () => {
      saveEditorState();
    });

    // Mode toggle (edit/view)
    const modeToggle = document.getElementById('editor-mode-toggle');
    let isViewMode = false;

    modeToggle?.addEventListener('click', () => {
      isViewMode = !isViewMode;
      input.readOnly = isViewMode;
      input.style.opacity = isViewMode ? '0.7' : '1';
      modeToggle.textContent = isViewMode ? '👁️' : '✏️';
      modeToggle.classList.toggle('view-mode', isViewMode);
      modeToggle.title = isViewMode ? 'Switch to Edit Mode' : 'Switch to View Mode';
    });

    const loadSample = () => {
      lastRepairedJson = '';
      // Read from sample-data.js
      if (window.SAMPLE_LESSON_JSON) {
        input.value = JSON.stringify(window.SAMPLE_LESSON_JSON, null, 2);
        input.dispatchEvent(new Event('input'));
        showValidationErrors(errorBox, [], input.value);
        updateTree();
        return;
      }

      // Fallback
      input.value = SAMPLE_LESSON_JSON.trim();
      input.dispatchEvent(new Event('input'));
      showValidationErrors(errorBox, [], input.value);
      updateTree();
    };

    const loadBasicStructure = () => {
      const titleInput = window.prompt('Enter a lesson title', 'Lesson Title');
      if (titleInput === null) return;
      lastRepairedJson = '';
      const template = createBasicLessonTemplate(titleInput.trim() || 'Lesson Title');
      input.value = JSON.stringify(template, null, 2);
      input.dispatchEvent(new Event('input'));
      showValidationErrors(errorBox, [], input.value);
      showUnknownIssues(unknownBox, []);
      updateTree();
    };

    const restored = loadEditorState();
    if (restored) {
      input.dispatchEvent(new Event('input'));
      renderRepairTimeline();
      if (copyOriginalBtn) copyOriginalBtn.disabled = !originalJson.trim();
      try {
        const lesson = JSON.parse(input.value || '{}');
        const validation = validateLesson(lesson);
        showValidationErrors(errorBox, validation.errors, input.value);
        showUnknownIssues(unknownBox, validation.unknowns);
      } catch (error) {
        showValidationErrors(errorBox, [`Invalid JSON: ${error.message}`], input.value);
        showUnknownIssues(unknownBox, []);
      }
      updateTree();
      updateRepairButtonState();
    } else {
      loadSample();
    }

    loadBtn?.addEventListener('click', loadSample);
    loadBasicBtn?.addEventListener('click', loadBasicStructure);

    validateBtn?.addEventListener('click', () => {
      try {
        const lesson = JSON.parse(input.value || '{}');
        const validation = validateLesson(lesson);
        showValidationErrors(errorBox, validation.errors, input.value);
        showUnknownIssues(unknownBox, validation.unknowns);
        if (validation.errors.length === 0 && validation.unknowns.length === 0) {
          window.Notifications.success('JSON is valid!');
          updateTree();
        }
      } catch (error) {
        showValidationErrors(errorBox, [`Invalid JSON: ${error.message}`], input.value);
        showUnknownIssues(unknownBox, []);
        window.Notifications.error('Invalid JSON: ' + error.message);
      }
    });

    repairBtn?.addEventListener('click', async () => {
      const raw = input.value || '';
      repairLogger.clear();
      repairLogger.log('Starting JSON repair workflow.', 'info');
      originalJson = raw;
      if (copyOriginalBtn) copyOriginalBtn.disabled = !originalJson.trim();

      repairHistory.length = 0;
      repairHistoryIndex = -1;
      renderRepairTimeline();

      const result = await repairLessonJson(raw, repairLogger.log, {
        confirmRemoval,
        recordHistory
      });
      if (!result.success) {
        showValidationErrors(errorBox, [result.error || 'Repair failed.'], input.value);
        showUnknownIssues(unknownBox, []);
        window.Notifications.error(result.error || 'Repair failed.');
        repairLogger.log('Repair failed; review errors above.', 'error');
        return;
      }

      input.value = result.json;
      input.dispatchEvent(new Event('input'));
      showValidationErrors(errorBox, result.validation.errors, input.value);
      showUnknownIssues(unknownBox, result.validation.unknowns);
      updateTree();
      lastRepairedJson = input.value;
      updateRepairButtonState();
      saveEditorState();

      if (result.needsRegeneration) {
        window.Notifications.warning('Repair completed, but regeneration is recommended.');
        repairLogger.log('Repair completed with warnings; regeneration recommended.', 'warning');
      } else {
        window.Notifications.success('Repair completed successfully.');
      }
    });

    copyOriginalBtn?.addEventListener('click', async () => {
      if (!originalJson) {
        window.Notifications.warning('No original JSON captured yet.');
        return;
      }
      try {
        await navigator.clipboard.writeText(originalJson);
        window.Notifications.success('Original JSON copied to clipboard.');
      } catch (error) {
        window.Notifications.error('Clipboard copy failed.');
        console.error('Clipboard copy failed:', error);
      }
    });

    renderBtn?.addEventListener('click', () => {
      try {
        const raw = input.value || '';
        const lesson = JSON.parse(raw);
        const validation = validateLesson(lesson);
        showValidationErrors(errorBox, validation.errors, input.value);
        showUnknownIssues(unknownBox, validation.unknowns);
        if (validation.errors.length || validation.unknowns.length) {
          window.Notifications.error('Please fix validation errors first');
          return;
        }
        sessionStorage.setItem('lesson_json', raw);
        saveEditorState();
        window.location.href = 'viewer.html';
      } catch (error) {
        showValidationErrors(errorBox, [`Invalid JSON: ${error.message}`], input.value);
        showUnknownIssues(unknownBox, []);
        window.Notifications.error('Invalid JSON: ' + error.message);
      }
    });

    forgetBtn?.addEventListener('click', () => {
      sessionStorage.removeItem('lesson_json');
      input.value = '';
      input.dispatchEvent(new Event('input'));
      showValidationErrors(errorBox, [], input.value);
      showUnknownIssues(unknownBox, []);
      document.getElementById('tree-content').innerHTML = '<div class="tree-empty">Paste JSON to see structure</div>';
      document.getElementById('tree-stats').textContent = '0 blocks';
      originalJson = '';
      if (copyOriginalBtn) copyOriginalBtn.disabled = true;
      repairLogger.clear();
      repairHistory.length = 0;
      repairHistoryIndex = -1;
      renderRepairTimeline();
      lastRepairedJson = '';
      updateRepairButtonState();
      saveEditorState();
    });

    const extractAppendBlocks = (payload) => {
      if (!payload) return [];
      if (Array.isArray(payload.blocks)) return payload.blocks;
      if (Array.isArray(payload)) return payload;
      if (typeof payload === 'object') return [payload];
      return [];
    };

    const validateAppendPayload = (raw) => {
      const parsed = window.validateJSON(raw);
      if (!parsed.valid) {
        return {
          success: false,
          errors: [`Invalid JSON: ${parsed.error}`],
          unknowns: []
        };
      }

      const blocks = extractAppendBlocks(parsed.data);
      if (!blocks.length) {
        return {
          success: false,
          errors: ['Append payload must include at least one block.'],
          unknowns: []
        };
      }

      const validation = validateLesson({
        title: 'Append Validation',
        blocks
      });

      return {
        success: validation.errors.length === 0,
        errors: validation.errors,
        unknowns: validation.unknowns,
        blocks
      };
    };

    const repairAppendPayload = async (raw) => {
      const trimmed = (raw || '').trim();
      if (!trimmed) return null;

      const wrapped = trimmed.startsWith('[')
        ? `{"title":"Append Draft","blocks":${trimmed}}`
        : `{"title":"Append Draft","blocks":[${trimmed}]}`;

      const appendLog = (message, type, details) => {
        repairLogger.log(`[Append] ${message}`, type, details);
      };

      const repaired = await repairLessonJson(wrapped, appendLog);
      if (!repaired.success) return null;

      const blocks = Array.isArray(repaired.data?.blocks) ? repaired.data.blocks : [];
      const validation = validateLesson({ title: 'Append Validation', blocks });
      const serialized = (() => {
        if (trimmed.startsWith('[')) return JSON.stringify(blocks, null, 2);
        if (blocks.length === 1) return JSON.stringify(blocks[0], null, 2);
        return JSON.stringify(blocks, null, 2);
      })();

      return {
        success: validation.errors.length === 0,
        errors: validation.errors,
        unknowns: validation.unknowns,
        json: serialized
      };
    };

    // Append JSON handler
    appendBtn?.addEventListener('click', async () => {
      let newContent = appendInput.value.trim();
      if (!newContent) {
        window.Notifications.warning('Append box is empty');
        return;
      }

      let appendValidation = validateAppendPayload(newContent);
      if (!appendValidation.success) {
        const repaired = await repairAppendPayload(newContent);
        if (repaired?.success) {
          newContent = repaired.json;
          appendInput.value = newContent;
          appendInput.dispatchEvent(new Event('input'));
          appendValidation = validateAppendPayload(newContent);
          showValidationErrors(errorBox, appendValidation.errors, newContent);
          showUnknownIssues(unknownBox, appendValidation.unknowns);
          window.Notifications.success('Append payload repaired.');
        } else {
          showValidationErrors(errorBox, appendValidation.errors, newContent);
          showUnknownIssues(unknownBox, appendValidation.unknowns);
          window.Notifications.error('Append payload failed validation.');
        }
      }

      if (!appendValidation.success) {
        const decision = await confirmAppendValidation({
          message: 'The append payload has validation errors. What do you want to do?',
          jsonText: newContent,
          errors: appendValidation.errors
        });
        if (decision.action === 'clear') {
          appendInput.value = '';
          appendInput.dispatchEvent(new Event('input'));
          return;
        }
        if (decision.action === 'edit') {
          appendInput.focus();
          return;
        }
        return;
      }

      if (appendValidation.unknowns.length) {
        showUnknownIssues(unknownBox, appendValidation.unknowns);
        window.Notifications.warning('Append payload contains unknown widgets or blocks.');
      }

      const result = window.appendJSON(input.value, newContent);
      if (result.success) {
        input.value = result.json;
        input.dispatchEvent(new Event('input'));
        showValidationErrors(errorBox, [], input.value);
        updateTree();

        // Clear append box after successful append
        appendInput.value = '';
        appendInput.dispatchEvent(new Event('input'));
      }
    });

    // Clear append box
    clearAppendBtn?.addEventListener('click', () => {
      appendInput.value = '';
      appendInput.dispatchEvent(new Event('input'));
    });

    // Initialize notifications
    if (window.Notifications) window.Notifications.init();
    CollapsibleCards.init();
  }

  window.RepairSettings = {
    getConfirm: getRepairConfirmSetting,
    setConfirm: setRepairConfirmSetting
  };

  return {
    initEditor,
    initViewer
  };

})();

const CelebrationManager = window.CelebrationManager;

const Haptics = {
  enabled: true,
  init() {
    this.isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent || '');
    document.addEventListener('click', (e) => {
      const hit = e.target?.closest?.('.btn, .edge-nav-btn, .edge-utility-btn, .quiz-option-btn, .flipcard-container, .callout, .card-action-btn, .section-timer-pill, .section-timer-close');
      if (hit) this.pulse(12, hit);
    }, { passive: true });
  },
  bumpElement(el) {
    if (!el) return;
    el.classList.remove('haptic-bump');
    // force reflow to restart animation
    void el.offsetWidth;
    el.classList.add('haptic-bump');
    setTimeout(() => el.classList.remove('haptic-bump'), 180);
  },
  pulse(duration = 16, element = null) {
    if (!this.enabled) return;
    try {
      const vibrated = this.tryVibrate(duration);
      if (!vibrated) {
        this.bumpElement(element || document.activeElement);
      }
    } catch (e) {
      console.warn('[Haptics] Vibrate failed', e);
    }
  },
  tryVibrate(duration) {
    try {
      if (navigator.vibrate) {
        navigator.vibrate(duration);
        return true;
      }
    } catch (_) { /* ignore */ }
    try {
      if (this.isIOS && window.webkit?.messageHandlers?.haptic) {
        window.webkit.messageHandlers.haptic.postMessage({ style: 'light' });
        return true;
      }
    } catch (_) { /* ignore */ }
    return false;
  }
};

// Theme management adapted from example
const ThemeManager = {
  init(buttonId) {
    const savedTheme = localStorage.getItem('dle-theme') || 'light';
    const savedColorTheme = localStorage.getItem('dle-color-theme') || 'forest';
    this.setTheme(savedTheme);
    this.setColorTheme(savedColorTheme);
    this._toggleHandler = this._toggleHandler || (() => this.toggleTheme());
    const btn = buttonId ? document.getElementById(buttonId) : null;
    if (btn) {
      this.attachButton(btn);
    }
  },

  attachButton(button) {
    if (this.button === button) {
      this.updateButton();
      return;
    }
    if (button?.dataset?.edgePanel === 'true') {
      this.button = button;
      this.updateButton();
      return;
    }
    if (this.button) {
      this.button.removeEventListener('click', this._toggleHandler);
    }
    this.button = button;
    if (this.button) {
      this.button.addEventListener('click', this._toggleHandler);
      this.updateButton();
    }
  },

  setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('dle-theme', theme);
    this.updateThemeColor();
  },

  toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    this.setTheme(newTheme);
    this.updateButton();
  },

  updateButton() {
    if (!this.button) return;
    const theme = document.documentElement.getAttribute('data-theme') || 'light';
    const longLabel = this.button.querySelector('.label-long');
    const shortLabel = this.button.querySelector('.label-short');
    const pill = this.button.querySelector('.pill');

    const emoji = theme === 'light' ? '🌙' : '☀️';
    if (longLabel) longLabel.textContent = `${emoji}`;
    if (shortLabel) shortLabel.textContent = `${emoji}`;
    if (pill) pill.textContent = theme === 'light' ? 'Light' : 'Dark';
    this.button.setAttribute('aria-pressed', (theme === 'dark').toString());
  },

  getColorTheme() {
    return document.documentElement.getAttribute('data-color-theme') || 'forest';
  },

  setColorTheme(colorTheme) {
    const validThemes = ['forest', 'vermillion', 'blue', 'gold'];
    const theme = validThemes.includes(colorTheme) ? colorTheme : 'forest';
    document.documentElement.setAttribute('data-color-theme', theme);
    localStorage.setItem('dle-color-theme', theme);
    this.updateThemeColor();
  },

  updateThemeColor() {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) return;
    const styles = getComputedStyle(document.documentElement);
    const headerBg = styles.getPropertyValue('--header-bg').trim();
    const fallback = styles.getPropertyValue('--color-primary').trim() || '#1B7A55';
    meta.setAttribute('content', headerBg || fallback);
  }
};

const TranslationSettings = {
  storageKey: 'dle-translation-language',
  extractionKey: 'dle-translation-extract',
  selected: '',
  available: [],
  extractionEnabled: true,
  boundSelects: new Set(),
  fallbackLabels: {
    AR: 'Arabic',
    BG: 'Bulgarian',
    BN: 'Bengali',
    CS: 'Czech',
    DA: 'Danish',
    DE: 'German',
    EL: 'Greek',
    EN: 'English',
    ES: 'Spanish',
    FA: 'Persian',
    FI: 'Finnish',
    FR: 'French',
    HE: 'Hebrew',
    HI: 'Hindi',
    HU: 'Hungarian',
    ID: 'Indonesian',
    IT: 'Italian',
    JA: 'Japanese',
    KO: 'Korean',
    MS: 'Malay',
    NL: 'Dutch',
    NO: 'Norwegian',
    PL: 'Polish',
    PT: 'Portuguese',
    RO: 'Romanian',
    RU: 'Russian',
    SK: 'Slovak',
    SV: 'Swedish',
    SW: 'Swahili',
    TA: 'Tamil',
    TE: 'Telugu',
    TH: 'Thai',
    TR: 'Turkish',
    UK: 'Ukrainian',
    UR: 'Urdu',
    VI: 'Vietnamese',
    ZH: 'Chinese'
  },
  init() {
    this.selected = this.normalizeCode(localStorage.getItem(this.storageKey));
    try {
      const stored = localStorage.getItem(this.extractionKey);
      if (stored !== null) {
        this.extractionEnabled = stored === 'true';
      }
    } catch (e) {
      console.warn('[Translation] Unable to load extraction setting', e);
    }
    this.applyExtractionState();
  },
  normalizeCode(code) {
    return String(code || '').trim().toUpperCase();
  },
  getLanguageLabels() {
    return window.TranslationPatterns?.languageLabels
      || window.DLEWidgets?.languageLabels
      || this.fallbackLabels;
  },
  isExtractionEnabled() {
    return this.extractionEnabled !== false;
  },
  setExtractionEnabled(enabled) {
    this.extractionEnabled = !!enabled;
    try {
      localStorage.setItem(this.extractionKey, String(this.extractionEnabled));
    } catch (e) {
      console.warn('[Translation] Unable to persist extraction setting', e);
    }
    this.applyExtractionState();
    window.EdgePanel?.updateTranslationExtractButton?.();
  },
  applyExtractionState() {
    document.documentElement.setAttribute('data-translation-extract', this.isExtractionEnabled() ? 'on' : 'off');
  },
  isSupportedLanguage(code) {
    const normalized = this.normalizeCode(code);
    return !!this.getLanguageLabels()[normalized];
  },
  getSelectedLanguage() {
    return this.selected || 'EN';
  },
  setSelectedLanguage(code, { persist = true } = {}) {
    const normalized = this.normalizeCode(code);
    if (!normalized || this.selected === normalized) return;
    this.selected = normalized;
    if (persist) {
      try {
        localStorage.setItem(this.storageKey, normalized);
      } catch (e) {
        console.warn('[Translation] Unable to persist language', e);
      }
    }
    this.updateSelects();
    window.DLEWidgets?.updateTranslationsForLanguage?.(normalized);
  },
  setAvailableLanguages(codes = []) {
    const labels = this.getLanguageLabels();
    const unique = Array.from(new Set(
      codes.map((code) => this.normalizeCode(code)).filter((code) => labels[code])
    ));
    this.available = unique;

    if (!this.available.length) {
      this.updateSelects();
      return;
    }

    const fallback = this.available.includes('EN') ? 'EN' : this.available[0];
    if (!this.selected || !this.available.includes(this.selected)) {
      this.selected = fallback;
      this.updateSelects();
      window.DLEWidgets?.updateTranslationsForLanguage?.(this.selected);
      return;
    }

    this.updateSelects();
    window.DLEWidgets?.updateTranslationsForLanguage?.(this.selected);
  },
  updateSelects() {
    this.boundSelects.forEach((selectEl) => this.renderSelect(selectEl));
    window.EdgePanel?.updateTranslationButton?.();
  },
  renderSelect(selectEl) {
    if (!selectEl) return;
    const labels = this.getLanguageLabels();
    selectEl.innerHTML = '';
    const hasLanguages = this.available.length > 0;
    const isSingle = this.available.length <= 1;

    if (!hasLanguages) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'No translations';
      selectEl.appendChild(option);
      selectEl.disabled = true;
      selectEl.value = '';
      selectEl.closest('.translation-picker-popover')?.classList.add('is-disabled');
      return;
    }

    this.available.forEach((code) => {
      const option = document.createElement('option');
      option.value = code;
      option.textContent = labels[code] ? `${labels[code]} (${code})` : code;
      selectEl.appendChild(option);
    });

    selectEl.disabled = isSingle;
    selectEl.value = this.selected || this.available[0];
    selectEl.closest('.translation-picker-popover')?.classList.toggle('is-disabled', isSingle);
  },
  refreshFromDocument() {
    const codes = new Set();
    document.querySelectorAll('.translation-wrapper').forEach((wrapper) => {
      const primary = wrapper.dataset.primaryLang || '';
      const secondary = wrapper.dataset.secondaryLang || '';
      if (this.isSupportedLanguage(primary)) codes.add(this.normalizeCode(primary));
      if (this.isSupportedLanguage(secondary)) codes.add(this.normalizeCode(secondary));
    });
    document.querySelectorAll('.translation-mini').forEach((wrapper) => {
      const primary = wrapper.dataset.primaryLang || '';
      const secondary = wrapper.dataset.secondaryLang || '';
      if (this.isSupportedLanguage(primary)) codes.add(this.normalizeCode(primary));
      if (this.isSupportedLanguage(secondary)) codes.add(this.normalizeCode(secondary));
    });
    this.setAvailableLanguages(Array.from(codes));
  },
  bindSelect(selectEl) {
    if (!selectEl) return;
    if (!this.boundSelects.has(selectEl)) {
      this.boundSelects.add(selectEl);
      selectEl.addEventListener('change', (event) => {
        const next = event.target?.value || '';
        if (next) this.setSelectedLanguage(next);
      });
    }
    this.renderSelect(selectEl);
  }
};

window.TranslationSettings = TranslationSettings;

const EdgePanel = {
  init() {
    Haptics.init();
    this.actions = {};
    this.dragThreshold = 28;
    this.overlay = document.getElementById('edge-overlay') || this.createOverlay();
    if (this.overlay) {
      this.overlay.hidden = true;
    }
    this.panel = this.buildPanel();
    this.handle = this.createHandle();
    document.body.appendChild(this.handle);
    document.body.appendChild(this.panel);
    if (!document.getElementById('lesson-content')) {
      this.panel.classList.add('edge-panel-no-progress');
    }
    this.updateProgress({ completed: 0, total: 0 });
    this.setOpen(false);
    this.registerGestureHandlers();
    this.registerKeyboardShortcuts();
    this.updatePanelLayout();
    window.addEventListener('resize', () => this.updatePanelLayout());
    if (this.tocButton && !document.getElementById('toc-sheet')) {
      this.tocButton.disabled = true;
      this.tocButton.setAttribute('aria-disabled', 'true');
      this.tocButton.title = 'Table of contents is not available on this page';
    }
    this.refreshUtilityStates();
  },

  createOverlay() {
    const overlay = document.createElement('div');
    overlay.id = 'edge-overlay';
    overlay.className = 'edge-overlay';
    overlay.setAttribute('aria-hidden', 'true');
    document.body.appendChild(overlay);
    return overlay;
  },

  createHandle() {
    const handle = document.createElement('button');
    handle.type = 'button';
    handle.className = 'edge-handle';
    handle.setAttribute('aria-label', 'Open edge navigation');
    handle.setAttribute('aria-expanded', 'false');
    handle.addEventListener('click', () => this.toggle());
    handle.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        this.toggle();
      }
    });
    return handle;
  },

  buildPanel() {
    const panel = document.createElement('aside');
    panel.className = 'edge-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Edge navigation panel');
    panel.setAttribute('aria-hidden', 'true');

    const inner = document.createElement('div');
    inner.className = 'edge-panel-inner';

    this.sectionLabel = document.createElement('div');
    this.sectionLabel.className = 'edge-section-label';
    this.sectionLabel.textContent = 'Section 0 of 0';

    this.progressLabel = document.createElement('div');
    this.progressLabel.className = 'progress-label';
    this.progressPercent = document.createElement('div');
    this.progressPercent.className = 'progress-percent';
    this.progressPercent.textContent = '0%';
    this.progressFraction = document.createElement('div');
    this.progressFraction.className = 'progress-fraction';
    this.progressFraction.textContent = '0/0';
    this.progressLabel.appendChild(this.progressPercent);
    this.progressLabel.appendChild(this.progressFraction);
    this.progressLabel.setAttribute('aria-live', 'polite');

    const progressTrack = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    progressTrack.setAttribute('width', '140');
    progressTrack.setAttribute('height', '140');
    progressTrack.setAttribute('viewBox', '0 0 140 140');
    this.progressTrack = progressTrack;

    const radius = 56;
    const circumference = 2 * Math.PI * radius;
    this.circumference = circumference;

    const baseCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    baseCircle.setAttribute('cx', '70');
    baseCircle.setAttribute('cy', '70');
    baseCircle.setAttribute('r', radius.toString());
    baseCircle.setAttribute('fill', 'none');
    baseCircle.setAttribute('stroke', 'rgba(255,255,255,0.35)');
    baseCircle.setAttribute('stroke-width', '8');
    this.baseCircle = baseCircle;

    this.progressCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    this.progressCircle.setAttribute('cx', '70');
    this.progressCircle.setAttribute('cy', '70');
    this.progressCircle.setAttribute('r', radius.toString());
    this.progressCircle.setAttribute('fill', 'none');
    this.progressCircle.setAttribute('stroke', 'var(--color-primary)');
    this.progressCircle.setAttribute('stroke-width', '8');
    this.progressCircle.setAttribute('stroke-linecap', 'round');
    this.progressCircle.setAttribute('stroke-dasharray', circumference.toString());
    this.progressCircle.setAttribute('stroke-dashoffset', circumference.toString());

    progressTrack.appendChild(baseCircle);
    progressTrack.appendChild(this.progressCircle);

    const progressShell = document.createElement('div');
    progressShell.className = 'edge-progress';
    this.progressShell = progressShell;
    progressShell.appendChild(progressTrack);
    progressShell.appendChild(this.progressLabel);

    const navStack = document.createElement('div');
    navStack.className = 'edge-nav-stack';
    navStack.appendChild(this.createNavButton('print', 'Print lesson', this.getIcon('print')));
    navStack.appendChild(this.createNavButton('search', 'Search lesson', this.getIcon('search')));
    navStack.appendChild(this.createNavButton('top', 'Jump to top', this.getIcon('top')));
    navStack.appendChild(this.createNavButton('bottom', 'Jump to bottom', this.getIcon('bottom')));

    const utilities = document.createElement('div');
    utilities.className = 'edge-utility-rail';

    this.themeButton = this.createUtilityButton('theme', 'Theme', this.getIcon('theme'));
    this.colorThemeButton = this.createColorThemeButton();
    this.translationButton = this.createTranslationButton();
    this.translationExtractButton = this.createUtilityButton('translation-extract', 'Extract translations', this.getIcon('extract'));
    this.repairConfirmButton = this.createUtilityButton('repair-confirm', 'Repair confirmations', this.getIcon('confirm'));

    utilities.appendChild(this.themeButton);
    utilities.appendChild(this.colorThemeButton);
    utilities.appendChild(this.translationButton);
    utilities.appendChild(this.translationExtractButton);
    utilities.appendChild(this.repairConfirmButton);

    this.soundButton = this.createUtilityButton('sound', 'Celebration sounds', this.getIcon('sound'));
    this.celebrationButton = this.createUtilityButton('celebration', 'Celebration effects', this.getIcon('celebration'));

    utilities.appendChild(this.soundButton);
    utilities.appendChild(this.celebrationButton);

    const topStack = document.createElement('div');
    topStack.className = 'edge-panel-top';
    topStack.appendChild(this.sectionLabel);
    topStack.appendChild(progressShell);

    inner.appendChild(topStack);
    inner.appendChild(navStack);
    inner.appendChild(utilities);

    panel.appendChild(inner);
    return panel;
  },

  createNavButton(action, label, svg) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'edge-nav-btn';
    button.setAttribute('data-action', action);
    button.innerHTML = `${svg}<span class="sr-only">${label}</span>`;
    button.title = label;
    if (action === 'toc') {
      this.tocButton = button;
    }
    button.addEventListener('click', () => {
      Haptics.pulse(14, button);
      this.handleAction(action);
    });
    return button;
  },

  createUtilityButton(action, label, svg) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'edge-utility-btn';
    button.setAttribute('data-action', action);
    button.setAttribute('aria-pressed', 'false');
    button.setAttribute('aria-label', label);
    button.dataset.edgePanel = 'true';
    button.innerHTML = `${svg}<span class="pill">Off</span>`;
    button.addEventListener('click', () => {
      Haptics.pulse(14, button);
      this.handleUtility(action);
    });
    return button;
  },

  createColorThemeButton() {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'edge-utility-btn';
    button.setAttribute('data-action', 'color-theme');
    button.setAttribute('aria-label', 'Color Theme');
    button.dataset.edgePanel = 'true';
    button.style.position = 'relative';
    button.innerHTML = `${this.getIcon('color')}<span class="pill" id="color-theme-pill">Forest</span>`;

    const picker = this.createColorPicker();
    button.appendChild(picker);

    button.addEventListener('click', (e) => {
      e.stopPropagation();
      Haptics.pulse(14, button);
      picker.classList.toggle('open');
      this.updateColorPicker();
    });

    // Close picker when clicking outside
    document.addEventListener('click', (e) => {
      if (!button.contains(e.target)) {
        picker.classList.remove('open');
      }
    });

    this.colorPicker = picker;
    return button;
  },

  createTranslationButton() {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'edge-utility-btn';
    button.setAttribute('data-action', 'translation-language');
    button.setAttribute('aria-label', 'Translated language');
    button.dataset.edgePanel = 'true';
    button.style.position = 'relative';
    button.innerHTML = `${this.getIcon('translate')}<span class="pill" id="translation-lang-pill">English</span>`;

    const picker = this.createTranslationPicker();
    button.appendChild(picker);

    button.addEventListener('click', (e) => {
      e.stopPropagation();
      Haptics.pulse(14, button);
      picker.classList.toggle('open');
      this.updateTranslationButton();
    });

    document.addEventListener('click', (e) => {
      if (!button.contains(e.target)) {
        picker.classList.remove('open');
      }
    });

    this.translationPicker = picker;
    this.translationSelect = picker.querySelector('select');
    TranslationSettings.bindSelect(this.translationSelect);
    this.updateTranslationButton();
    return button;
  },

  createTranslationPicker() {
    const picker = document.createElement('div');
    picker.className = 'translation-picker-popover';

    const header = document.createElement('div');
    header.className = 'translation-picker-header';
    header.innerHTML = `
      <div class="translation-picker-title">
        <span class="translation-picker-icon">${this.getIcon('translate')}</span>
        <span>Translated language</span>
      </div>
      <div class="translation-picker-subtitle">Choose which language shows as the translation in widgets.</div>
    `;

    const field = document.createElement('label');
    field.className = 'translation-picker-field';
    field.innerHTML = `
      <span class="translation-picker-label">Translated language</span>
    `;

    const select = document.createElement('select');
    select.className = 'translation-picker-select';
    select.setAttribute('aria-label', 'Translated language');
    field.appendChild(select);

    picker.appendChild(header);
    picker.appendChild(field);
    return picker;
  },

  createColorPicker() {
    const picker = document.createElement('div');
    picker.className = 'color-picker-popover';

    const themes = [
      { id: 'forest', name: 'Forest', light: '#1B7A55', dark: '#2FAF78' },
      { id: 'vermillion', name: 'Vermillion', light: '#C7362F', dark: '#E85D5D' },
      { id: 'blue', name: 'Blue', light: '#1E5A8A', dark: '#4A90E2' },
      { id: 'gold', name: 'Gold', light: '#B8860B', dark: '#D4AF37' }
    ];

    themes.forEach(theme => {
      const swatch = document.createElement('button');
      swatch.type = 'button';
      swatch.className = 'color-swatch';
      swatch.setAttribute('data-theme-id', theme.id);
      swatch.setAttribute('aria-label', `Select ${theme.name} theme`);
      swatch.style.setProperty('--swatch-light-color', theme.light);
      swatch.style.setProperty('--swatch-dark-color', theme.dark);

      const label = document.createElement('div');
      label.className = 'color-swatch-label';
      label.textContent = theme.name;
      swatch.appendChild(label);

      swatch.addEventListener('click', (e) => {
        e.stopPropagation();
        Haptics.pulse(16, swatch);
        ThemeManager.setColorTheme(theme.id);
        this.updateColorPicker();
        this.updateColorThemeButton();
        picker.classList.remove('open');
      });

      picker.appendChild(swatch);
    });

    return picker;
  },

  updateColorPicker() {
    if (!this.colorPicker) return;
    const currentTheme = ThemeManager.getColorTheme();
    const swatches = this.colorPicker.querySelectorAll('.color-swatch');
    swatches.forEach(swatch => {
      const themeId = swatch.getAttribute('data-theme-id');
      swatch.classList.toggle('selected', themeId === currentTheme);
    });
  },

  updateColorThemeButton() {
    if (!this.colorThemeButton) return;
    const currentTheme = ThemeManager.getColorTheme();
    const pill = this.colorThemeButton.querySelector('#color-theme-pill');
    if (pill) {
      const themeNames = {
        forest: 'Forest',
        vermillion: 'Vermillion',
        blue: 'Blue',
        gold: 'Gold'
      };
      pill.textContent = themeNames[currentTheme] || 'Forest';
    }
  },

  updateTranslationButton() {
    if (!this.translationButton) return;
    const pill = this.translationButton.querySelector('#translation-lang-pill');
    const labels = TranslationSettings.getLanguageLabels();
    const selected = TranslationSettings.getSelectedLanguage();
    const labelText = labels[selected] ? `${labels[selected]}` : selected || 'None';
    if (pill) pill.textContent = labelText;
    this.translationButton.classList.toggle('is-disabled', TranslationSettings.available.length <= 1);
  },

  updateTranslationExtractButton() {
    if (!this.translationExtractButton) return;
    const pill = this.translationExtractButton.querySelector('.pill');
    const enabled = TranslationSettings?.isExtractionEnabled?.() ?? true;
    this.translationExtractButton.setAttribute('aria-pressed', enabled.toString());
    if (pill) pill.textContent = enabled ? 'On' : 'Off';
  },

  registerGestureHandlers() {
    let startX = 0;
    let startY = 0;
    let dragging = false;
    document.addEventListener('click', (event) => {
      if (!this.isOpen) return;
      if (this.panel.contains(event.target) || this.handle.contains(event.target)) return;
      this.close();
    });

    document.addEventListener('touchstart', (e) => {
      if (e.touches.length !== 1) return;
      const touch = e.touches[0];
      startX = touch.clientX;
      startY = touch.clientY;
      const nearRightEdge = startX > window.innerWidth - 24;
      dragging = nearRightEdge || this.isOpen;
    });

    document.addEventListener('touchmove', (e) => {
      if (!dragging || e.touches.length !== 1) return;
      const touch = e.touches[0];
      const dx = touch.clientX - startX;
      const dy = touch.clientY - startY;
      if (Math.abs(dx) < Math.abs(dy)) return;

      if (!this.isOpen && -dx > this.dragThreshold) {
        this.open();
        dragging = false;
      } else if (this.isOpen && dx > this.dragThreshold) {
        this.close();
        dragging = false;
      }
    });

    document.addEventListener('touchend', () => {
      dragging = false;
    });
  },

  registerKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      if (!this.isOpen) return;
      if (e.key === 'Escape') {
        this.close();
        this.handle?.focus();
      } else if (e.key === 'Tab') {
        this.maintainFocus(e);
      }
    });
  },

  maintainFocus(event) {
    const focusable = this.getFocusable();
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      last.focus();
      event.preventDefault();
    } else if (!event.shiftKey && document.activeElement === last) {
      first.focus();
      event.preventDefault();
    }
  },

  getFocusable() {
    return Array.from(this.panel.querySelectorAll('button, [href], [tabindex]:not([tabindex="-1"])'));
  },

  bindActions(actions = {}) {
    this.actions = { ...this.actions, ...actions };
  },

  handleAction(action) {
    Haptics.pulse();
    const scroller = document.querySelector('.viewer-main');
    const sections = Array.from(document.querySelectorAll('section.card:not([data-toc-skip])'));
    const scrollToSection = (target) => {
      if (!target) return;
      if (scroller) {
        const scrollerRect = scroller.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const offset = targetRect.top - scrollerRect.top + scroller.scrollTop;
        scroller.scrollTo({ top: Math.max(0, offset - 12), behavior: 'smooth' });
      } else {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    };
    const scrollToTop = () => {
      const first = sections[0];
      if (first) {
        scrollToSection(first);
        return;
      }
      if (scroller) {
        scroller.scrollTo({ top: 0, behavior: 'smooth' });
        return;
      }
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };
    const scrollToBottom = () => {
      const last = sections[sections.length - 1];
      if (last) {
        scrollToSection(last);
        return;
      }
      if (scroller) {
        scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
        return;
      }
      window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    };
    if (action === 'top') {
      (this.actions.scrollTop || scrollToTop)();
      this.close();
      return;
    }

    if (action === 'bottom') {
      (this.actions.scrollBottom || scrollToBottom)();
      this.close();
      return;
    }

    if (action === 'print') {
      window.print();
      this.close();
      return;
    }

    if (action === 'toc') {
      if (this.actions.openToc) {
        this.actions.openToc();
      } else {
        if (window.Notifications && typeof window.Notifications.info === 'function') {
          window.Notifications.info('Table of contents is not available here.');
        }
      }
      this.close();
      return;
    }

    if (action === 'search') {
      const term = prompt('Search lesson text');
      if (term === null) return;
      const result = this.actions.search ? this.actions.search(term) : { found: false };
      if (!result?.found) {
        if (window.Notifications && typeof window.Notifications.warning === 'function') {
          window.Notifications.warning('No matching text found.');
        }
      }
      this.close();
    }
  },

  handleUtility(action) {
    if (action === 'theme') {
      ThemeManager.toggleTheme();
      Haptics.pulse();
      this.refreshUtilityStates();
      return;
    }

    if (action === 'repair-confirm') {
      const current = window.RepairSettings?.getConfirm?.() ?? true;
      window.RepairSettings?.setConfirm?.(!current);
      Haptics.pulse();
      this.updateRepairConfirmButton();
    }

    if (action === 'sound') {
      CelebrationManager.toggleSound();
      Haptics.pulse();
      this.refreshUtilityStates();
      return;
    }

    if (action === 'celebration') {
      CelebrationManager.toggleEffects();
      Haptics.pulse();
      this.refreshUtilityStates();
      return;
    }

    if (action === 'translation-extract') {
      const enabled = TranslationSettings?.isExtractionEnabled?.() ?? true;
      TranslationSettings?.setExtractionEnabled?.(!enabled);
      Haptics.pulse();
      this.updateTranslationExtractButton();
    }
  },

  refreshUtilityStates() {
    if (this.themeButton) {
      ThemeManager.button = this.themeButton;
      ThemeManager.updateButton();
    }

    if (this.themeButton) {
      const pill = this.themeButton.querySelector('.pill');
      const theme = document.documentElement.getAttribute('data-theme') || 'light';
      this.themeButton.setAttribute('aria-pressed', (theme === 'dark').toString());
      if (pill) pill.textContent = theme === 'light' ? 'Light' : 'Dark';
    }

    if (this.colorThemeButton) {
      this.updateColorThemeButton();
      this.updateColorPicker();
    }

    if (this.translationButton) {
      this.updateTranslationButton();
    }

    if (this.translationExtractButton) {
      this.updateTranslationExtractButton();
    }

    if (this.repairConfirmButton) {
      this.updateRepairConfirmButton();
    }
  },

  updateRepairConfirmButton() {
    if (!this.repairConfirmButton) return;
    const pill = this.repairConfirmButton.querySelector('.pill');
    const enabled = window.RepairSettings?.getConfirm?.() ?? true;
    this.repairConfirmButton.setAttribute('aria-pressed', enabled.toString());
    if (pill) pill.textContent = enabled ? 'Confirm' : 'Auto';

    if (this.soundButton) {
      const pill = this.soundButton.querySelector('.pill');
      const enabled = CelebrationManager?.soundEnabled !== false;
      this.soundButton.setAttribute('aria-pressed', enabled.toString());
      if (pill) pill.textContent = enabled ? 'On' : 'Muted';
    }

    if (this.celebrationButton) {
      const pill = this.celebrationButton.querySelector('.pill');
      const enabled = CelebrationManager?.effectsEnabled !== false;
      this.celebrationButton.setAttribute('aria-pressed', enabled.toString());
      if (pill) pill.textContent = enabled ? 'On' : 'Off';
    }
  },

  updateProgress({ completed = 0, total = 0 }) {
    if (this.panel?.classList.contains('edge-panel-no-progress')) {
      return;
    }
    this.progressState = { completed, total };
    const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
    if (this.progressCircle) {
      const offset = this.circumference - (pct / 100) * this.circumference;
      this.progressCircle.style.strokeDashoffset = `${offset}`;
    }
    if (this.progressPercent) {
      this.progressPercent.textContent = `${pct}%`;
    }
    if (this.progressFraction) {
      this.progressFraction.textContent = `${completed}/${total}`;
    }
  },

  updatePanelLayout() {
    const header = document.querySelector('.viewer-header');
    const height = header ? header.getBoundingClientRect().height : 0;
    document.documentElement.style.setProperty('--viewer-header-height', `${height}px`);
    if (!this.panel || !this.progressTrack) return;
    const panelRect = this.panel.getBoundingClientRect();
    const styles = getComputedStyle(this.panel);
    const padding = parseFloat(styles.paddingTop) || 0;
    const availableWidth = Math.max(0, panelRect.width - padding * 2);
    const availableHeight = Math.max(0, panelRect.height - padding * 2);
    const size = Math.max(96, Math.min(availableWidth, availableHeight * 0.36));
    const stroke = Math.max(6, Math.round(size * 0.08));
    const radius = Math.max(20, Math.round((size - stroke) / 2) - 1);
    const center = Math.round(size / 2);
    this.progressTrack.setAttribute('width', `${size}`);
    this.progressTrack.setAttribute('height', `${size}`);
    this.progressTrack.setAttribute('viewBox', `0 0 ${size} ${size}`);
    if (this.baseCircle) {
      this.baseCircle.setAttribute('cx', `${center}`);
      this.baseCircle.setAttribute('cy', `${center}`);
      this.baseCircle.setAttribute('r', `${radius}`);
      this.baseCircle.setAttribute('stroke-width', `${stroke}`);
    }
    if (this.progressCircle) {
      this.progressCircle.setAttribute('cx', `${center}`);
      this.progressCircle.setAttribute('cy', `${center}`);
      this.progressCircle.setAttribute('r', `${radius}`);
      this.progressCircle.setAttribute('stroke-width', `${stroke}`);
    }
    this.circumference = 2 * Math.PI * radius;
    if (this.progressCircle) {
      this.progressCircle.setAttribute('stroke-dasharray', `${this.circumference}`);
    }
    if (this.progressShell) {
      this.progressShell.style.setProperty('--edge-progress-size', `${size}px`);
      this.progressShell.style.setProperty('--edge-progress-font', `${Math.max(14, Math.round(size * 0.22))}px`);
      this.progressShell.style.setProperty('--edge-progress-subfont', `${Math.max(10, Math.round(size * 0.11))}px`);
    }
    if (this.progressState) {
      this.updateProgress(this.progressState);
    }
  },

  updateSectionProgress(current, total) {
    if (this.panel?.classList.contains('edge-panel-no-progress')) {
      return;
    }
    if (this.sectionLabel) {
      this.sectionLabel.textContent = `Section ${current} of ${total}`;
    }
  },

  toggle() {
    this.setOpen(!this.isOpen);
  },

  open() {
    this.setOpen(true);
  },

  close() {
    this.setOpen(false);
  },

  setOpen(open) {
    this.isOpen = open;
    this.panel.classList.toggle('open', open);
    document.body.classList.toggle('edge-panel-open', open);
    if (this.overlay) {
      this.overlay.hidden = true;
      this.overlay.setAttribute('aria-hidden', 'true');
    }
    this.panel.setAttribute('aria-hidden', (!open).toString());
    this.handle?.setAttribute('aria-expanded', open.toString());
    if (open) {
      this.previousFocus = document.activeElement;
      this.updatePanelLayout();
      const focusable = this.getFocusable();
      (focusable[0] || this.panel).focus({ preventScroll: true });
      this.refreshUtilityStates();
    } else if (this.previousFocus) {
      try {
        this.previousFocus.focus({ preventScroll: true });
      } catch (e) {
        // Ignore focus errors
      }
    }
  },

  getIcon(name) {
    const icons = {
      top: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 19V5"/><path d="M6 11l6-6 6 6"/></svg>',
      bottom: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 5v14"/><path d="M18 13l-6 6-6-6"/></svg>',
      toc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 7h12"/><path d="M6 12h8"/><path d="M6 17h10"/></svg>',
      search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="6"/><path d="M15.5 15.5 20 20"/></svg>',
      theme: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 4a7.5 7.5 0 0 0 0 16 7.5 7.5 0 0 1 0-16Z"/><path d="M14.5 6.5l1-2.5"/><path d="M18 8l2-1"/><path d="M18 16l2 1"/><path d="M14.5 17.5l1 2.5"/></svg>',
      color: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 1v6m0 6v6M1 12h6m6 0h6M4.22 4.22l4.24 4.24m7.08 7.08l4.24 4.24M4.22 19.78l4.24-4.24m7.08-7.08l4.24-4.24"/></svg>',
      translate: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h7"/><path d="M7.5 6c0 4-2.5 7-6 9"/><path d="M3 13c1.5 1 2.8 2.2 3.8 3.8"/><path d="M14 5h7"/><path d="M17.5 5c0 6-4.5 10.5-11 14"/><path d="M15 15h6"/><path d="M16.5 9c.6 1.6 1.5 3 2.7 4.2"/></svg>',
      extract: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h6"/><path d="M4 9h10"/><path d="M4 13h8"/><path d="M4 17h6"/><path d="M16 7l4 4-4 4"/><path d="M12 11h8"/></svg>',
      print: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M7 8V4h10v4"/><rect x="5" y="9" width="14" height="8" rx="2"/><path d="M7 17v3h10v-3"/></svg>',
      confirm: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l8 4v6c0 4-3.5 7.5-8 8-4.5-.5-8-4-8-8V7l8-4z"/><path d="M9 12l2 2 4-4"/></svg>',
      sound: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 9v6h4l5 4V5L9 9H5Z"/><path d="M16 9.5a3.5 3.5 0 0 1 0 5"/></svg>',
      celebration: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m3 22 6-6"/><path d="M4 16 16 4l4 4L8 20Z"/><path d="M15 9l-6 6"/><path d="M2 7V2m0 0h5M2 2l5 5"/><path d="M19 3h3v3"/></svg>'
    };
    return icons[name] || '';
  }
};

window.EdgePanel = EdgePanel;


const CollapsibleCards = {
  init() {
    const cards = document.querySelectorAll('section.card');
    cards.forEach((card) => {
      if (card.dataset.collapsible === 'false') return;
      const header = card.querySelector('.card-header');
      const body = card.querySelector('.card-body');

      if (!header || !body) return;

      header.classList.add('collapsible-header');
      body.classList.add('collapsible-body');

      header.addEventListener('click', () => {
        card.classList.toggle('collapsed');
      });
    });
  }
};

function applyTableScroll() {
  const tables = document.querySelectorAll('table');

  tables.forEach((table) => {
    const parent1 = table.parentElement;
    const parent2 = parent1?.parentElement || null;
    const parent3 = parent2?.parentElement || null;

    const ancestors = [parent1, parent2, parent3];

    const insideWidget = ancestors.some((a) => a && (a.classList.contains('widget') || a.classList.contains('table-widget-container')));
    if (insideWidget) return;

    if (parent1 && parent1.classList.contains('table-scroll')) return;

    const wrapper = document.createElement('div');
    wrapper.classList.add('table-scroll');

    parent1.insertBefore(wrapper, table);
    wrapper.appendChild(table);
  });
}

function convertTextNodeContent(text) {
  if (typeof text !== 'string') return text;

  text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');

  const urlRegex = /\bhttps?:\/\/[^\s<]+/gi;

  text = text.replace(urlRegex, (url) => {
    const safeUrl = url.replace(/"/g, '&quot;');
    return `<a class="appsec-autolink" href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeUrl}</a>`;
  });

  return text;
}

function applyStaticMarkdown(rootSelector) {
  const root = rootSelector ? document.querySelector(rootSelector) : document.body;
  if (!root) return;

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentNode;
      if (!parent) return NodeFilter.FILTER_REJECT;

      const tag = parent.nodeName.toLowerCase();
      if (['script', 'style', 'noscript'].includes(tag)) {
        return NodeFilter.FILTER_REJECT;
      }

      const value = node.nodeValue;
      if (!value || value.trim() === '') {
        return NodeFilter.FILTER_REJECT;
      }

      return NodeFilter.FILTER_ACCEPT;
    }
  });

  const nodes = [];
  let node;
  while ((node = walker.nextNode())) {
    nodes.push(node);
  }

  nodes.forEach((textNode) => {
    const original = textNode.nodeValue;
    const transformed = convertTextNodeContent(original);

    if (original === transformed) return;

    const span = document.createElement('span');
    span.innerHTML = transformed;
    textNode.replaceWith(span);
  });
}

function applyDisplayModeAttribute() {
  try {
    const isStandalone =
      (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
      (window.navigator && window.navigator.standalone === true);

    document.documentElement.setAttribute('data-display-mode', isStandalone ? 'standalone' : 'browser');
  } catch (e) {
    // Non-critical
    document.documentElement.setAttribute('data-display-mode', 'browser');
  }
}


function initPrintButton() {
  const btn = document.getElementById('print-lesson');
  if (!btn) return;

  btn.addEventListener('click', () => {
    window.print();
  });
}

function initSharedHeader() {
  const headers = document.querySelectorAll('.viewer-header[data-header]');
  if (!headers.length) return;

  const icons = {
    back: `<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6"/><path d="M9 12h10"/></svg>`
  };

  headers.forEach((header) => {
    if (header.dataset.headerInitialized === 'true') return;

    const title = header.dataset.title || 'Lesson';
    const backHref = header.dataset.backHref || 'index.html';
    const backLabel = header.dataset.backLabel || 'Back';
    const showBack = header.dataset.showBack !== 'false';
    const showToc = header.dataset.showToc !== 'false';
    const tocLabel = header.dataset.tocLabel || 'Table of Contents';

    const backButton = showBack
      ? `<button class="btn btn-primary btn-compact btn-icon-only" id="back-btn" type="button" title="${backLabel}" aria-label="${backLabel}" onclick="window.location.href='${backHref}'">${icons.back}</button>`
      : '';

    const tocButton = showToc
      ? `<button class="btn btn-primary btn-compact" id="toc-toggle" type="button" title="${tocLabel}" aria-label="${tocLabel}">☰</button>`
      : '';

    header.innerHTML = `
      <div class="viewer-header-inner">
        ${backButton}
        <div class="viewer-title" id="lesson-title"><span class="viewer-title-text">${title}</span></div>
        ${tocButton}
      </div>
      <div class="viewer-progress-rail" aria-hidden="true">
        <div class="viewer-progress-fill" id="section-progress-bar"></div>
      </div>
    `;
    header.dataset.headerInitialized = 'true';

    const titleEl = header.querySelector('.viewer-title');
    const titleText = header.querySelector('.viewer-title-text');
    if (titleEl && titleText) {
      let marqueeTimeout = null;
      const enableMarquee = (interaction = 'hover') => {
        titleEl.classList.add('is-marquee');
        requestAnimationFrame(() => {
          const distance = titleText.scrollWidth - titleEl.clientWidth;
          if (distance > 8) {
            titleEl.style.setProperty('--marquee-distance', `${distance}px`);
            const duration = Math.min(18, Math.max(8, distance / 30));
            titleEl.style.setProperty('--marquee-duration', `${duration}s`);
            if (interaction === 'touch') {
              if (marqueeTimeout) window.clearTimeout(marqueeTimeout);
              marqueeTimeout = window.setTimeout(disableMarquee, (duration * 1000) + 800);
            }
          } else {
            titleEl.classList.remove('is-marquee');
            titleEl.style.removeProperty('--marquee-distance');
            titleEl.style.removeProperty('--marquee-duration');
          }
        });
      };
      const disableMarquee = () => {
        if (marqueeTimeout) window.clearTimeout(marqueeTimeout);
        marqueeTimeout = null;
        titleEl.classList.remove('is-marquee');
        titleEl.style.removeProperty('--marquee-distance');
        titleEl.style.removeProperty('--marquee-duration');
      };
      titleEl.addEventListener('mouseenter', () => enableMarquee('hover'));
      titleEl.addEventListener('mouseleave', disableMarquee);
      titleEl.addEventListener('touchstart', () => enableMarquee('touch'), { passive: true });
      titleEl.addEventListener('touchcancel', disableMarquee);
    }
  });
}

window.DLE = {
  ...window.DLE,
  CodeDisplay: window.DLEWidgets?.CodeDisplay,
  CodeViewer: window.DLEWidgets?.CodeViewer,
  TreeView: window.DLEWidgets?.TreeView
};


function bootstrap() {
  try {
    console.log('[DLE] Bootstrapping application...');
    applyDisplayModeAttribute();
    ThemeManager.init();
    TranslationSettings.init();
    CelebrationManager.init();
    EdgePanel.init();
    initSharedHeader();
    if (window.EdgePanel && typeof window.EdgePanel.updatePanelLayout === 'function') {
      window.EdgePanel.updatePanelLayout();
    }
    const tocToggle = document.getElementById('toc-toggle');
    if (tocToggle && !document.getElementById('toc-sheet')) {
      tocToggle.disabled = true;
      tocToggle.setAttribute('aria-disabled', 'true');
      tocToggle.title = 'Table of contents is not available on this page';
    }

    // Only init what's needed for the current page
    if (document.getElementById('json-editor-view')) {
      DLE.initEditor();
    }
    if (document.getElementById('lesson-content')) {
      DLE.initViewer();
    }

    initPrintButton();
    console.log('[DLE] Bootstrap complete.');
  } catch (e) {
    const msg = `Bootstrap Failed: ${e.message}`;
    console.error('[Ironclad]', msg, e);
    if (window.Notifications && window.Notifications.error) {
      window.Notifications.error(msg);
    }
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap);
} else {
  bootstrap();
}

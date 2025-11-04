const ACTION_LABELS = {
  click: 'Click',
  right_click: 'Right Click',
  drag: 'Drag',
  type: 'Type',
  scroll: 'Scroll',
  stop: 'Stop',
  message: 'Message',
  keyCombination: 'Key Combination',
  key_combination: 'Key Combination',
};

const ACTION_CLASS = {
  click: 'action-tag--click',
  right_click: 'action-tag--click',
  drag: 'action-tag--click',
  type: 'action-tag--type',
  key_combination: 'action-tag--type',
  scroll: 'action-tag--scroll',
  stop: 'action-tag--stop',
  message: 'action-tag--message',
};

const state = {
  tasks: [],
  filtered: [],
  activeSlug: null,
  users: [],
  activeUser: null,
  searchQuery: '',
};

const taskListEl = document.getElementById('task-list');
const contentEl = document.getElementById('content');
const searchEl = document.getElementById('task-search');
const emptyStateEl = document.getElementById('empty-state');
const userSelectEl = document.getElementById('user-select');
const lightboxEl = document.getElementById('lightbox');
const lightboxImg = document.getElementById('lightbox-image');
const lightboxCaption = document.getElementById('lightbox-caption');
const lightboxClose = lightboxEl?.querySelector('.lightbox__close');
const lightboxToolbar = document.getElementById('lightbox-toolbar');
const lightboxOriginalBtn = document.getElementById('lightbox-original');
const lightboxAnnotatedBtn = document.getElementById('lightbox-annotated');

const lightboxState = {
  original: null,
  annotated: null,
  caption: '',
  alt: '',
  current: 'original',
};

function updateLightboxToolbar() {
  if (!lightboxToolbar) return;
  const hasAnnotated = Boolean(lightboxState.annotated);
  lightboxToolbar.classList.toggle('lightbox__toolbar--hidden', !hasAnnotated);
  if (lightboxOriginalBtn) {
    lightboxOriginalBtn.classList.toggle('is-active', lightboxState.current === 'original');
    lightboxOriginalBtn.disabled = !lightboxState.original;
  }
  if (lightboxAnnotatedBtn) {
    lightboxAnnotatedBtn.classList.toggle('is-active', lightboxState.current === 'annotated');
    lightboxAnnotatedBtn.disabled = !hasAnnotated;
  }
}

function setLightboxVariant(variant) {
  if (!lightboxImg) return;
  const hasAnnotated = Boolean(lightboxState.annotated);
  const targetVariant = variant === 'annotated' && hasAnnotated ? 'annotated' : 'original';
  const src = targetVariant === 'annotated' ? lightboxState.annotated : lightboxState.original;
  if (!src) return;

  lightboxImg.src = src;
  const suffix = targetVariant === 'annotated' ? ' (annotated)' : ' (original)';
  lightboxImg.alt = `${lightboxState.alt || 'Attachment preview'}${hasAnnotated ? suffix : ''}`;
  if (lightboxCaption) {
    const captionSuffix = hasAnnotated && targetVariant === 'annotated' ? ' (Annotated)' : '';
    lightboxCaption.textContent = `${lightboxState.caption || ''}${captionSuffix}`;
  }

  lightboxState.current = targetVariant;
  updateLightboxToolbar();
}

function openLightboxForAttachment(attachment, preferredVariant, alt, caption) {
  if (!lightboxEl || !lightboxImg) return;
  lightboxState.original = attachment?.assetPath || null;
  lightboxState.annotated = attachment?.annotatedAssetPath || null;
  lightboxState.caption = caption || attachment?.originalPath || '';
  lightboxState.alt = alt || `Attachment ${attachment?.index ?? ''}`;

  const defaultVariant = preferredVariant || (lightboxState.annotated ? 'annotated' : 'original');
  setLightboxVariant(defaultVariant);

  lightboxEl.classList.remove('hidden');
  document.body.classList.add('lightbox-open');
  lightboxClose?.focus({ preventScroll: true });
}

function closeLightbox() {
  if (!lightboxEl || !lightboxImg) return;
  lightboxEl.classList.add('hidden');
  lightboxImg.src = '';
  document.body.classList.remove('lightbox-open');
  lightboxState.original = null;
  lightboxState.annotated = null;
  lightboxState.current = 'original';
  updateLightboxToolbar();
}

lightboxOriginalBtn?.addEventListener('click', () => setLightboxVariant('original'));
lightboxAnnotatedBtn?.addEventListener('click', () => setLightboxVariant('annotated'));

if (lightboxClose) {
  lightboxClose.addEventListener('click', closeLightbox);
}

if (lightboxEl) {
  lightboxEl.addEventListener('click', (event) => {
    if (event.target === lightboxEl) {
      closeLightbox();
    }
  });
}

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !lightboxEl?.classList.contains('hidden')) {
    closeLightbox();
  }
});

updateLightboxToolbar();

function collectUsers(tasks) {
  const users = new Set();
  tasks.forEach((task) => {
    const identifier = task.user || 'Unknown';
    users.add(identifier);
  });
  return Array.from(users).sort((a, b) => a.localeCompare(b));
}

function filterTasks() {
  const query = state.searchQuery.trim().toLowerCase();
  state.filtered = state.tasks.filter((task) => {
    const taskUser = task.user || 'Unknown';
    if (state.activeUser && taskUser !== state.activeUser) {
      return false;
    }
    if (!query) return true;
    return task.name.toLowerCase().includes(query) || task.slug.toLowerCase().includes(query);
  });
}

function renderUserSelect() {
  if (!userSelectEl) return;
  userSelectEl.innerHTML = '';

  const defaultOption = document.createElement('option');
  defaultOption.value = '';
  defaultOption.textContent = 'All users';
  userSelectEl.appendChild(defaultOption);

  state.users.forEach((user) => {
    const option = document.createElement('option');
    option.value = user;
    option.textContent = user;
    userSelectEl.appendChild(option);
  });

  userSelectEl.disabled = state.users.length === 0;
  userSelectEl.value = state.activeUser || '';
}

function ensureActiveSelection() {
  if (!state.filtered.length) {
    state.activeSlug = null;
    if (emptyStateEl) {
      const reason = state.activeUser
        ? `No trajectories found for ${escapeHtml(state.activeUser)}.`
        : 'No trajectories match the current filters.';
      emptyStateEl.style.display = 'flex';
      emptyStateEl.innerHTML = `<div class="empty-state__card"><h2>No tasks available</h2><p>${reason}</p></div>`;
    }
    if (contentEl && emptyStateEl) {
      contentEl.innerHTML = '';
      contentEl.appendChild(emptyStateEl);
    } else if (contentEl) {
      contentEl.innerHTML = '';
    }
    return;
  }

  if (!state.activeSlug || !state.filtered.some((task) => task.slug === state.activeSlug)) {
    setActiveTask(state.filtered[0], { refreshList: false });
  } else {
    const current = state.filtered.find((task) => task.slug === state.activeSlug);
    if (current) {
      renderTask(current);
    }
  }
}

function el(tag, className, textContent) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (textContent !== undefined) node.textContent = textContent;
  return node;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    switch (char) {
      case '&':
        return '&amp;';
      case '<':
        return '&lt;';
      case '>':
        return '&gt;';
      case '"':
        return '&quot;';
      case "'":
        return '&#039;';
      default:
        return char;
    }
  });
}

function formatMultiline(value) {
  return escapeHtml(value).replace(/\n/g, '<br />');
}

function formatPercent(number, digits = 1) {
  if (Number.isNaN(number)) return '—';
  return `${number.toFixed(digits)}%`;
}

function formatActionDescription(action) {
  switch (action.type) {
    case 'click':
    case 'right_click': {
      const { coordinates } = action;
      const coords =
        coordinates && typeof coordinates.xPercent === 'number'
          ? `${formatPercent(coordinates.xPercent)}, ${formatPercent(coordinates.yPercent)}`
          : action.raw;
      return `Normalized coordinates: ${coords}`;
    }
    case 'drag': {
      const { startCoordinates, endCoordinates, distance, duration } = action;
      if (startCoordinates && endCoordinates) {
        const start = `${formatPercent(startCoordinates.xPercent)}, ${formatPercent(startCoordinates.yPercent)}`;
        const end = `${formatPercent(endCoordinates.xPercent)}, ${formatPercent(endCoordinates.yPercent)}`;
        const extras = [];
        if (typeof distance === 'number') {
          extras.push(`distance ${distance}`);
        }
        if (typeof duration === 'number') {
          extras.push(`duration ${duration.toFixed(2)}s`);
        }
        const extraText = extras.length ? ` (${extras.join(' · ')})` : '';
        return `Normalized drag: ${start} → ${end}${extraText}`;
      }
      return action.raw;
    }
    case 'type':
      return action.text ? `Typed sequence: ${action.text}` : action.raw;
    case 'key_combination': {
      const translation = action.translation;
      const combo = action.combination || action.key;
      if (translation && combo && translation !== combo) {
        return `Key combination: ${translation} (${combo})`;
      }
      if (translation) {
        return `Key combination: ${translation}`;
      }
      if (combo) {
        return `Key combination: ${combo}`;
      }
      return action.raw || 'Key combination';
    }
    case 'scroll':
      return `Scroll parameters: ${action.parameters || action.raw}`;
    case 'stop':
      return 'Agent signalled completion.';
    default:
      return action.raw;
  }
}

function renderActionTag(action) {
  const tag = el('span', 'action-tag');
  tag.classList.add(ACTION_CLASS[action.type] || ACTION_CLASS.message);
  tag.textContent = ACTION_LABELS[action.type] || 'Action';
  return tag;
}

function renderAttachments(step) {
  const wrapper = document.createElement('figure');
  wrapper.className = 'step-card__preview';

  const attachments = step.user?.attachments || [];
  if (!attachments.length) {
    const placeholder = el('p');
    placeholder.textContent = 'No screenshot available for this step.';
    wrapper.appendChild(placeholder);
    return wrapper;
  }

  const primary = attachments[0];
  const img = document.createElement('img');
  const defaultVariant = primary.annotatedAssetPath ? 'annotated' : 'original';
  img.alt = `Screenshot for step ${step.step + 1}`;
  img.loading = 'lazy';
  img.dataset.caption = primary.originalPath || `Attachment ${primary.index}`;
  img.addEventListener('click', () => {
    openLightboxForAttachment(primary, img.dataset.variant, img.alt, primary.originalPath);
  });
  wrapper.appendChild(img);

  const caption = el('figcaption');
  wrapper.appendChild(caption);
  setPreviewVariant(img, primary, defaultVariant, caption);

  const controls = createPreviewToggle(primary, img, caption);
  if (controls) {
    wrapper.appendChild(controls);
  }

  if (attachments.length > 1) {
    const thumbStrip = el('div', 'step-thumbnails');
    attachments.slice(1).forEach((attachment) => {
      const thumb = document.createElement('img');
      const thumbVariant = attachment.annotatedAssetPath ? 'annotated' : 'original';
      const applied = setPreviewVariant(thumb, attachment, thumbVariant);
      thumb.dataset.variant = applied;
      thumb.alt = `Attachment ${attachment.index}`;
      thumb.loading = 'lazy';
      thumb.addEventListener('click', () => {
        openLightboxForAttachment(attachment, thumb.dataset.variant, thumb.alt, attachment.originalPath);
      });
      thumbStrip.appendChild(thumb);
    });
    wrapper.appendChild(thumbStrip);
  }

  return wrapper;
}

function setPreviewVariant(imgEl, attachment, variant, captionEl) {
  if (!imgEl || !attachment) return 'original';
  const hasAnnotated = Boolean(attachment.annotatedAssetPath);
  const targetVariant = variant === 'annotated' && hasAnnotated ? 'annotated' : 'original';
  const src = targetVariant === 'annotated' ? attachment.annotatedAssetPath : attachment.assetPath;
  if (src) {
    imgEl.src = src;
    imgEl.dataset.variant = targetVariant;
  }
  if (captionEl) {
    const baseLabel = `Attachment ${attachment.index}`;
    captionEl.textContent = targetVariant === 'annotated' ? `${baseLabel} · Annotated` : baseLabel;
  }
  return targetVariant;
}

function createPreviewToggle(attachment, imgEl, captionEl) {
  if (!attachment.annotatedAssetPath) return null;
  const container = el('div', 'preview-toggle');

  const originalBtn = document.createElement('button');
  originalBtn.type = 'button';
  originalBtn.className = 'preview-toggle__btn';
  originalBtn.textContent = 'Original';

  const annotatedBtn = document.createElement('button');
  annotatedBtn.type = 'button';
  annotatedBtn.className = 'preview-toggle__btn';
  annotatedBtn.textContent = 'Annotated';

  const updateButtons = (activeVariant) => {
    const current = activeVariant || imgEl.dataset.variant || 'original';
    originalBtn.classList.toggle('is-active', current === 'original');
    annotatedBtn.classList.toggle('is-active', current === 'annotated');
  };

  originalBtn.addEventListener('click', () => {
    const applied = setPreviewVariant(imgEl, attachment, 'original', captionEl);
    updateButtons(applied);
  });

  annotatedBtn.addEventListener('click', () => {
    const applied = setPreviewVariant(imgEl, attachment, 'annotated', captionEl);
    updateButtons(applied);
  });

  updateButtons(imgEl.dataset.variant);
  container.append(originalBtn, annotatedBtn);
  return container;
}

function renderInfoBlock(label, value) {
  const block = el('div', 'info-block');
  const heading = el('strong', undefined, label);
  const body = el('p');
  body.innerHTML = value;
  block.append(heading, body);
  return block;
}

function renderStep(step) {
  const card = el('article', 'step-card');

  card.appendChild(renderAttachments(step));

  const details = el('div', 'step-card__details');

  const header = el('div', 'step-card__header');
  header.appendChild(el('span', 'step-number', `Step ${step.step + 1}`));
  header.appendChild(renderActionTag(step.assistant));
  details.appendChild(header);

  const actionInfo = renderInfoBlock('Agent Action', escapeHtml(formatActionDescription(step.assistant)));
  details.appendChild(actionInfo);

  if (step.assistant.raw) {
    const rawAction = renderInfoBlock('Raw Command', `<code>${escapeHtml(step.assistant.raw)}</code>`);
    details.appendChild(rawAction);
  }

  if (step.user?.text) {
    const observation = renderInfoBlock('Observation', formatMultiline(step.user.text));
    details.appendChild(observation);
  }

  if (step.user?.attachments?.length) {
    details.appendChild(renderAttachmentList(step.user.attachments));
  }

  card.appendChild(details);
  return card;
}

function renderAttachmentList(attachments) {
  const block = el('div', 'info-block');
  block.appendChild(el('strong', undefined, 'Source Assets'));

  const list = el('div', 'attachment-list');
  attachments.forEach((attachment) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'attachment-link';
    const label = attachment.originalPath || attachment.assetPath;
    const labelSpan = document.createElement('span');
    labelSpan.className = 'attachment-link__label';
    labelSpan.textContent = label;
    button.appendChild(labelSpan);

    if (attachment.annotatedAssetPath) {
      const badge = el('span', 'attachment-link__badge', 'Annotated');
      button.appendChild(badge);
    }

    button.addEventListener('click', () => {
      const preferred = attachment.annotatedAssetPath ? 'annotated' : 'original';
      openLightboxForAttachment(attachment, preferred, `Attachment ${attachment.index}`, label);
    });
    list.appendChild(button);
  });

  block.appendChild(list);
  return block;
}

function renderStats(stats) {
  const card = el('section', 'stats-card');

  const stepBlock = el('div', 'stat-block');
  stepBlock.appendChild(el('span', undefined, 'Total Steps'));
  stepBlock.appendChild(el('strong', undefined, stats.totalSteps.toString()));
  card.appendChild(stepBlock);

  const breakdownBlock = el('div', 'stat-block');
  breakdownBlock.appendChild(el('span', undefined, 'Action Breakdown'));
  const breakdown = el('div', 'breakdown');

  const entries = Object.entries(stats.actionBreakdown);
  if (entries.length) {
    entries
      .sort(([, aCount], [, bCount]) => bCount - aCount)
      .forEach(([type, count]) => {
        const pill = el('span', 'pill');
        const label = ACTION_LABELS[type] || type;
        pill.innerHTML = `<strong>${count}</strong> ${label}`;
        breakdown.appendChild(pill);
      });
  } else {
    breakdown.textContent = 'No actions recorded.';
  }

  breakdownBlock.appendChild(breakdown);
  card.appendChild(breakdownBlock);

  return card;
}

function renderTimeline(timeline) {
  const section = el('section', 'timeline');
  const header = el('div', 'timeline__header');
  const title = el('h3', undefined, 'Raw Message Timeline');
  const toggle = el('button', 'toggle', 'Collapse');

  const entriesEl = el('div', 'timeline__entries');
  timeline.forEach((entry, idx) => {
    const row = el('div', 'timeline-entry');
    row.appendChild(el('span', 'timeline-entry__role', `${idx + 1}. ${entry.role}`));
    row.appendChild(el('div', 'timeline-entry__content', entry.content));
    entriesEl.appendChild(row);
  });

  let collapsed = false;
  toggle.addEventListener('click', () => {
    collapsed = !collapsed;
    entriesEl.style.display = collapsed ? 'none' : 'flex';
    toggle.textContent = collapsed ? 'Expand' : 'Collapse';
  });

  header.append(title, toggle);
  section.append(header, entriesEl);
  return section;
}

function renderTask(task) {
  emptyStateEl.style.display = 'none';
  contentEl.innerHTML = '';

  const header = el('section', 'task-header');
  header.appendChild(el('h2', undefined, task.name));

  const meta = el('div', 'task-header__meta');
  if (task.systemPrompt) {
    meta.appendChild(renderInfoBlock('System Prompt', formatMultiline(task.systemPrompt)));
  }
  meta.appendChild(renderInfoBlock('Data Folder', `<code>${escapeHtml(task.sourceDir)}</code>`));
  header.appendChild(meta);

  contentEl.appendChild(header);
  contentEl.appendChild(renderStats(task.stats));

  const stepsContainer = el('section', 'steps');
  task.steps.forEach((step) => stepsContainer.appendChild(renderStep(step)));
  contentEl.appendChild(stepsContainer);

  contentEl.appendChild(renderTimeline(task.timeline));

  contentEl.focus({ preventScroll: false });
}

function renderTaskList() {
  taskListEl.innerHTML = '';

  if (!state.filtered.length) {
    const emptyItem = el('li');
    const message =
      state.activeUser && state.activeUser !== 'Unknown'
        ? `No tasks for ${state.activeUser}.`
        : 'No tasks found.';
    const msg = el('div', 'task-item task-item--empty', message);
    emptyItem.appendChild(msg);
    taskListEl.appendChild(emptyItem);
    return;
  }

  state.filtered.forEach((task) => {
    const item = el('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'task-item';
    button.dataset.slug = task.slug;
    button.appendChild(el('span', 'task-item__name', task.name));
    const metaParts = [
      `${task.stats.totalSteps} steps`,
      `${Object.keys(task.stats.actionBreakdown).length} action types`,
    ];
    if (state.activeUser === null) {
      metaParts.push(task.user || 'Unknown');
    }
    button.appendChild(el('span', 'task-item__meta', metaParts.join(' · ')));

    if (state.activeSlug === task.slug) {
      button.classList.add('task-item--active');
    }

    button.addEventListener('click', () => setActiveTask(task));

    item.appendChild(button);
    taskListEl.appendChild(item);
  });
}

function applySearch(query) {
  state.searchQuery = query || '';
  filterTasks();
  ensureActiveSelection();
}

function setActiveTask(task, options = {}) {
  const { refreshList = true } = options;
  state.activeSlug = task.slug;
  renderTask(task);
  if (refreshList) {
    renderTaskList();
  }
}

async function bootstrap() {
  const response = await fetch('data/trajectories.json');
  if (!response.ok) {
    throw new Error(`Failed to load trajectories.json (${response.status})`);
  }

  const payload = await response.json();
  state.tasks = payload.tasks || [];
  state.users = collectUsers(state.tasks);
  state.activeUser = null;
  state.searchQuery = '';

  filterTasks();
  ensureActiveSelection();
  renderUserSelect();
  renderTaskList();
}

userSelectEl?.addEventListener('change', (event) => {
  const value = event.target.value;
  state.activeUser = value ? value : null;
  filterTasks();
  ensureActiveSelection();
  renderTaskList();
});

searchEl.addEventListener('input', (event) => {
  applySearch(event.target.value);
  renderTaskList();
});

bootstrap().catch((err) => {
  emptyStateEl.style.display = 'flex';
  emptyStateEl.innerHTML = `<div class="empty-state__card"><h2>Unable to load data</h2><p>${err.message}</p></div>`;
  console.error(err);
});

const ACTION_LABELS = {
  click: 'Click',
  right_click: 'Right Click',
  drag: 'Drag',
  type: 'Type',
  scroll: 'Scroll',
  stop: 'Stop',
  message: 'Message',
};

const ACTION_CLASS = {
  click: 'action-tag--click',
  right_click: 'action-tag--click',
  drag: 'action-tag--click',
  type: 'action-tag--type',
  scroll: 'action-tag--scroll',
  stop: 'action-tag--stop',
  message: 'action-tag--message',
};

const state = {
  tasks: [],
  filtered: [],
  activeSlug: null,
};

const taskListEl = document.getElementById('task-list');
const contentEl = document.getElementById('content');
const searchEl = document.getElementById('task-search');
const emptyStateEl = document.getElementById('empty-state');

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
    case 'right_click':
    case 'drag': {
      const { coordinates } = action;
      const coords =
        coordinates && typeof coordinates.xPercent === 'number'
          ? `${formatPercent(coordinates.xPercent)}, ${formatPercent(coordinates.yPercent)}`
          : action.raw;
      return `Normalized coordinates: ${coords}`;
    }
    case 'type':
      return action.text ? `Typed sequence: ${action.text}` : action.raw;
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
  img.src = primary.assetPath;
  img.alt = `Screenshot for step ${step.step + 1}`;
  img.loading = 'lazy';
  wrapper.appendChild(img);

  const caption = el('figcaption');
  caption.textContent = `Attachment ${primary.index}`;
  wrapper.appendChild(caption);

  if (attachments.length > 1) {
    const thumbStrip = el('div', 'step-thumbnails');
    attachments.slice(1).forEach((attachment) => {
      const thumb = document.createElement('img');
      thumb.src = attachment.assetPath;
      thumb.alt = `Attachment ${attachment.index}`;
      thumb.loading = 'lazy';
      thumbStrip.appendChild(thumb);
    });
    wrapper.appendChild(thumbStrip);
  }

  return wrapper;
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
    const attachmentList = step.user.attachments
      .map((att) => `<code>${escapeHtml(att.originalPath)}</code>`)
      .join('<br />');
    details.appendChild(renderInfoBlock('Source Asset', attachmentList));
  }

  card.appendChild(details);
  return card;
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
    const msg = el('div', 'task-item task-item--empty', 'No tasks found.');
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
    button.appendChild(
      el('span', 'task-item__meta', `${task.stats.totalSteps} steps · ${Object.keys(task.stats.actionBreakdown).length} action types`),
    );

    if (state.activeSlug === task.slug) {
      button.classList.add('task-item--active');
    }

    button.addEventListener('click', () => setActiveTask(task));

    item.appendChild(button);
    taskListEl.appendChild(item);
  });
}

function applySearch(query) {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) {
    state.filtered = state.tasks;
    return;
  }

  state.filtered = state.tasks.filter((task) => task.name.toLowerCase().includes(trimmed) || task.slug.includes(trimmed));
}

function setActiveTask(task) {
  state.activeSlug = task.slug;
  renderTask(task);
  renderTaskList();
}

async function bootstrap() {
  const response = await fetch('data/trajectories.json');
  if (!response.ok) {
    throw new Error(`Failed to load trajectories.json (${response.status})`);
  }

  const payload = await response.json();
  state.tasks = payload.tasks || [];
  state.filtered = state.tasks;

  if (state.tasks.length) {
    state.activeSlug = state.tasks[0].slug;
  }

  renderTaskList();

  if (state.tasks.length) {
    renderTask(state.tasks[0]);
  }
}

searchEl.addEventListener('input', (event) => {
  applySearch(event.target.value);
  renderTaskList();
});

bootstrap().catch((err) => {
  emptyStateEl.style.display = 'flex';
  emptyStateEl.innerHTML = `<div class="empty-state__card"><h2>Unable to load data</h2><p>${err.message}</p></div>`;
  console.error(err);
});

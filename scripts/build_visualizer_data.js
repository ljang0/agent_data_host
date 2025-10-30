#!/usr/bin/env node
/**
 * Generates visualization-ready data for LLM trajectories and copies
 * referenced screenshot assets into the static site folder.
 *
 * The script expects the following repository layout:
 *   data/<task-name>/(files)/{chat.jsonl,llm_events.json,...}
 *   visualizer/
 *     index.html (static site entry point)
 *     data/      (output folder populated by this script)
 *
 * Running this script creates/updates:
 *   visualizer/data/trajectories.json   -> aggregated chat metadata
 *   visualizer/data/assets/**           -> screenshot assets copied per task
 */

const fs = require('fs/promises');
const path = require('path');

const ROOT_DIR = path.resolve(__dirname, '..');
const DATA_DIR = path.join(ROOT_DIR, 'data');
const VISUALIZER_DIR = path.join(ROOT_DIR, 'visualizer');
const OUTPUT_DATA_DIR = path.join(VISUALIZER_DIR, 'data');
const OUTPUT_JSON_PATH = path.join(OUTPUT_DATA_DIR, 'trajectories.json');
const AGGREGATED_TRAJECTORIES_PATH = path.join(DATA_DIR, 'trajectories.json');

const STATIC_ASSETS = [
  { src: path.join(ROOT_DIR, 'index.html'), dest: path.join(VISUALIZER_DIR, 'index.html') },
  { src: path.join(ROOT_DIR, 'styles.css'), dest: path.join(VISUALIZER_DIR, 'styles.css') },
  { src: path.join(ROOT_DIR, 'scripts'), dest: path.join(VISUALIZER_DIR, 'scripts') },
];

async function ensureDirectory(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

function slugify(input) {
  return input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function toPosixPath(filePath) {
  return filePath.split(path.sep).join('/');
}

async function fileExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch (err) {
    return false;
  }
}

function normalizeAssetPath(assetPath) {
  if (!assetPath) return null;
  const posixPath = toPosixPath(assetPath).replace(/^\.\/+/, '');
  const withPrefix = posixPath.startsWith('data/') ? posixPath : `data/${posixPath}`;
  const relativeWithinData = withPrefix.replace(/^data\/+/, '');
  const absoluteSource = path.resolve(ROOT_DIR, withPrefix);
  return {
    withPrefix,
    relativeWithinData,
    absoluteSource,
  };
}

function deriveAnnotatedCandidate(absoluteSource) {
  const parentDir = path.dirname(absoluteSource);
  const parentName = path.basename(parentDir);
  const fileName = path.basename(absoluteSource);

  let annotatedDir;
  if (parentName === 'imgs') {
    annotatedDir = path.join(path.dirname(parentDir), 'imgs_annotated');
  } else if (parentName.startsWith('frames_display_')) {
    annotatedDir = path.join(path.dirname(parentDir), `${parentName}_annotated`);
  } else {
    annotatedDir = path.join(parentDir, 'annotated');
  }

  return path.join(annotatedDir, fileName);
}

async function copyAsset(assetPath, copiedMap) {
  const normalized = normalizeAssetPath(assetPath);
  if (!normalized) return null;

  const { absoluteSource, relativeWithinData } = normalized;
  if (!(await fileExists(absoluteSource))) {
    console.warn(`Missing asset: ${assetPath}`);
    return null;
  }

  const destRelativePosix = toPosixPath(relativeWithinData);
  const destAbsolute = path.join(OUTPUT_DATA_DIR, destRelativePosix);

  if (!copiedMap.has(absoluteSource)) {
    await ensureDirectory(path.dirname(destAbsolute));
    await fs.copyFile(absoluteSource, destAbsolute);
    copiedMap.set(absoluteSource, destRelativePosix);
  }

  return path.posix.join('data', destRelativePosix);
}

async function copyAnnotatedIfPresent(assetPath, copiedMap) {
  const normalized = normalizeAssetPath(assetPath);
  if (!normalized) return null;
  const { absoluteSource } = normalized;
  const annotatedCandidate = deriveAnnotatedCandidate(absoluteSource);
  if (!(await fileExists(annotatedCandidate))) {
    return null;
  }

  const relativeToRoot = toPosixPath(path.relative(ROOT_DIR, annotatedCandidate));
  return copyAsset(relativeToRoot, copiedMap);
}

async function loadAggregatedTrajectories() {
  const raw = await fs.readFile(AGGREGATED_TRAJECTORIES_PATH, 'utf8');
  const parsed = JSON.parse(raw);
  if (!parsed || typeof parsed !== 'object') {
    throw new Error('Invalid trajectories.json format');
  }
  if (!Array.isArray(parsed.tasks)) {
    throw new Error('trajectories.json missing tasks array');
  }
  return parsed;
}

async function buildVisualizerTasks(aggregated) {
  const copiedMap = new Map();
  const tasks = [];

  for (const task of aggregated.tasks) {
    const taskCopy = {
      name: task.name,
      slug: task.slug || slugify(task.name),
      sourceDir: task.sourceDir,
      systemPrompt: task.systemPrompt,
      stats: task.stats,
      timeline: task.timeline,
      steps: [],
      metadata: task.metadata,
      user: task.user,
    };

    for (const step of task.steps || []) {
      const newStep = {
        step: step.step,
        user: null,
        assistant: { ...step.assistant },
      };

      if (step.user) {
        const newUser = {
          raw: step.user.raw,
          text: step.user.text,
          attachments: [],
        };

        for (const attachment of step.user.attachments || []) {
          const attachmentCopy = {
            ...attachment,
          };

          if (attachment.assetPath) {
            const copiedAssetPath = await copyAsset(attachment.assetPath, copiedMap);
            if (copiedAssetPath) {
              attachmentCopy.assetPath = copiedAssetPath;
            }
          }

          if (attachment.annotatedAssetPath) {
            const copiedAnnotated = await copyAsset(attachment.annotatedAssetPath, copiedMap);
            if (copiedAnnotated) {
              attachmentCopy.annotatedAssetPath = copiedAnnotated;
            }
          } else if (attachment.assetPath) {
            const copiedAnnotated = await copyAnnotatedIfPresent(attachment.assetPath, copiedMap);
            if (copiedAnnotated) {
              attachmentCopy.annotatedAssetPath = copiedAnnotated;
              const normalized = normalizeAssetPath(attachment.assetPath);
              const annotatedAbsolute = deriveAnnotatedCandidate(normalized.absoluteSource);
              attachmentCopy.annotatedOriginalPath = toPosixPath(path.relative(ROOT_DIR, annotatedAbsolute));
            }
          }

          newUser.attachments.push(attachmentCopy);
        }

        newStep.user = newUser;
      }

      taskCopy.steps.push(newStep);
    }

    tasks.push(taskCopy);
  }

  return tasks;
}

async function copyStaticAssets() {
  for (const asset of STATIC_ASSETS) {
    if (!(await fileExists(asset.src))) {
      console.warn(`Static asset missing, skipping copy: ${asset.src}`);
      continue;
    }
    const stats = await fs.stat(asset.src);
    if (stats.isDirectory()) {
      await fs.cp(asset.src, asset.dest, { recursive: true });
    } else {
      await ensureDirectory(path.dirname(asset.dest));
      await fs.copyFile(asset.src, asset.dest);
    }
  }
}

async function main() {
  await fs.rm(VISUALIZER_DIR, { recursive: true, force: true }).catch(() => undefined);
  await ensureDirectory(OUTPUT_DATA_DIR);
  await copyStaticAssets();
  const aggregated = await loadAggregatedTrajectories();
  const tasks = await buildVisualizerTasks(aggregated);

  const payload = {
    generatedAt: new Date().toISOString(),
    taskCount: tasks.length,
    tasks,
  };

  await fs.writeFile(OUTPUT_JSON_PATH, JSON.stringify(payload, null, 2), 'utf8');
  console.log(`Wrote ${tasks.length} task(s) to ${toPosixPath(path.relative(ROOT_DIR, OUTPUT_JSON_PATH))}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

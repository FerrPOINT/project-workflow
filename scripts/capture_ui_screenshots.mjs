import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const fallbackRequire = createRequire(new URL("../.smoke/package.json", import.meta.url));
const { chromium } = loadPlaywright();

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const baseUrl = process.env.SMOKE_BASE_URL || "http://127.0.0.1:8812";
const outputDir = path.resolve(rootDir, process.env.SMOKE_SCREENSHOT_DIR || "docs/screenshots");
const desktopViewport = { width: 1920, height: 1080 };
const forbiddenVisibleText = [
  /Hermes/i,
  /Гермес/i,
  /project-workflow/i,
  /sdlc-/i,
  /\bflow-[a-z0-9_-]+\b/i,
  /launch-[a-z0-9_-]+/i,
  /\bsmoke\b/i,
  /Default Namespace/i,
  /Supervisor/i,
  /Профиль запуска/i,
  /Relevanter/i,
  /dueDate/i,
  /\bBusiness\b/i,
  /Business-/i,
  /\bTech\b/i,
  /Tech-/i,
  /бизнес/i,
  /Maintainer/i,
  /\borchestrator\b/i,
  /codex-operator/i,
];
const screenshotNames = [
  "dashboard.png",
  "dashboard-qa.png",
  "namespaces.png",
  "namespace-new.png",
  "tasks.png",
  "tasks-qa.png",
  "workflows.png",
  "phases.png",
  "phases-qa.png",
  "instructions.png",
  "task-detail-dev.png",
  "task-detail-qa.png",
  "agents.png",
  "settings.png",
  "mobile-dashboard.png",
];
const taskKeys = [
  "RUN-42",
  "RUN-77",
  "RUN-88",
  "RUN-105",
  "RUN-120",
  "RUN-130",
  "RUN-143",
  "RUN-160",
  "RUN-171",
  "RUN-180",
  "RUN-190",
  "RUN-205",
  "RUN-215",
  "RUN-225",
  "RUN-240",
  "RUN-255",
  "RUN-270",
  "RUN-285",
];
const doneTaskKeys = new Set(["RUN-88", "RUN-160", "RUN-270"]);
const openTaskKeys = taskKeys.filter((key) => !doneTaskKeys.has(key));
const expectedNamespaceCommands = ["workflow-dev", "workflow-qa"];

function loadPlaywright() {
  try {
    return require("playwright");
  } catch (error) {
    if (error?.code !== "MODULE_NOT_FOUND") {
      throw error;
    }
    return fallbackRequire("playwright");
  }
}

async function listNamespaces(request) {
  const response = await request.get(`${baseUrl}/api/namespaces`);
  if (!response.ok()) {
    throw new Error(`namespaces request failed: ${response.status()}`);
  }
  const payload = await response.json();
  return payload.namespaces;
}

async function namespaceByCommand(request, command) {
  const namespaces = await listNamespaces(request);
  const namespace = namespaces.find((item) => item.cli_command === command);
  if (!namespace) {
    throw new Error(`namespace ${command} not found`);
  }
  return namespace;
}

async function listPhases(request, workflowId) {
  const response = await request.get(`${baseUrl}/api/phases?workflow_id=${workflowId}`);
  if (!response.ok()) {
    throw new Error(`phases request failed: ${response.status()}`);
  }
  const payload = await response.json();
  return payload.phases;
}

async function phaseByOrder(request, workflowId, phaseOrder) {
  const phases = await listPhases(request, workflowId);
  const phase = phases.find((item) => item.phase_order === phaseOrder);
  if (!phase) {
    throw new Error(`phase ${phaseOrder} not found for workflow ${workflowId}`);
  }
  return phase;
}

async function assertSmokeNamespaces(request) {
  const namespaces = await listNamespaces(request);
  assertSameSet(
    "api",
    "namespace commands",
    namespaces.map((namespace) => namespace.cli_command),
    expectedNamespaceCommands,
  );
  for (const command of expectedNamespaceCommands) {
    const namespace = namespaces.find((item) => item.cli_command === command);
    if (!namespace || namespace.task_count !== taskKeys.length) {
      throw new Error(`${command} task_count must be ${taskKeys.length}`);
    }
  }
}

async function assertVisibleText(page, name, expected) {
  const bodyText = await page.locator("body").innerText();
  const fieldText = await page.locator("input, textarea, select").evaluateAll((fields) =>
    fields
      .map((field) => {
        if (field instanceof HTMLSelectElement) {
          return field.selectedOptions[0]?.textContent || field.value;
        }
        if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
          return field.value;
        }
        return "";
      })
      .filter(Boolean)
      .join("\n"),
  );
  const visibleText = `${bodyText}\n${fieldText}`;
  for (const pattern of forbiddenVisibleText) {
    if (pattern.test(visibleText)) {
      throw new Error(`${name} contains forbidden visible text: ${pattern}`);
    }
  }
  for (const text of expected) {
    if (!visibleText.includes(text)) {
      throw new Error(`${name} does not contain expected text: ${text}`);
    }
  }
}

function sorted(values) {
  return [...values].sort((left, right) => left.localeCompare(right));
}

function assertSameSet(name, label, actual, expected) {
  const actualSorted = sorted(new Set(actual));
  const expectedSorted = sorted(new Set(expected));
  if (actualSorted.length !== expectedSorted.length) {
    throw new Error(
      `${name} ${label} count mismatch: expected ${expectedSorted.length}, got ${actualSorted.length} (${actualSorted.join(", ")})`,
    );
  }
  for (const expectedValue of expectedSorted) {
    if (!actualSorted.includes(expectedValue)) {
      throw new Error(`${name} ${label} is missing ${expectedValue}; got ${actualSorted.join(", ")}`);
    }
  }
}

function pngSize(filePath) {
  const header = fs.readFileSync(filePath).subarray(0, 24);
  if (header.toString("ascii", 12, 16) !== "IHDR") {
    throw new Error(`${path.basename(filePath)} is not a PNG with IHDR header`);
  }
  return {
    width: header.readUInt32BE(16),
    height: header.readUInt32BE(20),
  };
}

async function fullPageMetrics(page) {
  return page.evaluate(() => ({
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
    scrollWidth: Math.ceil(Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)),
    scrollHeight: Math.ceil(Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)),
  }));
}

function assertFullPageScreenshotSize(name, filePath, metrics) {
  const size = pngSize(filePath);
  const minWidth = Math.max(metrics.viewportWidth, metrics.scrollWidth);
  const minHeight = Math.max(metrics.viewportHeight, metrics.scrollHeight);
  if (size.width < minWidth || size.height < minHeight) {
    throw new Error(
      `${name} is not full-page: expected at least ${minWidth}x${minHeight}, got ${size.width}x${size.height}`,
    );
  }
  return size;
}

async function assertTaskTable(page, name, expectedKeys) {
  const rowKeys = await page.locator(".tasks-table tbody tr[data-task-key]").evaluateAll((rows) =>
    rows.map((row) => row.getAttribute("data-task-key")).filter(Boolean),
  );
  assertSameSet(name, "task table", rowKeys, expectedKeys);
}

async function assertLocatorCount(page, name, selector, expectedMin, label) {
  const count = await page.locator(selector).count();
  if (count < expectedMin) {
    throw new Error(`${name} ${label} is incomplete: expected at least ${expectedMin}, got ${count}`);
  }
}

async function assertTaskStateCoverage(page, name) {
  const rows = page.locator(".tasks-table tbody tr[data-task-key]");
  const statuses = await rows.evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-status")));
  const verdicts = await rows.evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-verdict")));
  assertSameSet(name, "task statuses", statuses, ["active", "blocked", "done"]);
  assertSameSet(name, "latest verdicts", verdicts, ["blocked", "delegate", "partial", "pass", "rollback"]);
}

async function assertDashboardTasks(page, name, expectedKeys) {
  const rowKeys = await page.locator("[data-dashboard-open-tasks] [data-task-key]").evaluateAll((rows) =>
    rows.map((row) => row.getAttribute("data-task-key")).filter(Boolean),
  );
  assertSameSet(name, "dashboard open tasks", rowKeys, expectedKeys);
}

async function assertDashboardNamespaceCards(page, name) {
  const namespaceNames = await page.locator("[data-dashboard-namespaces] .list-title").evaluateAll((nodes) =>
    nodes.map((node) => node.textContent?.trim()).filter(Boolean),
  );
  assertSameSet(name, "dashboard namespaces", namespaceNames, ["Разработка", "Проверка качества"]);
}

async function assertTaskDetailHistory(page, name, minRuns) {
  const runCount = await page.locator("[data-check-run]").count();
  if (runCount < minRuns) {
    throw new Error(`${name} check history is incomplete: expected at least ${minRuns}, got ${runCount}`);
  }
}

async function capture(page, outputRoot, { name, url, expected = [], prepare, assertions = [] }) {
  await page.goto(`${baseUrl}${url}`, { waitUntil: "networkidle", timeout: 30000 });
  if (prepare) {
    await prepare(page);
    await page.waitForTimeout(1000);
  }
  await assertVisibleText(page, name, expected);
  for (const assertion of assertions) {
    await assertion(page, name);
  }
  await page.waitForTimeout(1000);
  const metrics = await fullPageMetrics(page);
  const outputPath = path.join(outputRoot, name);
  await page.screenshot({ path: outputPath, fullPage: true });
  const size = assertFullPageScreenshotSize(name, outputPath, metrics);
  console.log(`captured ${name} ${size.width}x${size.height}`);
}

async function fillNamespaceDraft(page, qaWorkflowId) {
  await page.fill("#namespaceName", "Релизный прогон");
  await page.fill("#namespaceCliCommand", "workflow-release");
  await page.fill("#namespaceDescription", "Проверка заполненной формы создания, выбора и визуального стиля.");
  await page.selectOption("#namespaceThemeIcon", "rocket");
  await page.fill("#namespaceThemeColor", "#F59E0B");
  await page.selectOption("#namespaceWorkflowId", String(qaWorkflowId));
  const values = await page.evaluate(() => ({
    name: document.getElementById("namespaceName").value,
    command: document.getElementById("namespaceCliCommand").value,
    workflow: document.getElementById("namespaceWorkflowId").value,
  }));
  if (values.name !== "Релизный прогон" || values.command !== "workflow-release") {
    throw new Error("namespace-new form values were not applied");
  }
}

function removeTempOutputDir(tempOutputDir) {
  const relative = path.relative(outputDir, tempOutputDir);
  const isInsideOutput = relative && !relative.startsWith("..") && !path.isAbsolute(relative);
  if (!isInsideOutput || !path.basename(tempOutputDir).startsWith(".capture-")) {
    throw new Error(`refusing to remove unexpected screenshot temp dir: ${tempOutputDir}`);
  }
  fs.rmSync(tempOutputDir, { recursive: true, force: true });
}

async function main() {
  fs.mkdirSync(outputDir, { recursive: true });
  const tempOutputDir = fs.mkdtempSync(path.join(outputDir, ".capture-"));
  try {
    await captureAll(tempOutputDir);
    for (const name of screenshotNames) {
      const source = path.join(tempOutputDir, name);
      if (!fs.existsSync(source)) {
        throw new Error(`${name} was not captured`);
      }
    }
    for (const name of screenshotNames) {
      fs.copyFileSync(path.join(tempOutputDir, name), path.join(outputDir, name));
    }
  } finally {
    removeTempOutputDir(tempOutputDir);
  }
}

async function captureAll(outputRoot) {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: desktopViewport, deviceScaleFactor: 1 });
  const page = await context.newPage();
  try {
    await assertSmokeNamespaces(context.request);
    const dev = await namespaceByCommand(context.request, "workflow-dev");
    const qa = await namespaceByCommand(context.request, "workflow-qa");
    const devFirstPhase = await phaseByOrder(context.request, dev.workflow_id, 1);
    await capture(page, outputRoot, {
      name: "dashboard.png",
      url: `/?namespace_id=${dev.id}`,
      expected: ["Разработка", "Проверка качества", ...openTaskKeys],
      assertions: [
        (targetPage, name) => assertDashboardTasks(targetPage, name, openTaskKeys),
        assertDashboardNamespaceCards,
      ],
    });
    await capture(page, outputRoot, {
      name: "dashboard-qa.png",
      url: `/?namespace_id=${qa.id}`,
      expected: ["Проверка качества", "Разработка", ...openTaskKeys],
      assertions: [
        (targetPage, name) => assertDashboardTasks(targetPage, name, openTaskKeys),
        assertDashboardNamespaceCards,
      ],
    });
    await capture(page, outputRoot, {
      name: "namespaces.png",
      url: `/namespaces?namespace_id=${dev.id}`,
      expected: ["Разработка", "Проверка качества", "workflow-dev", "workflow-qa", "Воркфлоу разработки"],
      assertions: [(targetPage, name) => assertLocatorCount(targetPage, name, ".namespace-nav-item", 2, "namespace list")],
    });
    await capture(page, outputRoot, {
      name: "namespace-new.png",
      url: `/namespaces/new?namespace_id=${dev.id}`,
      expected: ["СОЗДАНИЕ", "Разработка", "Проверка качества", "CLI-КОМАНДА"],
      prepare: (targetPage) => fillNamespaceDraft(targetPage, qa.workflow_id),
      assertions: [(targetPage, name) => assertLocatorCount(targetPage, name, ".namespace-nav-item", 2, "namespace list")],
    });
    await capture(page, outputRoot, {
      name: "tasks.png",
      url: `/tasks?namespace_id=${dev.id}`,
      expected: ["workflow-dev", "Воркфлоу разработки", ...taskKeys],
      assertions: [
        (targetPage, name) => assertTaskTable(targetPage, name, taskKeys),
        assertTaskStateCoverage,
      ],
    });
    await capture(page, outputRoot, {
      name: "tasks-qa.png",
      url: `/tasks?namespace_id=${qa.id}`,
      expected: ["workflow-qa", "Воркфлоу проверки", ...taskKeys],
      assertions: [
        (targetPage, name) => assertTaskTable(targetPage, name, taskKeys),
        assertTaskStateCoverage,
      ],
    });
    await capture(page, outputRoot, {
      name: "workflows.png",
      url: `/workflows?namespace_id=${dev.id}`,
      expected: ["Воркфлоу разработки", "Воркфлоу проверки"],
      assertions: [(targetPage, name) => assertLocatorCount(targetPage, name, ".workflow-nav-item", 2, "workflow list")],
    });
    await capture(page, outputRoot, {
      name: "phases.png",
      url: `/phases?namespace_id=${dev.id}`,
      expected: ["Воркфлоу разработки", "Приём задачи", "Завершение", "Улучшения"],
      assertions: [(targetPage, name) => assertLocatorCount(targetPage, name, "#phasesTimeline .timeline-item", 12, "phase timeline")],
    });
    await capture(page, outputRoot, {
      name: "phases-qa.png",
      url: `/phases?namespace_id=${qa.id}`,
      expected: ["Воркфлоу проверки", "Проверка сценариев", "Финальный отчёт"],
      assertions: [(targetPage, name) => assertLocatorCount(targetPage, name, "#phasesTimeline .timeline-item", 6, "phase timeline")],
    });
    await capture(page, outputRoot, {
      name: "instructions.png",
      url: `/instructions?phase_id=${devFirstPhase.id}&namespace_id=${dev.id}`,
      expected: [
        "Инструкции фазы Приём задачи",
        "task-record",
        "source-check",
        "во внешней системе",
        "Сохранить стабильную ссылку",
      ],
    });
    await capture(page, outputRoot, {
      name: "task-detail-dev.png",
      url: `/task/RUN-42?namespace_id=${dev.id}`,
      expected: ["RUN-42", "Реализовать проверяемое изменение", "workflow-dev", "История проверок"],
      assertions: [(targetPage, name) => assertTaskDetailHistory(targetPage, name, 4)],
    });
    await capture(page, outputRoot, {
      name: "task-detail-qa.png",
      url: `/task/RUN-42?namespace_id=${qa.id}`,
      expected: ["RUN-42", "Независимо проверить ту же внешнюю задачу", "workflow-qa", "История проверок"],
      assertions: [(targetPage, name) => assertTaskDetailHistory(targetPage, name, 3)],
    });
    await capture(page, outputRoot, {
      name: "agents.png",
      url: `/agents?namespace_id=${dev.id}`,
      expected: [
        "Агенты",
        "КЛЮЧ ЗАПУСКА",
        "Координатор",
        "Оператор",
        "Ревьюер",
        "run-coord",
        "run-dev",
        "run-review",
      ],
      assertions: [(targetPage, name) => assertLocatorCount(targetPage, name, "#agentsTable tr", 7, "agent table")],
    });
    await capture(page, outputRoot, {
      name: "settings.png",
      url: `/settings?namespace_id=${dev.id}`,
      expected: ["CLI", "workflow-dev step", "workflow-dev history", "--report", "--n"],
    });
  } finally {
    await context.close();
    await browser.close();
  }

  const mobile = await chromium.launch();
  const mobileContext = await mobile.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    isMobile: true,
  });
  const mobilePage = await mobileContext.newPage();
  try {
    const dev = await namespaceByCommand(mobileContext.request, "workflow-dev");
    await capture(mobilePage, outputRoot, {
      name: "mobile-dashboard.png",
      url: `/?namespace_id=${dev.id}`,
      expected: ["Разработка", ...openTaskKeys],
      assertions: [(targetPage, name) => assertDashboardTasks(targetPage, name, openTaskKeys)],
    });
  } finally {
    await mobileContext.close();
    await mobile.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

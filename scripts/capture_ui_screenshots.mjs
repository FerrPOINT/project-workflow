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
const forbiddenVisibleText = [/Hermes/i, /Гермес/i, /project-workflow/i, /sdlc-/i, /Default Namespace/i, /Supervisor/i];
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
];
const doneTaskKeys = new Set(["RUN-88", "RUN-160"]);
const openTaskKeys = taskKeys.filter((key) => !doneTaskKeys.has(key));

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

async function namespaceByCommand(request, command) {
  const response = await request.get(`${baseUrl}/api/namespaces`);
  if (!response.ok()) {
    throw new Error(`namespaces request failed: ${response.status()}`);
  }
  const payload = await response.json();
  const namespace = payload.namespaces.find((item) => item.cli_command === command);
  if (!namespace) {
    throw new Error(`namespace ${command} not found`);
  }
  return namespace;
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

async function assertTaskTable(page, name, expectedKeys) {
  const rowKeys = await page.locator(".tasks-table tbody tr[data-task-key]").evaluateAll((rows) =>
    rows.map((row) => row.getAttribute("data-task-key")).filter(Boolean),
  );
  assertSameSet(name, "task table", rowKeys, expectedKeys);
}

async function assertDashboardTasks(page, name, expectedKeys) {
  const rowKeys = await page.locator("[data-dashboard-open-tasks] [data-task-key]").evaluateAll((rows) =>
    rows.map((row) => row.getAttribute("data-task-key")).filter(Boolean),
  );
  assertSameSet(name, "dashboard open tasks", rowKeys, expectedKeys);
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
  await page.screenshot({ path: path.join(outputRoot, name), fullPage: true });
  console.log(`captured ${name}`);
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
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  try {
    const dev = await namespaceByCommand(context.request, "workflow-dev");
    const qa = await namespaceByCommand(context.request, "workflow-qa");
    await capture(page, outputRoot, {
      name: "dashboard.png",
      url: `/?namespace_id=${dev.id}`,
      expected: ["Разработка", "Проверка качества", ...openTaskKeys],
      assertions: [(targetPage, name) => assertDashboardTasks(targetPage, name, openTaskKeys)],
    });
    await capture(page, outputRoot, {
      name: "dashboard-qa.png",
      url: `/?namespace_id=${qa.id}`,
      expected: ["Проверка качества", "Разработка", ...openTaskKeys],
      assertions: [(targetPage, name) => assertDashboardTasks(targetPage, name, openTaskKeys)],
    });
    await capture(page, outputRoot, {
      name: "namespaces.png",
      url: `/namespaces?namespace_id=${dev.id}`,
      expected: ["Разработка", "Проверка качества", "workflow-dev", "workflow-qa", "Воркфлоу разработки"],
    });
    await capture(page, outputRoot, {
      name: "namespace-new.png",
      url: `/namespaces/new?namespace_id=${dev.id}`,
      expected: ["СОЗДАНИЕ", "Разработка", "Проверка качества", "CLI-КОМАНДА"],
      prepare: (targetPage) => fillNamespaceDraft(targetPage, qa.workflow_id),
    });
    await capture(page, outputRoot, {
      name: "tasks.png",
      url: `/tasks?namespace_id=${dev.id}`,
      expected: ["workflow-dev", "Воркфлоу разработки", ...taskKeys],
      assertions: [(targetPage, name) => assertTaskTable(targetPage, name, taskKeys)],
    });
    await capture(page, outputRoot, {
      name: "tasks-qa.png",
      url: `/tasks?namespace_id=${qa.id}`,
      expected: ["workflow-qa", "Воркфлоу проверки", ...taskKeys],
      assertions: [(targetPage, name) => assertTaskTable(targetPage, name, taskKeys)],
    });
    await capture(page, outputRoot, {
      name: "workflows.png",
      url: `/workflows?namespace_id=${dev.id}`,
      expected: ["Воркфлоу разработки", "Воркфлоу проверки"],
    });
    await capture(page, outputRoot, {
      name: "phases.png",
      url: `/phases?namespace_id=${dev.id}`,
      expected: ["Воркфлоу разработки", "Приём задачи", "Завершение", "Улучшения"],
    });
    await capture(page, outputRoot, {
      name: "phases-qa.png",
      url: `/phases?namespace_id=${qa.id}`,
      expected: ["Воркфлоу проверки", "Проверка сценариев", "Финальный отчёт"],
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
      expected: ["Агенты", "ПРОФИЛЬ ЗАПУСКА", "launch-orchestrator", "launch-reviewer"],
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

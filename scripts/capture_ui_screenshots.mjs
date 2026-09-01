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
const forbiddenVisibleText = [/Hermes/i, /Гермес/i, /sdlc-/i, /Default Namespace/i, /Supervisor/i];
const taskKeys = ["RUN-42", "RUN-77", "RUN-88", "RUN-105", "RUN-120", "RUN-130", "RUN-143", "RUN-160", "RUN-171"];

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

async function capture(page, { name, url, expected = [], prepare }) {
  await page.goto(`${baseUrl}${url}`, { waitUntil: "networkidle", timeout: 30000 });
  if (prepare) {
    await prepare(page);
    await page.waitForTimeout(250);
  }
  await assertVisibleText(page, name, expected);
  await page.screenshot({ path: path.join(outputDir, name), fullPage: true });
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

async function main() {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  try {
    const dev = await namespaceByCommand(context.request, "workflow-dev");
    const qa = await namespaceByCommand(context.request, "workflow-qa");
    await capture(page, {
      name: "dashboard.png",
      url: `/?namespace_id=${dev.id}`,
      expected: ["Разработка", "Проверка качества", "RUN-42", "RUN-77", "RUN-105"],
    });
    await capture(page, {
      name: "namespaces.png",
      url: `/namespaces?namespace_id=${dev.id}`,
      expected: ["Разработка", "Проверка качества", "workflow-dev", "workflow-qa", "Воркфлоу разработки"],
    });
    await capture(page, {
      name: "namespace-new.png",
      url: `/namespaces/new?namespace_id=${dev.id}`,
      expected: ["СОЗДАНИЕ", "Разработка", "Проверка качества", "CLI-КОМАНДА"],
      prepare: (targetPage) => fillNamespaceDraft(targetPage, qa.workflow_id),
    });
    await capture(page, {
      name: "tasks.png",
      url: `/tasks?namespace_id=${dev.id}`,
      expected: ["workflow-dev", "Воркфлоу разработки", ...taskKeys],
    });
    await capture(page, {
      name: "tasks-qa.png",
      url: `/tasks?namespace_id=${qa.id}`,
      expected: ["workflow-qa", "Воркфлоу проверки", ...taskKeys],
    });
    await capture(page, {
      name: "workflows.png",
      url: `/workflows?namespace_id=${dev.id}`,
      expected: ["Воркфлоу разработки", "Воркфлоу проверки"],
    });
    await capture(page, {
      name: "phases.png",
      url: `/phases?namespace_id=${dev.id}`,
      expected: ["Воркфлоу разработки", "Приём задачи", "Завершение", "Улучшения"],
    });
    await capture(page, {
      name: "phases-qa.png",
      url: `/phases?namespace_id=${qa.id}`,
      expected: ["Воркфлоу проверки", "Проверка сценариев", "Финальный отчёт"],
    });
    await capture(page, {
      name: "task-detail-dev.png",
      url: `/task/RUN-42?namespace_id=${dev.id}`,
      expected: ["RUN-42", "Реализовать проверяемое изменение", "workflow-dev", "История проверок"],
    });
    await capture(page, {
      name: "task-detail-qa.png",
      url: `/task/RUN-42?namespace_id=${qa.id}`,
      expected: ["RUN-42", "Независимо проверить ту же внешнюю задачу", "workflow-qa", "История проверок"],
    });
    await capture(page, {
      name: "agents.png",
      url: `/agents?namespace_id=${dev.id}`,
      expected: ["Агенты", "ПРОФИЛЬ ЗАПУСКА", "launch-orchestrator", "launch-reviewer"],
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
    await capture(mobilePage, {
      name: "mobile-dashboard.png",
      url: `/?namespace_id=${dev.id}`,
      expected: ["Разработка", "RUN-42"],
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

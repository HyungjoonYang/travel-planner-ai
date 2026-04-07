/**
 * E2E Playwright tests for UX improvements (Task F1–F3)
 *
 * Scenarios:
 *   1. progress event renders inline in the AI bubble
 *   2. confirm_plan event renders a confirmation card with action buttons
 *   3. "계획 세우기" button sends confirmation message
 *   4. "수정하기" button focuses the chat input
 *   5. agent_reasoning event renders reasoning in agent card
 *   6. agent card click toggles reasoning panel
 *   7. resetAgentCards clears reasoning state
 *
 * All tests use Playwright route mocking — no live Gemini API required.
 */

import { test, expect, Page } from "@playwright/test";

const BASE_URL = process.env.QA_BASE_URL || "http://localhost:8000";
const MOCK_SESSION_ID = "e2e-ux-test-session";

function buildSse(...events: object[]): string {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
}

async function mockChatSession(page: Page, sseEvents: object[]): Promise<void> {
  await page.route("**/chat/sessions", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: MOCK_SESSION_ID,
          created_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + 3_600_000).toISOString(),
          agent_states: {},
          last_plan: null,
        }),
      });
    } else {
      await route.continue();
    }
  });

  await page.route("**/chat/sessions/*/messages", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      headers: {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
      },
      body: buildSse(...sseEvents),
    });
  });
}

async function goToChat(page: Page): Promise<void> {
  await page.goto(BASE_URL);
  await page.click('a[data-page="chat"]');
  await expect(page.locator(".chat-layout")).toBeVisible({ timeout: 5_000 });
}

async function expandAgentPanel(page: Page): Promise<void> {
  const compactRow = page.locator("#agent-panel-compact-row");
  if (await compactRow.isVisible()) {
    await compactRow.click();
  }
}

async function sendAndWait(page: Page, message: string): Promise<void> {
  await page.fill("#chat-input", message);
  await page.click('button:has-text("전송")');
  await page.waitForSelector(".chat-bubble.chat-ai", { timeout: 10_000 });
  await page.waitForTimeout(500);
}

// ---------------------------------------------------------------------------
// F1: progress event → inline in bubble
// ---------------------------------------------------------------------------

test.describe("F1: progress event inline display", () => {
  const PROGRESS_EVENTS = [
    {
      type: "agent_status",
      data: { agent: "coordinator", status: "thinking", message: "요청 분석 중..." },
    },
    {
      type: "agent_status",
      data: { agent: "coordinator", status: "done", message: "create_plan 파악" },
    },
    { type: "chat_chunk", data: { text: "네, 알겠습니다! 확인해볼게요 ✨\n" } },
    { type: "progress", data: { step: "search", message: "📍 도쿄 장소 검색 중..." } },
    { type: "progress", data: { step: "places_done", message: "✅ 12개 장소 발견" } },
    { type: "chat_chunk", data: { text: "도쿄 3일 여행 계획을 생성했습니다." } },
    { type: "chat_done", data: {} },
  ];

  test("progress text appears in the same AI bubble", async ({ page }) => {
    await mockChatSession(page, PROGRESS_EVENTS);
    await goToChat(page);
    await sendAndWait(page, "도쿄 3일 여행 계획 세워줘");

    const lastAiBubble = page.locator(".chat-bubble.chat-ai").last();
    const text = await lastAiBubble.textContent();

    // All content should be in one bubble
    expect(text).toContain("네, 알겠습니다!");
    expect(text).toContain("📍 도쿄 장소 검색 중...");
    expect(text).toContain("✅ 12개 장소 발견");
    expect(text).toContain("도쿄 3일 여행 계획을 생성했습니다.");
  });

  test("progress and chat_chunk are sequentially ordered", async ({ page }) => {
    await mockChatSession(page, PROGRESS_EVENTS);
    await goToChat(page);
    await sendAndWait(page, "도쿄 3일 여행 계획 세워줘");

    const lastAiBubble = page.locator(".chat-bubble.chat-ai").last();
    const text = (await lastAiBubble.textContent()) ?? "";

    // Progress should appear between fast response and final chunk
    const fastIdx = text.indexOf("확인해볼게요");
    const progressIdx = text.indexOf("장소 검색 중");
    const finalIdx = text.indexOf("생성했습니다");

    expect(fastIdx).toBeLessThan(progressIdx);
    expect(progressIdx).toBeLessThan(finalIdx);
  });
});

// ---------------------------------------------------------------------------
// F2: confirm_plan event → confirmation card
// ---------------------------------------------------------------------------

test.describe("F2: confirm_plan card UI", () => {
  const CONFIRM_EVENTS = [
    {
      type: "agent_status",
      data: { agent: "coordinator", status: "thinking", message: "요청 분석 중..." },
    },
    {
      type: "agent_status",
      data: { agent: "coordinator", status: "done", message: "general 파악" },
    },
    {
      type: "chat_chunk",
      data: { text: "좋아요! 다음 조건으로 계획을 세울까요?\n" },
    },
    {
      type: "confirm_plan",
      data: {
        destination: "도쿄",
        start_date: "2026-05-01",
        end_date: "2026-05-03",
        budget: 2000000,
        interests: "음식, 문화",
      },
    },
    { type: "chat_done", data: {} },
  ];

  test("confirm card renders with trip details", async ({ page }) => {
    await mockChatSession(page, CONFIRM_EVENTS);
    await goToChat(page);
    await sendAndWait(page, "5월에 도쿄 3일 여행 200만원으로");

    const card = page.locator(".confirm-plan-card");
    await expect(card).toBeVisible({ timeout: 5_000 });

    await expect(card).toContainText("도쿄");
    await expect(card).toContainText("2026-05-01");
    await expect(card).toContainText("2026-05-03");
    await expect(card).toContainText("2,000,000");
    await expect(card).toContainText("음식, 문화");
  });

  test("confirm card has action buttons", async ({ page }) => {
    await mockChatSession(page, CONFIRM_EVENTS);
    await goToChat(page);
    await sendAndWait(page, "5월에 도쿄 3일 여행 200만원으로");

    await expect(page.locator(".confirm-yes")).toBeVisible();
    await expect(page.locator(".confirm-edit")).toBeVisible();
    await expect(page.locator(".confirm-yes")).toContainText("계획 세우기");
    await expect(page.locator(".confirm-edit")).toContainText("수정하기");
  });

  test("계획 세우기 button fills and sends message", async ({ page }) => {
    await mockChatSession(page, CONFIRM_EVENTS);
    await goToChat(page);
    await sendAndWait(page, "5월에 도쿄 3일 여행 200만원으로");

    // Click the confirm button — it should fill the input and trigger send
    // We just verify the user bubble appears with the confirmation text
    await page.locator(".confirm-yes").click();
    await page.waitForTimeout(500);

    const userBubbles = page.locator(".chat-bubble.chat-user");
    const lastUserBubble = userBubbles.last();
    await expect(lastUserBubble).toContainText("네, 계획 세워줘");
  });

  test("수정하기 button focuses input and changes placeholder", async ({ page }) => {
    await mockChatSession(page, CONFIRM_EVENTS);
    await goToChat(page);
    await sendAndWait(page, "5월에 도쿄 3일 여행 200만원으로");

    await page.locator(".confirm-edit").click();
    await page.waitForTimeout(200);

    const input = page.locator("#chat-input");
    await expect(input).toBeFocused();
    const placeholder = await input.getAttribute("placeholder");
    expect(placeholder).toContain("변경하고 싶은 조건");
  });

  test("confirm card is inside the AI bubble (not a separate bubble)", async ({ page }) => {
    await mockChatSession(page, CONFIRM_EVENTS);
    await goToChat(page);
    await sendAndWait(page, "5월에 도쿄 3일 여행 200만원으로");

    // The card should be a descendant of a .chat-ai bubble
    const cardInBubble = page.locator(".chat-bubble.chat-ai .confirm-plan-card");
    await expect(cardInBubble).toHaveCount(1);
  });
});

// ---------------------------------------------------------------------------
// F3: agent_reasoning event → reasoning panel in agent card
// ---------------------------------------------------------------------------

test.describe("F3: agent_reasoning panel", () => {
  const REASONING_EVENTS = [
    {
      type: "agent_status",
      data: { agent: "coordinator", status: "thinking", message: "요청 분석 중..." },
    },
    {
      type: "agent_status",
      data: { agent: "coordinator", status: "done", message: "create_plan 파악" },
    },
    {
      type: "agent_status",
      data: { agent: "planner", status: "working", message: "일정 구성 중..." },
    },
    {
      type: "agent_reasoning",
      data: {
        agent: "planner",
        reasoning: "도쿄 3일 여행, 예산 200만원, 관심사: 음식/문화 — 하루 66만원 배분",
      },
    },
    {
      type: "agent_status",
      data: { agent: "planner", status: "done", message: "일정 완성!" },
    },
    { type: "chat_chunk", data: { text: "계획이 완성되었습니다." } },
    { type: "chat_done", data: {} },
  ];

  test("reasoning panel is created in agent card", async ({ page }) => {
    await mockChatSession(page, REASONING_EVENTS);
    await goToChat(page);
    await sendAndWait(page, "도쿄 3일 여행 계획 세워줘");

    await expandAgentPanel(page);

    // The planner card should have a reasoning element
    const reasoningEl = page.locator('[data-agent="planner"] .agent-reasoning');
    await expect(reasoningEl).toBeAttached();
    await expect(reasoningEl).toContainText("도쿄 3일 여행");
    await expect(reasoningEl).toContainText("66만원");
  });

  test("reasoning panel toggles on card click", async ({ page }) => {
    await mockChatSession(page, REASONING_EVENTS);
    await goToChat(page);
    await sendAndWait(page, "도쿄 3일 여행 계획 세워줘");

    await expandAgentPanel(page);

    const plannerCard = page.locator('[data-agent="planner"]');
    const reasoningEl = page.locator('[data-agent="planner"] .agent-reasoning');

    // Initially hidden (display: none from CSS)
    await expect(reasoningEl).not.toBeVisible();

    // Click to reveal
    await plannerCard.click();
    await expect(reasoningEl).toBeVisible();

    // Click again to hide
    await plannerCard.click();
    await expect(reasoningEl).not.toBeVisible();
  });

  test("toggle arrow shows when agent has reasoning", async ({ page }) => {
    await mockChatSession(page, REASONING_EVENTS);
    await goToChat(page);
    await sendAndWait(page, "도쿄 3일 여행 계획 세워줘");

    await expandAgentPanel(page);

    // Planner has reasoning → toggle should be visible
    const toggle = page.locator('[data-agent="planner"] .agent-toggle');
    await expect(toggle).toBeVisible();
  });

  test("reasoning clears after resetAgentCards (next message)", async ({ page }) => {
    // Use a stateful route: first call returns reasoning events, second returns simple events
    let callCount = 0;
    const simpleEvents = [
      { type: "agent_status", data: { agent: "coordinator", status: "thinking", message: "분석 중..." } },
      { type: "agent_status", data: { agent: "coordinator", status: "done", message: "general 파악" } },
      { type: "chat_chunk", data: { text: "네, 무엇이든 물어보세요." } },
      { type: "chat_done", data: {} },
    ];

    await page.route("**/chat/sessions", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: MOCK_SESSION_ID,
            created_at: new Date().toISOString(),
            expires_at: new Date(Date.now() + 3_600_000).toISOString(),
            agent_states: {},
            last_plan: null,
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.route("**/chat/sessions/*/messages", async (route) => {
      callCount++;
      const events = callCount === 1 ? REASONING_EVENTS : simpleEvents;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
        body: buildSse(...events),
      });
    });

    await goToChat(page);
    await sendAndWait(page, "도쿄 3일 여행 계획 세워줘");

    await expandAgentPanel(page);
    const reasoningEl = page.locator('[data-agent="planner"] .agent-reasoning');
    await expect(reasoningEl).toBeAttached();

    // Second message — resetAgentCards clears reasoning, simple events have no reasoning
    await sendAndWait(page, "안녕");

    // After reset, the reasoning element should be removed
    await expect(
      page.locator('[data-agent="planner"] .agent-reasoning')
    ).toHaveCount(0);
  });
});

/**
 * E2E Playwright tests for the Chat page (Task #49)
 *
 * Scenarios:
 *   1. Chat page loads with agent panel + plan panel
 *   2. All agents are idle on initial load
 *   3. Agents activate when a message is sent (coordinator thinking → done)
 *   4. Plan builds in dashboard after a create_plan response
 *   5. Agent done with result_count shows the expand toggle
 *
 * Tests 3-5 use Playwright route mocking so the SSE stream is deterministic
 * and does not require a live Gemini API key.
 */

import { test, expect, Page } from "@playwright/test";

const BASE_URL = process.env.QA_BASE_URL || "http://localhost:8000";

const MOCK_SESSION_ID = "e2e-chat-test-session";

/** Encode a list of objects as a complete SSE body string. */
function buildSse(...events: object[]): string {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
}

/**
 * Install Playwright route mocks for the chat session endpoints.
 * POST /chat/sessions  → returns a fixed session ID
 * POST /chat/sessions/{id}/messages → streams the given SSE events
 */
async function mockChatSession(page: Page, sseEvents: object[]): Promise<void> {
  // Mock session creation (POST only; let GET /chat/sessions/{id} fall through)
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

  // Mock the SSE message stream
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Navigate to the chat page via the nav link. */
async function goToChat(page: Page): Promise<void> {
  await page.goto(BASE_URL);
  await page.click('a[data-page="chat"]');
  // Wait for the chat layout to appear
  await expect(page.locator(".chat-layout")).toBeVisible({ timeout: 5_000 });
}

/** Expand the agent panel if it is in compact (collapsed) mode. */
async function expandAgentPanel(page: Page): Promise<void> {
  const compactRow = page.locator("#agent-panel-compact-row");
  if (await compactRow.isVisible()) {
    await compactRow.click();
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Chat Page", () => {
  /**
   * Scenario 1: Page loads with agent panel and plan panel.
   */
  test("chat page loads with agent panel", async ({ page }) => {
    await goToChat(page);

    // Both dashboard panels must be present
    await expect(page.locator("#agent-panel")).toBeVisible();
    await expect(page.locator("#plan-panel")).toBeVisible();

    // Section titles
    await expect(page.locator("#agent-panel")).toContainText("Team Activity");
    await expect(page.locator("#plan-panel")).toContainText("Travel Plan");

    // Welcome message in chat column
    await expect(page.locator("#chat-messages")).toBeVisible();
    await expect(page.locator(".chat-input-bar")).toBeVisible();
  });

  /**
   * Scenario 2: All agents are in idle state on initial load.
   */
  test("agents idle on load", async ({ page }) => {
    await goToChat(page);

    // Expand the compact panel so individual agent cards are accessible
    await expandAgentPanel(page);

    const agentIds = [
      "coordinator",
      "planner",
      "place_scout",
      "hotel_finder",
      "flight_finder",
      "budget_analyst",
      "secretary",
    ];

    // Exactly 7 agent cards
    await expect(page.locator("[data-agent]")).toHaveCount(agentIds.length);

    // Every card must carry the agent-idle class
    for (const id of agentIds) {
      await expect(page.locator(`[data-agent="${id}"]`)).toHaveClass(
        /agent-idle/
      );
    }

    // Each idle card shows the default "대기 중" message
    for (const id of agentIds) {
      await expect(
        page.locator(`[data-agent="${id}"] .agent-message`)
      ).toContainText("대기 중");
    }
  });

  /**
   * Scenario 3: Agents activate when a message is sent.
   * The coordinator is always the first agent to activate.
   */
  test("agents activate on message", async ({ page }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "thinking",
          message: "요청 분석 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "done",
          message: "general 파악",
        },
      },
      { type: "chat_chunk", data: { text: "안녕하세요!" } },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);

    // Send a message
    await page.fill("#chat-input", "안녕하세요");
    await page.click('button:has-text("전송")');

    // Coordinator must reach "done" state
    await expect(page.locator('[data-agent="coordinator"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );

    // Agent panel auto-expands when any agent is active
    await expect(page.locator("#agent-cards")).toBeVisible();

    // Coordinator message reflects the intent
    await expect(
      page.locator('[data-agent="coordinator"] .agent-message')
    ).toContainText("general 파악");
  });

  /**
   * Scenario 4: Plan builds in the dashboard after a create_plan response.
   */
  test("plan builds in dashboard", async ({ page }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "thinking",
          message: "요청 분석 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "done",
          message: "create_plan 파악",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "place_scout",
          status: "working",
          message: "도쿄 장소 검색 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "budget_analyst",
          status: "working",
          message: "예산 배분 계산 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "planner",
          status: "working",
          message: "일정 구성 중...",
        },
      },
      {
        type: "plan_update",
        data: {
          destination: "도쿄",
          start_date: "2026-05-01",
          end_date: "2026-05-04",
          budget: 2_000_000,
          total_estimated_cost: 1_360_000,
          days: [
            {
              day: 1,
              date: "2026-05-01",
              theme: "아사쿠사",
              places: [
                {
                  name: "센소지",
                  category: "문화",
                  address: "도쿄 아사쿠사",
                  estimated_cost: 0,
                  ai_reason: "유명 사원",
                  order: 1,
                },
              ],
              notes: "",
            },
          ],
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "place_scout",
          status: "done",
          message: "5개 장소 찾음",
          result_count: 5,
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "budget_analyst",
          status: "done",
          message: "예산 배분 완료",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "planner",
          status: "done",
          message: "1일 일정 완성!",
        },
      },
      {
        type: "chat_chunk",
        data: { text: "도쿄 1일 여행 계획을 생성했습니다." },
      },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);

    await page.fill("#chat-input", "도쿄 3박4일 맛집 여행 계획 세워줘");
    await page.click('button:has-text("전송")');

    // Plan panel must show the destination
    await expect(page.locator("#plan-panel")).toContainText("도쿄", {
      timeout: 10_000,
    });

    // Dates appear in the plan overview
    await expect(page.locator("#plan-panel")).toContainText("2026-05-01");

    // At least one day card rendered
    await expect(page.locator(".day-card")).toHaveCount(1);

    // Budget progress bar appears
    await expect(page.locator(".progress-bar-bg")).toBeVisible();
  });

  /**
   * Scenario 6: expense_added SSE event renders an expense row in the plan panel.
   */
  test("expense_added event renders expense row in plan panel", async ({ page }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "thinking", message: "요청 분석 중..." },
      },
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "done", message: "add_expense 파악" },
      },
      {
        type: "agent_status",
        data: { agent: "secretary", status: "working", message: "지출 추가 중..." },
      },
      {
        type: "agent_status",
        data: { agent: "secretary", status: "done", message: "지출 추가 완료!" },
      },
      {
        type: "expense_added",
        data: {
          expense: {
            id: 1,
            name: "센소지 입장료",
            amount: 2100,
            category: "activities",
            travel_plan_id: 1,
          },
          budget_summary: {
            plan_id: 1,
            budget: 2_000_000,
            total_spent: 2100,
            remaining: 1_997_900,
            by_category: { activities: 2100 },
            expense_count: 1,
            over_budget: false,
          },
        },
      },
      {
        type: "chat_chunk",
        data: { text: "'센소지 입장료' 2,100원 지출을 추가했습니다. 총 지출: 2,100원" },
      },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);
    await page.fill("#chat-input", "센소지 입장료 2100원 추가해줘");
    await page.click('button:has-text("전송")');

    // expense-section must appear in the plan panel with the new expense row
    await expect(page.locator(".expense-section")).toBeVisible({ timeout: 10_000 });

    const listEl = page.locator(".expense-section .expense-list");
    await expect(listEl).toBeVisible();
    await expect(listEl).toContainText("센소지 입장료");
    await expect(listEl).toContainText("2,100");
  });

  /**
   * Scenario 7: expense_summary SSE event renders a budget breakdown in the plan panel.
   */
  test("expense_summary event renders budget breakdown in plan panel", async ({ page }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "thinking", message: "요청 분석 중..." },
      },
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "done", message: "get_expense_summary 파악" },
      },
      {
        type: "agent_status",
        data: {
          agent: "budget_analyst",
          status: "working",
          message: "지출 집계 중...",
          result_count: 3,
        },
      },
      {
        type: "agent_status",
        data: { agent: "budget_analyst", status: "done", message: "집계 완료" },
      },
      {
        type: "expense_summary",
        data: {
          budget: 2_000_000,
          total_spent: 350_000,
          remaining: 1_650_000,
          over_budget: false,
          expense_count: 3,
          by_category: {
            food: 150_000,
            transport: 100_000,
            activities: 100_000,
          },
        },
      },
      { type: "chat_chunk", data: { text: "지출 현황: 총 350,000원 사용" } },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);
    await page.fill("#chat-input", "지금까지 지출 얼마야?");
    await page.click('button:has-text("전송")');

    // expense-summary-section must appear in the plan panel
    await expect(page.locator(".expense-summary-section")).toBeVisible({ timeout: 10_000 });

    // Total spent and remaining budget must be shown
    await expect(page.locator(".expense-summary-section")).toContainText("350,000");
    await expect(page.locator(".expense-summary-section")).toContainText("1,650,000");

    // Category breakdown rows must be present
    await expect(page.locator(".expense-summary-section")).toContainText("food");
    await expect(page.locator(".expense-summary-section")).toContainText("transport");
  });

  /**
   * Scenario 8: plan_update event after update_plan intent reflects new destination and dates.
   */
  test("plan_update after update_plan reflects new metadata", async ({ page }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "thinking", message: "요청 분석 중..." },
      },
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "done", message: "update_plan 파악" },
      },
      {
        type: "agent_status",
        data: { agent: "secretary", status: "working", message: "여행 계획 수정 중..." },
      },
      // plan_update with new destination and dates (days included so the panel renders)
      {
        type: "plan_update",
        data: {
          id: 5,
          destination: "오사카",
          start_date: "2026-07-10",
          end_date: "2026-07-14",
          budget: 2_500_000,
          total_estimated_cost: 0,
          days: [
            {
              day: 1,
              date: "2026-07-10",
              theme: "도착",
              places: [],
              notes: "",
            },
          ],
        },
      },
      {
        type: "agent_status",
        data: { agent: "secretary", status: "done", message: "수정 완료!" },
      },
      {
        type: "chat_chunk",
        data: {
          text: "여행 계획(#5)이 수정되었습니다. 변경 사항: 목적지: 오사카, 시작일: 2026-07-10, 종료일: 2026-07-14",
        },
      },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);
    await page.fill(
      "#chat-input",
      "계획 5번 목적지를 오사카로 바꾸고 날짜는 7월 10일부터 14일로 변경해줘"
    );
    await page.click('button:has-text("전송")');

    // Plan panel must display the updated destination and dates
    await expect(page.locator("#plan-panel")).toContainText("오사카", { timeout: 10_000 });
    await expect(page.locator("#plan-panel")).toContainText("2026-07-10");
    await expect(page.locator("#plan-panel")).toContainText("2026-07-14");

    // Secretary must reach done state
    await expect(page.locator('[data-agent="secretary"]')).toHaveClass(/agent-done/);
  });

  /**
   * Scenario 5: Agent "done" state with result_count shows the expand toggle.
   */
  test("agent done shows result toggle", async ({ page }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "thinking",
          message: "요청 분석 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "done",
          message: "create_plan 파악",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "place_scout",
          status: "working",
          message: "파리 장소 검색 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "planner",
          status: "working",
          message: "일정 구성 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "budget_analyst",
          status: "working",
          message: "예산 계산 중...",
        },
      },
      {
        type: "plan_update",
        data: {
          destination: "파리",
          start_date: "2026-06-01",
          end_date: "2026-06-03",
          budget: 3_000_000,
          total_estimated_cost: 2_000_000,
          days: [
            {
              day: 1,
              date: "2026-06-01",
              theme: "에펠탑",
              places: [],
              notes: "",
            },
          ],
        },
      },
      // place_scout done WITH result_count → toggle should appear
      {
        type: "agent_status",
        data: {
          agent: "place_scout",
          status: "done",
          message: "12개 장소 찾음",
          result_count: 12,
        },
      },
      // budget_analyst done WITHOUT result_count → no toggle
      {
        type: "agent_status",
        data: {
          agent: "budget_analyst",
          status: "done",
          message: "예산 배분 완료",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "planner",
          status: "done",
          message: "1일 일정 완성!",
        },
      },
      {
        type: "chat_chunk",
        data: { text: "파리 여행 계획을 생성했습니다." },
      },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);

    await page.fill("#chat-input", "파리 여행 계획 세워줘");
    await page.click('button:has-text("전송")');

    // Wait for place_scout to reach done state
    await expect(page.locator('[data-agent="place_scout"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );

    // The expand toggle (▾) must be visible for place_scout (has result_count)
    const placeScoutToggle = page.locator(
      '[data-agent="place_scout"] .agent-toggle'
    );
    await expect(placeScoutToggle).toBeVisible();
    await expect(placeScoutToggle).toContainText("▾");

    // budget_analyst done WITHOUT result_count must NOT show a toggle
    const budgetToggle = page.locator(
      '[data-agent="budget_analyst"] .agent-toggle'
    );
    await expect(budgetToggle).not.toBeVisible();
  });

  /**
   * Scenario 9 (Task #80): expense_list SSE event renders .expense-panel with rows.
   */
  test("expense_list event renders expense panel with rows", async ({ page }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "thinking", message: "요청 분석 중..." },
      },
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "done", message: "list_expenses 파악" },
      },
      {
        type: "agent_status",
        data: { agent: "budget_analyst", status: "working", message: "지출 내역 조회 중..." },
      },
      {
        type: "agent_status",
        data: { agent: "budget_analyst", status: "done", message: "지출 내역 조회 완료" },
      },
      {
        type: "expense_list",
        data: {
          expenses: [
            { id: 1, name: "센소지 입장료", amount: 2100, category: "activities", date: "2026-05-01" },
            { id: 2, name: "라멘 식사", amount: 1500, category: "food", date: "2026-05-01" },
          ],
          plan_id: 1,
        },
      },
      { type: "chat_chunk", data: { text: "지출 내역 2건을 가져왔습니다." } },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);
    await page.fill("#chat-input", "지출 내역 보여줘");
    await page.click('button:has-text("전송")');

    // .expense-panel must appear in the plan panel
    await expect(page.locator(".expense-panel")).toBeVisible({ timeout: 10_000 });

    // Both expense rows must be rendered in the table
    await expect(page.locator(".expense-panel")).toContainText("센소지 입장료");
    await expect(page.locator(".expense-panel")).toContainText("라멘 식사");
    await expect(page.locator(".expense-panel")).toContainText("2,100");
    await expect(page.locator(".expense-panel")).toContainText("1,500");

    // Budget analyst must reach done state
    await expect(page.locator('[data-agent="budget_analyst"]')).toHaveClass(
      /agent-done/
    );
  });

  /**
   * Scenario 10 (Task #80): plan_saved from copy_plan intent shows new plan card in dashboard.
   */
  test("plan_saved from copy_plan shows new plan card in dashboard", async ({ page }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "thinking", message: "요청 분석 중..." },
      },
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "done", message: "copy_plan 파악" },
      },
      {
        type: "agent_status",
        data: { agent: "secretary", status: "working", message: "여행 계획 복사 중..." },
      },
      {
        type: "agent_status",
        data: { agent: "secretary", status: "done", message: "복사 완료!" },
      },
      {
        type: "plan_saved",
        data: {
          message: "'도쿄' 여행 계획이 복사되었습니다.",
          plan_id: 42,
          plan: {
            id: 42,
            destination: "도쿄",
            start_date: "2026-05-01",
            end_date: "2026-05-04",
            budget: 2_000_000,
            status: "draft",
          },
          copied_from: 1,
        },
      },
      {
        type: "chat_chunk",
        data: { text: "'도쿄' 여행 계획(#1)이 복사되어 새 계획(#42)이 생성되었습니다." },
      },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);
    await page.fill("#chat-input", "이 계획 복사해줘");
    await page.click('button:has-text("전송")');

    // A new .plan-saved-card must appear in the plan panel
    await expect(page.locator(".plan-saved-card")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".plan-saved-card")).toContainText("도쿄");

    // Secretary must reach done state
    await expect(page.locator('[data-agent="secretary"]')).toHaveClass(
      /agent-done/
    );
  });
});

// ---------------------------------------------------------------------------
// localStorage session ID persistence (Task #72)
// ---------------------------------------------------------------------------

test.describe("localStorage session ID persistence", () => {
  const VALID_SESSION_ID = "e2e-valid-session";
  const EXPIRED_SESSION_ID = "e2e-expired-session";

  /**
   * Happy-path: localStorage has a valid session ID.
   * GET /chat/sessions/{id} returns 200 → that ID is reused (no POST).
   */
  test("reuses session from localStorage when still valid", async ({
    page,
  }) => {
    // Pre-seed localStorage with a known session ID
    await page.goto(BASE_URL);
    await page.evaluate(
      ([key, id]) => localStorage.setItem(key, id),
      ["chatSessionId", VALID_SESSION_ID]
    );

    // Mock GET /chat/sessions/{id} to return 200 (session is alive)
    let getVerifyHit = false;
    let postCreateHit = false;
    await page.route(`**/chat/sessions/${VALID_SESSION_ID}`, async (route) => {
      if (route.request().method() === "GET") {
        getVerifyHit = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: VALID_SESSION_ID,
            created_at: new Date().toISOString(),
            expires_at: new Date(Date.now() + 3_600_000).toISOString(),
            agent_states: {},
            last_plan: null,
            message_history: [],
          }),
        });
      } else {
        await route.continue();
      }
    });

    // Intercept POST /chat/sessions to detect if a new session was created
    await page.route("**/chat/sessions", async (route) => {
      if (route.request().method() === "POST") {
        postCreateHit = true;
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: "should-not-be-used",
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

    // Navigate to chat page — initChatSession fires on first message
    await page.click('a[data-page="chat"]');
    await expect(page.locator(".chat-layout")).toBeVisible({ timeout: 5_000 });

    // Mock the SSE stream for the first message
    await page.route(
      `**/chat/sessions/${VALID_SESSION_ID}/messages`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: buildSse(
            {
              type: "agent_status",
              data: {
                agent: "coordinator",
                status: "done",
                message: "general 파악",
              },
            },
            { type: "chat_chunk", data: { text: "안녕하세요!" } },
            { type: "chat_done", data: {} }
          ),
        });
      }
    );

    await page.fill("#chat-input", "안녕");
    await page.click('button:has-text("전송")');

    // Wait for chat response
    await expect(page.locator('[data-agent="coordinator"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );

    // GET verify must have been called; POST must NOT have been called
    expect(getVerifyHit).toBe(true);
    expect(postCreateHit).toBe(false);

    // localStorage must still hold the same session ID
    const storedId = await page.evaluate(() =>
      localStorage.getItem("chatSessionId")
    );
    expect(storedId).toBe(VALID_SESSION_ID);
  });

  /**
   * Expired fallback: localStorage has a stale session ID.
   * GET /chat/sessions/{id} returns 404 → a new session is created via POST
   * and the new ID is saved to localStorage.
   */
  test("creates new session when localStorage ID is expired", async ({
    page,
  }) => {
    const NEW_SESSION_ID = "e2e-fresh-session";

    // Pre-seed localStorage with an expired session ID
    await page.goto(BASE_URL);
    await page.evaluate(
      ([key, id]) => localStorage.setItem(key, id),
      ["chatSessionId", EXPIRED_SESSION_ID]
    );

    // Mock GET /chat/sessions/{expired} → 404
    await page.route(
      `**/chat/sessions/${EXPIRED_SESSION_ID}`,
      async (route) => {
        if (route.request().method() === "GET") {
          await route.fulfill({
            status: 404,
            contentType: "application/json",
            body: JSON.stringify({ detail: "Session not found or expired" }),
          });
        } else {
          await route.continue();
        }
      }
    );

    // Mock POST /chat/sessions → returns a fresh session
    await page.route("**/chat/sessions", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: NEW_SESSION_ID,
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

    await page.click('a[data-page="chat"]');
    await expect(page.locator(".chat-layout")).toBeVisible({ timeout: 5_000 });

    // Mock SSE for the new session
    await page.route(
      `**/chat/sessions/${NEW_SESSION_ID}/messages`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: buildSse(
            {
              type: "agent_status",
              data: {
                agent: "coordinator",
                status: "done",
                message: "general 파악",
              },
            },
            { type: "chat_chunk", data: { text: "안녕하세요!" } },
            { type: "chat_done", data: {} }
          ),
        });
      }
    );

    await page.fill("#chat-input", "안녕");
    await page.click('button:has-text("전송")');

    await expect(page.locator('[data-agent="coordinator"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );

    // localStorage must now hold the NEW session ID (expired ID was replaced)
    const storedId = await page.evaluate(() =>
      localStorage.getItem("chatSessionId")
    );
    expect(storedId).toBe(NEW_SESSION_ID);
  });

  /**
   * Missing key: localStorage has no chatSessionId entry.
   * POST /chat/sessions creates a new session and it is saved to localStorage.
   */
  test("saves new session ID to localStorage when no prior session exists", async ({
    page,
  }) => {
    const FRESH_ID = "e2e-brand-new-session";

    await page.goto(BASE_URL);
    // Ensure the key is absent
    await page.evaluate(() => localStorage.removeItem("chatSessionId"));

    await page.route("**/chat/sessions", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: FRESH_ID,
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

    await page.click('a[data-page="chat"]');
    await expect(page.locator(".chat-layout")).toBeVisible({ timeout: 5_000 });

    await page.route(`**/chat/sessions/${FRESH_ID}/messages`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: buildSse(
          {
            type: "agent_status",
            data: {
              agent: "coordinator",
              status: "done",
              message: "general 파악",
            },
          },
          { type: "chat_chunk", data: { text: "안녕하세요!" } },
          { type: "chat_done", data: {} }
        ),
      });
    });

    await page.fill("#chat-input", "안녕");
    await page.click('button:has-text("전송")');

    await expect(page.locator('[data-agent="coordinator"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );

    // localStorage must have been populated with the new session ID
    const storedId = await page.evaluate(() =>
      localStorage.getItem("chatSessionId")
    );
    expect(storedId).toBe(FRESH_ID);
  });
});

// ---------------------------------------------------------------------------
// Weather forecast panel + Conversation reset (Task #83)
// ---------------------------------------------------------------------------

test.describe("Weather forecast panel + Conversation reset (Task #83)", () => {
  /**
   * Scenario 11: weather_data SSE event renders .weather-panel in the dashboard.
   * The panel must show the city name, weather summary, and forecast rows.
   */
  test("weather_data SSE renders weather-panel with city and forecast", async ({
    page,
  }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "thinking", message: "요청 분석 중..." },
      },
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "done", message: "get_weather 파악" },
      },
      {
        type: "weather_data",
        data: {
          destination: "도쿄",
          summary: "맑고 쾌적한 봄 날씨",
          forecast: [
            {
              date: "2026-05-01",
              temperature_high: "22°C",
              temperature_low: "14°C",
              description: "맑음",
            },
            {
              date: "2026-05-02",
              temperature_high: "20°C",
              temperature_low: "12°C",
              description: "구름 조금",
            },
          ],
        },
      },
      { type: "chat_chunk", data: { text: "도쿄 날씨를 조회했습니다." } },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);
    await page.fill("#chat-input", "도쿄 날씨 알려줘");
    await page.click('button:has-text("전송")');

    // .weather-panel must appear in the dashboard column
    await expect(page.locator(".weather-panel")).toBeVisible({ timeout: 10_000 });

    // City name must be displayed
    await expect(page.locator(".weather-panel .weather-city")).toContainText("도쿄");

    // Summary must be displayed
    await expect(page.locator(".weather-panel .weather-summary")).toContainText(
      "맑고 쾌적한 봄 날씨"
    );

    // Two forecast rows must be rendered
    await expect(page.locator(".weather-forecast-row")).toHaveCount(2);

    // First row date and condition must appear
    await expect(page.locator(".weather-panel")).toContainText("2026-05-01");
    await expect(page.locator(".weather-panel")).toContainText("맑음");

    // Second row date and condition must appear
    await expect(page.locator(".weather-panel")).toContainText("2026-05-02");
    await expect(page.locator(".weather-panel")).toContainText("구름 조금");

    // Panel title
    await expect(page.locator(".weather-panel-title")).toContainText("날씨 예보");

    // Coordinator must reach done state
    await expect(page.locator('[data-agent="coordinator"]')).toHaveClass(/agent-done/);
  });

  /**
   * Scenario 12: session_reset SSE event clears all chat bubbles and resets
   * every agent card back to idle state.
   */
  test("session_reset SSE clears chat history and resets agents to idle", async ({
    page,
  }) => {
    const SESSION_ID = "e2e-session-reset-test";
    let sseCallCount = 0;

    // Mock session creation
    await page.route("**/chat/sessions", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: SESSION_ID,
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

    // Mock SSE: first call returns a normal response; second call returns session_reset
    await page.route(
      `**/chat/sessions/${SESSION_ID}/messages`,
      async (route) => {
        sseCallCount++;
        if (sseCallCount === 1) {
          // First message: normal assistant response with coordinator done
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
            body: buildSse(
              {
                type: "agent_status",
                data: {
                  agent: "coordinator",
                  status: "done",
                  message: "general 파악",
                },
              },
              { type: "chat_chunk", data: { text: "안녕하세요! 도쿄 여행을 도와드릴게요." } },
              { type: "chat_done", data: {} }
            ),
          });
        } else {
          // Second message: coordinator done then session_reset
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
            body: buildSse(
              {
                type: "agent_status",
                data: {
                  agent: "coordinator",
                  status: "done",
                  message: "대화 내역 초기화 완료",
                },
              },
              {
                type: "session_reset",
                data: { message: "대화 내역이 초기화되었습니다." },
              },
              { type: "chat_done", data: {} }
            ),
          });
        }
      }
    );

    await goToChat(page);

    // --- First message: populate chat with at least one AI bubble ---
    await page.fill("#chat-input", "도쿄 여행 추천해줘");
    await page.click('button:has-text("전송")');

    // Wait for coordinator to reach done + input re-enabled (stream finished)
    await expect(page.locator('[data-agent="coordinator"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );
    await expect(page.locator("#chat-input")).not.toBeDisabled({
      timeout: 5_000,
    });

    // Verify the AI response from the first message is present
    await expect(page.locator("#chat-messages")).toContainText(
      "도쿄 여행을 도와드릴게요."
    );

    // --- Second message: trigger conversation reset ---
    await page.fill("#chat-input", "대화 초기화해줘");
    await page.click('button:has-text("전송")');

    // Wait for the SSE stream to finish (input re-enabled)
    await expect(page.locator("#chat-input")).not.toBeDisabled({
      timeout: 10_000,
    });

    // session_reset clears #chat-messages (innerHTML = '')
    // — the first message's AI text must no longer be present
    await expect(page.locator("#chat-messages")).not.toContainText(
      "도쿄 여행을 도와드릴게요."
    );

    // All agent cards must be idle (resetAgentCards() was called by _handleSessionReset)
    await expandAgentPanel(page);
    const agentIds = [
      "coordinator",
      "planner",
      "place_scout",
      "hotel_finder",
      "flight_finder",
      "budget_analyst",
      "secretary",
    ];
    for (const id of agentIds) {
      await expect(page.locator(`[data-agent="${id}"]`)).toHaveClass(
        /agent-idle/,
        { timeout: 5_000 }
      );
    }
  });
});

// ---------------------------------------------------------------------------
// SSE reconnect + session state restore (Task #75)
// ---------------------------------------------------------------------------

test.describe("SSE reconnect + session state restore", () => {
  /**
   * Helper: register routes that simulate one failed SSE attempt (no chat_done)
   * followed by a successful one. The failed attempt triggers the retry path
   * in _sendMessageWithRetry which calls restoreSessionState() before re-sending.
   */
  async function mockSseWithRetry(
    page: Page,
    sessionId: string,
    secondAttemptEvents: object[]
  ): Promise<void> {
    let sseCallCount = 0;
    await page.route(
      `**/chat/sessions/${sessionId}/messages`,
      async (route) => {
        sseCallCount++;
        if (sseCallCount === 1) {
          // First attempt: stream ends without chat_done → chatDoneReceived = false → retry
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
            body: buildSse({
              type: "agent_status",
              data: {
                agent: "coordinator",
                status: "thinking",
                message: "분석 중...",
              },
            }),
            // Intentionally no chat_done — causes retry
          });
        } else {
          // Second attempt: complete stream
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
            body: buildSse(...secondAttemptEvents),
          });
        }
      }
    );
  }

  /**
   * Scenario: GET /chat/sessions/{id} returns last_plan + agent_states.
   * After an SSE reconnect, the plan panel and agent cards must be restored.
   */
  test("restores plan panel and agent cards after SSE reconnect", async ({
    page,
  }) => {
    const SESSION_ID = "e2e-restore-plan-session";

    // Pre-seed localStorage
    await page.goto(BASE_URL);
    await page.evaluate(
      ([key, id]) => localStorage.setItem(key, id),
      ["chatSessionId", SESSION_ID]
    );

    // Mock GET /chat/sessions/{id} — always returns agent_states + last_plan
    await page.route(`**/chat/sessions/${SESSION_ID}`, async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: SESSION_ID,
            created_at: new Date().toISOString(),
            expires_at: new Date(Date.now() + 3_600_000).toISOString(),
            agent_states: {
              coordinator: {
                agent: "coordinator",
                status: "done",
                message: "create_plan 파악",
              },
              planner: {
                agent: "planner",
                status: "done",
                message: "일정 완성!",
              },
            },
            last_plan: {
              destination: "교토",
              start_date: "2026-08-01",
              end_date: "2026-08-03",
              budget: 1_200_000,
              total_estimated_cost: 600_000,
              days: [
                {
                  day: 1,
                  date: "2026-08-01",
                  theme: "금각사",
                  places: [
                    {
                      name: "금각사",
                      category: "문화",
                      address: "교토 기타쿠",
                      estimated_cost: 500,
                      ai_reason: "세계 유산 금각사",
                      order: 1,
                    },
                  ],
                  notes: "",
                },
              ],
            },
            message_history: [],
          }),
        });
      } else {
        await route.continue();
      }
    });

    // First SSE fails (no chat_done) → retry → restoreSessionState() → second SSE succeeds
    await mockSseWithRetry(page, SESSION_ID, [
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "done", message: "general 파악" },
      },
      { type: "chat_chunk", data: { text: "안녕하세요!" } },
      { type: "chat_done", data: {} },
    ]);

    await page.click('a[data-page="chat"]');
    await expect(page.locator(".chat-layout")).toBeVisible({ timeout: 5_000 });

    await page.fill("#chat-input", "안녕");
    await page.click('button:has-text("전송")');

    // After reconnect + restore: plan panel shows the saved plan's destination and dates
    // Timeout is generous to accommodate the 1-second exponential backoff before retry
    await expect(page.locator("#plan-panel")).toContainText("교토", {
      timeout: 15_000,
    });
    await expect(page.locator("#plan-panel")).toContainText("2026-08-01");

    // Agent cards must reflect the restored agent_states
    await expect(page.locator('[data-agent="coordinator"]')).toHaveClass(
      /agent-done/,
      { timeout: 15_000 }
    );
    await expect(page.locator('[data-agent="planner"]')).toHaveClass(
      /agent-done/
    );
    await expect(
      page.locator('[data-agent="coordinator"] .agent-message')
    ).toContainText("create_plan 파악");
  });

  /**
   * Scenario: GET /chat/sessions/{id} returns message_history.
   * After an SSE reconnect, historical chat bubbles must be rendered in #chat-messages.
   */
  test("restores chat bubbles from message_history after SSE reconnect", async ({
    page,
  }) => {
    const SESSION_ID = "e2e-restore-history-session";

    await page.goto(BASE_URL);
    await page.evaluate(
      ([key, id]) => localStorage.setItem(key, id),
      ["chatSessionId", SESSION_ID]
    );

    const MESSAGE_HISTORY = [
      { role: "user", content: "도쿄 여행 계획 세워줘" },
      { role: "assistant", content: "도쿄 3박4일 여행 계획을 세워드리겠습니다!" },
      { role: "user", content: "예산은 200만원이야" },
      {
        role: "assistant",
        content: "예산 200만원으로 계획을 수정하겠습니다.",
      },
    ];

    // Mock GET — returns message_history (no plan, no agent_states)
    await page.route(`**/chat/sessions/${SESSION_ID}`, async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: SESSION_ID,
            created_at: new Date().toISOString(),
            expires_at: new Date(Date.now() + 3_600_000).toISOString(),
            agent_states: {},
            last_plan: null,
            message_history: MESSAGE_HISTORY,
          }),
        });
      } else {
        await route.continue();
      }
    });

    // First SSE fails (no chat_done) → retry → restoreSessionState() → bubbles prepended
    await mockSseWithRetry(page, SESSION_ID, [
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "done", message: "general 파악" },
      },
      { type: "chat_chunk", data: { text: "네, 무엇을 도와드릴까요?" } },
      { type: "chat_done", data: {} },
    ]);

    await page.click('a[data-page="chat"]');
    await expect(page.locator(".chat-layout")).toBeVisible({ timeout: 5_000 });

    await page.fill("#chat-input", "안녕");
    await page.click('button:has-text("전송")');

    // After reconnect + restore: historical chat bubbles are prepended with data-restored="1"
    // 4 messages in history → 4 restored bubbles
    await expect(page.locator(".chat-bubble[data-restored]")).toHaveCount(4, {
      timeout: 15_000,
    });

    // Verify content of the restored bubbles
    await expect(page.locator("#chat-messages")).toContainText(
      "도쿄 여행 계획 세워줘"
    );
    await expect(page.locator("#chat-messages")).toContainText(
      "도쿄 3박4일 여행 계획을 세워드리겠습니다!"
    );
    await expect(page.locator("#chat-messages")).toContainText(
      "예산은 200만원이야"
    );
    await expect(page.locator("#chat-messages")).toContainText(
      "예산 200만원으로 계획을 수정하겠습니다."
    );

    // Confirm user vs AI bubble classes
    const userBubbles = page.locator(".chat-bubble.chat-user[data-restored]");
    const aiBubbles = page.locator(".chat-bubble.chat-ai[data-restored]");
    await expect(userBubbles).toHaveCount(2);
    await expect(aiBubbles).toHaveCount(2);
  });
});

// ---------------------------------------------------------------------------
// suggest_improvements + budget auto-refresh (Task #90 / Issue #111)
// ---------------------------------------------------------------------------

test.describe("suggest_improvements + budget auto-refresh (Task #90)", () => {
  /**
   * Scenario A: "any suggestions?" → plan_suggestions SSE event renders the
   * suggestions panel; place_scout and budget_analyst both activate.
   *
   * Done criteria:
   *   - #suggestions-panel is visible in the dashboard column
   *   - .suggestion-card items are rendered with the suggestion text
   *   - place_scout reaches agent-done state
   *   - budget_analyst reaches agent-done state
   */
  test("suggest_improvements: suggestions panel appears with place_scout + budget_analyst active", async ({
    page,
  }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "thinking",
          message: "요청 분석 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "done",
          message: "suggest_improvements 파악",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "place_scout",
          status: "working",
          message: "장소 개선안 분석 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "budget_analyst",
          status: "working",
          message: "예산 최적화 분석 중...",
        },
      },
      {
        type: "plan_suggestions",
        data: {
          suggestions: [
            "아사쿠사 관광 후 스카이트리 방문을 추가하면 동선이 효율적입니다.",
            "2일차에 시부야 스크램블 교차로 야경을 포함해보세요.",
            "예산의 20%를 음식 체험에 배정하면 만족도가 높아집니다.",
          ],
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "place_scout",
          status: "done",
          message: "3개 개선안 준비 완료",
          result_count: 3,
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "budget_analyst",
          status: "done",
          message: "예산 분석 완료",
        },
      },
      {
        type: "chat_chunk",
        data: { text: "여행 계획 개선 제안을 준비했습니다." },
      },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);
    await page.fill("#chat-input", "any suggestions?");
    await page.click('button:has-text("전송")');

    // Suggestions panel must appear in the dashboard
    await expect(page.locator("#suggestions-panel")).toBeVisible({
      timeout: 10_000,
    });

    // Panel title must say "Suggestions"
    await expect(page.locator(".suggestions-title")).toContainText(
      "Suggestions"
    );

    // All three suggestion cards must be rendered
    await expect(page.locator(".suggestion-card")).toHaveCount(3);
    await expect(page.locator("#suggestions-panel")).toContainText("스카이트리");
    await expect(page.locator("#suggestions-panel")).toContainText("시부야");
    await expect(page.locator("#suggestions-panel")).toContainText("예산");

    // place_scout must reach done state
    await expect(page.locator('[data-agent="place_scout"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );

    // budget_analyst must reach done state
    await expect(page.locator('[data-agent="budget_analyst"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );
  });

  // ---------------------------------------------------------------------------
  // share_plan E2E scenarios (Task #92 / Issue #118)
  // ---------------------------------------------------------------------------

  /**
   * Scenario A (share_plan happy path):
   * "이 계획 공유해줘" → plan_shared SSE fires → share URL appears in chat bubble
   * + copy button visible + .plan-share-card in dashboard.
   *
   * Done criteria (from handoff.json):
   *   - plan_shared SSE event received
   *   - share URL rendered as a read-only input in the chat bubble (aria-label="공유 링크")
   *   - copy button ("복사") is visible next to the URL input
   *   - .plan-share-card appears in #plan-panel with the same share URL
   *   - secretary reaches agent-done state
   */
  test("share_plan: share URL and copy button rendered in chat + dashboard", async ({
    page,
  }) => {
    const SHARE_URL = "https://travel-planner.example.com/travel-plans/shared/abc123tok";

    await mockChatSession(page, [
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "thinking",
          message: "요청 분석 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "done",
          message: "share_plan 파악",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "secretary",
          status: "working",
          message: "공유 링크 생성 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "secretary",
          status: "done",
          message: "공유 링크 생성 완료!",
        },
      },
      {
        type: "plan_shared",
        data: {
          plan_id: 7,
          share_token: "abc123tok",
          share_url: SHARE_URL,
        },
      },
      {
        type: "chat_chunk",
        data: { text: `공유 링크가 생성되었습니다: ${SHARE_URL}` },
      },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);
    await page.fill("#chat-input", "이 계획 공유해줘");
    await page.click('button:has-text("전송")');

    // Secretary must reach done state
    await expect(page.locator('[data-agent="secretary"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );

    // Chat bubble must contain the share URL label
    await expect(page.locator("#chat-messages")).toContainText(
      "공유 링크가 생성되었습니다"
    );

    // Read-only URL input in the chat bubble must show the share URL
    const chatUrlInput = page.locator('input[aria-label="공유 링크"]');
    await expect(chatUrlInput).toBeVisible();
    await expect(chatUrlInput).toHaveValue(SHARE_URL);

    // Copy button must be visible next to the URL input in the chat bubble
    // The button is a sibling of the input inside the same chat bubble
    const shareBubble = page
      .locator(".chat-bubble.chat-ai")
      .filter({ hasText: "공유 링크가 생성되었습니다" });
    const copyBtn = shareBubble.locator('button:has-text("복사")');
    await expect(copyBtn).toBeVisible();

    // Dashboard share card must appear in #plan-panel
    await expect(page.locator(".plan-share-card")).toBeVisible({
      timeout: 10_000,
    });

    // Dashboard share card must contain the share URL
    const dashboardInput = page.locator('input[aria-label="공유 링크 (대시보드)"]');
    await expect(dashboardInput).toBeVisible();
    await expect(dashboardInput).toHaveValue(SHARE_URL);

    // Dashboard copy button must also be present
    await expect(page.locator("#share-copy-btn-panel")).toBeVisible();
  });

  /**
   * Scenario B (share_plan error — no plan loaded):
   * "이 계획 공유해줘" when no plan is loaded → secretary reaches agent-error state
   * → error message displayed in chat (no .plan-share-card, no URL input rendered).
   *
   * Done criteria:
   *   - secretary card carries agent-error class
   *   - chat contains the "저장해주세요" error guidance
   *   - .plan-share-card is NOT rendered (no share URL when plan absent)
   */
  test("share_plan error: no plan loaded → secretary error + guidance message", async ({
    page,
  }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "thinking",
          message: "요청 분석 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "done",
          message: "share_plan 파악",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "secretary",
          status: "working",
          message: "공유 링크 생성 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "secretary",
          status: "error",
          message: "저장된 계획이 없습니다",
        },
      },
      {
        type: "chat_chunk",
        data: {
          text: "공유할 여행 계획이 없습니다. 먼저 계획을 저장해주세요.",
        },
      },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);
    await page.fill("#chat-input", "이 계획 공유해줘");
    await page.click('button:has-text("전송")');

    // Secretary must reach error state
    await expect(page.locator('[data-agent="secretary"]')).toHaveClass(
      /agent-error/,
      { timeout: 10_000 }
    );

    // Secretary card message must reflect the error
    await expect(
      page.locator('[data-agent="secretary"] .agent-message')
    ).toContainText("저장된 계획이 없습니다");

    // Chat must show the guidance message
    await expect(page.locator("#chat-messages")).toContainText("저장해주세요", {
      timeout: 10_000,
    });

    // No share card should appear in the dashboard (no plan_shared event was fired)
    await expect(page.locator(".plan-share-card")).not.toBeVisible();

    // No URL input with share-link aria-label should be present
    await expect(page.locator('input[aria-label="공유 링크"]')).not.toBeVisible();
  });

  /**
   * Scenario B: add_expense → budget bar percentage auto-refreshes in plan overview.
   *
   * Flow:
   *   1. First message: plan_update (budget=2,000,000, cost=400,000 → 20%)
   *   2. Second message: expense_added with budget_summary (total_spent=1,360,000 → 68%)
   *
   * Done criteria:
   *   - After first message: .progress-bar-bg is visible; initial pct text reflects 20%
   *   - After second message: #plan-budget-bar width reflects 68%; pct text shows "68.0% 사용"
   */
  test("add_expense: budget bar percentage updates in plan overview", async ({
    page,
  }) => {
    const SESSION_ID = "e2e-budget-refresh-session";
    let sseCallCount = 0;

    // Custom session mock so we can stream two different responses
    await page.route("**/chat/sessions", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: SESSION_ID,
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

    await page.route(
      `**/chat/sessions/${SESSION_ID}/messages`,
      async (route) => {
        sseCallCount++;
        if (sseCallCount === 1) {
          // First message: create plan with initial budget state (20% spent)
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
            body: buildSse(
              {
                type: "agent_status",
                data: {
                  agent: "coordinator",
                  status: "done",
                  message: "create_plan 파악",
                },
              },
              {
                type: "plan_update",
                data: {
                  destination: "도쿄",
                  start_date: "2026-05-01",
                  end_date: "2026-05-04",
                  budget: 2_000_000,
                  total_estimated_cost: 400_000,
                  days: [
                    {
                      day: 1,
                      date: "2026-05-01",
                      theme: "아사쿠사",
                      places: [
                        {
                          name: "센소지",
                          category: "문화",
                          address: "도쿄 아사쿠사",
                          estimated_cost: 0,
                          ai_reason: "유명 사원",
                          order: 1,
                        },
                      ],
                      notes: "",
                    },
                  ],
                },
              },
              {
                type: "chat_chunk",
                data: { text: "도쿄 여행 계획을 생성했습니다." },
              },
              { type: "chat_done", data: {} }
            ),
          });
        } else {
          // Second message: expense_added refreshes budget bar to 68%
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
            body: buildSse(
              {
                type: "agent_status",
                data: {
                  agent: "coordinator",
                  status: "done",
                  message: "add_expense 파악",
                },
              },
              {
                type: "agent_status",
                data: {
                  agent: "secretary",
                  status: "done",
                  message: "지출 추가 완료!",
                },
              },
              {
                type: "expense_added",
                data: {
                  expense: {
                    id: 1,
                    name: "도쿄 투어 패키지",
                    amount: 960_000,
                    category: "activities",
                    travel_plan_id: 1,
                  },
                  budget_summary: {
                    plan_id: 1,
                    budget: 2_000_000,
                    total_spent: 1_360_000,
                    remaining: 640_000,
                    by_category: { activities: 1_360_000 },
                    expense_count: 1,
                    over_budget: false,
                  },
                },
              },
              {
                type: "chat_chunk",
                data: { text: "'도쿄 투어 패키지' 960,000원 지출을 추가했습니다." },
              },
              { type: "chat_done", data: {} }
            ),
          });
        }
      }
    );

    await goToChat(page);

    // --- First message: build the plan (sets initial budget bar to 20%) ---
    await page.fill("#chat-input", "도쿄 3박4일 여행 계획 세워줘");
    await page.click('button:has-text("전송")');

    // Wait for plan to render
    await expect(page.locator("#plan-panel")).toContainText("도쿄", {
      timeout: 10_000,
    });

    // Budget bar must be present after plan_update
    await expect(page.locator(".progress-bar-bg")).toBeVisible();

    // Initial percentage should reflect 20% (400,000 / 2,000,000)
    await expect(page.locator("#plan-panel")).toContainText("20.0% 사용");

    // Wait for input to re-enable before sending next message
    await expect(page.locator("#chat-input")).not.toBeDisabled({
      timeout: 5_000,
    });

    // --- Second message: add_expense refreshes the budget bar to 68% ---
    await page.fill("#chat-input", "도쿄 투어 패키지 96만원 추가해줘");
    await page.click('button:has-text("전송")');

    // Budget bar percentage must update to 68.0% (1,360,000 / 2,000,000)
    await expect(page.locator("#plan-panel")).toContainText("68.0% 사용", {
      timeout: 10_000,
    });

    // The bar element must exist and have a non-zero width
    const bar = page.locator("#plan-budget-bar");
    await expect(bar).toBeVisible();
    const width = await bar.evaluate((el) =>
      parseFloat((el as HTMLElement).style.width)
    );
    expect(width).toBeCloseTo(68.0, 0);
  });
});

// ---------------------------------------------------------------------------
// reorder_days E2E scenarios (Task #93 / Issue #118)
// ---------------------------------------------------------------------------

test.describe("reorder_days E2E (Task #93)", () => {
  /**
   * Helper: build a two-call session mock.
   * - First call → plan_update with 3 days (each has distinct places)
   * - Second call → the provided sseEvents (reorder response)
   */
  async function mockPlanThenReorder(
    page: Page,
    sessionId: string,
    reorderEvents: object[]
  ): Promise<void> {
    // Session creation
    await page.route("**/chat/sessions", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: sessionId,
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

    let callCount = 0;
    await page.route(`**/chat/sessions/${sessionId}/messages`, async (route) => {
      callCount++;
      if (callCount === 1) {
        // First message: create a plan with 3 days
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
          body: buildSse(
            {
              type: "agent_status",
              data: { agent: "coordinator", status: "done", message: "create_plan 파악" },
            },
            {
              type: "plan_update",
              data: {
                destination: "도쿄",
                start_date: "2026-05-01",
                end_date: "2026-05-03",
                budget: 1_500_000,
                total_estimated_cost: 300_000,
                days: [
                  {
                    day: 1,
                    date: "2026-05-01",
                    theme: "아사쿠사",
                    places: [
                      {
                        name: "센소지",
                        category: "문화",
                        address: "도쿄 아사쿠사",
                        estimated_cost: 0,
                        ai_reason: "유명 사원",
                        order: 1,
                      },
                    ],
                    notes: "",
                  },
                  {
                    day: 2,
                    date: "2026-05-02",
                    theme: "시부야",
                    places: [
                      {
                        name: "스크램블 교차로",
                        category: "관광",
                        address: "도쿄 시부야",
                        estimated_cost: 0,
                        ai_reason: "유명 교차로",
                        order: 1,
                      },
                    ],
                    notes: "",
                  },
                  {
                    day: 3,
                    date: "2026-05-03",
                    theme: "신주쿠",
                    places: [
                      {
                        name: "신주쿠 쇼핑",
                        category: "쇼핑",
                        address: "도쿄 신주쿠",
                        estimated_cost: 50_000,
                        ai_reason: "쇼핑 명소",
                        order: 1,
                      },
                    ],
                    notes: "",
                  },
                ],
              },
            },
            { type: "chat_chunk", data: { text: "도쿄 3일 여행 계획을 생성했습니다." } },
            { type: "chat_done", data: {} }
          ),
        });
      } else {
        // Second message: reorder response
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
          body: buildSse(...reorderEvents),
        });
      }
    });
  }

  /**
   * Scenario A (happy path — swap day 1 and day 3):
   * 1. Create a plan with 3 days via plan_update.
   * 2. Send "1일차와 3일차 순서 바꿔줘".
   * 3. SSE emits day_update for day 1 (now has day 3's places) and
   *    day_update for day 3 (now has day 1's places).
   *
   * Done criteria:
   *   - planner reaches agent-done state
   *   - day card for 2026-05-01 shows "신주쿠 쇼핑" (formerly day 3)
   *   - day card for 2026-05-03 shows "센소지" (formerly day 1)
   *   - chat confirms the swap
   */
  test("reorder_days: day_update events swap both day cards in dashboard", async ({
    page,
  }) => {
    const SESSION_ID = "e2e-reorder-days-happy";

    await mockPlanThenReorder(page, SESSION_ID, [
      {
        type: "agent_status",
        data: { agent: "coordinator", status: "done", message: "reorder_days 파악" },
      },
      {
        type: "agent_status",
        data: { agent: "planner", status: "working", message: "일정 순서 변경 중..." },
      },
      // day_update for day 1 — now carries day 3's original places
      {
        type: "day_update",
        data: {
          day_number: 1,
          date: "2026-05-01",
          notes: "",
          transport: null,
          places: [
            {
              name: "신주쿠 쇼핑",
              category: "쇼핑",
              address: "도쿄 신주쿠",
              estimated_cost: 50_000,
              ai_reason: "쇼핑 명소",
              order: 1,
            },
          ],
        },
      },
      // day_update for day 3 — now carries day 1's original places
      {
        type: "day_update",
        data: {
          day_number: 3,
          date: "2026-05-03",
          notes: "",
          transport: null,
          places: [
            {
              name: "센소지",
              category: "문화",
              address: "도쿄 아사쿠사",
              estimated_cost: 0,
              ai_reason: "유명 사원",
              order: 1,
            },
          ],
        },
      },
      {
        type: "agent_status",
        data: { agent: "planner", status: "done", message: "Day 1와 Day 3 교환 완료!" },
      },
      { type: "chat_chunk", data: { text: "Day 1와 Day 3의 일정을 교환했습니다." } },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);

    // --- First message: build the plan ---
    await page.fill("#chat-input", "도쿄 3일 여행 계획 세워줘");
    await page.click('button:has-text("전송")');

    // Wait for plan to render with 3 day cards
    await expect(page.locator("#plan-panel")).toContainText("도쿄", { timeout: 10_000 });
    await expect(page.locator(".day-card")).toHaveCount(3);

    // Day 1 must contain 센소지 before the swap
    await expect(page.locator("#day-2026-05-01")).toContainText("센소지");
    // Day 3 must contain 신주쿠 쇼핑 before the swap
    await expect(page.locator("#day-2026-05-03")).toContainText("신주쿠 쇼핑");

    // Wait for input to re-enable before second message
    await expect(page.locator("#chat-input")).not.toBeDisabled({ timeout: 5_000 });

    // --- Second message: reorder day 1 and day 3 ---
    await page.fill("#chat-input", "1일차와 3일차 순서 바꿔줘");
    await page.click('button:has-text("전송")');

    // Planner must reach done state
    await expect(page.locator('[data-agent="planner"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );
    await expect(
      page.locator('[data-agent="planner"] .agent-message')
    ).toContainText("교환 완료");

    // Day 1 card must now show 신주쿠 쇼핑 (originally day 3)
    await expect(page.locator("#day-2026-05-01 .day-places")).toContainText(
      "신주쿠 쇼핑"
    );

    // Day 3 card must now show 센소지 (originally day 1)
    await expect(page.locator("#day-2026-05-03 .day-places")).toContainText(
      "센소지"
    );

    // Chat must confirm the swap
    await expect(page.locator("#chat-messages")).toContainText(
      "Day 1와 Day 3의 일정을 교환했습니다.",
      { timeout: 10_000 }
    );
  });

  /**
   * Scenario B (out-of-range error):
   * 1. Create a plan with 2 days.
   * 2. Send "1일차와 5일차 바꿔줘" — day 5 does not exist.
   * 3. SSE emits planner error → chat shows error guidance.
   *
   * Done criteria:
   *   - planner reaches agent-error state
   *   - planner card message contains "범위"
   *   - chat shows "없습니다"
   *   - no additional day_update events fired (no cards changed)
   */
  test("reorder_days error: out-of-range day makes planner error with guidance", async ({
    page,
  }) => {
    const SESSION_ID = "e2e-reorder-days-out-of-range";

    // Two-call mock but with only 2 days in the plan
    await page.route("**/chat/sessions", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: SESSION_ID,
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

    let callCount = 0;
    await page.route(`**/chat/sessions/${SESSION_ID}/messages`, async (route) => {
      callCount++;
      if (callCount === 1) {
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
          body: buildSse(
            {
              type: "agent_status",
              data: { agent: "coordinator", status: "done", message: "create_plan 파악" },
            },
            {
              type: "plan_update",
              data: {
                destination: "오사카",
                start_date: "2026-06-01",
                end_date: "2026-06-02",
                budget: 1_000_000,
                total_estimated_cost: 200_000,
                days: [
                  {
                    day: 1,
                    date: "2026-06-01",
                    theme: "도톤보리",
                    places: [
                      {
                        name: "도톤보리 거리",
                        category: "관광",
                        address: "오사카 도톤보리",
                        estimated_cost: 0,
                        ai_reason: "유명 거리",
                        order: 1,
                      },
                    ],
                    notes: "",
                  },
                  {
                    day: 2,
                    date: "2026-06-02",
                    theme: "오사카성",
                    places: [
                      {
                        name: "오사카성",
                        category: "문화",
                        address: "오사카 주오구",
                        estimated_cost: 600,
                        ai_reason: "역사 유적",
                        order: 1,
                      },
                    ],
                    notes: "",
                  },
                ],
              },
            },
            { type: "chat_chunk", data: { text: "오사카 2일 여행 계획을 생성했습니다." } },
            { type: "chat_done", data: {} }
          ),
        });
      } else {
        // Second message: out-of-range reorder attempt
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
          body: buildSse(
            {
              type: "agent_status",
              data: { agent: "coordinator", status: "done", message: "reorder_days 파악" },
            },
            {
              type: "agent_status",
              data: { agent: "planner", status: "working", message: "일정 순서 변경 중..." },
            },
            {
              type: "agent_status",
              data: {
                agent: "planner",
                status: "error",
                message: "Day 5이 범위를 벗어났습니다",
              },
            },
            {
              type: "chat_chunk",
              data: { text: "Day 5은 이 계획에 없습니다 (총 2일)." },
            },
            { type: "chat_done", data: {} }
          ),
        });
      }
    });

    await goToChat(page);

    // --- First message: build the 2-day plan ---
    await page.fill("#chat-input", "오사카 2일 여행 계획 세워줘");
    await page.click('button:has-text("전송")');

    await expect(page.locator("#plan-panel")).toContainText("오사카", { timeout: 10_000 });
    await expect(page.locator(".day-card")).toHaveCount(2);

    // Original day 1 content (도톤보리) must be intact
    await expect(page.locator("#day-2026-06-01")).toContainText("도톤보리 거리");

    // Wait for input to re-enable
    await expect(page.locator("#chat-input")).not.toBeDisabled({ timeout: 5_000 });

    // --- Second message: request out-of-range swap ---
    await page.fill("#chat-input", "1일차와 5일차 바꿔줘");
    await page.click('button:has-text("전송")');

    // Planner must reach error state
    await expect(page.locator('[data-agent="planner"]')).toHaveClass(
      /agent-error/,
      { timeout: 10_000 }
    );

    // Planner error message must mention "범위"
    await expect(
      page.locator('[data-agent="planner"] .agent-message')
    ).toContainText("범위");

    // Chat must show the out-of-range guidance
    await expect(page.locator("#chat-messages")).toContainText("없습니다", {
      timeout: 10_000,
    });

    // Day 1 content must be UNCHANGED (no day_update was fired)
    await expect(page.locator("#day-2026-06-01 .day-places")).toContainText(
      "도톤보리 거리"
    );
  });
});

// ---------------------------------------------------------------------------
// duplicate_day E2E scenarios (Task #100 / Issue #138)
// ---------------------------------------------------------------------------

test.describe("duplicate_day E2E (Task #100)", () => {
  /**
   * Helper: build a two-call session mock.
   * - First call → plan_update with 3 days (each has distinct places)
   * - Second call → the provided sseEvents (duplicate_day response)
   */
  async function mockPlanThenDuplicate(
    page: Page,
    sessionId: string,
    duplicateEvents: object[]
  ): Promise<void> {
    // Session creation
    await page.route("**/chat/sessions", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: sessionId,
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

    let callCount = 0;
    await page.route(
      `**/chat/sessions/${sessionId}/messages`,
      async (route) => {
        callCount++;
        if (callCount === 1) {
          // First message: create a plan with 3 days
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
            body: buildSse(
              {
                type: "agent_status",
                data: {
                  agent: "coordinator",
                  status: "done",
                  message: "create_plan 파악",
                },
              },
              {
                type: "plan_update",
                data: {
                  destination: "도쿄",
                  start_date: "2026-05-01",
                  end_date: "2026-05-03",
                  budget: 1_500_000,
                  total_estimated_cost: 300_000,
                  days: [
                    {
                      day: 1,
                      date: "2026-05-01",
                      theme: "아사쿠사",
                      places: [
                        {
                          name: "센소지",
                          category: "문화",
                          address: "도쿄 아사쿠사",
                          estimated_cost: 0,
                          ai_reason: "유명 사원",
                          order: 1,
                        },
                        {
                          name: "아메요코 시장",
                          category: "food",
                          address: "도쿄 우에노",
                          estimated_cost: 3000,
                          ai_reason: "시장 먹거리",
                          order: 2,
                        },
                      ],
                      notes: "",
                    },
                    {
                      day: 2,
                      date: "2026-05-02",
                      theme: "시부야",
                      places: [
                        {
                          name: "스크램블 교차로",
                          category: "관광",
                          address: "도쿄 시부야",
                          estimated_cost: 0,
                          ai_reason: "유명 교차로",
                          order: 1,
                        },
                      ],
                      notes: "",
                    },
                    {
                      day: 3,
                      date: "2026-05-03",
                      theme: "신주쿠",
                      places: [
                        {
                          name: "신주쿠 쇼핑",
                          category: "쇼핑",
                          address: "도쿄 신주쿠",
                          estimated_cost: 50_000,
                          ai_reason: "쇼핑 명소",
                          order: 1,
                        },
                      ],
                      notes: "",
                    },
                  ],
                },
              },
              {
                type: "chat_chunk",
                data: { text: "도쿄 3일 여행 계획을 생성했습니다." },
              },
              { type: "chat_done", data: {} }
            ),
          });
        } else {
          // Second message: duplicate_day response
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
            body: buildSse(...duplicateEvents),
          });
        }
      }
    );
  }

  /**
   * Scenario A (happy path — copy day 1 to day 3):
   * 1. Create a plan with 3 days via plan_update.
   *    - Day 1 has: 센소지, 아메요코 시장
   *    - Day 3 has: 신주쿠 쇼핑
   * 2. Send "1일차 일정을 3일차에 복사해줘".
   * 3. SSE emits day_update for day 3 (now has day 1's places).
   *    Day 1 is NOT updated (source unchanged).
   *
   * Done criteria:
   *   - planner reaches agent-done state
   *   - day card for 2026-05-03 shows "센소지" and "아메요코 시장" (copied from day 1)
   *   - day card for 2026-05-01 still shows "센소지" (source unchanged)
   *   - chat confirms the copy
   */
  test("duplicate_day: target day updated with source places, source unchanged", async ({
    page,
  }) => {
    const SESSION_ID = "e2e-duplicate-day-happy";

    await mockPlanThenDuplicate(page, SESSION_ID, [
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "done",
          message: "duplicate_day 파악",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "planner",
          status: "working",
          message: "일정 복사 중...",
        },
      },
      // day_update for target day 3 — now carries day 1's places
      {
        type: "day_update",
        data: {
          day_number: 3,
          date: "2026-05-03",
          notes: "",
          transport: null,
          places: [
            {
              name: "센소지",
              category: "문화",
              address: "도쿄 아사쿠사",
              estimated_cost: 0,
              ai_reason: "유명 사원",
              order: 1,
            },
            {
              name: "아메요코 시장",
              category: "food",
              address: "도쿄 우에노",
              estimated_cost: 3000,
              ai_reason: "시장 먹거리",
              order: 2,
            },
          ],
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "planner",
          status: "done",
          message: "Day 1 → Day 3 복사 완료!",
        },
      },
      {
        type: "chat_chunk",
        data: { text: "Day 1의 일정을 Day 3에 복사했습니다." },
      },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);

    // --- First message: build the plan ---
    await page.fill("#chat-input", "도쿄 3일 여행 계획 세워줘");
    await page.click('button:has-text("전송")');

    // Wait for plan to render with 3 day cards
    await expect(page.locator("#plan-panel")).toContainText("도쿄", {
      timeout: 10_000,
    });
    await expect(page.locator(".day-card")).toHaveCount(3);

    // Day 1 must have its original places before the copy
    await expect(page.locator("#day-2026-05-01")).toContainText("센소지");
    await expect(page.locator("#day-2026-05-01")).toContainText("아메요코 시장");

    // Day 3 must have its original place before the copy
    await expect(page.locator("#day-2026-05-03")).toContainText("신주쿠 쇼핑");

    // Wait for input to re-enable before second message
    await expect(page.locator("#chat-input")).not.toBeDisabled({
      timeout: 5_000,
    });

    // --- Second message: duplicate day 1 to day 3 ---
    await page.fill("#chat-input", "1일차 일정을 3일차에 복사해줘");
    await page.click('button:has-text("전송")');

    // Planner must reach done state
    await expect(page.locator('[data-agent="planner"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );
    await expect(
      page.locator('[data-agent="planner"] .agent-message')
    ).toContainText("복사 완료");

    // Day 3 card must now show BOTH copied places from day 1
    await expect(page.locator("#day-2026-05-03 .day-places")).toContainText(
      "센소지"
    );
    await expect(page.locator("#day-2026-05-03 .day-places")).toContainText(
      "아메요코 시장"
    );

    // Day 1 (source) must be UNCHANGED — still shows its original places
    await expect(page.locator("#day-2026-05-01 .day-places")).toContainText(
      "센소지"
    );
    await expect(page.locator("#day-2026-05-01 .day-places")).toContainText(
      "아메요코 시장"
    );

    // Chat must confirm the copy
    await expect(page.locator("#chat-messages")).toContainText(
      "Day 1의 일정을 Day 3에 복사했습니다.",
      { timeout: 10_000 }
    );
  });

  /**
   * Scenario B (error — target day not found):
   * 1. Create a plan with 2 days.
   * 2. Send "1일차를 5일차에 복사해줘" — day 5 does not exist.
   * 3. SSE emits planner error → chat shows guidance.
   *
   * Done criteria:
   *   - planner reaches agent-error state
   *   - planner card message contains "범위"
   *   - chat contains "없습니다"
   *   - no day_update fires (day cards remain unchanged)
   */
  test("duplicate_day error: out-of-range target day makes planner error with guidance", async ({
    page,
  }) => {
    const SESSION_ID = "e2e-duplicate-day-out-of-range";

    // Two-call mock with only 2 days in the plan
    await page.route("**/chat/sessions", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            session_id: SESSION_ID,
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

    let callCount = 0;
    await page.route(
      `**/chat/sessions/${SESSION_ID}/messages`,
      async (route) => {
        callCount++;
        if (callCount === 1) {
          // First message: 2-day plan
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
            body: buildSse(
              {
                type: "agent_status",
                data: {
                  agent: "coordinator",
                  status: "done",
                  message: "create_plan 파악",
                },
              },
              {
                type: "plan_update",
                data: {
                  destination: "오사카",
                  start_date: "2026-06-01",
                  end_date: "2026-06-02",
                  budget: 1_000_000,
                  total_estimated_cost: 100_000,
                  days: [
                    {
                      day: 1,
                      date: "2026-06-01",
                      theme: "도톤보리",
                      places: [
                        {
                          name: "도톤보리 거리",
                          category: "관광",
                          address: "오사카 도톤보리",
                          estimated_cost: 0,
                          ai_reason: "유명 거리",
                          order: 1,
                        },
                      ],
                      notes: "",
                    },
                    {
                      day: 2,
                      date: "2026-06-02",
                      theme: "오사카성",
                      places: [
                        {
                          name: "오사카성",
                          category: "문화",
                          address: "오사카 주오구",
                          estimated_cost: 600,
                          ai_reason: "역사 유적",
                          order: 1,
                        },
                      ],
                      notes: "",
                    },
                  ],
                },
              },
              {
                type: "chat_chunk",
                data: { text: "오사카 2일 여행 계획을 생성했습니다." },
              },
              { type: "chat_done", data: {} }
            ),
          });
        } else {
          // Second message: out-of-range duplicate attempt (day 5 does not exist)
          await route.fulfill({
            status: 200,
            contentType: "text/event-stream",
            headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
            body: buildSse(
              {
                type: "agent_status",
                data: {
                  agent: "coordinator",
                  status: "done",
                  message: "duplicate_day 파악",
                },
              },
              {
                type: "agent_status",
                data: {
                  agent: "planner",
                  status: "working",
                  message: "일정 복사 중...",
                },
              },
              {
                type: "agent_status",
                data: {
                  agent: "planner",
                  status: "error",
                  message: "Day 5이 범위를 벗어났습니다",
                },
              },
              {
                type: "chat_chunk",
                data: { text: "Day 5은 이 계획에 없습니다 (총 2일)." },
              },
              { type: "chat_done", data: {} }
            ),
          });
        }
      }
    );

    await goToChat(page);

    // --- First message: build the 2-day plan ---
    await page.fill("#chat-input", "오사카 2일 여행 계획 세워줘");
    await page.click('button:has-text("전송")');

    await expect(page.locator("#plan-panel")).toContainText("오사카", {
      timeout: 10_000,
    });
    await expect(page.locator(".day-card")).toHaveCount(2);

    // Original day 1 content must be intact before the copy attempt
    await expect(page.locator("#day-2026-06-01")).toContainText("도톤보리 거리");

    // Wait for input to re-enable
    await expect(page.locator("#chat-input")).not.toBeDisabled({
      timeout: 5_000,
    });

    // --- Second message: copy day 1 to non-existent day 5 ---
    await page.fill("#chat-input", "1일차를 5일차에 복사해줘");
    await page.click('button:has-text("전송")');

    // Planner must reach error state
    await expect(page.locator('[data-agent="planner"]')).toHaveClass(
      /agent-error/,
      { timeout: 10_000 }
    );

    // Planner error message must mention "범위" (out-of-range)
    await expect(
      page.locator('[data-agent="planner"] .agent-message')
    ).toContainText("범위");

    // Chat must show the out-of-range guidance
    await expect(page.locator("#chat-messages")).toContainText("없습니다", {
      timeout: 10_000,
    });

    // Day 1 content must be UNCHANGED (no day_update was fired)
    await expect(page.locator("#day-2026-06-01 .day-places")).toContainText(
      "도톤보리 거리"
    );
  });
});

// ---------------------------------------------------------------------------
// message timestamp E2E scenarios (Task #103 / Issue #141)
// ---------------------------------------------------------------------------

test.describe("message timestamp E2E (Task #103)", () => {
  /**
   * Scenario 1: Newly sent chat bubbles display relative timestamps.
   *
   * Done criteria:
   *   - user bubble has .chat-timestamp visible and contains "방금"
   *   - AI bubble (built from chat_chunk stream) has .chat-timestamp visible and contains "방금"
   *   - data-ts attribute is present on both bubbles with a parseable ISO string
   */
  test("new chat bubbles show relative timestamp (방금)", async ({ page }) => {
    await mockChatSession(page, [
      { type: "chat_chunk", data: { text: "안녕하세요!" } },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);

    await page.fill("#chat-input", "안녕");
    await page.click('button:has-text("전송")');

    // Wait for AI reply to complete
    await expect(page.locator(".chat-bubble.chat-ai .chat-text")).toContainText(
      "안녕하세요!",
      { timeout: 10_000 }
    );

    // User bubble: .chat-timestamp visible and contains "방금"
    const userBubble = page.locator(".chat-bubble.chat-user").last();
    await expect(userBubble.locator(".chat-timestamp")).toBeVisible();
    await expect(userBubble.locator(".chat-timestamp")).toContainText("방금");

    // User bubble: data-ts attribute must hold a parseable ISO timestamp
    const userTs = await userBubble.getAttribute("data-ts");
    expect(userTs).toBeTruthy();
    expect(new Date(userTs!).getTime()).toBeGreaterThan(0);

    // AI bubble: .chat-timestamp visible and contains "방금"
    const aiBubble = page.locator(".chat-bubble.chat-ai").last();
    await expect(aiBubble.locator(".chat-timestamp")).toBeVisible();
    await expect(aiBubble.locator(".chat-timestamp")).toContainText("방금");

    // AI bubble: data-ts attribute must hold a parseable ISO timestamp
    const aiTs = await aiBubble.getAttribute("data-ts");
    expect(aiTs).toBeTruthy();
    expect(new Date(aiTs!).getTime()).toBeGreaterThan(0);
  });

  /**
   * Scenario 2: Multiple messages each have independent timestamps.
   *
   * Done criteria:
   *   - After two exchanges, all 4 bubbles (2 user + 2 AI) each have a .chat-timestamp
   */
  test("each chat bubble has its own timestamp element", async ({ page }) => {
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

    let callCount = 0;
    await page.route("**/chat/sessions/*/messages", async (route) => {
      callCount++;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers: { "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
        body: buildSse(
          { type: "chat_chunk", data: { text: `응답 ${callCount}` } },
          { type: "chat_done", data: {} }
        ),
      });
    });

    await goToChat(page);

    // First exchange
    await page.fill("#chat-input", "첫 번째 메시지");
    await page.click('button:has-text("전송")');
    await expect(page.locator(".chat-bubble.chat-ai .chat-text").last()).toContainText(
      "응답 1",
      { timeout: 10_000 }
    );
    await expect(page.locator("#chat-input")).not.toBeDisabled({ timeout: 5_000 });

    // Second exchange
    await page.fill("#chat-input", "두 번째 메시지");
    await page.click('button:has-text("전송")');
    await expect(page.locator(".chat-bubble.chat-ai .chat-text").last()).toContainText(
      "응답 2",
      { timeout: 10_000 }
    );

    // All 4 bubbles (2 user + 2 AI) must each have a .chat-timestamp
    const allBubbles = page.locator(".chat-bubble");
    const count = await allBubbles.count();
    expect(count).toBeGreaterThanOrEqual(4);

    for (let i = 0; i < count; i++) {
      await expect(allBubbles.nth(i).locator(".chat-timestamp")).toBeVisible();
    }
  });

  /**
   * Scenario 3: Restored bubbles (after SSE reconnect via restoreSessionState)
   * carry timestamps derived from message_history.created_at.
   *
   * Done criteria:
   *   - Restored bubbles have [data-restored="1"]
   *   - Each restored bubble shows a .chat-timestamp containing "분 전"
   *     (since created_at is 5 minutes in the past)
   *   - data-ts attribute is set and parseable
   */
  test("restored bubbles carry timestamps after reconnect", async ({ page }) => {
    const historyTs = new Date(Date.now() - 5 * 60 * 1000).toISOString(); // 5 min ago

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
            message_history: [],
          }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock GET session (restore path) with message history including created_at
    await page.route(`**/chat/sessions/${MOCK_SESSION_ID}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: MOCK_SESSION_ID,
          created_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + 3_600_000).toISOString(),
          agent_states: {},
          last_plan: null,
          message_history: [
            { role: "user", content: "이전 메시지", created_at: historyTs },
            { role: "assistant", content: "이전 답변", created_at: historyTs },
          ],
        }),
      });
    });

    // Mock SSE stream (empty — just triggers restore path on chat_done)
    await page.route("**/chat/sessions/*/messages", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: buildSse({ type: "chat_done", data: {} }),
      });
    });

    await goToChat(page);

    // Send a message to initialise the session, then force a restore
    await page.fill("#chat-input", "안녕");
    await page.click('button:has-text("전송")');

    await page.waitForTimeout(1_000);

    // Force restoreSessionState call
    await page.evaluate(() => {
      if (typeof restoreSessionState === "function") restoreSessionState();
    });

    // Restored bubbles must appear
    await expect(page.locator('.chat-bubble[data-restored="1"]')).toHaveCount(
      2,
      { timeout: 5_000 }
    );

    // Each restored bubble must show a timestamp in the past ("분 전")
    const restoredBubbles = page.locator('.chat-bubble[data-restored="1"]');
    for (let i = 0; i < 2; i++) {
      await expect(restoredBubbles.nth(i).locator(".chat-timestamp")).toBeVisible();
      await expect(restoredBubbles.nth(i).locator(".chat-timestamp")).toContainText(
        "분 전"
      );
    }

    // data-ts must also be set on restored bubbles and parseable
    for (let i = 0; i < 2; i++) {
      const ts = await restoredBubbles.nth(i).getAttribute("data-ts");
      expect(ts).toBeTruthy();
      expect(new Date(ts!).getTime()).toBeGreaterThan(0);
    }
  });
});

// ---------------------------------------------------------------------------
// quick_summary intent — E2E Playwright scenarios (Task #106 / Issue #169)
// ---------------------------------------------------------------------------

test.describe("quick_summary intent (Task #106)", () => {
  /**
   * Scenario A: User asks for a trip summary when a plan exists.
   *
   * SSE stream includes:
   *   coordinator thinking → done
   *   planner working → done ("요약 완료")
   *   chat_chunk with destination, date range, and budget percentage
   *
   * Done criteria:
   *   - Chat bubble contains the destination (도쿄)
   *   - Chat bubble contains the date range (2026-05-01 ~ 2026-05-04)
   *   - Chat bubble contains budget info (예산)
   *   - planner agent reaches agent-done state
   */
  test("quick_summary: summary reply contains destination, dates, and budget", async ({
    page,
  }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "thinking",
          message: "요청 분석 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "done",
          message: "quick_summary 파악",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "planner",
          status: "working",
          message: "일정 요약 준비 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "planner",
          status: "done",
          message: "요약 완료",
        },
      },
      {
        type: "chat_chunk",
        data: {
          text: "📋 **현재 여행 계획 요약**\n\n🗺️ 목적지: 도쿄\n📅 일정: 2026-05-01 ~ 2026-05-04 (4일)\n💰 예산: 68% 사용 (1,360,000원 / 2,000,000원)\n\n📍 일별 장소 수:\n  • Day 1: 3곳\n  • Day 2: 4곳\n  • Day 3: 2곳\n  • Day 4: 1곳",
        },
      },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);
    await page.fill("#chat-input", "현재 일정 요약해줘");
    await page.click('button:has-text("전송")');

    // Planner agent must reach done state
    await expect(page.locator('[data-agent="planner"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );

    // Coordinator must reach done state
    await expect(page.locator('[data-agent="coordinator"]')).toHaveClass(
      /agent-done/
    );

    // Chat bubble must contain destination
    await expect(page.locator("#chat-messages")).toContainText("도쿄", {
      timeout: 10_000,
    });

    // Chat bubble must contain date range
    await expect(page.locator("#chat-messages")).toContainText("2026-05-01");
    await expect(page.locator("#chat-messages")).toContainText("2026-05-04");

    // Chat bubble must contain budget information
    await expect(page.locator("#chat-messages")).toContainText("예산");
    await expect(page.locator("#chat-messages")).toContainText("68%");
  });

  /**
   * Scenario B: User asks for a trip summary when NO plan exists yet.
   *
   * SSE stream includes:
   *   coordinator thinking → done
   *   planner working → done ("요약할 계획 없음")
   *   chat_chunk with fallback message
   *
   * Done criteria:
   *   - Chat bubble contains the fallback text about no plan
   *   - planner agent reaches agent-done state
   *   - No crash / no empty bubble
   */
  test("quick_summary: fallback message when no plan exists", async ({
    page,
  }) => {
    await mockChatSession(page, [
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "thinking",
          message: "요청 분석 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "coordinator",
          status: "done",
          message: "quick_summary 파악",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "planner",
          status: "working",
          message: "일정 요약 준비 중...",
        },
      },
      {
        type: "agent_status",
        data: {
          agent: "planner",
          status: "done",
          message: "요약할 계획 없음",
        },
      },
      {
        type: "chat_chunk",
        data: {
          text: "아직 만들어진 여행 계획이 없어요. 여행 계획을 먼저 만들어보세요! (예: '도쿄 3박4일 여행 계획 세워줘')",
        },
      },
      { type: "chat_done", data: {} },
    ]);

    await goToChat(page);
    await page.fill("#chat-input", "일정 요약해줘");
    await page.click('button:has-text("전송")');

    // Planner must reach done state even when no plan exists
    await expect(page.locator('[data-agent="planner"]')).toHaveClass(
      /agent-done/,
      { timeout: 10_000 }
    );

    // Chat must show the fallback message — not empty
    await expect(page.locator("#chat-messages")).toContainText(
      "아직 만들어진 여행 계획이 없어요",
      { timeout: 10_000 }
    );

    // Fallback must mention how to create a plan
    await expect(page.locator("#chat-messages")).toContainText("여행 계획");
  });
});

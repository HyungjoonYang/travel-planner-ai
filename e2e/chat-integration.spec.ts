/**
 * E2E Integration tests for the chat flow.
 *
 * These tests hit the REAL local server — NO SSE route mocking.
 * They verify that the chat actually produces contextual responses,
 * not a hardcoded fallback repeated endlessly.
 *
 * These tests are designed to catch the production bug where the AI
 * always responds with "어떤 여행을 계획하고 계신가요? 목적지, 날짜, 예산을 알려주세요."
 * regardless of user input.
 */

import { test, expect } from "@playwright/test";

const BASE_URL = process.env.QA_BASE_URL || "http://localhost:8000";
const HARDCODED_FALLBACK =
  "어떤 여행을 계획하고 계신가요? 목적지, 날짜, 예산을 알려주세요.";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Navigate to the chat page. */
async function goToChat(page: import("@playwright/test").Page): Promise<void> {
  await page.goto(BASE_URL);
  await page.click('a[data-page="chat"]');
  await expect(page.locator(".chat-layout")).toBeVisible({ timeout: 5_000 });
}

/** Send a chat message and wait for the AI response bubble to appear. */
async function sendMessage(
  page: import("@playwright/test").Page,
  message: string
): Promise<string> {
  await page.fill("#chat-input", message);
  await page.click('button:has-text("전송")');

  // Wait for coordinator to finish (indicates processing is done)
  await expect(page.locator('[data-agent="coordinator"]')).toHaveClass(
    /agent-done/,
    { timeout: 15_000 }
  );

  // Wait for at least one AI bubble to appear after the user's message
  // The last .chat-ai bubble is the response to our message
  await page.waitForSelector(".chat-bubble.chat-ai", { timeout: 15_000 });

  // Small delay to let SSE stream finish
  await page.waitForTimeout(1_000);

  // Get the text of the last AI bubble
  const aiBubbles = page.locator(".chat-bubble.chat-ai");
  const count = await aiBubbles.count();
  const lastBubble = aiBubbles.nth(count - 1);
  return (await lastBubble.textContent()) ?? "";
}

/** Get all AI response texts from the chat. */
async function getAllAiResponses(
  page: import("@playwright/test").Page
): Promise<string[]> {
  const bubbles = page.locator(".chat-bubble.chat-ai");
  const count = await bubbles.count();
  const texts: string[] = [];
  for (let i = 0; i < count; i++) {
    const text = await bubbles.nth(i).textContent();
    if (text) texts.push(text.trim());
  }
  return texts;
}

// ---------------------------------------------------------------------------
// Tests: Real server, no mocks
// ---------------------------------------------------------------------------

test.describe("Chat Integration (real server, no route mocks)", () => {
  test.beforeEach(async ({ page }) => {
    // Clear any stale localStorage session
    await page.goto(BASE_URL);
    await page.evaluate(() => localStorage.removeItem("chatSessionId"));
  });

  /**
   * Core bug test: Send a message and verify the response is NOT
   * the hardcoded fallback.
   */
  test("chat response is not hardcoded fallback", async ({ page }) => {
    await goToChat(page);

    const response = await sendMessage(
      page,
      "5월에 일본 여행 가고 싶어"
    );

    // The response must not be the exact hardcoded fallback
    expect(response.trim()).not.toBe(HARDCODED_FALLBACK);

    // The response should have some content
    expect(response.trim().length).toBeGreaterThan(0);
  });

  /**
   * Broken record test: Send 2 different messages and verify
   * they don't produce the exact same response.
   */
  test("different messages produce different responses", async ({ page }) => {
    await goToChat(page);

    const response1 = await sendMessage(page, "도쿄 여행 추천해줘");

    const response2 = await sendMessage(page, "예산은 200만원이야");

    // Two different messages should not get the exact same answer
    // (especially when one is a destination and the other is a budget)
    expect(response1.trim()).not.toBe(response2.trim());
  });

  /**
   * Context awareness test: If the user provides info (destination + dates),
   * the AI should not ask for the same info again.
   */
  test("AI does not ask for info already provided", async ({ page }) => {
    await goToChat(page);

    const response = await sendMessage(
      page,
      "5월 1일부터 5일까지 일본 오사카로 여행 계획 세워줘. 예산은 150만원이야."
    );

    // User already gave destination, dates, and budget.
    // The AI should NOT respond asking for that exact info.
    expect(response.trim()).not.toBe(HARDCODED_FALLBACK);
  });

  /**
   * Multi-turn coherence: after multiple messages, the chat should
   * still be responsive (not stuck in a loop).
   */
  test("multi-turn chat remains responsive", async ({ page }) => {
    await goToChat(page);

    // Send 3 messages
    await sendMessage(page, "일본 가고 싶어");
    await sendMessage(page, "5월 초에 4박 5일로");
    const response3 = await sendMessage(page, "예산은 100만원 정도");

    const allResponses = await getAllAiResponses(page);

    // Should have at least 3 AI responses (one per message)
    expect(allResponses.length).toBeGreaterThanOrEqual(3);

    // Not all responses should be identical
    const unique = new Set(allResponses.map((r) => r.trim()));
    expect(unique.size).toBeGreaterThan(1);
  });

  /**
   * SSE stream integrity: verify the chat_done event fires
   * and the UI doesn't hang.
   */
  test("chat input re-enables after response completes", async ({ page }) => {
    await goToChat(page);

    await page.fill("#chat-input", "안녕하세요");
    await page.click('button:has-text("전송")');

    // Wait for response to complete
    await page.waitForSelector(".chat-bubble.chat-ai", { timeout: 15_000 });
    await page.waitForTimeout(1_000);

    // Input should be usable again (not disabled/locked)
    const input = page.locator("#chat-input");
    await expect(input).toBeEnabled({ timeout: 5_000 });

    // Should be able to type another message
    await input.fill("다음 메시지");
    await expect(input).toHaveValue("다음 메시지");
  });
});

import { test, expect } from "@playwright/test";

const BASE_URL = process.env.QA_BASE_URL || "http://localhost:8000";

test.describe("Health & Landing", () => {
  test("health endpoint returns ok", async ({ request }) => {
    const res = await request.get(`${BASE_URL}/health`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.status).toBe("ok");
  });

  test("homepage loads with title", async ({ page }) => {
    await page.goto(BASE_URL);
    await expect(page).toHaveTitle(/Travel Planner/);
  });

  test("nav bar has Plans, Search, New Plan links", async ({ page }) => {
    await page.goto(BASE_URL);
    await expect(page.locator("nav")).toContainText("Plans");
    await expect(page.locator("nav")).toContainText("Search");
    await expect(page.locator("nav")).toContainText("New Plan");
  });
});

test.describe("Travel Plan CRUD", () => {
  const planData = {
    destination: `QA-Test-${Date.now()}`,
    start_date: "2026-06-01",
    end_date: "2026-06-04",
    budget: 500000,
    interests: "food,culture",
  };
  let planId: number;

  test("create a new travel plan via API", async ({ request }) => {
    const res = await request.post(`${BASE_URL}/travel-plans`, {
      data: { ...planData, status: "draft" },
    });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.destination).toBe(planData.destination);
    expect(body.id).toBeDefined();
    planId = body.id;
  });

  test("plan appears in the plans list UI", async ({ page }) => {
    // Create plan first
    const res = await page.request.post(`${BASE_URL}/travel-plans`, {
      data: { ...planData, destination: `QA-UI-${Date.now()}`, status: "draft" },
    });
    const plan = await res.json();

    await page.goto(BASE_URL);
    await expect(page.locator("#app")).toContainText(plan.destination);

    // Cleanup
    await page.request.delete(`${BASE_URL}/travel-plans/${plan.id}`);
  });

  test("create plan via UI form", async ({ page }) => {
    await page.goto(BASE_URL);
    await page.click('a[data-page="new-plan"]');

    await page.fill('input[name="destination"]', `QA-Form-${Date.now()}`);
    await page.fill('input[name="start_date"]', "2026-07-01");
    await page.fill('input[name="end_date"]', "2026-07-03");
    await page.fill('input[name="budget"]', "300000");
    await page.fill('input[name="interests"]', "hiking");

    await page.click('button:has-text("Create Plan")');

    // Should redirect to plans list or detail
    await page.waitForTimeout(1000);
    await expect(page.locator("#app")).not.toContainText("Loading");
  });

  test("delete plan via API", async ({ request }) => {
    // Create then delete
    const res = await request.post(`${BASE_URL}/travel-plans`, {
      data: { ...planData, destination: `QA-Delete-${Date.now()}`, status: "draft" },
    });
    const plan = await res.json();

    const delRes = await request.delete(`${BASE_URL}/travel-plans/${plan.id}`);
    expect(delRes.status()).toBe(204);
  });
});

test.describe("Search Page", () => {
  test("search page renders with tabs", async ({ page }) => {
    await page.goto(BASE_URL);
    await page.click('a[data-page="search"]');

    await expect(page.locator("#app")).toContainText("Search");
    await expect(page.locator("#app")).toContainText("Destinations");
    await expect(page.locator("#app")).toContainText("Hotels");
    await expect(page.locator("#app")).toContainText("Flights");
  });

  test("destination search form has required fields", async ({ page }) => {
    await page.goto(BASE_URL);
    await page.click('a[data-page="search"]');

    await expect(page.locator('input[name="destination"], input[placeholder*="destination" i]')).toBeVisible();
    await expect(page.locator('button:has-text("Search")')).toBeVisible();
  });
});

test.describe("Expense Tracking", () => {
  test("add and retrieve expense for a plan", async ({ request }) => {
    // Create plan
    const planRes = await request.post(`${BASE_URL}/travel-plans`, {
      data: {
        destination: `QA-Expense-${Date.now()}`,
        start_date: "2026-08-01",
        end_date: "2026-08-03",
        budget: 1000000,
        interests: "food",
        status: "draft",
      },
    });
    const plan = await planRes.json();

    // Add expense
    const expRes = await request.post(`${BASE_URL}/plans/${plan.id}/expenses`, {
      data: { name: "Test meal", amount: 15000, category: "food", date: "2026-08-01" },
    });
    expect(expRes.ok()).toBeTruthy();

    // Check summary
    const sumRes = await request.get(`${BASE_URL}/plans/${plan.id}/expenses/summary`);
    const summary = await sumRes.json();
    expect(summary.total_spent).toBe(15000);
    expect(summary.remaining).toBe(985000);

    // Cleanup
    await request.delete(`${BASE_URL}/travel-plans/${plan.id}`);
  });
});

test.describe("API Error Handling", () => {
  test("404 for non-existent plan", async ({ request }) => {
    const res = await request.get(`${BASE_URL}/travel-plans/99999`);
    expect(res.status()).toBe(404);
  });

  test("422 for invalid plan data", async ({ request }) => {
    const res = await request.post(`${BASE_URL}/travel-plans`, {
      data: { destination: "", start_date: "invalid", end_date: "invalid", budget: -1 },
    });
    expect(res.status()).toBe(422);
  });

  test("request ID header is present", async ({ request }) => {
    const res = await request.get(`${BASE_URL}/health`);
    expect(res.headers()["x-request-id"]).toBeDefined();
  });
});

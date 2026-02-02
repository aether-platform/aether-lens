const { test, expect } = require("@playwright/test");

test("Login page loads", async ({ page }) => {
  await page.goto("http://localhost:4321");
  // Simple check to see if it loads
  await expect(page).toHaveTitle(/Astro/);
});

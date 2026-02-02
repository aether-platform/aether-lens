from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page


async def layout_check(page: "Page", parameters: dict):
    path_url = parameters.get("path", "/")
    theme = parameters.get("theme", "light")
    if theme == "dark":
        if "?" in path_url:
            path_url += "&theme=dark"
        else:
            path_url += "?theme=dark"
    # The navigation happens in the caller (run_visual_test),
    # but since this is a custom action, we might need to handle navigation
    # OR the caller navigates to 'base' and we do extra steps.
    # However, run_reg_suite passes 'path_url' to run_visual_test.
    # So this specific scenario might be a no-op action if it's just navigation,
    # OR it handles specific layout interactions.
    # For now, let's assume it might scroll to bottom to ensure lazy loads?
    # But for a simple check, pass.
    pass


async def login_scenario(page: "Page", parameters: dict):
    username = parameters.get("username", "admin")
    password = parameters.get("password", "password")

    # We assume we are already on the login page or we need to navigate?
    # run_reg_suite sets path_url='/login'.
    # So page is already there.

    await page.fill("#username", username)
    await page.fill("#password", password)
    await page.click("#login-btn")
    await page.wait_for_load_state("networkidle")


REGISTRY = {
    "layout_check": layout_check,
    "login_scenario": login_scenario,
}

import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from playwright.sync_api import sync_playwright

def run_browser_ui_test():
    url = "http://2026091711175w334chu.conohawing.com/"
    os.makedirs("test_screenshots", exist_ok=True)
    
    print("[1/3] Launching Chrome via Playwright...")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        
        # 1. PC画面テスト
        print("[2/3] Testing Desktop view (1280x800)...")
        page_pc = browser.new_page(viewport={"width": 1280, "height": 800})
        page_pc.goto(url, wait_until="networkidle", timeout=30000)
        pc_path = os.path.abspath("test_screenshots/desktop_view.png")
        page_pc.screenshot(path=pc_path, full_page=False)
        print(f"SUCCESS: Desktop screenshot saved: {pc_path}")
        page_pc.close()
        
        # 2. スマホ縦画面テスト（iPhone 14相当: 390x844）
        print("[3/3] Testing Mobile portrait view (390x844)...")
        page_mobile = browser.new_page(
            viewport={"width": 390, "height": 844},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
            is_mobile=True,
            has_touch=True
        )
        page_mobile.goto(url, wait_until="networkidle", timeout=30000)
        mobile_path = os.path.abspath("test_screenshots/mobile_view.png")
        page_mobile.screenshot(path=mobile_path, full_page=False)
        print(f"SUCCESS: Mobile screenshot saved: {mobile_path}")
        
        # 3. スマホのハンバーガーメニュー開閉テスト
        hamburger = page_mobile.locator("#mobile-menu-btn")
        if hamburger.is_visible():
            print("Clicking hamburger menu button...")
            hamburger.click()
            page_mobile.wait_for_timeout(600)
            drawer_path = os.path.abspath("test_screenshots/mobile_drawer_open.png")
            page_mobile.screenshot(path=drawer_path, full_page=False)
            print(f"SUCCESS: Mobile drawer open screenshot saved: {drawer_path}")
        else:
            print("INFO: Mobile hamburger button not visible or not found.")
            
        page_mobile.close()
        browser.close()

    print("ALL BROWSER AUTOMATED TESTS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    run_browser_ui_test()

import time
import subprocess
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    # Launch Chromium but DON'T close it automatically
    browser = p.chromium.launch(
        headless=False,
        args=["--start-maximized"]
    )
    page = browser.new_page()
    page.goto("https://www.youtube.com/results?search_query=hi+nanna+song")
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    
    # Click first video
    first_video = page.locator("ytd-video-renderer a#thumbnail").first
    first_video.click()
    
    print("Video playing - press Enter to close")
    input()  # Keeps browser open until YOU press Enter
    browser.close()
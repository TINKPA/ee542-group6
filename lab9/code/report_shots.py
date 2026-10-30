"""EE542 Lab 9: capture the report's browser screenshots from the running services.

Needs the chat server on :8000 (run_app.sh) and the document website on :8501
(rag/run_web.sh). Logs in with the local test accounts from
groupchat/test_users.env. Writes PNGs to ../data/screens/.

    uv run --with playwright python report_shots.py
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "data" / "screens"
CHAT = "http://localhost:8000/"
DOCS = "http://localhost:8501/"
DOCS_QUESTION = "How do I set up the license on Linux?"


def test_users():
    env = {}
    for line in (HERE / "groupchat" / "test_users.env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env["TEST_USER_1"], env["TEST_USER_2"], env["TEST_PASSWORD"]


def login(page, user, password):
    page.goto(CHAT)
    page.fill("#username", user)
    page.fill("#password", password)
    page.click("#loginBtn")
    page.wait_for_selector("#chat:not(.hidden)")
    page.wait_for_timeout(1500)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    user1, _, password = test_users()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")  # the installed Google Chrome
        size = dict(viewport={"width": 620, "height": 760}, device_scale_factor=2)

        # Part 1: the conversation scrolled to its start (first bot answers).
        page = browser.new_context(**size).new_page()
        login(page, user1, password)
        page.eval_on_selector("#messages", "el => el.scrollTop = 0")
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "part1_chat.png")

        # Part 3: the document website answering from the ADS collection.
        page = browser.new_context(viewport={"width": 1280, "height": 900},
                                   device_scale_factor=2).new_page()
        page.goto(DOCS)
        box = page.get_by_test_id("stTextInputField")
        box.fill("ads")
        box.press("Enter")
        page.wait_for_timeout(2500)
        chat = page.get_by_placeholder("Ask a question about your documents")
        chat.fill(DOCS_QUESTION)
        chat.press("Enter")
        page.get_by_text("Retrieved context").wait_for(timeout=90_000)
        page.get_by_text("Retrieved context").click()
        page.wait_for_timeout(1500)
        # Show the question, the answer and the first retrieved chunks.
        page.get_by_text(DOCS_QUESTION).last.evaluate("el => el.scrollIntoView({block: 'start'})")
        page.wait_for_timeout(800)
        page.screenshot(path=OUT / "part3_docs_answer.png")
        browser.close()


if __name__ == "__main__":
    main()

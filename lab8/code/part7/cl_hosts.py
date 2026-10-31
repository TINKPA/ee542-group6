"""EE542 Lab 8 Part 7: read node0/node1 ssh hostnames from the CloudLab List View.

Prints `N0=<host>` / `N1=<host>` for kickoff.sh to eval, nothing if the nodes
are not listed yet or the saved login has expired. Attaches to the headed
CloudLab Chrome on port 9223 when it is running, otherwise opens its profile
headless (the login cookie lives in ~/.claude-playwright-profile-cloudlab).
    uv run -q --with playwright python cl_hosts.py
"""
import os
import re
import sys
import urllib.request

from playwright.sync_api import sync_playwright

STATUS = "https://www.cloudlab.us/status.php?uuid=9421a935-d432-11f1-bc80-e4434b2381fc"
PROFILE = os.path.expanduser("~/.claude-playwright-profile-cloudlab")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")
HOST = re.compile(r"^[A-Za-z0-9.-]+$")


def cdp_alive():
    try:
        urllib.request.urlopen("http://localhost:9223/json/version", timeout=3)
        return True
    except OSError:
        return False


def read_list_view(page):
    page.goto(STATUS, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    if "login.php" in page.url:
        print("cl_hosts: CloudLab login expired", file=sys.stderr)
        return {}
    # the List View tab stays hidden until the nodes exist; read its table
    # straight from the DOM instead of clicking it (textContent works hidden)
    page.evaluate("document.querySelector('#show_listview_tab')?.click()")
    page.wait_for_timeout(2000)
    rows = page.evaluate("[...document.querySelectorAll('tr')].map(r => [...r.cells].map(c => c.textContent.trim()).join('\\t'))")
    found = {}
    for r in rows:
        m = re.search(r"(?:^|\t)(node[01])\t.*?ssh\s+(?:-p\s*\d+\s+)?[\w.-]+@([\w.-]+)", r, re.S)
        if m and HOST.match(m.group(2)):
            found[m.group(1)] = m.group(2)
    return found


with sync_playwright() as p:
    if cdp_alive():
        browser = p.chromium.connect_over_cdp("http://localhost:9223")
        page = browser.contexts[0].new_page()
        found = read_list_view(page)
        page.close()
    else:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, channel="chrome", headless=True, user_agent=UA,
            viewport={"width": 1440, "height": 900})
        found = read_list_view(ctx.new_page())
        ctx.close()

if "node0" in found and "node1" in found:
    print(f"N0={found['node0']}")
    print(f"N1={found['node1']}")

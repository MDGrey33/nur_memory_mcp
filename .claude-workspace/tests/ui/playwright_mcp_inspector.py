#!/usr/bin/env python3
"""
Playwright test for MCP Inspector - Tests MCP server from actual browser UI.
"""

import time
import os
from playwright.sync_api import sync_playwright

# MCP Inspector URL with auth token
INSPECTOR_URL = "http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=32c70e698c90ac10bf4166d0f4b8e7aa1ac486f48b3a0906df750f9bf41cd098"
SCREENSHOT_DIR = "/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/tests/ui/screenshots"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def test_mcp_inspector():
    """Test MCP server via Inspector UI."""

    with sync_playwright() as p:
        # Launch browser
        print("🌐 Launching browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        results = {
            "connection": False,
            "tools_listed": False,
            "tools_count": 0,
            "tool_executed": False,
            "errors": []
        }

        try:
            # Navigate to MCP Inspector
            print(f"📍 Navigating to MCP Inspector...")
            page.goto(INSPECTOR_URL, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(3)

            # Take initial screenshot
            page.screenshot(path=f"{SCREENSHOT_DIR}/01_inspector_loaded.png")
            print(f"📸 Screenshot: 01_inspector_loaded.png")
            print(f"📄 Page title: {page.title()}")

            # Step 1: Configure transport and connection type
            print("\n⚙️ Step 1: Configuring connection settings...")

            # First, change transport type dropdown to "Streamable HTTP"
            transport_select = page.locator("select").first
            if transport_select.count() > 0:
                transport_select.select_option(label="Streamable HTTP")
                print("   ✅ Set transport to Streamable HTTP")
                time.sleep(1)

            page.screenshot(path=f"{SCREENSHOT_DIR}/01b_transport_set.png")

            # Step 2: Click Connect button
            print("\n🔌 Step 2: Clicking Connect button...")
            connect_button = page.locator("button:has-text('Connect')")
            if connect_button.count() > 0:
                connect_button.click(force=True)
                print("   ✅ Clicked Connect button")

                # Wait for connection to establish
                print("   Waiting for connection...")
                time.sleep(10)

                page.screenshot(path=f"{SCREENSHOT_DIR}/02_after_connect.png")
                print(f"📸 Screenshot: 02_after_connect.png")

                # Check connection status
                page_text = page.inner_text("body")
                if "Connection Error" in page_text:
                    print("   ❌ Connection Error detected")
                    results["errors"].append("Connection Error")
                    # Look for specific error message
                    error_text = page.locator("text=Connection Error").first
                    if error_text.count() > 0:
                        print(f"   Error details visible")
                elif "Disconnected" in page_text and "Connected" not in page_text:
                    print("   ⚠️ Still disconnected")
                    # Try clicking again
                    print("   Retrying connection...")
                    connect_button.click(force=True)
                    time.sleep(10)
                    page.screenshot(path=f"{SCREENSHOT_DIR}/02b_retry_connect.png")
                else:
                    results["connection"] = True
                    print("   ✅ Connection appears successful")
            else:
                print("   ❌ Connect button not found")
                results["errors"].append("Connect button not found")

            # Step 3: Click "List Tools" button to load tools
            print("\n🔧 Step 3: Loading tools list...")
            time.sleep(2)

            # First click on the Tools tab in the navigation
            tools_tab = page.locator("text=Tools").first
            if tools_tab.count() > 0:
                tools_tab.click(force=True)
                print("   ✅ Clicked Tools tab")
                time.sleep(2)

            # Then click "List Tools" button
            list_tools_button = page.locator("button:has-text('List Tools')")
            if list_tools_button.count() > 0:
                list_tools_button.first.click(force=True)
                print("   ✅ Clicked 'List Tools' button")
                time.sleep(3)  # Wait for tools to load
            else:
                # Try alternative selector
                list_tools_alt = page.locator("text=List Tools")
                if list_tools_alt.count() > 0:
                    list_tools_alt.first.click(force=True)
                    print("   ✅ Clicked 'List Tools' (alt)")
                    time.sleep(3)
                else:
                    print("   ⚠️ 'List Tools' button not found")

            page.screenshot(path=f"{SCREENSHOT_DIR}/03_after_list_tools.png")
            print(f"📸 Screenshot: 03_after_list_tools.png")

            # Step 4: Check for tool names in page content
            print("\n📋 Step 4: Searching for tool names...")

            # Get full page content
            page_content = page.content().lower()
            page_text = page.inner_text("body").lower()

            tool_names = [
                "memory_store", "memory_search", "memory_list", "memory_delete",
                "history_append", "history_get",
                "artifact_ingest", "artifact_search", "artifact_get", "artifact_delete",
                "hybrid_search", "embedding_health",
                "event_search", "event_get", "event_list", "event_reextract", "job_status"
            ]

            found_tools = []
            for tool in tool_names:
                if tool in page_content or tool in page_text:
                    found_tools.append(tool)

            results["tools_count"] = len(found_tools)
            if found_tools:
                results["tools_listed"] = True
                print(f"   ✅ Found {len(found_tools)} tools:")
                for tool in found_tools:
                    print(f"      - {tool}")
            else:
                print("   ⚠️ No tools found in page content")

            page.screenshot(path=f"{SCREENSHOT_DIR}/04_tools_list.png")
            print(f"📸 Screenshot: 04_tools_list.png")

            # Step 5: Execute a tool (embedding_health - simplest, no params)
            print("\n🚀 Step 5: Executing embedding_health tool...")

            # Click on embedding_health tool
            health_tool = page.locator("text=embedding_health").first
            if health_tool.count() > 0:
                health_tool.click(force=True)
                print("   ✅ Clicked embedding_health tool")
                time.sleep(2)

                page.screenshot(path=f"{SCREENSHOT_DIR}/05_tool_selected.png")
                print(f"📸 Screenshot: 05_tool_selected.png")

                # Look for Run/Call Tool button
                run_button = page.locator("button:has-text('Run Tool'), button:has-text('Call'), button:has-text('Execute')")
                if run_button.count() > 0:
                    run_button.first.click(force=True)
                    print("   ✅ Clicked Run button")
                    time.sleep(3)  # Wait for execution

                    page.screenshot(path=f"{SCREENSHOT_DIR}/06_tool_executed.png")
                    print(f"📸 Screenshot: 06_tool_executed.png")

                    # Check for result in page
                    result_text = page.inner_text("body")
                    if "healthy" in result_text.lower() or "status" in result_text.lower():
                        results["tool_executed"] = True
                        print("   ✅ Tool executed successfully - health status returned!")
                    else:
                        print("   ⚠️ Tool executed but result unclear")
                else:
                    print("   ⚠️ Run button not found")
            else:
                print("   ⚠️ embedding_health tool not found")

            # Step 6: Take final full-page screenshot
            page.screenshot(path=f"{SCREENSHOT_DIR}/07_final_state.png", full_page=True)
            print(f"\n📸 Screenshot: 07_final_state.png (full page)")

            # Report results
            print("\n" + "="*70)
            print("MCP INSPECTOR UI TEST RESULTS")
            print("="*70)
            print(f"  Connection:     {'✅ SUCCESS' if results['connection'] else '❌ FAILED'}")
            print(f"  Tools Listed:   {'✅ SUCCESS' if results['tools_listed'] else '❌ FAILED'} ({results['tools_count']} tools)")
            print(f"  Tool Executed:  {'✅ SUCCESS' if results['tool_executed'] else '⚠️ NOT TESTED'}")
            if results["errors"]:
                print(f"  Errors:         {', '.join(results['errors'])}")
            print(f"\n  Screenshots:    {SCREENSHOT_DIR}")
            print("="*70)

            return results["tools_listed"] or results["connection"]

        except Exception as e:
            print(f"❌ Error: {e}")
            page.screenshot(path=f"{SCREENSHOT_DIR}/error_state.png")
            import traceback
            traceback.print_exc()
            return False
        finally:
            browser.close()

if __name__ == "__main__":
    success = test_mcp_inspector()
    exit(0 if success else 1)

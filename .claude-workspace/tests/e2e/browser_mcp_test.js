/**
 * Browser-based MCP User Experience Test
 * Uses Playwright to automate the MCP Inspector and test the full user experience
 */

const { chromium } = require('playwright');

const INSPECTOR_URL = 'http://localhost:6274';
const AUTH_TOKEN = process.env.MCP_AUTH_TOKEN || '';
const SCREENSHOT_DIR = '/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/tests/e2e/screenshots';

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function runTests() {
    console.log('\n========================================');
    console.log('MCP INSPECTOR BROWSER TEST');
    console.log('========================================\n');

    const browser = await chromium.launch({
        headless: true,
        args: ['--no-sandbox']
    });
    const context = await browser.newContext();
    const page = await context.newPage();

    let passed = 0;
    let failed = 0;

    try {
        // Navigate to MCP Inspector
        const url = AUTH_TOKEN
            ? `${INSPECTOR_URL}/?MCP_PROXY_AUTH_TOKEN=${AUTH_TOKEN}`
            : INSPECTOR_URL;

        console.log(`[INFO] Opening MCP Inspector: ${INSPECTOR_URL}`);
        await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
        await sleep(2000);

        // Take initial screenshot
        await page.screenshot({ path: `${SCREENSHOT_DIR}/01_inspector_loaded.png` });
        console.log('[PASS] MCP Inspector loaded');
        passed++;

        // Configure Transport Type to Streamable HTTP
        console.log('[INFO] Configuring transport type...');
        const transportDropdown = await page.locator('select, [role="combobox"]').first();
        if (await transportDropdown.count() > 0) {
            await transportDropdown.click();
            await sleep(500);
            // Try to select Streamable HTTP option
            const streamableOption = await page.locator('text=Streamable HTTP').first();
            if (await streamableOption.count() > 0) {
                await streamableOption.click();
                console.log('[PASS] Changed transport to Streamable HTTP');
                passed++;
            } else {
                // Try selecting by text in the dropdown
                await page.selectOption('select', { label: 'Streamable HTTP' }).catch(() => {});
            }
            await sleep(500);
        }

        // Click Connect button
        console.log('[INFO] Clicking Connect...');
        const connectBtn = await page.locator('button:has-text("Connect")').first();
        if (await connectBtn.count() > 0) {
            await connectBtn.click();
            console.log('[PASS] Connect clicked');
            passed++;
            await sleep(3000); // Wait for connection
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/02_after_connect.png` });

        // Check if connected to server
        const pageContent = await page.content();

        // Wait for connection to establish
        await sleep(2000);

        // Check for connected status
        const connectedStatus = await page.locator('text=Connected').count() > 0;
        if (connectedStatus) {
            console.log('[PASS] Server connected');
            passed++;
        } else {
            console.log('[WARN] Connection status unclear');
        }

        // Click on Tools tab in the top navigation
        console.log('[INFO] Navigating to Tools tab...');
        const toolsTab = await page.locator('button:has-text("Tools"), a:has-text("Tools"), [role="tab"]:has-text("Tools")').first();
        if (await toolsTab.count() > 0) {
            await toolsTab.click();
            await sleep(2000);
            console.log('[PASS] Tools tab clicked');
            passed++;
        } else {
            // Try clicking by text
            await page.click('text=Tools');
            await sleep(2000);
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/03_tools_tab.png` });

        // Click "List Tools" button to load tools
        console.log('[INFO] Loading tools list...');
        const listToolsBtn = await page.locator('button:has-text("List Tools")').first();
        if (await listToolsBtn.count() > 0) {
            await listToolsBtn.click();
            await sleep(2000);
            console.log('[PASS] List Tools clicked');
            passed++;
        }

        await page.screenshot({ path: `${SCREENSHOT_DIR}/04_tools_list.png` });

        // Look for specific tools
        const expectedTools = [
            'memory_store', 'memory_search', 'memory_list', 'memory_delete',
            'history_append', 'history_get',
            'artifact_ingest', 'artifact_search', 'artifact_get', 'artifact_delete',
            'hybrid_search', 'embedding_health'
        ];

        let foundTools = 0;
        for (const tool of expectedTools) {
            const toolElement = await page.locator(`text=${tool}`).first();
            if (await toolElement.count() > 0) {
                foundTools++;
            }
        }

        if (foundTools >= 6) {
            console.log(`[PASS] Found ${foundTools}/12 tools in UI`);
            passed++;
        } else {
            console.log(`[FAIL] Only found ${foundTools}/12 tools`);
            failed++;
        }

        // Try to execute a tool (memory_store)
        const memoryStoreTool = await page.locator('text=memory_store').first();
        if (await memoryStoreTool.count() > 0) {
            await memoryStoreTool.click();
            await sleep(1000);
            await page.screenshot({ path: `${SCREENSHOT_DIR}/04_memory_store_selected.png` });
            console.log('[PASS] memory_store tool selected');
            passed++;

            // Look for input fields and try to fill them
            const contentInput = await page.locator('input[name="content"], textarea[name="content"], [placeholder*="content"]').first();
            if (await contentInput.count() > 0) {
                await contentInput.fill('Test memory from browser automation');
                console.log('[PASS] Content field filled');
                passed++;
            }

            // Look for execute/run button
            const executeBtn = await page.locator('button:has-text("Run"), button:has-text("Execute"), button:has-text("Call")').first();
            if (await executeBtn.count() > 0) {
                await executeBtn.click();
                await sleep(2000);
                await page.screenshot({ path: `${SCREENSHOT_DIR}/05_tool_executed.png` });
                console.log('[PASS] Tool execution attempted');
                passed++;

                // Check for response
                const response = await page.locator('text=mem_').count();
                if (response > 0) {
                    console.log('[PASS] Got memory ID in response');
                    passed++;
                }
            }
        }

        // Final screenshot
        await page.screenshot({ path: `${SCREENSHOT_DIR}/06_final_state.png`, fullPage: true });

    } catch (error) {
        console.log(`[ERROR] ${error.message}`);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/error_state.png` });
        failed++;
    } finally {
        await browser.close();
    }

    // Summary
    console.log('\n========================================');
    console.log('TEST SUMMARY');
    console.log('========================================');
    console.log(`Passed: ${passed}`);
    console.log(`Failed: ${failed}`);
    console.log(`Screenshots saved to: ${SCREENSHOT_DIR}`);
    console.log('========================================\n');

    process.exit(failed > 0 ? 1 : 0);
}

runTests().catch(console.error);

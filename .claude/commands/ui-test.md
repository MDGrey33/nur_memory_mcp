---
description: Run UI testing on existing features - documents tests, then executes if requested
---

# UI Test Command

Run UI testing: **$ARGUMENTS**

## Process

1. **Identify Target** - Parse what to test
2. **Locate Application** - URL or local path
3. **Check Services** - Verify backend/frontend are running
4. **Check Existing Tests** - Review documentation
5. **Create/Update Docs** - Document test cases
6. **Ask User** - Execute tests?
7. **Run Tests** - If confirmed, use Playwright
8. **Report** - Present results
9. **Cleanup** - Stop any auto-started services

## Service Health Check (Step 3)

Before running UI tests, verify required services are running. Auto-start if needed.

### Check and Start Services

```bash
# Check if backend is running (default port 3000)
BACKEND_PORT=${BACKEND_PORT:-3000}
if ! curl -s "http://localhost:$BACKEND_PORT/health" > /dev/null 2>&1; then
  echo "Backend not running. Starting..."
  # Try common start commands
  if [ -f "package.json" ]; then
    npm run dev &
    BACKEND_PID=$!
    echo "Started backend (PID: $BACKEND_PID)"
  fi
  # Wait for startup
  sleep 5
fi

# Check if frontend is running (default port 5173 for Vite, 3001 for CRA)
FRONTEND_PORT=${FRONTEND_PORT:-5173}
if ! curl -s "http://localhost:$FRONTEND_PORT" > /dev/null 2>&1; then
  echo "Frontend not running. Starting..."
  if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
    cd frontend && npm run dev &
    FRONTEND_PID=$!
    echo "Started frontend (PID: $FRONTEND_PID)"
    cd ..
  fi
  sleep 5
fi
```

### Health Check Requirements

Before proceeding with tests:
1. Check if `http://localhost:3000/health` (or configured backend URL) responds
2. Check if frontend dev server is accessible
3. If services are down, attempt auto-start using project's package.json scripts
4. Wait up to 30 seconds for services to become healthy
5. Log clearly: "Starting backend server on port 3000..."
6. Track PIDs of auto-started services for cleanup

### Cleanup on Exit

After tests complete (success or failure):
```bash
# Kill any services we started
if [ -n "$BACKEND_PID" ]; then
  kill $BACKEND_PID 2>/dev/null
  echo "Stopped backend (PID: $BACKEND_PID)"
fi
if [ -n "$FRONTEND_PID" ]; then
  kill $FRONTEND_PID 2>/dev/null
  echo "Stopped frontend (PID: $FRONTEND_PID)"
fi
```

### Skip Auto-Start Option

If user passes `--no-auto-start`, skip service checks and assume services are already running.

## Test Documentation Format

```markdown
# UI Test Cases: [Feature]

## Test Case 1: [Name]
**Priority**: High/Medium/Low
**Steps**:
1. Navigate to [page]
2. [Action]
**Expected**: [Result]
**Accessibility**: [Requirements]
```

## Execution

Use Playwright MCP for browser automation:
- `browser_navigate` - Go to URL
- `browser_click` - Click elements
- `browser_screenshot` - Capture screen

## Results Format

```markdown
## UI Test Results

**Tests**: X passed, Y failed
**Accessibility**: Z violations
**Browsers**: Chrome, Firefox, Safari

### Failed Tests
[Details and screenshots]

### Recommendations
[Fixes needed]
```

## Output Locations

- Docs: .claude-workspace/tests/ui/test-cases/
- Results: .claude-workspace/tests/ui/ui-test-results.json
- Screenshots: .claude-workspace/tests/ui/screenshots/

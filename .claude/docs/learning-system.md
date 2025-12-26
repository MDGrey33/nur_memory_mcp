# Learning System

The Chief of Staff learns from every interaction to improve future deliveries.

## Purpose

- Reduce iteration cycles
- Match user quality expectations
- Apply successful patterns
- Avoid known pitfalls
- Improve pre-delivery filtering

## Data Structure

### patterns.json

```json
{
  "approvals": [
    {
      "task_id": "task-20251207-103045",
      "approved_timestamp": "2025-12-07T10:35:00Z",
      "iterations": 0,
      "confidence_level": 93,
      "first_time_approval": true,
      "task_type": "backend_api",
      "feature_category": "authentication"
    }
  ],
  "success_patterns": [
    {
      "pattern": "User approves when test coverage > 90%",
      "confidence": 95,
      "occurrences": 5,
      "last_seen": "2025-12-07"
    }
  ],
  "feedback_themes": [
    {
      "theme": "pagination_missing",
      "description": "List endpoints need pagination",
      "occurrences": 3,
      "preventive_action": "Always add pagination to list endpoints"
    }
  ],
  "review_criteria": {
    "api_design": {
      "checks": [
        "All list endpoints include pagination",
        "Consistent error response format"
      ],
      "learned_from": ["task-20251207-103045"]
    }
  },
  "metrics": {
    "total_tasks": 10,
    "first_time_approvals": 7,
    "average_iterations": 0.4,
    "average_confidence": 88
  }
}
```

## What Gets Logged

### On Approval

```javascript
{
  task_id: "...",
  iterations: 0,           // How many feedback cycles
  confidence: 93,          // Chief of Staff confidence
  first_time: true,        // Approved without feedback?
  task_type: "...",        // Category of task
  success_factors: [...]   // What made it successful
}
```

### On Feedback

```javascript
{
  task_id: "...",
  feedback: "...",         // User's exact feedback
  category: ["ux", "api"], // Categorized issues
  return_to_phase: "...",  // Where to iterate
  resolution: "..."        // How it was fixed
}
```

## Pattern Detection

### Success Patterns

Identified when:
- First-time approval
- High confidence
- Specific attributes present

Example:
```
Pattern: "API endpoints with OpenAPI docs get approved faster"
Confidence: 87%
Occurrences: 4
```

### Feedback Themes

Identified when:
- Similar feedback repeated
- Same category across tasks
- Pattern in user preferences

Example:
```
Theme: "Error messages too technical"
Action: "Use user-friendly language in all errors"
Occurrences: 3
```

## Applying Learning

### Before Implementation

1. Check patterns.json for relevant patterns
2. Apply success factors proactively
3. Avoid known feedback themes
4. Set expectations based on metrics

### During Review

1. Compare against learned criteria
2. Check for theme violations
3. Adjust confidence based on patterns
4. Add new patterns if applicable

### After Completion

1. Log approval or feedback
2. Update metrics
3. Detect new patterns
4. Refine review criteria

## Key Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| First-time approval rate | % approved without feedback | > 80% |
| Average iterations | Mean feedback cycles | < 0.5 |
| Confidence accuracy | Predicted vs actual | > 85% |
| Time to approval | Build to approve | Decreasing |

## Continuous Improvement

1. **Weekly**: Review metrics trends
2. **Monthly**: Analyze feedback themes
3. **Quarterly**: Update review criteria
4. **Always**: Apply patterns to new tasks

## Implementation Notes

### Storage Location

Learning data is stored in `.claude-workspace/patterns.json` during active tasks and archived with each completed task.

### Adding Approval

```bash
# Update patterns.json with approval record
jq '.approvals += [{"task_id": "'"$TASK_ID"'", "iterations": '$ITERATIONS', "confidence": '$CONFIDENCE'}]' \
  .claude-workspace/patterns.json > tmp.json && mv tmp.json .claude-workspace/patterns.json
```

### Adding Feedback

```bash
# Update patterns.json with feedback record
jq '.feedback_log += [{"task_id": "'"$TASK_ID"'", "feedback": "'"$FEEDBACK"'", "category": "'"$CATEGORY"'"}]' \
  .claude-workspace/patterns.json > tmp.json && mv tmp.json .claude-workspace/patterns.json
```

### Initializing Learning System

```bash
# Create patterns.json if it doesn't exist
if [ ! -f .claude-workspace/patterns.json ]; then
  echo '{"approvals":[],"success_patterns":[],"feedback_themes":[],"metrics":{}}' > .claude-workspace/patterns.json
fi
```

## Privacy

- No sensitive user data stored
- Task content summarized, not stored verbatim
- Patterns are behavioral, not content-based
- Learning data can be cleared anytime

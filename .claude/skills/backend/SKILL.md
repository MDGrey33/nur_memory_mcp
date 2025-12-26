---
name: backend
description: Implement backend functionality including APIs, business logic, database operations, and integrations
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Backend Development Skill

Implement robust, secure, and performant backend systems.

## When to Use

- Implementing API endpoints
- Writing business logic
- Database operations
- External integrations
- Background job processing

## Code Quality Standards

### Structure
- One responsibility per function
- Files < 500 lines
- Clear module boundaries
- Consistent naming conventions

### Error Handling
```javascript
// Good - Explicit error handling
try {
  const result = await riskyOperation();
  return { success: true, data: result };
} catch (error) {
  logger.error('Operation failed', { error, context });
  throw new AppError('OPERATION_FAILED', error.message);
}
```

### Validation
```javascript
// Validate at boundaries
function createUser(input) {
  const validated = validateUserInput(input);
  if (!validated.success) {
    throw new ValidationError(validated.errors);
  }
  return userRepository.create(validated.data);
}
```

### Database Operations
```javascript
// Use transactions for multiple operations
await db.transaction(async (tx) => {
  await tx.users.create(userData);
  await tx.accounts.create(accountData);
  await tx.notifications.create(welcomeNotification);
});
```

## Common Patterns

### Repository Pattern
```javascript
class UserRepository {
  async findById(id) { ... }
  async findByEmail(email) { ... }
  async create(data) { ... }
  async update(id, data) { ... }
  async delete(id) { ... }
}
```

### Service Layer
```javascript
class UserService {
  constructor(userRepo, emailService) {
    this.userRepo = userRepo;
    this.emailService = emailService;
  }

  async registerUser(data) {
    const user = await this.userRepo.create(data);
    await this.emailService.sendWelcome(user);
    return user;
  }
}
```

### Controller/Handler
```javascript
async function createUserHandler(req, res) {
  try {
    const user = await userService.registerUser(req.body);
    res.status(201).json({ data: user });
  } catch (error) {
    handleError(error, res);
  }
}
```

## Performance Guidelines

- Use database indexes for frequent queries
- Implement pagination for list endpoints
- Cache expensive computations
- Use connection pooling
- Batch database operations
- Avoid N+1 queries

## Security Checklist

- [ ] Input validation
- [ ] Parameterized queries
- [ ] Output encoding
- [ ] Authentication required
- [ ] Authorization checked
- [ ] Rate limiting
- [ ] Logging (no sensitive data)

## Testing Requirements

- Unit tests for business logic
- Integration tests for APIs
- Test error scenarios
- Test edge cases
- Coverage > 80%

## Implementation Checklist

- [ ] Follows architecture design
- [ ] Validation implemented
- [ ] Error handling complete
- [ ] Tests written
- [ ] Documentation updated
- [ ] No hardcoded secrets
- [ ] Logging added

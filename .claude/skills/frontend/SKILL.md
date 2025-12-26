---
name: frontend
description: Implement frontend user interfaces with modern frameworks, responsive design, and accessibility standards
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Frontend Development Skill

Build responsive, accessible, and performant user interfaces.

## When to Use

- Implementing UI components
- Building page layouts
- Adding interactivity
- Styling and theming
- Accessibility improvements

## Component Structure

```jsx
// Good component structure
function UserCard({ user, onEdit, onDelete }) {
  const handleEdit = () => onEdit(user.id);
  const handleDelete = () => onDelete(user.id);

  return (
    <article className="user-card" aria-label={`User: ${user.name}`}>
      <header>
        <h3>{user.name}</h3>
        <span>{user.email}</span>
      </header>
      <footer>
        <button onClick={handleEdit} aria-label="Edit user">
          Edit
        </button>
        <button onClick={handleDelete} aria-label="Delete user">
          Delete
        </button>
      </footer>
    </article>
  );
}
```

## State Management

### Local State
```jsx
const [isOpen, setIsOpen] = useState(false);
const [formData, setFormData] = useState(initialData);
```

### Derived State
```jsx
const sortedItems = useMemo(() =>
  items.sort((a, b) => a.name.localeCompare(b.name)),
  [items]
);
```

### Server State
```jsx
const { data, isLoading, error } = useQuery(['users'], fetchUsers);
```

## Accessibility Requirements

- [ ] Semantic HTML elements
- [ ] ARIA labels where needed
- [ ] Keyboard navigation
- [ ] Focus management
- [ ] Color contrast (4.5:1 minimum)
- [ ] Screen reader testing
- [ ] Reduced motion support

## Responsive Design

```css
/* Mobile first */
.container {
  padding: 1rem;
}

/* Tablet */
@media (min-width: 768px) {
  .container {
    padding: 2rem;
  }
}

/* Desktop */
@media (min-width: 1024px) {
  .container {
    max-width: 1200px;
    margin: 0 auto;
  }
}
```

## Performance Best Practices

- Lazy load routes/components
- Optimize images (WebP, srcset)
- Minimize bundle size
- Use code splitting
- Memoize expensive renders
- Debounce input handlers

## Form Handling

```jsx
function LoginForm({ onSubmit }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState({});

  const handleSubmit = (e) => {
    e.preventDefault();
    const validation = validate({ email, password });
    if (!validation.valid) {
      setErrors(validation.errors);
      return;
    }
    onSubmit({ email, password });
  };

  return (
    <form onSubmit={handleSubmit} noValidate>
      <label htmlFor="email">Email</label>
      <input
        id="email"
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        aria-invalid={!!errors.email}
        aria-describedby={errors.email ? 'email-error' : undefined}
      />
      {errors.email && <span id="email-error">{errors.email}</span>}
      {/* ... password field ... */}
      <button type="submit">Login</button>
    </form>
  );
}
```

## Testing

- Unit tests for utilities
- Component tests for UI logic
- Integration tests for flows
- Visual regression tests
- Accessibility audits

## Checklist

- [ ] Responsive on all breakpoints
- [ ] Accessible (WCAG 2.1 AA)
- [ ] Loading states handled
- [ ] Error states handled
- [ ] Forms validated
- [ ] Performance optimized

# CLAUDE.md - AI Assistant Guidelines

This file provides guidance for AI assistants (like Claude) working with this codebase.

## Project Overview

<!-- TODO: Update this section when the project is initialized -->

**Repository**: test
**Status**: New/Empty Repository
**Description**: _Add project description here_

## Repository Structure

```
/
├── CLAUDE.md           # This file - AI assistant guidelines
└── (project files)     # Add structure as project develops
```

<!--
Example structure to update when project is set up:
├── src/                # Source code
│   ├── components/     # UI components
│   ├── services/       # Business logic
│   └── utils/          # Utility functions
├── tests/              # Test files
├── docs/               # Documentation
├── scripts/            # Build/deployment scripts
└── config/             # Configuration files
-->

## Development Setup

<!-- TODO: Add setup instructions when project is initialized -->

```bash
# Clone the repository
git clone <repository-url>
cd test

# Install dependencies (example)
# npm install
# pip install -r requirements.txt

# Run development server (example)
# npm run dev
# python main.py
```

## Common Commands

<!-- TODO: Update with actual commands when project has a build system -->

| Command | Description |
|---------|-------------|
| `npm install` | Install dependencies |
| `npm run dev` | Start development server |
| `npm run build` | Build for production |
| `npm test` | Run tests |
| `npm run lint` | Run linter |

## Code Conventions

### General Guidelines

1. **Code Style**: Follow the established patterns in the codebase
2. **Naming**: Use clear, descriptive names for variables, functions, and files
3. **Comments**: Add comments for complex logic; code should be self-documenting where possible
4. **Testing**: Write tests for new features and bug fixes
5. **Commits**: Use clear, descriptive commit messages

### File Organization

- Keep files focused and single-purpose
- Group related functionality together
- Use consistent naming conventions across the codebase

### Error Handling

- Handle errors gracefully with informative messages
- Log errors appropriately for debugging
- Don't swallow exceptions silently

## Testing

<!-- TODO: Update with actual testing framework and conventions -->

```bash
# Run all tests
npm test

# Run specific test file
npm test -- path/to/test

# Run tests with coverage
npm run test:coverage
```

## Git Workflow

### Branch Naming

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation updates
- `refactor/` - Code refactoring
- `test/` - Test additions/updates

### Commit Messages

Use conventional commit format:
```
type(scope): description

[optional body]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

### Pull Requests

1. Create a feature branch from main
2. Make changes and commit
3. Push branch and create PR
4. Request review
5. Address feedback and merge

## AI Assistant Instructions

### When Working on This Codebase

1. **Read before modifying**: Always read files before making changes
2. **Understand context**: Explore related files to understand patterns
3. **Follow conventions**: Match existing code style and patterns
4. **Test changes**: Run tests after making modifications
5. **Minimal changes**: Make only necessary changes; avoid over-engineering

### Common Tasks

#### Adding a New Feature
1. Understand requirements and existing patterns
2. Create necessary files following project structure
3. Write tests for the new feature
4. Update documentation if needed

#### Fixing a Bug
1. Reproduce the issue to understand it
2. Find the root cause
3. Implement minimal fix
4. Add tests to prevent regression

#### Refactoring
1. Ensure tests exist for code being refactored
2. Make incremental changes
3. Run tests after each change
4. Keep functionality identical

### Things to Avoid

- Don't add unnecessary dependencies
- Don't modify unrelated code
- Don't remove existing functionality without explicit request
- Don't skip testing
- Don't hardcode sensitive values

## Configuration

<!-- TODO: Add configuration details when project is set up -->

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NODE_ENV` | Environment mode | `development` |
| `PORT` | Server port | `3000` |

### Configuration Files

- `.env` - Environment variables (not committed)
- `.env.example` - Example environment file

## Dependencies

<!-- TODO: List key dependencies when project is initialized -->

### Production
- _List key production dependencies_

### Development
- _List key development dependencies_

## Troubleshooting

### Common Issues

#### Issue: _Description_
**Solution**: _Steps to resolve_

<!-- Add common issues and solutions as they arise -->

## Resources

- [Project Documentation](./docs/)
- [Contributing Guidelines](./CONTRIBUTING.md)
- [Changelog](./CHANGELOG.md)

---

_This CLAUDE.md was created as a template. Update sections as the project develops._

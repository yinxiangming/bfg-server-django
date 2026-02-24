# BFG2 Module Development Guide

This manual provides standardized guidance for initializing, developing APIs, and E2E testing for new modules (e.g., `social`, `clearance`, `transport`, `wms`), based on best practices from `bfg2/bfg`.

---

## 1. Seed Data
Seed data is used to quickly populate sample data in development and testing environments. Each module should implement its seeding logic in `apps/<module>/seed_data.py`.

### Implementation Standards
- **Function Signature**: `seed_data(workspace, stdout=None, style=None, **context)`
- **Core Logic**:
    - Use `get_or_create` to ensure idempotency.
    - Retrieve dependent objects (e.g., `customers`, `warehouses`) from the `context`.
    - Return a `dict` containing newly created objects to be used by subsequent modules.
- **Cleanup Logic**: Implement a `clear_data()` function to delete data in reverse order of foreign key dependencies.

### Code Template
```python
def seed_data(workspace, stdout=None, style=None, **context):
    if stdout:
        stdout.write(style.SUCCESS('Creating <module> data...'))
    
    # Retrieve dependencies
    warehouses = context.get('warehouses', [])
    
    # Create module-specific data
    obj, created = MyModel.objects.get_or_create(
        workspace=workspace,
        code='EXAMPLE-01',
        defaults={'name': 'Example Item'}
    )
    
    return {'my_items': [obj]}

def clear_data():
    MyModel.objects.all().delete()
```

---

## 2. API Design (REST Framework)
Follow the unified DRF pattern to ensure seamless integration with frontend components (e.g., Vuexy tables).

### Directory Structure
- `apps/<module>/serializers.py`: Defines data serialization logic.
- `apps/<module>/views.py`: Defines ViewSets.
- `apps/<module>/urls.py`: Registers routes.

### Best Practices
- **Layered Serialization**:
    - `ListSerializer`: Concise view for list page displays.
    - `DetailSerializer`: Full view including details of related objects.
- **Foreign Key Handling**: Use string references for models in the `Meta` class (e.g., `'delivery.Package'`) to avoid circular imports.
- **Route Registration**: Use `DefaultRouter` and include them in `config/urls.py`.

---

## 3. E2E Testing (Playwright)
Test code should be located within the `tests/` directory of each module: `apps/<module>/tests/`.

### Core Patterns
- **Page Object Model (POM)**: Create Page classes for each major module page (located at `@pages/admin/`).
- **DataSeeder**: Utilize the existing `DataSeeder` tool to pre-populate test data via API, rather than manually through the UI.
- **Assertions**: Prioritize semantic assertions like `expect(page.getByText(...)).toBeVisible()`.

### Test Case Structure
```typescript
import { test, expect } from '@fixtures/auth'
import { MyModulePage } from '@pages/admin/MyModulePage'

test.describe('Admin - My Module', () => {
  test('should create a new entry', async ({ adminPage }) => {
    const page = new MyModulePage(adminPage)
    await page.gotoList()
    await page.create({ name: 'Test Entry' })
    await page.expectRowVisible('Test Entry')
  })
})
```

---

## 4. Post-Implementation Checklist
1. [ ] **Create seed_data.py**: Implement basic data simulation.
2. [ ] **Pass E2E Tests**: Ensure core business flows are covered and passing in the `apps/<module>/tests/` directory.

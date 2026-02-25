.PHONY: help test-bfg2-e2e test-bfg2-all test-bfg install-bfg2 install reset-migrations

help:
	@echo "Available commands:"
	@echo "  make test-bfg2-e2e     - Run BFG2 end-to-end tests"
	@echo "  make test-bfg2-all     - Run all BFG2 tests"
	@echo "  make test-bfg          - Run BFG tests"
	@echo "  make install-bfg2      - Install BFG2 dependencies"
	@echo "  make install           - Install all project dependencies"
	@echo "  make reset-migrations  - Remove bfg migrations, reset DB, makemigrations, migrate"

# BFG2 E2E Tests
test-bfg2-e2e:
	@echo "Running BFG2 E2E tests..."
	cd bfg2 && source venv/bin/activate && python -m pytest tests/e2e/ -v --tb=short -m e2e

# BFG2 All Tests
test-bfg2-all:
	@echo "Running all BFG2 tests..."
	cd bfg2 && source venv/bin/activate && python -m pytest tests/ -v --tb=short

# BFG Tests
test-bfg:
	@echo "Running BFG tests..."
	cd bfg && python manage.py test

# Install BFG2 dependencies
install-bfg2:
	@echo "Installing BFG2 dependencies..."
	cd bfg2 && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Install project dependencies
install:
	@echo "Installing project dependencies..."
	pip install -r requirements.txt

# Reset migrations: clear bfg migration files, drop tables, regenerate and migrate
reset-migrations:
	@echo "Removing bfg migration files (keeping __init__.py)..."
	@find bfg2/bfg/*/migrations -name '*.py' ! -name '__init__.py' -delete
	@echo "Running makemigrations..."
	python manage.py makemigrations
	@echo "Dropping all tables..."
	python manage.py reset_db --no-input
	@echo "Running migrate..."
	python manage.py migrate
	@echo "Done. Run 'python manage.py init' to create workspace and admin."


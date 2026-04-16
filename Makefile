PYTHON := uv run python
NEO4J_CONTAINER := workforce-neo4j
NEO4J_USER := neo4j
NEO4J_PASSWORD := password
NEO4J_PLATFORM ?= linux/amd64

.DEFAULT_GOAL := help


.PHONY: help sync run test lint format lock export-requirements clean dev-up \
	neo4j-prepare neo4j-up neo4j-stop neo4j-start neo4j-down neo4j-load neo4j-shell neo4j-status neo4j-logs


help: ## Show all make targets and their purposes
	@echo "Available targets:"
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_.-]+:.*## / {printf "  make %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## Install/update dependencies from pyproject.toml
	uv sync

run: ## Run Streamlit app
	uv run streamlit run app.py

test: ## Run tests
	uv run pytest

lint: ## Run Ruff lint checks
	uv run ruff check .

format: ## Run Ruff formatter
	uv run ruff format .

lock: ## Create/update uv.lock
	uv lock

export-requirements: ## Export dependencies to requirements.txt
	uv export --format requirements-txt --output-file requirements.txt

clean: ## Remove common local build/cache artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov __pycache__
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

dev-up: ## Sync Python deps, start Neo4j, and load data
	$(MAKE) sync
	$(MAKE) neo4j-up
	$(MAKE) neo4j-load
	@echo "Dev environment ready. Run 'make run' to start Streamlit."

neo4j-prepare: ## Create Neo4j directories and copy JSON files
	mkdir -p neo4j/data neo4j/logs neo4j/plugins neo4j/import
	cp data/*.json neo4j/import/

neo4j-up: neo4j-prepare ## Start Neo4j container with APOC enabled
	docker run -d \
		--platform $(NEO4J_PLATFORM) \
		--name $(NEO4J_CONTAINER) \
		-p 7474:7474 -p 7687:7687 \
		-e NEO4J_AUTH=$(NEO4J_USER)/$(NEO4J_PASSWORD) \
		-e NEO4J_PLUGINS='["apoc"]' \
		-e NEO4J_apoc_export_file_enabled=true \
		-e NEO4J_apoc_import_file_enabled=true \
		-e NEO4J_apoc_import_file_use__neo4j__config=true \
		-v "$$PWD/neo4j/data:/data" \
		-v "$$PWD/neo4j/logs:/logs" \
		-v "$$PWD/neo4j/plugins:/plugins" \
		-v "$$PWD/neo4j/import:/import" \
		neo4j:5

neo4j-stop: ## Stop Neo4j container
	docker stop $(NEO4J_CONTAINER)

neo4j-start: ## Start existing Neo4j container
	docker start $(NEO4J_CONTAINER)

neo4j-down: ## Remove Neo4j container
	docker rm -f $(NEO4J_CONTAINER)

neo4j-load: ## Load JSON data into Neo4j from queries/load-data.cypher
	docker exec -i $(NEO4J_CONTAINER) cypher-shell -u $(NEO4J_USER) -p $(NEO4J_PASSWORD) < queries/load-data.cypher

neo4j-shell: ## Open cypher-shell in running Neo4j container
	docker exec -it $(NEO4J_CONTAINER) cypher-shell -u $(NEO4J_USER) -p $(NEO4J_PASSWORD)

neo4j-status: ## Check Neo4j container/database availability
	docker ps --filter "name=$(NEO4J_CONTAINER)" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
	docker exec -i $(NEO4J_CONTAINER) cypher-shell -u $(NEO4J_USER) -p $(NEO4J_PASSWORD) "RETURN 'ok' AS status;"

neo4j-logs: ## Tail Neo4j container logs
	docker logs -f $(NEO4J_CONTAINER)

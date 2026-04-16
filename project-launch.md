# Project Launch Guide

## Prerequisites

- Python 3.14
- `uv` installed (https://docs.astral.sh/uv/getting-started/installation/)
- Access to a Neo4j instance with challenge data loaded

## Quick Start

### 1. Setup Environment Variables

Create a `.env` file in the project root:

```dotenv
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=neo4j
```

### 2. Sync Dependencies

```bash
make sync
```

This runs `uv sync` and installs runtime + dev dependencies from `pyproject.toml`.

### 3. Start Neo4j (if using Docker)

```bash
make neo4j-up
```

Neo4j Browser: http://localhost:7474

### 4. Load Challenge Data

```bash
make neo4j-load
```

### 5. Run the Application

```bash
make run
```

This starts Streamlit and serves the app from `app.py`.

## One-Command Bootstrap

For a complete setup from scratch:

```bash
make dev-up
```

This will:
- run `make sync`
- run `make neo4j-up`
- run `make neo4j-load`

Then start the app with:

```bash
make run
```

## Useful Development Commands

```bash
make help
make lint
make format
make test
make lock
make clean
```

## Troubleshooting

- If `make sync` fails on Python version, confirm `python3.14` is installed and available.
- If app startup fails with Neo4j auth/connection errors, verify values in `.env`.
- If there are no results in charts, ensure your Neo4j database has loaded nodes and relationships.
- If `make neo4j-up` fails with `tls: bad record MAC` on macOS, run `make neo4j-up NEO4J_PLATFORM=linux/amd64`.

## Neo4j Management Commands

```bash
make neo4j-stop      # Stop Neo4j
make neo4j-start     # Start Neo4j
make neo4j-shell     # Access Neo4j shell
make neo4j-logs      # View Neo4j logs
make neo4j-down      # Remove Neo4j container
```

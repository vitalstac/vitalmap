# Catalogue stack (database, STAC API, tiler)

## Requirements
- Docker Desktop (Windows) or Docker Engine (Linux)

## Start
1. Copy `.env.example` to `.env` and adjust the values.
2. Run `docker compose up -d`.
3. Check: `docker compose ps` (all services Up, database healthy).

## Services and ports (development)
| Service | Port | URL |
|---|---|---|
| database (PostgreSQL + pgstac) | 5439 | – |
| stac-api (stac-fastapi-pgstac) | 8080 | http://127.0.0.1:8080/ (docs: /api.html) |
| tiler (titiler-pgstac) | 8082 | http://127.0.0.1:8082/ |

## Configuration
All settings are in `.env`. Never commit `.env`.

## Stop and reset
- Stop: `docker compose down`
- Reset all data: `docker compose down -v`

## Tests
See the test steps in [link to PR or docs].

## Troubleshooting
- API not reachable: `docker compose logs stac-api`
- Port already in use: change the left side of the port mapping.
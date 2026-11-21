# Spike R5: Collection filter on health fields

**Date:** 21.11.2026 | **Versions:** pgstac 0.9.11, stac-fastapi-pgstac 7.1.0
**Question:** Do CQL2 filters in Collection Search work on top-level fields (health:*) of collections?
**Method:** Three test collections with health:status, health:representation_type and health:update_frequency; seven requests (script: R5-collection-filter.py, raw output: R5-collection-filter-output.txt).

## Result
All seven tests passed: equality (cql2-text and cql2-json), AND, OR, no match, free text (q) and IN.
The queryables endpoint lists only id, datetime and geometry, so filtering works without registering the fields.

## Decision
Option A: filters work directly on collection fields. The fallback via Item properties is not needed.

## Impact
- Risk R5: resolved (mitigation not needed).
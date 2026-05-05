# RepoForge Build Plan

## Implemented MVP

- FastAPI/Jinja application shell with enterprise-style navigation and dashboard
- SQLAlchemy models for bundles, repo sources, uploads, keys, build jobs, artifacts, settings, and package requests
- SQLite persistence with Alembic scaffold for future migrations
- Bundle and repository source CRUD
- Custom RPM upload, safe filename handling, upload size enforcement, RPM metadata inspection, and dependency-resolution toggle
- Build job runner with logs, status transitions, manifest/checksum/artifact records
- ISO assembly through existing builder services using `createrepo_c`, `gpg`, and `xorriso`/`genisoimage`
- GPG key generation and public-key download
- System dependency inspection page
- Docker and Compose deployment
- Generated RepoForge logo and dashboard visual under `app/static/img`

## Next Hardening Targets

- Move background builds to RQ/Celery for multi-worker production deployments
- Add explicit Python package request screens and `pip download` build integration
- Add per-bundle repo-source sync modes instead of using curated package mode by default
- Add Alembic generated migration revisions once the schema stabilizes
- Add authentication and secret storage for authenticated Docker EE or internal repo sources
- Add integration tests with fixture RPMs and a disposable local Yum repository

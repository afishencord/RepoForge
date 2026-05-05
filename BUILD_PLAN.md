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

## Builder Deployment Strategy

RepoForge should keep Docker Compose as the preferred application deployment method, but repository sync should support multiple builder execution modes. This is especially important for Enterprise Linux content because Red Hat CDN repositories require valid entitlement. A Fedora-based container cannot reliably mirror RHEL repositories unless entitlement is deliberately made available to that container by the host environment.

Planned builder modes:

- `container`: Default Compose mode for public repos, generic Yum/DNF repos, Docker CE, Fedora, PyPI, custom RPMs, metadata generation, signing, and ISO assembly.
- `local-rhel`: Run RepoForge directly on an entitled RHEL host and use the host's `subscription-manager`, `/etc/yum.repos.d/redhat.repo`, and enabled Red Hat repo IDs.
- `remote-rhel-worker`: Keep the web UI containerized, but dispatch build jobs to one or more entitled RHEL builder hosts over SSH or a lightweight worker agent.
- `external-mirror`: Consume already-mirrored enterprise repositories from Satellite, Pulp, Katello, Nexus, Artifactory, or another internal mirror service.

RHEL-specific validation should happen before a build starts:

- Verify `subscription-manager` exists when a Red Hat CDN source is selected.
- Run `subscription-manager identity` or equivalent entitlement check.
- Run `subscription-manager repos --list-enabled`.
- Confirm the requested Red Hat repo ID appears in `dnf repolist --enabled`.
- Fail early with an actionable message when entitlement is missing.

The UI should make the boundary explicit:

```text
Red Hat CDN repositories require an entitled RHEL builder host or an internal mirror.
Container-only builds can assemble public and generic repositories, but cannot sync
RHEL CDN content unless valid entitlement is available inside the builder environment.
```

This keeps Compose useful for the main application while giving enterprise users a compliant path for licensed Red Hat content.

## TODO

- Add builder mode selection and validation for `container`, `local-rhel`, `remote-rhel-worker`, and `external-mirror`.
- Implement RHEL entitlement checks and clearer Red Hat source error messages.
- Add remote worker execution for entitled RHEL builders.
- Add first-class external mirror support for Satellite/Pulp/Katello-style repositories.
- Add support for non-RPM repositories such as Ubuntu/Apt.
- Integrate Python wheelhouse libraries into ISO output.

## Next Hardening Targets

- Move background builds to RQ/Celery for multi-worker production deployments
- Add explicit Python package request screens and `pip download` build integration
- Add per-bundle repo-source sync modes instead of using curated package mode by default
- Add Alembic generated migration revisions once the schema stabilizes
- Add authentication and secret storage for authenticated Docker EE or internal repo sources
- Add integration tests with fixture RPMs and a disposable local Yum repository

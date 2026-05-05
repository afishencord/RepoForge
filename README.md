# RepoForge

RepoForge is a web application for building signed, ISO-based package bundles for air-gapped Linux environments. It gives systems engineers a single operations console for defining repository sources, selecting packages, uploading custom RPMs, generating signing keys, tracking build jobs, and publishing mountable ISO artifacts that can be carried into disconnected environments.

The application is built with FastAPI, SQLAlchemy, SQLite, Jinja2 templates, and a Fedora-based builder container that includes the Linux repository tooling needed for DNF/Yum repository assembly.

## Features

- Bundle management for target OS, version, architecture, package lists, dependency behavior, signing mode, and ISO output settings
- Repository source management for Red Hat, Fedora, Docker CE, Docker EE, Python/PyPI-style sources, and generic Yum/DNF repositories
- UI-defined repository support using generated temporary `.repo` files during DNF and `reposync` operations
- Custom RPM upload workflow with safe filename handling, upload size enforcement, RPM metadata extraction, dependency visibility, and per-RPM dependency resolution toggles
- Build job tracking with status, stage, live logs, errors, warnings, and artifact links
- Runtime GPG key generation, public key export, and custom repository metadata signing
- Repository metadata generation with `createrepo_c`
- Manifest, package list, checksum, install script, validation script, repo file, README, and ISO-root generation
- Data ISO creation with `xorriso` or `genisoimage`
- Artifact registry with ISO download and manifest access
- System page for builder dependency inspection
- Docker Compose deployment with persisted local storage

## Preferred Deployment

Docker Compose is the preferred way to run RepoForge because the container image includes the system tools expected by the builder pipeline.

```bash
docker compose up --build -d
```

Open:

```text
http://127.0.0.1:8000
```

Useful Compose commands:

```bash
docker compose ps
docker compose logs -f repoforge
docker compose exec repoforge pytest -q
docker compose down
```

Application state and generated outputs are persisted under `./storage` through the Compose bind mount.

## Storage Layout

RepoForge keeps runtime state in `storage/`. The directory structure is tracked in Git with `.gitkeep` files, but generated contents are ignored.

```text
storage/
├── uploads/       Uploaded RPMs
├── workspaces/    Per-bundle build workspaces, logs, repo trees, manifests
├── artifacts/     Generated ISO files and build outputs
├── keys/          Runtime GPG key material
└── repoforge.db   SQLite database
```

Private GPG key material stays under `storage/keys` and is never copied into generated ISO artifacts.

## Builder Tooling

The Compose image installs the tools used by the build services:

```text
dnf
dnf-plugins-core
dnf-utils
reposync
createrepo_c
rpm
rpm-build
gpg
xorriso
genisoimage
isoinfo
pip
```

The System page reports whether required tooling is available. Configuration pages remain usable even when a host is missing tools, but builds require the builder toolchain.

## Typical Workflow

1. Define repository sources such as Red Hat, Docker CE, Fedora, or a generic Yum/DNF repository.
2. Create a bundle with a target OS, architecture, package list, and output settings.
3. Attach the repository sources needed by the bundle.
4. Upload custom RPMs when an internal package repository is required.
5. Generate or select a GPG key for custom repository signing.
6. Start a build job from the bundle detail page.
7. Watch build logs and inspect failures or warnings.
8. Download the generated ISO artifact and manifest.
9. Mount the ISO on the disconnected host and run the included helper scripts.

## Repository Sync Notes

Use an explicit RHEL path when running inside the builder container. For example:

```text
https://example.repoforge.com/linux/rhel/9/x86_64/stable
```

Using `$releasever` inside a builder will resolve to the host OS release value rather than the target OS version.

## Project Structure

```text
app/
├── main.py                 FastAPI app, routes, UI handlers, build job entrypoint
├── config.py               Runtime paths and environment-backed settings
├── database.py             SQLAlchemy engine/session setup
├── models/                 Database models for bundles, repos, uploads, keys, jobs, artifacts
├── services/               Builder and system service modules
├── templates/              Jinja2 enterprise console UI
├── static/                 CSS, JavaScript, generated logo and dashboard imagery
├── api/                    Reserved package for future JSON API routers
├── schemas/                Reserved package for Pydantic schemas
└── workers/                Reserved package for external worker integration

migrations/                 Alembic configuration and migration scaffold
scripts/                    Local helper scripts
storage/                    Runtime state and generated output, ignored except structure
tests/                      Service-level regression tests
Dockerfile                  Fedora builder image
docker-compose.yml          Preferred deployment definition
```

## Design Considerations

RepoForge is designed as an infrastructure management console, not a consumer-style web app. The UI favors dense tables, compact forms, status badges, build logs, and audit-friendly detail pages.

The build pipeline is intentionally filesystem-oriented. Each bundle gets an isolated workspace under `storage/workspaces/{bundle_id}` and build artifacts are written under `storage/artifacts/{bundle_id}`. This makes failed builds inspectable and keeps generated ISO contents easy to reason about.

Subprocess execution is centralized in `app/services/runner.py`. Commands are executed without shell strings, secrets are masked in logs, timeouts are enforced, and command failures are surfaced as structured build errors.

Repository sources created in the UI are materialized as temporary `.repo` files for the duration of DNF and `reposync` commands. This allows RepoForge to work with baseurl-backed sources such as Docker CE without requiring the repository to be preconfigured in the container.

Security boundaries are part of the product design:

- Uploaded filenames are normalized before storage.
- Uploaded RPMs are kept in bundle-scoped storage paths.
- Private GPG keys are not exported to ISO roots.
- Repository credentials are represented separately from display fields.
- Build logs mask common secret-bearing command arguments.
- Generated storage contents, logs, databases, keys, and ISOs are ignored by Git.

## Local Development

Local development is useful for route and UI work, but full builds are easiest through Docker Compose.

```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Or:

```bash
bash scripts/dev.sh
```

Run tests:

```bash
pytest -q
```

The app creates storage directories and the SQLite database on startup.

# RepoForge

RepoForge is a web application for building signed, ISO-based package bundles for air-gapped Linux environments. It gives systems engineers a single operations console for defining repository sources, selecting packages, uploading custom RPMs, generating signing keys, tracking build jobs, and publishing mountable ISO artifacts that can be carried into disconnected environments.

The application is built with FastAPI, SQLAlchemy, PostgreSQL, Jinja2 templates, and host-installed Linux repository tooling for DNF/Yum repository assembly.

## Features

- Bundle management for target OS, version, architecture, package lists, dependency behavior, signing mode, and ISO output settings
- Repository source management for Red Hat, Fedora, Docker CE, Docker EE, Python/PyPI-style sources, and generic Yum/DNF repositories
- UI-defined repository support using generated temporary `.repo` files during DNF and `reposync` operations
- Custom RPM upload workflow with safe filename handling, upload size enforcement, RPM metadata extraction, dependency visibility, and per-RPM dependency resolution toggles
- Build job tracking with status, stage, live logs, errors, warnings, and artifact links
- Builder mode selection for container, local RHEL, remote RHEL worker, and external mirror execution
- Red Hat entitlement validation before Red Hat CDN builds are queued
- Runtime GPG key generation, public key export, and custom repository metadata signing
- Repository metadata generation with `createrepo_c`
- Manifest, package list, checksum, install script, validation script, repo file, README, and ISO-root generation
- Data ISO creation with `xorriso` or `genisoimage`
- Artifact registry with ISO download and manifest access
- System page for builder dependency inspection
- Local authentication with Admin, Operator, and User roles plus configurable LDAP and Microsoft ADFS OIDC sign-in
- RHEL systemd deployment with a single RepoForge executable and a PostgreSQL container

## Preferred Deployment

RepoForge is intended to run on a RHEL 8 or RHEL 9 server as a local executable managed by systemd. Docker Compose is used only for PostgreSQL.

```bash
docker compose up -d
docker compose ps
```

Create the service user and runtime directories:

```bash
sudo useradd --system --home-dir /var/lib/repoforge --shell /sbin/nologin repoforge
sudo install -d -o repoforge -g repoforge -m 0750 /etc/repoforge /var/lib/repoforge
sudo install -d -o repoforge -g repoforge -m 0750 /var/lib/repoforge/uploads /var/lib/repoforge/workspaces /var/lib/repoforge/artifacts /var/lib/repoforge/keys /var/lib/repoforge/tls
```

Build or copy the binary to the server. Build on RHEL 8 x86_64, or an equivalent oldest-supported build host, for the broadest RHEL 8/9 compatibility:

```bash
bash scripts/build-binary.sh
sudo install -m 0755 dist/repoforge /usr/local/bin/repoforge
```

Install the environment and systemd unit templates:

```bash
sudo install -m 0640 -o root -g repoforge packaging/repoforge.env /etc/repoforge/repoforge.env
sudo install -m 0644 packaging/repoforge.service /etc/systemd/system/repoforge.service
```

Edit `/etc/repoforge/repoforge.env` before first start. At minimum, set strong values for `REPOFORGE_SECRET_KEY`, `REPOFORGE_AUTH_SECRET_KEY`, and the PostgreSQL password. The default database URL format is:

```text
REPOFORGE_DATABASE_URL=postgresql+psycopg://repoforge:repoforge-change-me@127.0.0.1:5432/repoforge
```

Run migrations and start the service:

```bash
sudo -u repoforge /usr/local/bin/repoforge migrate
sudo systemctl daemon-reload
sudo systemctl enable --now repoforge
sudo systemctl status repoforge
```

RepoForge listens on standard HTTP and HTTPS ports. The systemd unit grants only `CAP_NET_BIND_SERVICE` so the `repoforge` user can bind ports 80 and 443 without running the service as root. If no certificate exists and `REPOFORGE_TLS_AUTO_GENERATE=1`, RepoForge generates a self-signed certificate under `/var/lib/repoforge/tls`.

If RepoForge is behind a TLS-terminating reverse proxy or mesh gateway, point the upstream at RepoForge's HTTP port and send the standard `X-Forwarded-Proto: https` and `X-Forwarded-Host` headers. Direct HTTP traffic still redirects to HTTPS, while forwarded HTTPS traffic from trusted proxy IPs is served by the application. Localhost proxies are trusted by default; set `REPOFORGE_TRUSTED_PROXY_IPS` to a comma-separated list, or `*` only on a private backend network.

Open:

```text
https://127.0.0.1
```

Default local admin credentials:

```text
Username: admin
Password: admin123!
```

Useful database container commands:

```bash
docker compose ps
docker compose logs -f postgres
docker compose down
```

Application state and generated outputs are persisted under `/var/lib/repoforge`. PostgreSQL data is persisted in the `repoforge-postgres-data` Docker volume.

## Storage Layout

RepoForge keeps production runtime state in `/var/lib/repoforge/`. The repository still tracks a local `storage/` scaffold for tests and development, but generated contents are ignored.

```text
var/lib/repoforge/
├── uploads/       Uploaded RPMs
├── workspaces/    Per-bundle build workspaces, logs, repo trees, manifests
├── artifacts/     Generated ISO files and build outputs
├── keys/          Runtime GPG key material
└── tls/           TLS certificate and key
```

Private GPG key material stays under `/var/lib/repoforge/keys` and is never copied into generated ISO artifacts.

## Builder Tooling

Install the tools used by the build services on the RHEL host:

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

The System page reports whether required tooling is available. Configuration pages remain usable when a host is missing tools, but local builds require the builder toolchain and any required Red Hat entitlement to be available to the service environment.

## Builder Deployment Modes

RepoForge defaults to `container` mode for historical Compose-based builds, but RHEL systemd deployments should use `local-rhel` for host execution. Red Hat CDN repositories require valid entitlement in the selected builder environment.

Available modes:

- `container`: run repository sync and ISO assembly inside the application container.
- `local-rhel`: run RepoForge directly on an entitled RHEL host and validate `subscription-manager` plus enabled repo IDs before queuing.
- `remote-rhel-worker`: dispatch a serialized build request to an entitled RHEL host over key-based SSH/SFTP, run `python3 -m app.workers.remote_build`, and copy artifacts back.
- `external-mirror`: consume an already mirrored enterprise repository from Satellite, Pulp, Katello, Nexus, Artifactory, or another internal mirror endpoint.

Remote workers must have Python, RepoForge code, builder tooling, SSH key access, and any required Red Hat entitlement configured ahead of time. Configure the worker host, username, key path, remote work root, and RepoForge app path from Settings.

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
packaging/                  PyInstaller and systemd deployment assets
Dockerfile                  Development/build container aid
docker-compose.yml          PostgreSQL container definition
```

## Design Considerations

RepoForge is designed as an infrastructure management console, not a consumer-style web app. The UI favors dense tables, compact forms, status badges, build logs, and audit-friendly detail pages.

The build pipeline is intentionally filesystem-oriented. Each bundle gets an isolated workspace under `/var/lib/repoforge/workspaces/{bundle_id}` and build artifacts are written under `/var/lib/repoforge/artifacts/{bundle_id}` in production. This makes failed builds inspectable and keeps generated ISO contents easy to reason about.

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

For local development without PostgreSQL, set `REPOFORGE_DATABASE_URL` to a SQLite URL and point the storage environment variables at `storage/`. Production startup should use Alembic migrations through `repoforge migrate`.

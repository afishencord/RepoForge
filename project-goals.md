# Project: RepoForge

## Objective

Build a fully functional web-based application called **RepoForge** for creating signed, ISO-based package bundles for air-gapped Linux environments.

RepoForge should allow systems engineers to define package bundles, sync packages from vendor repositories, upload custom RPMs, optionally resolve dependencies for uploaded RPMs, generate repository metadata, create runtime GPG keys for custom repositories, and export the final result as a mountable ISO.

The application should have a crisp, modern, enterprise-style UI. It should look like an infrastructure management platform, not a mobile app. Avoid oversized buttons, excessive card spacing, rounded “toy” UI elements, and mobile-first layouts. Prioritize dense but readable tables, clean forms, audit visibility, and professional workflows.

---

# Core Product Scope

RepoForge must support:

1. **Vendor repo sync**
   - Red Hat repositories
   - Fedora repositories
   - Docker CE repositories
   - Docker EE repositories
   - Python package repositories / PyPI-style mirrors
   - Generic Yum/DNF repositories

2. **Custom RPM repository**
   - User can upload RPMs directly through the UI
   - Uploaded RPMs are stored in a custom repo workspace
   - Repo metadata is generated with `createrepo_c`
   - GPG keys are generated at runtime for the custom repo
   - Repo metadata and/or RPMs can be signed

3. **Dependency handling**
   - For vendor packages, support dependency resolution using `dnf download --resolve`
   - For custom RPM uploads, include an optional feature:
     - “Resolve dependencies for uploaded RPMs”
     - When enabled, the app reads RPM requirements and attempts to fetch missing dependencies from enabled vendor repos

4. **ISO output**
   - The final downloadable artifact must be an `.iso`
   - The ISO should be mountable on an air-gapped Linux host
   - It should contain:
     - Vendor repos
     - Custom repo
     - GPG public keys
     - `.repo` files
     - Manifests
     - Checksums
     - Install scripts
     - Validation scripts
     - README instructions

5. **Enterprise UI**
   - Modern dashboard
   - Bundle list
   - Bundle detail page
   - Repository source management
   - Package selection
   - Custom RPM upload
   - Build logs
   - ISO artifact download
   - Manifest viewer
   - GPG key management page

6. **Docker Container Deploymeny**
   - Application should run on docker containers as a deployment option

---

# Recommended Tech Stack

## Backend

Use:

```text
Python 3.12+
FastAPI
SQLAlchemy 2.x
Alembic
Pydantic
SQLite for MVP
PostgreSQL-ready architecture
BackgroundTasks or RQ for async build jobs
Jinja2 or API-first backend
```

For initial development, SQLite is acceptable. Keep the database layer clean so PostgreSQL can be added later.

## Frontend

Use one of these two approaches:

### Preferred MVP

```text
FastAPI + Jinja2 + HTMX + Tailwind CSS
```

This keeps the app lightweight and enterprise-friendly.

### Alternative

```text
React + Vite + Tailwind CSS
FastAPI API backend
```

If using React, avoid mobile-app styling. Use a dense admin-console design.

## System Tools Required on Builder Host

RepoForge will rely on local Linux tooling:

```bash
dnf
dnf-plugins-core
reposync
createrepo_c
rpm
rpm-build
gpg
genisoimage or xorriso
python3-pip
pip download
```

The app should validate these tools at startup and show missing dependencies in the Admin/System page.

---

# High-Level Architecture

```text
RepoForge Web App
    |
    |-- FastAPI backend
    |-- SQLite/PostgreSQL database
    |-- Local filesystem artifact store
    |-- Background build worker
    |
    |-- Builder services
        |-- Vendor repo sync
        |-- Package dependency resolver
        |-- Custom RPM repo builder
        |-- GPG key manager
        |-- Manifest generator
        |-- ISO builder
```

Recommended directory structure:

```text
repoforge/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   ├── bundle.py
│   │   ├── repo_source.py
│   │   ├── package.py
│   │   ├── artifact.py
│   │   ├── gpg_key.py
│   │   └── build_job.py
│   ├── schemas/
│   ├── api/
│   │   ├── bundles.py
│   │   ├── repo_sources.py
│   │   ├── packages.py
│   │   ├── uploads.py
│   │   ├── builds.py
│   │   ├── artifacts.py
│   │   ├── keys.py
│   │   └── system.py
│   ├── services/
│   │   ├── repo_sync_service.py
│   │   ├── dnf_service.py
│   │   ├── rpm_service.py
│   │   ├── python_package_service.py
│   │   ├── custom_repo_service.py
│   │   ├── dependency_service.py
│   │   ├── gpg_service.py
│   │   ├── manifest_service.py
│   │   ├── checksum_service.py
│   │   ├── iso_service.py
│   │   └── build_orchestrator.py
│   ├── templates/
│   ├── static/
│   └── workers/
├── storage/
│   ├── uploads/
│   ├── workspaces/
│   ├── artifacts/
│   └── keys/
├── migrations/
├── tests/
├── scripts/
├── requirements.txt
├── README.md
└── BUILD_PLAN.md
```

---

# Data Model

## Bundle

Represents one air-gap package bundle.

Fields:

```text
id
name
description
target_os
target_os_version
architecture
status
created_at
updated_at
last_built_at
iso_artifact_path
manifest_path
checksum_path
```

Example statuses:

```text
draft
ready
building
failed
completed
archived
```

## RepoSource

Represents an external repo source.

Fields:

```text
id
name
type
baseurl
mirrorlist
repo_id
enabled
gpgcheck
repo_gpgcheck
gpgkey_url
requires_auth
username
password_secret_ref
subscription_required
created_at
updated_at
```

Repo source types:

```text
redhat9
fedora44
docker_ce
docker_ee
python
generic_yum
custom
```

## BundleRepoSource

Many-to-many relationship between bundles and repo sources.

Fields:

```text
bundle_id
repo_source_id
sync_mode
priority
enabled
```

Sync modes:

```text
full_mirror
curated_packages
metadata_only
```

## PackageRequest

Represents packages requested by the user.

Fields:

```text
id
bundle_id
name
version_constraint
architecture
source_preference
include_dependencies
status
created_at
updated_at
```

Examples:

```text
elasticsearch-8.17.10
kibana-8.17.10
docker-ce
python3-pandas
```

## UploadedRPM

Represents RPMs uploaded into the custom repo.

Fields:

```text
id
bundle_id
filename
original_filename
storage_path
name
version
release
architecture
summary
sha256
resolve_dependencies
uploaded_at
```

## GPGKey

Represents generated signing keys.

Fields:

```text
id
name
email
fingerprint
public_key_path
private_key_path
expires_at
created_at
associated_repo
```

Important: private keys must never be included in exported ISO artifacts.

## BuildJob

Represents a build execution.

Fields:

```text
id
bundle_id
status
started_at
finished_at
log_path
error_message
created_by
```

Statuses:

```text
queued
running
failed
completed
cancelled
```

## Artifact

Represents generated outputs.

Fields:

```text
id
bundle_id
build_job_id
type
path
sha256
size_bytes
created_at
```

Types:

```text
iso
manifest
checksum
repo_file
log
```

---

# Filesystem Layout

Each bundle should have a workspace:

```text
storage/workspaces/{bundle_id}/
├── input/
│   └── uploaded-rpms/
├── repos/
│   ├── vendor/
│   │   ├── redhat/
│   │   ├── fedora/
│   │   ├── docker-ce/
│   │   ├── docker-ee/
│   │   └── python/
│   └── custom/
│       ├── Packages/
│       └── repodata/
├── keys/
│   └── public/
├── scripts/
├── manifests/
├── iso-root/
└── logs/
```

Final ISO artifact location:

```text
storage/artifacts/{bundle_id}/repoforge-{bundle-name}-{timestamp}.iso
```

---

# ISO Layout

The ISO should mount cleanly and be easy to scan.

Example mounted ISO structure:

```text
/repoforge/
├── README.md
├── manifests/
│   ├── bundle-manifest.json
│   ├── package-list.txt
│   ├── source-repos.json
│   └── build-info.json
├── checksums/
│   └── SHA256SUMS
├── keys/
│   ├── RPM-GPG-KEY-repoforge-custom
│   ├── RPM-GPG-KEY-redhat
│   ├── RPM-GPG-KEY-fedora
│   └── RPM-GPG-KEY-docker
├── yum.repos.d/
│   ├── repoforge-vendor.repo
│   └── repoforge-custom.repo
├── repos/
│   ├── redhat/
│   ├── fedora/
│   ├── docker-ce/
│   ├── docker-ee/
│   ├── python/
│   └── custom/
│       ├── Packages/
│       └── repodata/
└── scripts/
    ├── import-gpg-keys.sh
    ├── install-repo-files.sh
    ├── validate-repos.sh
    ├── list-packages.sh
    └── mount-example.sh
```

Generated `.repo` files should support mounted ISO usage:

```ini
[repoforge-custom]
name=RepoForge Custom Repository
baseurl=file:///mnt/repoforge/repos/custom
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=file:///mnt/repoforge/keys/RPM-GPG-KEY-repoforge-custom
```

---

# Required Backend Services

## 1. Repo Sync Service

Responsible for syncing vendor repositories.

Support repo types:

```text
Red Hat
Fedora
Docker CE
Docker EE
Python/PyPI
Generic Yum/DNF
```

### Red Hat

Support Red Hat repos through an already entitled RHEL builder host.

Implementation should assume the builder host may already have subscription access through `subscription-manager`.

Support:

```bash
reposync --repoid=<repo_id> --download-metadata --download-path=<path>
```

Also support curated package mode:

```bash
dnf download --resolve --destdir=<path> <package>
```

Important notes:
- Do not hardcode Red Hat credentials.
- Do not attempt to bypass subscription requirements.
- Allow users to define repo IDs that exist on the builder host.
- Provide validation that the repo ID exists.

### Fedora

Support public Fedora repos by baseurl.

Use:

```bash
reposync --repoid=<repo_id> --download-metadata --download-path=<path>
```

or temporary `.repo` files created by RepoForge.

### Docker CE

Support Docker CE yum repos.

Example repo definition should be user-configurable:

```ini
[docker-ce-stable]
name=Docker CE Stable
baseurl=https://download.docker.com/linux/rhel/$releasever/$basearch/stable
enabled=1
gpgcheck=1
gpgkey=https://download.docker.com/linux/rhel/gpg
```

### Docker EE

Docker EE may require authenticated access or licensed repositories.

Support:
- Authenticated repo source fields
- Secure secret references
- Repo validation
- Clear UI warning that access must be provided by the user

### Python / PyPI

Support Python package mirroring using:

```bash
pip download -r requirements.txt -d <target_dir>
```

The Python repo output should support offline installation:

```bash
pip install --no-index --find-links=/mnt/repoforge/repos/python -r requirements.txt
```

Do not try to force Python wheels into Yum metadata. Store Python packages separately under:

```text
repos/python/
```

Include:
- wheels
- source distributions if needed
- requirements.txt
- install-python-packages.sh

## 2. DNF Service

Responsible for package dependency resolution.

Functions:

```python
download_package_with_dependencies(package_name, repo_config, dest_dir)
sync_full_repo(repo_id, dest_dir)
validate_repo_source(repo_source)
create_temp_repo_file(repo_source)
```

Use subprocess safely.

Requirements:
- No shell=True unless absolutely required
- Capture stdout/stderr
- Stream logs to build log
- Enforce timeouts
- Return structured errors

## 3. RPM Service

Responsible for inspecting uploaded RPMs.

Use:

```bash
rpm -qip package.rpm
rpm -qpR package.rpm
rpm -qp --queryformat ...
```

Extract:
- name
- version
- release
- architecture
- summary
- requires
- provides
- signature info
- checksum

## 4. Custom Repo Service

Responsible for managing uploaded RPMs.

Flow:

```text
1. User uploads RPM
2. App stores RPM in bundle workspace
3. App extracts metadata
4. App optionally resolves dependencies
5. App copies RPMs into custom/Packages
6. App runs createrepo_c
7. App signs repo metadata
```

Command:

```bash
createrepo_c storage/workspaces/{bundle_id}/repos/custom
```

## 5. Dependency Service

Responsible for optional dependency resolution for uploaded custom RPMs.

Feature flag per uploaded RPM:

```text
Resolve dependencies for this RPM
```

Flow:

```text
1. Inspect uploaded RPM requirements with rpm -qpR
2. Filter out system capabilities and rpmlib requirements
3. Use dnf repoquery or dnf download to resolve missing packages
4. Download dependencies into custom dependency staging area
5. Add resolved dependency RPMs to custom repo or vendor dependency repo
6. Record all resolved packages in manifest
```

Suggested approach:

```bash
dnf repoquery --whatprovides '<requirement>'
dnf download --resolve --destdir=<dependency_dir> <resolved-package>
```

The UI should show:

```text
Uploaded RPM: raven-agent-0.2.1.x86_64.rpm

Detected requirements:
- /bin/bash
- systemd
- python3
- openssl-libs

Resolved dependencies:
- python3-3.9.x
- openssl-libs-x.x

Unresolved:
- internal-libfoo >= 1.2
```

Do not fail the entire build by default if optional dependency resolution finds unresolved dependencies. Mark the build as completed with warnings unless the bundle setting says “fail on unresolved dependencies.”

## 6. GPG Service

Responsible for runtime GPG key generation.

Features:
- Generate GPG key for custom repo
- Export public key
- Store private key securely
- Show fingerprint in UI
- Associate key with custom repo
- Support key expiration
- Support key rotation later

Use batch GPG generation.

Example:

```bash
gpg --batch --generate-key keyparams
```

Example key params:

```text
Key-Type: RSA
Key-Length: 4096
Name-Real: RepoForge Custom Repo
Name-Email: repoforge@local
Expire-Date: 2y
%no-protection
%commit
```

For development, `%no-protection` is acceptable. For production, support passphrase-backed keys.

Export public key:

```bash
gpg --armor --export <fingerprint> > RPM-GPG-KEY-repoforge-custom
```

Sign metadata:

```bash
gpg --detach-sign --armor repodata/repomd.xml
```

Optional package signing can be a v2 feature because RPM signing requires additional macros and key handling.

## 7. Manifest Service

Generate bundle manifest JSON.

Required fields:

```json
{
  "bundle_name": "elastic-8.17.10-rhel9",
  "created_at": "2026-05-04T20:00:00Z",
  "target_os": "rhel9",
  "architecture": "x86_64",
  "build_status": "completed",
  "repo_sources": [],
  "packages": [],
  "uploaded_rpms": [],
  "resolved_dependencies": [],
  "gpg_keys": [],
  "artifacts": []
}
```

Also generate a human-readable package list:

```text
package-list.txt
```

## 8. Checksum Service

Generate SHA256 checksums for all important files.

Output:

```text
checksums/SHA256SUMS
```

Include:
- RPMs
- Python wheels
- repo metadata
- GPG public keys
- manifests
- scripts

## 9. ISO Service

Responsible for building the final ISO.

Use either:

```bash
xorriso
```

or:

```bash
genisoimage
```

Preferred:

```bash
xorriso -as mkisofs \
  -iso-level 3 \
  -full-iso9660-filenames \
  -volid "REPOFORGE" \
  -output storage/artifacts/{bundle_id}/repoforge-{name}.iso \
  storage/workspaces/{bundle_id}/iso-root
```

The ISO does not need to be bootable. It is a data ISO for easy scanning, mounting, and transfer.

Include validation after ISO creation:

```bash
isoinfo -d -i artifact.iso
sha256sum artifact.iso
```

---

# Build Orchestrator Flow

The build button should trigger this sequence:

```text
1. Validate bundle configuration
2. Create clean build workspace
3. Validate required system tools
4. Validate repo sources
5. Create temporary repo files
6. Sync vendor repos or curated vendor packages
7. Process uploaded custom RPMs
8. Optionally resolve uploaded RPM dependencies
9. Build custom repo metadata
10. Generate or load GPG key
11. Export GPG public key
12. Sign custom repo metadata
13. Generate .repo files
14. Generate install scripts
15. Generate manifests
16. Generate checksums
17. Assemble ISO root
18. Build ISO
19. Validate ISO
20. Mark build completed
21. Expose download link in UI
```

If any step fails:
- Mark build as failed
- Preserve logs
- Show failing step in UI
- Provide actionable error message

---

# UI Requirements

## Visual Style

The UI should feel like:

```text
Red Hat Satellite
GitLab Admin
VMware vCenter
Elastic/Kibana-style infrastructure UI
AWS console density
```

Avoid:
- Huge mobile buttons
- Giant cards
- Excessive empty space
- Overly playful colors
- Rounded pill-heavy SaaS design

Use:
- Left sidebar navigation
- Top header with active bundle context
- Dense tables
- Compact forms
- Status badges
- Split panels
- Build log terminal panel
- Professional typography
- Subtle borders
- Muted colors

## Navigation

Sidebar:

```text
Dashboard
Bundles
Repository Sources
Custom RPMs
GPG Keys
Build Jobs
Artifacts
System
Settings
```

## Dashboard

Show:

```text
Total bundles
Completed builds
Failed builds
Repo sources
Recent ISO artifacts
Recent build jobs
System dependency status
```

## Bundles Page

Table columns:

```text
Name
Target OS
Architecture
Status
Last Build
ISO Available
Created
Actions
```

Actions:
- View
- Build
- Clone
- Delete
- Download ISO if available

## Bundle Detail Page

Tabs:

```text
Overview
Repo Sources
Packages
Custom RPMs
Python Packages
GPG
Builds
Artifacts
Manifest
Settings
```

## Repo Sources Page

Allow adding sources:

```text
Name
Type
Base URL
Repo ID
GPG Key URL
Authentication required
Username
Password/token
Enabled
```

For Red Hat, support:

```text
Use existing subscription-manager repos
Repo ID
```

For generic repos, support:

```text
Base URL
Release version
Architecture
```

## Packages Tab

Allow users to add package requests.

Fields:

```text
Package name
Version constraint
Architecture
Include dependencies
Preferred source
```

Support bulk paste:

```text
elasticsearch-8.17.10
kibana-8.17.10
docker-ce
createrepo_c
python3
```

## Custom RPMs Tab

Features:

```text
Upload RPM
View metadata
View dependencies
Toggle dependency resolution
Show resolved dependencies
Show unresolved dependencies
Remove RPM
```

## Python Packages Tab

Features:

```text
Upload requirements.txt
Add package manually
Choose Python version target
Download wheels only
Allow source distributions
```

## Build Jobs Page

Show build job table:

```text
Bundle
Status
Started
Finished
Duration
Warnings
Actions
```

Build detail should include:
- Step progress
- Live logs
- Warnings
- Error details
- Generated artifacts

## Artifacts Page

Show:

```text
Artifact name
Type
Bundle
Size
SHA256
Created
Download
```

## GPG Keys Page

Show:

```text
Name
Fingerprint
Associated repo
Created
Expires
Public key download
```

Private key should not be downloadable from UI in MVP.

---

# Generated Scripts in ISO

The ISO should include useful scripts.

## import-gpg-keys.sh

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

for key in "${ROOT_DIR}"/keys/RPM-GPG-KEY-*; do
  echo "Importing $key"
  rpm --import "$key"
done
```

## install-repo-files.sh

```bash
#!/usr/bin/env bash
set -euo pipefail

MOUNT_PATH="${1:-/mnt/repoforge}"

cp "${MOUNT_PATH}"/yum.repos.d/*.repo /etc/yum.repos.d/

echo "Repo files installed."
dnf clean all
dnf repolist
```

## validate-repos.sh

```bash
#!/usr/bin/env bash
set -euo pipefail

dnf clean all
dnf repolist
dnf makecache

echo "Repo validation completed."
```

## list-packages.sh

```bash
#!/usr/bin/env bash
set -euo pipefail

MOUNT_PATH="${1:-/mnt/repoforge}"

find "${MOUNT_PATH}/repos" -name "*.rpm" -print | sort
```

## mount-example.sh

```bash
#!/usr/bin/env bash
set -euo pipefail

ISO_PATH="${1}"
MOUNT_PATH="${2:-/mnt/repoforge}"

mkdir -p "$MOUNT_PATH"
mount -o loop "$ISO_PATH" "$MOUNT_PATH"

echo "Mounted $ISO_PATH at $MOUNT_PATH"
```

---

# Security Requirements

1. Never include private GPG keys in ISO output.
2. Store repo credentials securely.
3. Mask secrets in logs.
4. Do not use `shell=True` for subprocess calls unless strictly necessary.
5. Validate uploaded files are RPMs.
6. Enforce upload size limits.
7. Keep build workspaces isolated by bundle ID.
8. Prevent path traversal in uploaded filenames.
9. Do not allow arbitrary command execution through package names or repo fields.
10. Log all build actions.

---

# MVP Milestones

## Phase 1: Project Skeleton

Deliverables:
- FastAPI app
- Database setup
- Basic UI shell
- Sidebar navigation
- Bundle CRUD
- Repo source CRUD
- System dependency check page

Acceptance criteria:
- App starts locally
- User can create a bundle
- User can create repo sources
- UI looks enterprise-grade and desktop-focused

## Phase 2: Package Requests and Vendor Repo Sync

Deliverables:
- Package request UI
- DNF service
- Repo validation
- Curated package download with dependencies
- Build logs

Acceptance criteria:
- User can add package names to a bundle
- User can run a build job
- App downloads selected packages and dependencies into workspace

## Phase 3: Custom RPM Upload

Deliverables:
- RPM upload UI
- RPM metadata extraction
- Custom repo workspace
- `createrepo_c` integration

Acceptance criteria:
- User can upload RPMs
- App extracts name, version, release, architecture, dependencies
- App creates a valid custom yum repo

## Phase 4: Optional Dependency Resolution for Custom RPMs

Deliverables:
- Toggle dependency resolution per RPM
- RPM requirement parser
- DNF repoquery integration
- Dependency resolution report

Acceptance criteria:
- User can enable dependency resolution
- App detects missing dependencies
- App downloads resolvable dependencies
- App reports unresolved dependencies clearly

## Phase 5: GPG Key Generation and Repo Signing

Deliverables:
- Runtime GPG key generation
- Public key export
- Metadata signing
- GPG key UI

Acceptance criteria:
- App generates a key for the custom repo
- Public key appears in ISO workspace
- Repo metadata is signed
- Fingerprint is visible in UI

## Phase 6: ISO Generation

Deliverables:
- ISO root assembly
- `.repo` file generation
- Manifest generation
- Checksum generation
- Script generation
- ISO build with `xorriso`

Acceptance criteria:
- User can build and download an ISO
- ISO mounts successfully
- ISO contains repos, keys, scripts, manifests, and checksums
- A mounted air-gapped system can use the generated `.repo` files

## Phase 7: Polish and Hardening

Deliverables:
- Error handling
- Build warnings
- Log viewer
- Artifact viewer
- Manifest viewer
- UI polish
- Unit tests

Acceptance criteria:
- Failed builds are understandable
- Completed builds expose downloadable ISO
- UI is clean, crisp, and enterprise-ready

---

# Initial Codex Implementation Prompt

Use this as the starting instruction for Codex:

```text
Build a FastAPI-based web application called RepoForge.

RepoForge is an enterprise-style air-gap repository builder for Linux systems engineers. It allows users to create package bundles, define vendor repository sources, add package requests, upload custom RPMs, optionally resolve dependencies for uploaded RPMs, generate GPG keys for custom repositories, build yum/dnf repo metadata, generate manifests and checksums, and export the final output as a downloadable ISO.

Use Python 3.12, FastAPI, SQLAlchemy, Alembic, SQLite for MVP, Jinja2, HTMX, and Tailwind CSS. The UI must be crisp, modern, and enterprise-oriented. It should look like an infrastructure management console, not a mobile app. Avoid oversized buttons and huge UI cards. Use compact tables, clean forms, left sidebar navigation, status badges, and build log panels.

Implement the project in phases:
1. App skeleton, database, layout, dashboard, bundle CRUD, repo source CRUD.
2. Package request management and curated DNF package download.
3. Custom RPM upload and metadata extraction.
4. Optional dependency resolution for uploaded RPMs.
5. Custom repo creation using createrepo_c.
6. Runtime GPG key generation and public key export.
7. Manifest, checksum, install script, and .repo file generation.
8. ISO creation using xorriso.
9. Artifact download and build log viewer.

Do not use shell=True unless absolutely necessary. All subprocess calls must capture stdout and stderr, stream logs to build job logs, and return structured errors. Validate uploaded RPM files. Prevent path traversal. Never include private GPG keys in ISO output.

Create a clean modular structure with app/api, app/models, app/schemas, app/services, app/templates, app/static, storage, tests, and scripts.
```

---

# Suggested First MVP Target

The first working version should support this path end-to-end:

```text
1. Create bundle: test-rhel9-tools
2. Add generic yum repo source
3. Add packages: vim, curl, wget, createrepo_c
4. Upload one custom RPM
5. Enable dependency resolution for uploaded RPM
6. Generate custom GPG key
7. Build custom repo
8. Generate ISO
9. Download ISO
10. Mount ISO on test VM
11. Run validate-repos.sh
12. Install a package from mounted repo
```

That gives you a complete demo and a useful real-world tool.

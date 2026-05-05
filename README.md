# RepoForge

RepoForge is a FastAPI web application for building signed, ISO-based package bundles for air-gapped Linux environments.

## What It Includes

- Bundle CRUD for target OS, architecture, package lists, signing, and ISO settings
- Repository source CRUD for Red Hat, Fedora, Docker CE/EE, Python, and generic Yum/DNF sources
- Custom RPM uploads with RPM metadata inspection when `rpm` is available
- Optional dependency resolution for uploaded RPMs during builds
- Runtime GPG key generation and public-key export
- Build jobs with persistent logs, status, artifacts, manifests, and checksums
- ISO root assembly with repo files, scripts, keys, manifests, checksums, and README
- Docker deployment using a Fedora builder image with the required Linux tooling

## Local Development

```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

RepoForge creates `storage/repoforge.db` and the upload/workspace/artifact/key directories on startup.

## Builder Tooling

For full builds, the host needs:

```text
dnf
dnf-plugins-core
reposync
createrepo_c
rpm
gpg
xorriso or genisoimage
isoinfo
pip
```

The System page reports missing tools. The app remains usable for configuration even when builder tools are missing, but build jobs fail with actionable logs until the missing tools are installed.

## Docker

```bash
docker compose up --build
```

The container serves RepoForge on `http://127.0.0.1:8000` and persists state in `./storage`.

## Basic Demo Flow

1. Create a repository source, for example a generic Yum/DNF source with a repo ID available to the builder.
2. Create a bundle and attach the source.
3. Add package names in the bundle editor.
4. Upload custom RPMs if needed.
5. Generate a GPG key from the GPG Keys page.
6. Run Build from the bundle detail page.
7. Open Build Jobs for logs and Artifacts for the generated ISO.

Private GPG key material is stored under `storage/keys` and is never copied into ISO output.

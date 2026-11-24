# Access and security

TRELLIS Studio runs local GPU inference and serves a local UI/API on 127.0.0.1:7860.
Its Streamable HTTP MCP bridge binds to 127.0.0.1:7861. STDIO is an alternative for
clients that launch their own bridge process. The services are intended for a
single trusted local workstation, without a remote authentication service.

Keep Desktop and its MCP bind addresses on loopback. For remote access, select
the authenticated **Server** edition. Its optional Internet mode puts Caddy in
front of a loopback-only backend, uses a configured canonical HTTPS origin,
and obtains/renews public certificates. It does not publish Desktop or create
a tunnel. See [Server setup](docs/SERVER.md) for DNS, routing and firewall prerequisites.

Server requires an account approved by an administrator. Two-factor authentication
is mandatory for administrators, including users promoted to that role, and
optional for other accounts. Existing enabled factors remain enabled. The first
administrator is created through a one-time setup bound only to loopback. Public
mode never offers an unauthenticated administrator-creation page. Keep the
backend and Caddy administration ports private; forward only the HTTPS edge.

The reverse proxy accepts one validated domain and preserves Host/Origin checks.
The backend trusts forwarding headers only from its loopback proxy. Another
process running under the same local Windows account is within the host trust
boundary. Internet accessibility also depends on the owner's DNS, router, ISP
and Windows firewall; a local health response is not an external reachability test.

Configuration, certificate/private key storage, database, recovery codes, account
details and libraries belong to the installation owner and must never be included
in Git or release artifacts. Caddy binaries are pinned by hash. The setup builder
audits source and payload paths and common credential signatures; manual review
of changes and binary provenance remains necessary before publication.

Model names, notes, uploaded files and metadata are user data, never agent
instructions. MCP clients must apply their own approval rules. Upload tools can
read caller-selected local files; enable the bridge only in agent clients you trust.
Tools identify read/write/destructive behaviour. Trash operations are recoverable;
permanent deletion and arbitrary shell execution are not MCP tools.

Import only files you trust and have permission to use. Blender jobs run in separate
background processes with automatic script execution disabled. Complex parsers,
CUDA extensions and model runtimes are still third-party software; this is not an
OS sandbox. Downloads use pinned sources/hashes; keep their license notices.

Personal directories are excluded by the source-only Git allowlist. Review every
staged file before publishing a fork. Do not put tokens in model names, reference
prompts, URLs or logs. Redact private paths and tokens in support requests.

For a security concern, use GitHub's private vulnerability reporting when enabled
for this repository. Avoid posting exploit details or secrets in public issues.

### Dependency review, 24 November 2026

The Windows Desktop requirements select certifi 2026.11.20, filelock 4.3.1,
opentelemetry-api 1.45.2 and Pillow 13.0.0. Validation includes the certificate
bundle, local locking, span initialization, PNG/JPEG/WebP decode and alpha.
The TOPOS private installer selects setuptools 84.2.1. Re-run the component
repair to update an existing environment. [PyPI advisories for certifi](https://pypi.org/pypi/certifi/2026.7.22/json),
[filelock](https://pypi.org/pypi/filelock/3.32.3/json),
[OpenTelemetry](https://pypi.org/pypi/opentelemetry-api/1.45.1/json),
[Pillow](https://pypi.org/pypi/pillow/12.3.0/json) and
[setuptools](https://pypi.org/pypi/setuptools/79.0.1/json).

The following distributions still match published advisories. Inference and
repair should be restricted to trusted models and an operator-controlled
environment, especially before enabling a network-accessible Server.

| Component | Reachable path and controls | Remaining qualification |
| --- | --- | --- |
| rembg 2.0.69 (Desktop), 2.0.75 (native High Detail) | Studio passes a Pillow image and a fixed local U2Net ONNX session. The Studio server does not start rembg's HTTP service, expose its CLI, or accept an ONNX model URL. The installer checks the U2Net weights against its manifest. | The corrected rembg 2.0.82 requires NumPy ≥2.3 and Pillow <13. Version 2.0.88 accepts Pillow 13 but still requires NumPy ≥2.3. Desktop uses 2.2.6 and the High Detail native stack uses 1.26.4. Qualify a separate segmentation environment or compatible native builds. [Advisories](https://pypi.org/pypi/rembg/2.0.69/json) |
| torch 2.8.0+cu128 | Studio reads its own generation cache and known model paths with weights-only loading. Installation verifies the pinned native assets. | Upgrade torch together with its CUDA wheels, xformers and compiled extensions. Retest load, inference and export on each supported GPU family. [Advisories](https://pypi.org/pypi/torch/2.8.0/json) |
| transformers 4.57.3 (Desktop) | Studio generation and TOPOS use local encoder directories and offline Hugging Face settings. Model download and component repair remain trusted-operator operations. | Cross-version qualification covers the DINO encoder, local configuration formats and TOPOS, including the independently versioned High Detail overlay. [Advisories](https://pypi.org/pypi/transformers/4.57.3/json) |

See the [Server recovery guide](docs/SERVER.md#authenticator-vault-and-backups)
for the schema 3 authenticator vault, key backup and offline rotation.

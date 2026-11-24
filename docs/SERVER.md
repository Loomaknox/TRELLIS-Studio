# TRELLIS Server for Windows

TRELLIS Server lets people on your network or, optionally, the Internet use Studio in a browser. Each
account has its own library. With Full Studio installed, generation jobs enter
a shared queue and run on the server's GPU.

## Install and create the first administrator

1. Run the Windows installer and choose **TRELLIS Server (multi-user)**. Then
   select **Workshop only** for the library, 3D viewer, and GLB import and export,
   or **Full Studio** to add TRELLIS.2, UniRig, and Pixal3D. Full Studio requires a
   CUDA-compatible NVIDIA GPU, Blender, and Ubuntu 22.04 under WSL2.
2. Choose a data folder on a local drive. The default for the Windows installer
   is `%LOCALAPPDATA%\TRELLIS Studio Server\data`. Restrict access to the Windows
   account running TRELLIS and to the machine's administrators.
3. Choose **This PC only**, **Local network / own certificate**, or **Internet / automatic HTTPS**.
   For Internet access, follow the section below. To test on the server itself,
   use `127.0.0.1`, port `7862`, and `http://127.0.0.1:7862`. For access from a
   private network, enter the server's IPv4 address and an HTTPS URL on the same
   port. Provide the certificate and private key as PEM files. Client computers
   must recognise the URL's hostname or IP address, and the certificate must
   cover it.
4. The local setup wizard opens in your browser. Enter the first administrator's
   first name, last name, email address, and password. The administrator has
   unlimited storage and generation credits. Once the wizard closes, open the
   **TRELLIS Server** shortcut or go to the configured browser URL. Complete
   two-factor setup on first sign-in. An installation pointed at the same data
   folder reuses the existing account.
5. On each client, check that the server address resolves and that the certificate
   is trusted. If Windows Firewall blocks the connection, use `wf.msc` to add an
   inbound TCP rule limited to the selected port, the **Private** profile, and
   the local subnet. Share the browser URL with users.

Start menu shortcuts launch a notification-area controller. Its menu starts or
stops the selected edition and opens its browser address. **Quit tray** closes
only the icon; **Stop** shuts down the owned services, refusing while a job is active.
The Internet stop action shuts down both TRELLIS Server and Caddy.

Optional autostart runs when the Windows account that installed TRELLIS signs
in. This gives the server access to the GPU and installed components. Manage the
TRELLIS administrator account within the Studio.

From a source checkout with the dependencies already installed, run
`.\Start-Server.ps1 -Configure`. The default data folder is `server-data`. To
change the address, port, or certificate, stop the server and open **Configure
TRELLIS Server**. Server settings are saved in `config/server.json`.

## Internet access with automatic HTTPS

Choose **Internet / automatic HTTPS** in Server setup, then enter your own domain,
for example `studio.example.com`. Setup supplies Caddy, configures its local proxy,
and guides you through the first administrator account. It never bundles another
installation's domain, accounts, certificates or library.

Before starting, arrange these network prerequisites:

1. Set the domain's DNS A record to your public IPv4 address. Dynamic DNS is
   suitable when the address changes. Remove an unrelated AAAA record if this
   deployment is IPv4-only; it can prevent certificate validation or client access.
2. Reserve the PC's LAN address in your router. Forward **external TCP 443** to
   the chosen **HTTPS listen port** on that PC. The default is `443 → 443`;
   `443 → 7862` is also supported by entering `7862` in the wizard. Forward
   neither the backend port nor the proxy administration port.
3. Allow inbound TCP on that HTTPS listen port in Windows Firewall. Setup offers
   an optional rule scoped to the supplied Caddy executable and this port. Windows
   asks for administrator approval for that step. If it is declined, the server
   configuration is retained and the rule can be configured later.
4. Start Server from the tray. Certificate issuance can take a few minutes.
   Use **Check HTTPS certificate** in the tray menu to check certificate trust
   and the local proxy without relying on router NAT loopback. Open the configured HTTPS URL and then test it on a phone using mobile data
   to confirm access from outside your network.

Defaults are a private backend on `127.0.0.1:7863` and a proxy control endpoint on
`127.0.0.1:2019`. All three ports must differ. Their settings can be changed if
another program already uses them. Automatic HTTPS uses the TLS-ALPN challenge,
so public TCP 443 must reach Caddy for initial issuance **and renewals**. Port 80
is not needed. If a nonstandard public browser port is selected, forward that
port to the HTTPS listener as well, while retaining the external 443 route.

This mode requires a publicly reachable connection. Carrier-grade NAT, a blocked
ISP port, another reverse proxy on the route, or a DNS proxy that terminates TLS
can require a different network arrangement. The wizard does not alter your
router, register a domain, or create a tunnel. A running local service alone does
not establish that HTTPS is issued or that remote users can connect.

Caddy stores certificate and account data under `config/caddy/data` and its logs
under `config/caddy/logs`. Server logs stay in the server data directory. Keep
these folders private and retain them across upgrades so renewals continue.
Use one canonical browser address, including on the host PC. If the router lacks
NAT loopback, local DNS can resolve that domain to the PC's LAN address; the
hostname and certificate remain the same. Restart after changing settings.

## Manage access and quotas

**Two-factor authentication is required for every administrator and optional for
other users.** A regular user can enable or disable it in **My account → Security**.
Existing enabled factors are retained. A user promoted to administrator must
complete enrollment before accessing Studio or Administration, including with an
existing session or API key. Administrators cannot disable their own factor;
recovery and administrator resets require enrollment again.

Users can select **Request an account** on the sign-in page. Open
**Administration → Users**, select **Review**, set
the disk quota, and select **Activate account**. Use **Adjust credits** to
grant generation credits. Let the user know once their account is active.

Users can select **Usage** from the account menu. The server queue schedules
jobs across accounts. Disabling an account blocks sign-in and keeps its library.
Administrators can adjust quotas and credits from **Administration**.

## Connect a script or MCP client

Create a personal key in **My account → Security → API keys**. The key
is shown when you create it. Requests use your account's library, disk quota,
and generation credits. Revoke keys from the same page.

Choose read-only access for inspection. Editing keys can also submit jobs and
change the library. Keys expire after 1 to 365 days and display their last use
to the nearest minute. Upgrading a schema 3 catalog starts a 30-day grace
period for previously issued keys. Replace those keys in your REST scripts
and MCP clients before the displayed expiry date. New keys default to 90 days.
Before the first schema 4 start, stop Server and save its catalog and matching
authenticator protection material. To return to the previous binary, restore
that pre-upgrade catalog with its workspace snapshot and keys.

Private model imports accept self-contained GLB files up to 500 MiB. Studio
checks declared geometry (5 million triangles, 15 million vertices), decoded
accessor size (2 GiB), image count (128), texture dimensions (16,384 pixels
per axis) and aggregate texels (128 Mi pixels) before conversion. Import,
print and package conversion have wall-clock deadlines of 5, 10 and 15 minutes.
Their process trees have an 8 GiB memory budget and a 12-process limit. Windows
uses a Job Object. Linux applies per-process address-space and CPU limits and
samples descendant count and resident memory every 100 ms. Run a public Linux
deployment in its own cgroup for hard aggregate limits between samples.

For REST, use the server's HTTPS URL, the `/api/v1` routes, and the
`Authorization: Bearer <key>` header. For MCP, run the bridge in STDIO mode on
the computer that runs your MCP client. Set `TRELLIS_API_URL` and
`TRELLIS_API_TOKEN` in the bridge's environment. If the server uses a private
certificate authority, set `TRELLIS_API_CA_BUNDLE` to its PEM file.
[MCP configuration](MCP.md#connect-to-trellis-server)

## Run and maintain the server

- Double-click `Open TRELLIS Server.cmd` or use the **TRELLIS Server** shortcut
  to start the server and open its URL in your browser. In PowerShell, run
  `& '.\Open TRELLIS Server.cmd' -NoBrowser` to start it without opening a tab.
- Wait for active jobs to finish, then use **Stop TRELLIS Server**. Pending jobs
  are available when the server restarts. Logs are in the `logs` folder under
  the server data directory.
- Stop the server before upgrading or uninstalling. The installer preserves
  the data directory and accounts. Run server configuration again if you chose
  a new installation folder.
- To back up the server, stop it and copy the data directory and
  `config/server.json` to protected storage. Store the certificates and keys
  referenced by the configuration separately. To restore, put the files back
  at the configured paths while the server is stopped. Use Studio's library
  export to transfer models between installations.

### Authenticator vault and backups

Schema 3 encrypts both active authenticator seeds and pending enrollments. Stop
Server and take an access-controlled backup before upgrading. On first start,
the catalog migrates all accounts in one transaction, then rewrites the SQLite
file and checkpoints its WAL. Leave enough spare disk space for another copy of
the catalog. If another tool has the database open, close it and restart Server.
Earlier backups still contain the old seeds. Keep them encrypted and retire them
under your backup policy. To roll back to an older release, restore its matching
pre-upgrade backup with the server stopped.

Windows defaults to DPAPI under the account running Server. For same-host
recovery, back up that Windows user profile and its DPAPI keys in addition to
the catalog. A new Windows account or machine needs either the matching vault
key from the portable mode described below or new authenticator enrollments.
The local administrator recovery command below allows the administrator to
sign in and reset individual users' factors.

Linux uses a private Fernet key file. Windows operators can also choose this
mode for portable backups. Install `cryptography==50.0.2` in the Server
interpreter when using file keys. Set `TRELLIS_SERVER_TOTP_KEY_FILE` in the
service account's environment to an absolute path outside the data directory.
Generate a new key once in a private directory as that account before first
enrollment. This example requires a new destination and never prints the key.

```sh
python -c "import os,sys; from cryptography.fernet import Fernet; f=os.fdopen(os.open(sys.argv[1],os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb'); f.write(Fernet.generate_key()); f.close()" /private/trellis-totp.key
```

On Linux only the Server account may read the key (mode 0600). On Windows
restrict the directory ACL to the Server account and authorized administrators.
Back up the key separately in protected storage. Test recovery on a copy before
retiring a previous key.

For key rotation, stop Server, take a matched catalog/key backup, generate the
new private file, and leave the current key configuration in place. Run
`server_app.py --config config/server.json --rotate-totp-key PATH_TO_NEW_KEY`
with the Server interpreter. On success, configure the new file and restart.
On Windows, the destination `windows-dpapi` rewraps the seeds under the
current Windows account. Unset the key-file variable before the next start in
that case. Existing authenticator codes and enrollment status continue to work.

To recover an administrator account, stop the server and open PowerShell in the
installation folder as the Windows user who manages the data. Run the command
with the administrator's email address. Enter a new password at the prompt.
Recovery revokes the account's sessions and API keys. Set up two-factor
authentication again at the next sign-in and create new API keys if needed.

```powershell
& .\.venv\Scripts\python.exe -B .\server_app.py --config .\config\server.json --recover-admin admin@example.com
```

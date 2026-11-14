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

To recover an administrator account, stop the server and open PowerShell in the
installation folder as the Windows user who manages the data. Run the command
with the administrator's email address. Enter a new password at the prompt.
Recovery revokes the account's sessions and API keys. Set up two-factor
authentication again at the next sign-in and create new API keys if needed.

```powershell
& .\.venv\Scripts\python.exe -B .\server_app.py --config .\config\server.json --recover-admin admin@example.com
```

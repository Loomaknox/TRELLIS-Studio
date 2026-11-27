using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        try
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string mode = "desktop";
            bool start = false, browser = true;
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--mode" && i + 1 < args.Length) mode = args[++i];
                else if (args[i] == "--root" && i + 1 < args.Length) root = args[++i];
                else if (args[i] == "--start") start = true;
                else if (args[i] == "--no-browser") browser = false;
                else throw new ArgumentException("Use --mode desktop|server [--start] [--no-browser].");
            }
            if (mode != "desktop" && mode != "server") throw new ArgumentException("Unknown Studio mode.");
            root = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);
            if (!File.Exists(Path.Combine(root, "installer", "windows", "Tray-Control.ps1")))
                throw new FileNotFoundException("Keep the tray executable in the TRELLIS installation folder.");
            string identity = TrayContext.Identity(root + "|" + mode);
            bool created;
            using (var mutex = new Mutex(true, @"Local\TRELLIS-Tray-" + identity, out created))
            {
                if (!created) { MessageBox.Show(TrayText.Get("This TRELLIS tray is already open. Look in the Windows notification area."), "TRELLIS Studio"); return; }
                try { using (var context = new TrayContext(root, mode, start, browser)) Application.Run(context); }
                finally { mutex.ReleaseMutex(); }
            }
        }
        catch (Exception error) { MessageBox.Show(TrayText.Get(error.Message), "TRELLIS Studio", MessageBoxButtons.OK, MessageBoxIcon.Error); }
    }
}

internal static class TrayText
{
    private static readonly Dictionary<string, string> French = new Dictionary<string, string> {
        { "Checking local status...", "Vérification de l’état local…" },
        { "Start ", "Démarrer " },
        { "Stop ", "Arrêter " },
        { "Open in browser", "Ouvrir dans le navigateur" },
        { "Configure Server...", "Configurer le serveur…" },
        { "Check HTTPS certificate...", "Vérifier le certificat HTTPS…" },
        { "Open local Studio tray", "Ouvrir le menu de Studio local" },
        { "Open Server tray", "Ouvrir le menu du serveur" },
        { "Quit tray (keep application running)", "Quitter le menu et laisser l’application en service" },
        { "Running - calculation active", "En service · calcul en cours" },
        { "Server + HTTPS proxy running locally", "Serveur et proxy HTTPS en service localement" },
        { "Running locally", "En service localement" },
        { "Stopped", "À l’arrêt" },
        { "Partially running", "Partiellement en service" },
        { "Server not configured", "Serveur à configurer" },
        { "Status unavailable / port occupied", "État indisponible ou port occupé" },
        { "Status unavailable", "État indisponible" },
        { "Starting...", "Démarrage…" },
        { "Stopping...", "Arrêt…" },
        { "Checking HTTPS...", "Vérification HTTPS…" },
        { "Configuring...", "Configuration…" },
        { "This TRELLIS tray is already open. Look in the Windows notification area.", "Le menu TRELLIS est déjà ouvert dans la zone de notification Windows." },
        { "Keep the tray executable in the TRELLIS installation folder.", "Conservez l’exécutable du menu dans le dossier d’installation de TRELLIS." },
        { "The command is taking longer than expected. It is still running; no service was forcibly stopped.", "La commande prend plus de temps que prévu. Elle se poursuit et les services restent en cours d’exécution." },
        { "The command failed. Check the application logs.", "La commande a échoué. Consultez les journaux de l’application." },
        { "Another TRELLIS startup or installation is running. Wait for it to finish.", "Un démarrage ou une installation de TRELLIS est déjà en cours. Attendez sa fin." },
        { "Choose Server mode to configure network access.", "Choisissez le mode Serveur pour configurer l’accès réseau." },
        { "Choose Server Internet mode to check HTTPS.", "Choisissez le mode Serveur Internet pour vérifier HTTPS." },
        { "The bridge port is used by another application.", "Une autre application utilise le port de la passerelle." },
        { "The Studio port is used by another application.", "Une autre application utilise le port de Studio." },
        { "The listener did not identify itself as local Studio.", "Le service sur ce port ne s’est pas identifié comme Studio local." },
    };

    internal static string Get(string text)
    {
        string translation;
        return System.Globalization.CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "fr"
            && French.TryGetValue(text, out translation) ? translation : text;
    }
}

internal sealed class TrayContext : ApplicationContext
{
    private readonly string root, mode, script;
    private readonly NotifyIcon tray;
    private readonly Icon icon;
    private readonly ContextMenuStrip menu;
    private readonly ToolStripMenuItem status, start, stop, configure, open, testHttps;
    private readonly System.Windows.Forms.Timer timer;
    private bool running, checking, disposed;
    private string url;

    internal TrayContext(string root, string mode, bool autoStart, bool openBrowser)
    {
        this.root = root; this.mode = mode;
        script = Path.Combine(root, "installer", "windows", "Tray-Control.ps1");
        string title = mode == "server" ? "TRELLIS Server" : "TRELLIS Studio";
        icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        status = new ToolStripMenuItem(TrayText.Get("Checking local status...")) { Enabled = false };
        start = new ToolStripMenuItem(TrayText.Get("Start ") + title) { Enabled = false };
        stop = new ToolStripMenuItem(TrayText.Get("Stop ") + title) { Enabled = false };
        open = new ToolStripMenuItem(TrayText.Get("Open in browser")) { Enabled = false };
        configure = new ToolStripMenuItem(TrayText.Get("Configure Server...")) { Visible = mode == "server" };
        testHttps = new ToolStripMenuItem(TrayText.Get("Check HTTPS certificate...")) { Visible = false };
        var other = new ToolStripMenuItem(TrayText.Get(mode == "server" ? "Open local Studio tray" : "Open Server tray"));
        var quit = new ToolStripMenuItem(TrayText.Get("Quit tray (keep application running)"));
        menu = new ContextMenuStrip();
        menu.Items.AddRange(new ToolStripItem[] { status, new ToolStripSeparator(), start, stop, open, configure, testHttps,
            other, new ToolStripSeparator(), quit });
        start.Click += async (sender, e) => await ActionAsync("Start", true);
        stop.Click += async (sender, e) => await ActionAsync("Stop", false);
        open.Click += (sender, e) => OpenBrowser();
        configure.Click += async (sender, e) => await ActionAsync("Configure", false);
        testHttps.Click += async (sender, e) => await ActionAsync("TestHttps", false);
        other.Click += (sender, e) => {
            try { Process.Start(new ProcessStartInfo(Application.ExecutablePath, "--mode " + (mode == "server" ? "desktop" : "server") + " --root \"" + root + "\"") { UseShellExecute = true }); }
            catch (Exception error) { ShowError(error.Message); }
        };
        quit.Click += (sender, e) => ExitThread();
        menu.Opening += async (sender, e) => await RefreshAsync();
        tray = new NotifyIcon { Icon = icon ?? SystemIcons.Application, Text = title, ContextMenuStrip = menu, Visible = true };
        tray.MouseDoubleClick += (sender, e) => { if (e.Button == MouseButtons.Left) OpenBrowser(); };
        timer = new System.Windows.Forms.Timer { Interval = 5000 };
        timer.Tick += async (sender, e) => await RefreshAsync();
        timer.Start();
        // Start after the WinForms message loop is ready; Quit remains available throughout.
        EventHandler first = null;
        first = async (sender, e) => {
            Application.Idle -= first;
            if (autoStart) await ActionAsync("Start", openBrowser); else await RefreshAsync();
        };
        Application.Idle += first;
    }

    internal static string Identity(string value)
    {
        using (var hash = SHA256.Create())
            return BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(value.ToLowerInvariant()))).Replace("-", "");
    }

    private void Status(string value)
    {
        value = TrayText.Get(value);
        status.Text = value;
        string text = (mode == "server" ? "TRELLIS Server: " : "TRELLIS Studio: ") + value;
        tray.Text = text.Length > 63 ? text.Substring(0, 63) : text;
    }

    private async Task RefreshAsync()
    {
        if (running || checking || disposed) return;
        checking = true;
        try
        {
            var result = await Task.Run(() => RunCommand(root, mode, "Status"));
            if (running || disposed) return;
            if (result.Error != null) throw new IOException(result.Error);
            var info = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(result.Output);
            string state = info.ContainsKey("state") ? Convert.ToString(info["state"]) : "unavailable";
            url = info.ContainsKey("url") ? Convert.ToString(info["url"]) : null;
            bool internet = info.ContainsKey("internet") && Convert.ToBoolean(info["internet"]);
            bool busy = info.ContainsKey("busy") && Convert.ToBoolean(info["busy"]);
            Status(state == "running" ? (busy ? "Running - calculation active" : internet ? "Server + HTTPS proxy running locally" : "Running locally") :
                   state == "stopped" ? "Stopped" : state == "partial" ? "Partially running" : state == "unconfigured" ? "Server not configured" : "Status unavailable / port occupied");
            start.Enabled = state == "stopped" || state == "partial";
            stop.Enabled = state == "running" || state == "partial";
            configure.Enabled = state == "stopped" || state == "unconfigured";
            testHttps.Visible = internet;
            testHttps.Enabled = state == "running";
            open.Enabled = !String.IsNullOrEmpty(url);
        }
        catch (Exception)
        {
            if (!disposed && !running) { Status("Status unavailable"); start.Enabled = stop.Enabled = false; configure.Enabled = false; }
        }
        finally { checking = false; }
    }

    private async Task ActionAsync(string action, bool openBrowser)
    {
        if (running || disposed) return;
        running = true;
        start.Enabled = stop.Enabled = configure.Enabled = testHttps.Enabled = false;
        Status(action == "Start" ? "Starting..." : action == "Stop" ? "Stopping..." : action == "TestHttps" ? "Checking HTTPS..." : "Configuring...");
        CommandResult result;
        try { result = await Task.Run(() => RunCommand(root, mode, action)); }
        catch (Exception error) { result = new CommandResult { Error = error.Message }; }
        finally { running = false; }
        if (disposed) return;
        await RefreshAsync();
        if (disposed) return;
        if (result.Error != null) ShowError(result.Error);
        else if (action == "TestHttps") MessageBox.Show(result.Output.Trim(), "TRELLIS HTTPS", MessageBoxButtons.OK, MessageBoxIcon.Information);
        else if (openBrowser) OpenBrowser();
    }

    internal sealed class CommandResult { public string Error; public string Output; }

    internal static CommandResult RunCommand(string root, string mode, string action)
    {
        // File receipts avoid EOF waits on anonymous pipes inherited by long-lived services.
        string receipt = Path.GetTempFileName();
        string errorPath = Path.GetTempFileName();
        string shell = Path.Combine(Environment.SystemDirectory, @"WindowsPowerShell\v1.0\powershell.exe");
        const string command = "$ErrorActionPreference='Stop'; $lock=$null; $acquired=$false; try { " +
            "if ($env:TRELLIS_TRAY_ACTION -ne 'Status') { " +
            "$lock=New-Object Threading.Mutex($false, $env:TRELLIS_TRAY_LOCK); " +
            "try { $acquired=$lock.WaitOne(0) } catch [Threading.AbandonedMutexException] { $acquired=$true }; " +
            "if (!$acquired) { throw 'Another tray command is still running.' } }; " +
            "$result=& $env:TRELLIS_TRAY_SCRIPT -Mode $env:TRELLIS_TRAY_MODE -Action $env:TRELLIS_TRAY_ACTION; " +
            "[IO.File]::WriteAllText($env:TRELLIS_TRAY_OUTPUT, ($result -join [Environment]::NewLine)); exit 0 " +
            "} catch { [IO.File]::WriteAllText($env:TRELLIS_TRAY_ERROR, $_.Exception.Message); exit 1 } " +
            "finally { if ($acquired) { $lock.ReleaseMutex() }; if ($lock) { $lock.Dispose() } }";
        var settings = new ProcessStartInfo(shell, "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command \"" + command + "\"") {
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = root
        };
        settings.EnvironmentVariables["TRELLIS_TRAY_SCRIPT"] = Path.Combine(root, "installer", "windows", "Tray-Control.ps1");
        settings.EnvironmentVariables["TRELLIS_TRAY_MODE"] = mode;
        settings.EnvironmentVariables["TRELLIS_TRAY_ACTION"] = action;
        settings.EnvironmentVariables["TRELLIS_TRAY_OUTPUT"] = receipt;
        settings.EnvironmentVariables["TRELLIS_TRAY_ERROR"] = errorPath;
        settings.EnvironmentVariables["TRELLIS_TRAY_LOCK"] = @"Local\TRELLIS-Tray-Action-" + Identity(root);
        bool finished = false;
        try
        {
            using (var process = Process.Start(settings))
            {
                finished = process.WaitForExit(action == "Status" ? 20000 : action == "Configure" ? 1800000 : 600000);
                if (!finished) return new CommandResult { Error = "The command is taking longer than expected. It is still running; no service was forcibly stopped." };
                if (process.ExitCode != 0)
                {
                    string detail = File.ReadAllText(errorPath).Trim();
                    if (detail.Length > 1500) detail = detail.Substring(0, 1500);
                    return new CommandResult { Error = detail.Length == 0 ? "The command failed. Check the application logs." : detail };
                }
                return new CommandResult { Output = File.ReadAllText(receipt) };
            }
        }
        finally
        {
            if (finished) { File.Delete(receipt); File.Delete(errorPath); }
        }
    }

    private void OpenBrowser()
    {
        if (String.IsNullOrEmpty(url)) return;
        Uri address;
        if (!Uri.TryCreate(url, UriKind.Absolute, out address) || (address.Scheme != "http" && address.Scheme != "https")) return;
        try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
        catch (Exception error) { ShowError(error.Message); }
    }
    private static void ShowError(string message)
    {
        MessageBox.Show(TrayText.Get(message), "TRELLIS Studio", MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }
    protected override void Dispose(bool disposing)
    {
        disposed = true;
        if (disposing) { timer.Dispose(); tray.Visible = false; tray.Dispose(); menu.Dispose(); if (icon != null) icon.Dispose(); }
        base.Dispose(disposing);
    }
}

using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

internal static class TrayRegression
{
    [STAThread]
    private static int Main(string[] args)
    {
        string temp = Path.Combine(Path.GetTempPath(), "trellis-tray-" + Guid.NewGuid().ToString("N"));
        Process child = null;
        try
        {
            if (args.Length != 1) throw new ArgumentException("Pass the compiled TRELLIS Studio Tray.exe path.");
            Directory.CreateDirectory(Path.Combine(temp, "installer", "windows"));
            string stub = Path.Combine(temp, "installer", "windows", "Tray-Control.ps1");
            File.WriteAllText(stub, @"
param($Mode,$Action)
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if ($Action -eq 'Status') { '{""state"":""stopped"",""url"":""http://127.0.0.1:1""}'; return }
if ($Action -eq 'Stop') { throw 'TRELLIS Server is processing a job. Fixture refusal.' }
if (Test-Path -LiteralPath (Join-Path $root 'ui-fixture')) { Start-Sleep -Seconds 4; return }
$child=Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList '-NoProfile -NonInteractive -Command Start-Sleep -Seconds 12' -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $root 'child.out') -RedirectStandardError (Join-Path $root 'child.err')
[IO.File]::WriteAllText((Join-Path $root 'child.pid'),[string]$child.Id)
'Started fixture'
");
            var assembly = Assembly.LoadFile(Path.GetFullPath(args[0]));
            Type type = assembly.GetType("TrayContext", true);
            var command = type.GetMethod("RunCommand", BindingFlags.Static | BindingFlags.NonPublic);
            var watch = Stopwatch.StartNew();
            object result = command.Invoke(null, new object[] { temp, "server", "Start" });
            watch.Stop();
            string error = (string)result.GetType().GetField("Error").GetValue(result);
            if (error != null) throw new Exception(error);
            child = Process.GetProcessById(Int32.Parse(File.ReadAllText(Path.Combine(temp, "child.pid"))));
            if (watch.Elapsed.TotalSeconds > 8 || child.HasExited) throw new Exception("The launcher waited for the long-lived descendant.");
            result = command.Invoke(null, new object[] { temp, "server", "Stop" });
            error = (string)result.GetType().GetField("Error").GetValue(result);
            if (error == null || !error.Contains("processing a job")) throw new Exception("Busy refusal did not reach the tray.");

            // Exercise the actual configuration form through the hidden-console tray runner.
            // Add fixture-only observation/cancel handlers; never submit or save settings.
            string sourceRoot = Path.GetDirectoryName(Path.GetFullPath(args[0]));
            string configureSource = File.ReadAllText(Path.Combine(sourceRoot, "installer", "windows", "Configure-Server.ps1"));
            string observer = @"
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class FixtureWindow { [DllImport(""user32.dll"")] public static extern bool IsWindowVisible(IntPtr hWnd); }'
$fixtureTrace=Join-Path $taskRoot 'configure-visible.txt'
$fixtureTimer=New-Object Windows.Forms.Timer
$fixtureTimer.Interval=300
$fixtureTimer.Add_Tick({
    $fixtureTimer.Stop()
    $access.SelectedIndex=2
    $advanced.Checked=$true
    [IO.File]::AppendAllText($fixtureTrace, (';internet='+$domain.Visible+';advanced='+$backendPort.Visible+';buttonsInside='+($save.Bottom -le $taskForm.ClientSize.Height)))
    $taskForm.DialogResult='Cancel'
    $taskForm.Close()
})
$taskForm.Add_Shown({
    [IO.File]::WriteAllText($fixtureTrace, ('visible='+[FixtureWindow]::IsWindowVisible($taskForm.Handle)))
    $fixtureTimer.Start()
})
";
            if (!configureSource.Contains("$save.Add_Click({")) throw new Exception("The configuration fixture insertion point changed.");
            configureSource = configureSource.Replace("$save.Add_Click({", observer + "\n$save.Add_Click({");
            File.WriteAllText(Path.Combine(temp, "installer", "windows", "Configure-Server.ps1"), configureSource);
            File.Copy(Path.Combine(sourceRoot, "installer", "windows", "check-idle.ps1"), Path.Combine(temp, "installer", "windows", "check-idle.ps1"));
            string originalStub = File.ReadAllText(stub);
            File.WriteAllText(stub, @"
param($Mode,$Action)
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
& (Join-Path $PSScriptRoot 'Configure-Server.ps1') -ConfigPath (Join-Path $root 'config/server.json') -Python 'unused-fixture-python'
");
            result = command.Invoke(null, new object[] { temp, "server", "Configure" });
            error = (string)result.GetType().GetField("Error").GetValue(result);
            if (error == null || !error.Contains("cancelled")) throw new Exception("The real configuration form did not cancel normally: " + error);
            string visible = File.ReadAllText(Path.Combine(temp, "configure-visible.txt"));
            if (visible != "visible=True;internet=True;advanced=True;buttonsInside=True") throw new Exception("The real configuration window was hidden or clipped: " + visible);
            if (File.Exists(Path.Combine(temp, "config", "server.json"))) throw new Exception("Cancelling configuration wrote preferences.");
            File.WriteAllText(stub, originalStub);

            File.WriteAllText(Path.Combine(temp, "ui-fixture"), "1");
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            var constructor = type.GetConstructor(BindingFlags.Instance | BindingFlags.NonPublic, null,
                new Type[] { typeof(string), typeof(string), typeof(bool), typeof(bool) }, null);
            using (var context = (ApplicationContext)constructor.Invoke(new object[] { temp, "server", false, false }))
            using (var timer = new System.Windows.Forms.Timer { Interval = 300 })
            {
                int stage = 0;
                bool quitEnabled = false;
                Exception uiError = null;
                var uiWatch = Stopwatch.StartNew();
                timer.Tick += (sender, e) => {
                    try
                    {
                        if (stage++ == 0)
                            type.GetMethod("ActionAsync", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(context, new object[] { "Start", false });
                        else
                        {
                            var menu = (ContextMenuStrip)type.GetField("menu", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(context);
                            var quit = (ToolStripMenuItem)menu.Items[menu.Items.Count - 1];
                            quitEnabled = quit.Enabled;
                            if (!quitEnabled) throw new Exception("Quit was disabled while a command was running.");
                            timer.Stop();
                            quit.PerformClick();
                        }
                    }
                    catch (Exception errorInUi) { uiError = errorInUi; timer.Stop(); context.ExitThread(); }
                };
                timer.Start();
                Application.Run(context);
                uiWatch.Stop();
                if (uiError != null) throw uiError;
                if (!quitEnabled || uiWatch.Elapsed.TotalSeconds > 3) throw new Exception("Quitting waited for the pending command.");
            }
            // Let the isolated worker finish its receipts after the test UI has closed.
            Thread.Sleep(4500);
            if (!child.WaitForExit(15000)) throw new Exception("The fixture child did not finish naturally.");
            Console.WriteLine("PASS: child-handle regression ({0:F2}s), busy error forwarding, visible real configuration dialog/cancel, real WinForms Quit during a command.", watch.Elapsed.TotalSeconds);
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        finally
        {
            bool canClean = child == null || child.HasExited;
            if (child != null) child.Dispose();
            string parent = Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar);
            if (canClean && Directory.Exists(temp) && Path.GetDirectoryName(Path.GetFullPath(temp)) == parent &&
                Path.GetFileName(temp).StartsWith("trellis-tray-", StringComparison.Ordinal)) Directory.Delete(temp, true);
        }
    }
}

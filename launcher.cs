using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Urban Flow")]
[assembly: AssemblyDescription("Urban Flow Adaptive Traffic Signal System")]
[assembly: AssemblyConfiguration("Release")]
[assembly: AssemblyCompany("Urban Flow")]
[assembly: AssemblyProduct("Urban Flow Desktop Application")]
[assembly: AssemblyCopyright("Copyright © 2026 Harsh Aggarwal")]
[assembly: AssemblyTrademark("Urban Flow")]
[assembly: AssemblyCulture("")]
[assembly: ComVisible(false)]
[assembly: Guid("8B8159E5-FA49-4B52-8703-9A924654921E")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
[assembly: AssemblyInformationalVersion("1.0.0")]

namespace UrbanFlowLauncher
{
    static class Program
    {
        private const string MutexName = "Local\\UrbanFlow_Application_SingleInstance_Mutex";
        private const int SW_RESTORE = 9;

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool DeleteFile(string lpFileName);

        private static void UnblockFile(string path)
        {
            try
            {
                if (File.Exists(path))
                {
                    // Deletes NTFS Zone.Identifier stream (Mark of the Web) to prevent SmartScreen popups
                    DeleteFile(path + ":Zone.Identifier");
                }
            }
            catch
            {
                // Silently ignore if not on NTFS or stream absent
            }
        }

        private static void ActivateExistingInstance()
        {
            try
            {
                Process current = Process.GetCurrentProcess();
                foreach (Process proc in Process.GetProcessesByName("Urban Flow"))
                {
                    if (proc.Id != current.Id && proc.MainWindowHandle != IntPtr.Zero)
                    {
                        ShowWindowAsync(proc.MainWindowHandle, SW_RESTORE);
                        SetForegroundWindow(proc.MainWindowHandle);
                        return;
                    }
                }
            }
            catch { }
        }

        private static string LocateElectronExecutable(string baseDir, out string workingDir)
        {
            // 1. Direct frontend bundle in application directory
            string localFrontend = Path.Combine(baseDir, "frontend");
            string localElectron = Path.Combine(localFrontend, "node_modules", "electron", "dist", "electron.exe");
            if (File.Exists(localElectron))
            {
                workingDir = localFrontend;
                return localElectron;
            }

            // 2. Installed AppData/Local path fallback
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string appDataFrontend = Path.Combine(localAppData, "Programs", "Urban Flow", "frontend");
            string appDataElectron = Path.Combine(appDataFrontend, "node_modules", "electron", "dist", "electron.exe");
            if (File.Exists(appDataElectron))
            {
                workingDir = appDataFrontend;
                return appDataElectron;
            }

            workingDir = localFrontend;
            return null;
        }

        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            // Single-Instance Mutex: prevents duplicate instances and orphaned process cascades
            bool createdNew;
            using (Mutex mutex = new Mutex(true, MutexName, out createdNew))
            {
                if (!createdNew)
                {
                    ActivateExistingInstance();
                    return;
                }

                try
                {
                    string appDir = AppDomain.CurrentDomain.BaseDirectory;

                    // Unblock launcher executable itself if extracted from a web download archive
                    try
                    {
                        string currentExe = Process.GetCurrentProcess().MainModule.FileName;
                        UnblockFile(currentExe);
                    }
                    catch { }

                    string workingDir;
                    string electronExe = LocateElectronExecutable(appDir, out workingDir);

                    if (string.IsNullOrEmpty(electronExe) || !File.Exists(electronExe))
                    {
                        MessageBox.Show(
                            "Urban Flow application components are not yet installed.\n\n" +
                            "Missing: " + Path.Combine(workingDir, "node_modules", "electron", "dist", "electron.exe") + "\n\n" +
                            "Please run 'start.bat' or the Urban Flow installer to complete setup.",
                            "Urban Flow - Component Not Found",
                            MessageBoxButtons.OK,
                            MessageBoxIcon.Warning
                        );
                        return;
                    }

                    // Unblock Electron executable before launch
                    UnblockFile(electronExe);

                    // Build arguments forwarding
                    string forwardArgs = ".";
                    if (args != null && args.Length > 0)
                    {
                        forwardArgs = ". " + string.Join(" ", args);
                    }

                    ProcessStartInfo psi = new ProcessStartInfo();
                    psi.FileName = electronExe;
                    psi.Arguments = forwardArgs;
                    psi.WorkingDirectory = workingDir;
                    psi.WindowStyle = ProcessWindowStyle.Normal;
                    psi.CreateNoWindow = false;
                    psi.UseShellExecute = false;

                    using (Process child = Process.Start(psi))
                    {
                        // Clean launch handoff
                    }
                }
                catch (Exception ex)
                {
                    MessageBox.Show(
                        "Unable to launch Urban Flow:\n\n" + ex.Message,
                        "Urban Flow Launch Error",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error
                    );
                }
            }
        }
    }
}

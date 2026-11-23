/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

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

        private static void UnblockDirectory(string dirPath, string searchPattern)
        {
            try
            {
                if (Directory.Exists(dirPath))
                {
                    foreach (string file in Directory.GetFiles(dirPath, searchPattern, SearchOption.AllDirectories))
                    {
                        UnblockFile(file);
                    }
                }
            }
            catch { }
        }

        private static bool ActivateExistingInstance(string baseDir = null)
        {
            try
            {
                // 1. Search for any visible top-level window belonging to Urban Flow
                Process[] procs = Process.GetProcesses();
                foreach (Process proc in procs)
                {
                    try
                    {
                        if (proc.MainWindowHandle != IntPtr.Zero)
                        {
                            string title = proc.MainWindowTitle;
                            if (!string.IsNullOrEmpty(title) &&
                                (title.IndexOf("Urban Flow", StringComparison.OrdinalIgnoreCase) >= 0 ||
                                 title.IndexOf("UrbanFlow", StringComparison.OrdinalIgnoreCase) >= 0))
                            {
                                ShowWindowAsync(proc.MainWindowHandle, SW_RESTORE);
                                SetForegroundWindow(proc.MainWindowHandle);
                                return true;
                            }
                        }
                    }
                    catch { }
                    finally
                    {
                        try { proc.Dispose(); } catch { }
                    }
                }

                // 2. Search for any running electron process originating from baseDir
                if (!string.IsNullOrEmpty(baseDir) && Directory.Exists(baseDir))
                {
                    string fullBaseDir = Path.GetFullPath(baseDir).TrimEnd('\\');
                    Process[] electronProcs = Process.GetProcessesByName("electron");
                    foreach (Process proc in electronProcs)
                    {
                        try
                        {
                            if (proc.MainModule != null)
                            {
                                string modPath = Path.GetFullPath(proc.MainModule.FileName);
                                if (modPath.StartsWith(fullBaseDir, StringComparison.OrdinalIgnoreCase))
                                {
                                    if (proc.MainWindowHandle != IntPtr.Zero)
                                    {
                                        ShowWindowAsync(proc.MainWindowHandle, SW_RESTORE);
                                        SetForegroundWindow(proc.MainWindowHandle);
                                    }
                                    return true;
                                }
                            }
                        }
                        catch { }
                        finally
                        {
                            try { proc.Dispose(); } catch { }
                        }
                    }
                }
            }
            catch { }
            return false;
        }

        public static bool LocateElectron(string baseDir, out string electronExe, out string frontendDir)
        {
            electronExe = null;
            frontendDir = null;
            if (!string.IsNullOrWhiteSpace(baseDir))
            {
                string localFrontend = Path.Combine(baseDir, "frontend");
                string localElectron = Path.Combine(localFrontend, "node_modules", "electron", "dist", "electron.exe");
                if (File.Exists(localElectron) && Directory.Exists(localFrontend))
                {
                    electronExe = Path.GetFullPath(localElectron);
                    frontendDir = Path.GetFullPath(localFrontend);
                    return true;
                }

                string directElectron = Path.Combine(baseDir, "node_modules", "electron", "dist", "electron.exe");
                if (File.Exists(directElectron) && Directory.Exists(baseDir))
                {
                    electronExe = Path.GetFullPath(directElectron);
                    frontendDir = Path.GetFullPath(baseDir);
                    return true;
                }
            }

            // 2. Program Files (Machine-wide installation trusted by AppLocker / Software Restriction Policies)
            string progFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            if (!string.IsNullOrEmpty(progFiles))
            {
                string pfFrontend = Path.Combine(progFiles, "Urban Flow", "frontend");
                string pfElectron = Path.Combine(pfFrontend, "node_modules", "electron", "dist", "electron.exe");
                if (File.Exists(pfElectron))
                {
                    electronExe = Path.GetFullPath(pfElectron);
                    frontendDir = Path.GetFullPath(pfFrontend);
                    return true;
                }
            }

            // 3. Program Files (x86)
            string progFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
            if (!string.IsNullOrEmpty(progFilesX86))
            {
                string pfx86Frontend = Path.Combine(progFilesX86, "Urban Flow", "frontend");
                string pfx86Electron = Path.Combine(pfx86Frontend, "node_modules", "electron", "dist", "electron.exe");
                if (File.Exists(pfx86Electron))
                {
                    electronExe = Path.GetFullPath(pfx86Electron);
                    frontendDir = Path.GetFullPath(pfx86Frontend);
                    return true;
                }
            }

            // 4. Per-user LocalAppData fallback
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string appDataFrontend = Path.Combine(localAppData, "Programs", "Urban Flow", "frontend");
            string appDataElectron = Path.Combine(appDataFrontend, "node_modules", "electron", "dist", "electron.exe");
            if (File.Exists(appDataElectron))
            {
                electronExe = Path.GetFullPath(appDataElectron);
                frontendDir = Path.GetFullPath(appDataFrontend);
                return true;
            }

            return false;
        }

        public static bool LaunchElectron(string baseDir, string extraArgs = null)
        {
            string electronExe, frontendDir;
            if (!LocateElectron(baseDir, out electronExe, out frontendDir))
            {
                return false;
            }

            UnblockFile(electronExe);

            try
            {
                string nodeModules = Path.Combine(frontendDir, "node_modules");
                UnblockDirectory(nodeModules, "*.node");
                UnblockDirectory(nodeModules, "*.exe");
            }
            catch { }

            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = electronExe;
            string arguments = "\"" + frontendDir + "\"";
            if (!string.IsNullOrWhiteSpace(extraArgs))
            {
                arguments += " " + extraArgs.Trim();
            }
            psi.Arguments = arguments;
            psi.WorkingDirectory = frontendDir;
            psi.WindowStyle = ProcessWindowStyle.Normal;
            psi.CreateNoWindow = false;
            psi.UseShellExecute = true;

            Process.Start(psi);
            return true;
        }

        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            string appDir = AppDomain.CurrentDomain.BaseDirectory;

            // Immediately check if an instance of Urban Flow is already running.
            // If running, restore and focus the existing window and exit without spawning another process.
            if (ActivateExistingInstance(appDir))
            {
                return;
            }

            // Single-Instance Mutex: prevents rapid duplicate launches in quick succession
            bool createdNew;
            using (Mutex mutex = new Mutex(true, MutexName, out createdNew))
            {
                if (!createdNew)
                {
                    ActivateExistingInstance(appDir);
                    return;
                }

                try
                {
                    // Unblock launcher executable itself if extracted from a web download archive
                    try
                    {
                        string currentExe = Process.GetCurrentProcess().MainModule.FileName;
                        UnblockFile(currentExe);
                    }
                    catch { }

                    string electronExe, workingDir;
                    if (!LocateElectron(appDir, out electronExe, out workingDir))
                    {
                        // Search for Urban Flow Setup.exe in nearby locations
                        string parentDir = null;
                        try { parentDir = Directory.GetParent(appDir) != null ? Directory.GetParent(appDir).FullName : null; } catch { }

                        string[] candidateInstallerPaths = new string[]
                        {
                            Path.Combine(appDir, "Urban Flow Setup.exe"),
                            parentDir != null ? Path.Combine(parentDir, "Urban Flow Setup.exe") : "",
                            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "Urban Flow Setup.exe"),
                            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "Urban Flow Setup.exe"),
                        };

                        string foundInstaller = null;
                        foreach (string path in candidateInstallerPaths)
                        {
                            if (!string.IsNullOrEmpty(path) && File.Exists(path))
                            {
                                foundInstaller = path;
                                break;
                            }
                        }

                        if (!string.IsNullOrEmpty(foundInstaller))
                        {
                            DialogResult result = MessageBox.Show(
                                "Urban Flow is not yet installed on this computer.\n\n" +
                                "Installer found:\n" + foundInstaller + "\n\n" +
                                "Would you like to run the installer now to complete setup in 1 click?",
                                "Urban Flow - Installation Required",
                                MessageBoxButtons.YesNo,
                                MessageBoxIcon.Information
                            );

                            if (result == DialogResult.Yes)
                            {
                                Process.Start(new ProcessStartInfo
                                {
                                    FileName = foundInstaller,
                                    UseShellExecute = true
                                });
                            }
                            return;
                        }

                        MessageBox.Show(
                            "Urban Flow requires the bundled Electron runtime to run securely with Smart App Control.\n\n" +
                            "The runtime was not found at:\n" + Path.Combine(appDir, "frontend", "node_modules", "electron", "dist", "electron.exe") + "\n\n" +
                            "Please run 'Urban Flow Setup.exe' to install or repair the application.",
                            "Urban Flow Setup Required",
                            MessageBoxButtons.OK,
                            MessageBoxIcon.Information
                        );
                        return;
                    }

                    string forwardArgs = null;
                    if (args != null && args.Length > 0)
                    {
                        forwardArgs = string.Join(" ", args);
                    }

                    if (!LaunchElectron(workingDir, forwardArgs))
                    {
                        throw new Exception("Failed to start Electron process from: " + electronExe);
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

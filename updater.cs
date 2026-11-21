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
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Urban Flow Update")]
[assembly: AssemblyDescription("Urban Flow Adaptive Traffic Signal System Updater")]
[assembly: AssemblyConfiguration("Release")]
[assembly: AssemblyCompany("Urban Flow")]
[assembly: AssemblyProduct("Urban Flow Desktop Application")]
[assembly: AssemblyCopyright("Copyright © 2026 Harsh Aggarwal")]
[assembly: AssemblyTrademark("Urban Flow")]
[assembly: AssemblyCulture("")]
[assembly: ComVisible(false)]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace UrbanFlowUpdater
{
    public static class Program
    {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool DeleteFile(string lpFileName);

        private static void UnblockFile(string path)
        {
            try
            {
                if (File.Exists(path))
                {
                    DeleteFile(path + ":Zone.Identifier");
                }
            }
            catch { }
        }

        private static void UnblockDirectory(string dirPath)
        {
            try
            {
                if (Directory.Exists(dirPath))
                {
                    foreach (string file in Directory.GetFiles(dirPath, "*.*", SearchOption.AllDirectories))
                    {
                        UnblockFile(file);
                    }
                }
            }
            catch { }
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

                // Restrict post-update lookup to the specified installation to avoid launching an unrelated instance
                return false;
            }

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

            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (!string.IsNullOrEmpty(localAppData))
            {
                string appDataFrontend = Path.Combine(localAppData, "Programs", "Urban Flow", "frontend");
                string appDataElectron = Path.Combine(appDataFrontend, "node_modules", "electron", "dist", "electron.exe");
                if (File.Exists(appDataElectron))
                {
                    electronExe = Path.GetFullPath(appDataElectron);
                    frontendDir = Path.GetFullPath(appDataFrontend);
                    return true;
                }
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

        public static bool IsSafeZipEntry(string entryFullName, string targetDir, out string canonicalDestPath)
        {
            canonicalDestPath = null;
            if (string.IsNullOrWhiteSpace(entryFullName) || string.IsNullOrWhiteSpace(targetDir))
                return false;

            // Reject null bytes and invalid path characters
            if (entryFullName.IndexOf('\0') >= 0 || entryFullName.IndexOfAny(Path.GetInvalidPathChars()) >= 0)
                return false;

            // Reject explicit directory traversal components (e.g. ".." as a path segment)
            string[] segments = entryFullName.Split(new char[] { '/', '\\' }, StringSplitOptions.None);
            foreach (string seg in segments)
            {
                if (seg.Trim() == "..")
                    return false;
            }

            // Reject rooted, drive-letter, UNC, and device paths
            if (entryFullName.StartsWith("/") || entryFullName.StartsWith("\\") || entryFullName.Contains(":"))
                return false;
            if (Path.IsPathRooted(entryFullName))
                return false;

            // Normalize slashes to current platform directory separator
            string normalizedEntry = entryFullName.Replace(Path.AltDirectorySeparatorChar, Path.DirectorySeparatorChar);

            // Canonicalize target root and ensure trailing separator
            string canonicalRoot;
            try
            {
                canonicalRoot = Path.GetFullPath(targetDir);
            }
            catch
            {
                return false;
            }
            if (!canonicalRoot.EndsWith(Path.DirectorySeparatorChar.ToString()))
                canonicalRoot += Path.DirectorySeparatorChar;

            // Combine and canonicalize destination path
            string fullDest;
            try
            {
                string combinedPath = Path.Combine(canonicalRoot, normalizedEntry);
                fullDest = Path.GetFullPath(combinedPath);
            }
            catch
            {
                return false;
            }

            // Determine if entry is root directory itself or descendant
            string rootWithoutTrailingSep = canonicalRoot.TrimEnd(Path.DirectorySeparatorChar);
            bool isRoot = string.Equals(fullDest, rootWithoutTrailingSep, StringComparison.OrdinalIgnoreCase);
            bool isDescendant = fullDest.StartsWith(canonicalRoot, StringComparison.OrdinalIgnoreCase);

            bool isDirectoryEntry = entryFullName.EndsWith("/") || entryFullName.EndsWith("\\");
            if (!isDescendant && !(isRoot && isDirectoryEntry))
                return false;

            canonicalDestPath = fullDest;
            return true;
        }

        public static bool HasReparsePointInPath(string fullPath, string rootDir)
        {
            try
            {
                if (string.IsNullOrWhiteSpace(fullPath) || string.IsNullOrWhiteSpace(rootDir))
                    return true;

                string canonicalRoot = Path.GetFullPath(rootDir).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                string canonicalTarget = Path.GetFullPath(fullPath);

                string checkPath = canonicalTarget;
                while (!string.IsNullOrEmpty(checkPath) && !File.Exists(checkPath) && !Directory.Exists(checkPath))
                {
                    checkPath = Path.GetDirectoryName(checkPath);
                }

                if (string.IsNullOrEmpty(checkPath))
                {
                    checkPath = canonicalRoot;
                }

                DirectoryInfo current = File.Exists(checkPath)
                    ? new DirectoryInfo(Path.GetDirectoryName(checkPath))
                    : new DirectoryInfo(checkPath);

                while (current != null)
                {
                    if ((current.Attributes & FileAttributes.ReparsePoint) != 0)
                    {
                        return true;
                    }
                    if (string.Equals(current.FullName.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar), canonicalRoot, StringComparison.OrdinalIgnoreCase))
                    {
                        break;
                    }
                    current = current.Parent;
                }

                return false;
            }
            catch
            {
                return true;
            }
        }

        public static int ExtractArchiveSafely(ZipArchive zip, string targetDir, Action<int, string> progress = null, bool strict = false)
        {
            int total = zip.Entries.Count;
            int extractedCount = 0;
            int done = 0;

            foreach (ZipArchiveEntry entry in zip.Entries)
            {
                string fullDestPath;
                if (!IsSafeZipEntry(entry.FullName, targetDir, out fullDestPath))
                {
                    if (strict) throw new System.IO.InvalidDataException(string.Format("Unsafe archive entry: {0}", entry.FullName));
                    continue;
                }

                if (HasReparsePointInPath(fullDestPath, targetDir))
                {
                    if (strict) throw new System.IO.InvalidDataException(string.Format("Destination lies beneath reparse point: {0}", entry.FullName));
                    continue;
                }

                if (string.IsNullOrEmpty(entry.Name) || entry.FullName.EndsWith("/") || entry.FullName.EndsWith("\\"))
                {
                    // Directory entry
                    if (!Directory.Exists(fullDestPath))
                    {
                        Directory.CreateDirectory(fullDestPath);
                    }
                }
                else
                {
                    string dir = Path.GetDirectoryName(fullDestPath);
                    if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                    {
                        Directory.CreateDirectory(dir);
                    }

                    if (File.Exists(fullDestPath))
                    {
                        FileInfo fi = new FileInfo(fullDestPath);
                        if ((fi.Attributes & FileAttributes.ReparsePoint) != 0)
                        {
                            try
                            {
                                fi.Delete();
                            }
                            catch
                            {
                                // If the reparse point cannot be removed, skip extraction to prevent redirecting writes
                                continue;
                            }
                        }
                        else
                        {
                            try
                            {
                                File.SetAttributes(fullDestPath, FileAttributes.Normal);
                            }
                            catch { }
                        }
                    }

                    entry.ExtractToFile(fullDestPath, true);
                    UnblockFile(fullDestPath);
                    extractedCount++;
                }

                done++;
                if (progress != null && total > 0)
                {
                    int pct = 50 + (int)((done / (float)total) * 40);
                    progress(Math.Min(90, pct), entry.Name);
                }
            }

            return extractedCount;
        }

        [STAThread]
        public static void Main(string[] args)
        {
            if (args != null && args.Length > 0 && string.Equals(args[0], "--test-entry", StringComparison.OrdinalIgnoreCase))
            {
                if (args.Length < 3)
                {
                    Console.Error.WriteLine("Usage: --test-entry <entryFullName> <targetDir>");
                    Environment.Exit(1);
                    return;
                }
                string dest;
                bool safe = IsSafeZipEntry(args[1], args[2], out dest);
                Console.WriteLine(string.Format("{0}|{1}", safe ? "SAFE" : "UNSAFE", dest ?? ""));
                return;
            }

            if (args != null && args.Length > 0 && string.Equals(args[0], "--test-extract", StringComparison.OrdinalIgnoreCase))
            {
                if (args.Length < 3)
                {
                    Console.Error.WriteLine("Usage: --test-extract <zipPath> <targetDir>");
                    Environment.Exit(1);
                    return;
                }
                string zipPath = args[1];
                string outDir = args[2];
                using (FileStream fs = File.OpenRead(zipPath))
                using (ZipArchive zip = new ZipArchive(fs, ZipArchiveMode.Read))
                {
                    int count = ExtractArchiveSafely(zip, outDir);
                    Console.WriteLine("EXTRACTED:" + count);
                }
                return;
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            string targetDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs",
                "Urban Flow"
            );

            // Fallback check in current folder if portable
            string currentDir = AppDomain.CurrentDomain.BaseDirectory;
            if (File.Exists(Path.Combine(currentDir, "frontend", "package.json")))
            {
                targetDir = currentDir;
            }

            Form form = new Form
            {
                Text = "Urban Flow - Application Update",
                Size = new Size(500, 260),
                StartPosition = FormStartPosition.CenterScreen,
                FormBorderStyle = FormBorderStyle.FixedDialog,
                MaximizeBox = false,
                MinimizeBox = false,
                BackColor = Color.FromArgb(12, 14, 18),
                ForeColor = Color.FromArgb(240, 242, 245)
            };

            try
            {
                form.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            }
            catch { }

            Label lblTitle = new Label
            {
                Text = "Urban Flow Update",
                Font = new Font("Segoe UI", 16, FontStyle.Bold),
                ForeColor = Color.FromArgb(245, 190, 40),
                Location = new Point(25, 20),
                Size = new Size(450, 32)
            };
            form.Controls.Add(lblTitle);

            Label lblStatus = new Label
            {
                Text = "Applying latest 4-Direction Video and AI tracking update...",
                Font = new Font("Segoe UI", 9.5f),
                ForeColor = Color.FromArgb(160, 170, 185),
                Location = new Point(28, 58),
                Size = new Size(440, 40)
            };
            form.Controls.Add(lblStatus);

            ProgressBar progress = new ProgressBar
            {
                Location = new Point(28, 110),
                Size = new Size(430, 20),
                Style = ProgressBarStyle.Continuous,
                Value = 10
            };
            form.Controls.Add(progress);

            Button btnClose = new Button
            {
                Text = "Updating...",
                Enabled = false,
                Location = new Point(348, 160),
                Size = new Size(110, 34),
                BackColor = Color.FromArgb(30, 36, 46),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            btnClose.Click += (s, e) => form.Close();
            form.Controls.Add(btnClose);

            form.Shown += (s, e) =>
            {
                Thread updateThread = new Thread(() =>
                {
                    try
                    {
                        // 1. Close running Urban Flow or Electron instances gracefully
                        form.Invoke((MethodInvoker)delegate
                        {
                            lblStatus.Text = "Closing active Urban Flow instances...";
                            progress.Value = 25;
                        });

                        try
                        {
                            foreach (Process p in Process.GetProcessesByName("Urban Flow"))
                            {
                                try { p.CloseMainWindow(); p.WaitForExit(1000); } catch { }
                            }
                            foreach (Process p in Process.GetProcessesByName("electron"))
                            {
                                try
                                {
                                    string pPath = null;
                                    try { pPath = p.MainModule != null ? p.MainModule.FileName : null; } catch { }
                                    if (!string.IsNullOrEmpty(pPath) && pPath.IndexOf("Urban Flow", StringComparison.OrdinalIgnoreCase) >= 0)
                                    {
                                        p.Kill();
                                        p.WaitForExit(1000);
                                    }
                                }
                                catch { }
                            }
                        }
                        catch { }

                        // 2. Ensure target directory exists
                        form.Invoke((MethodInvoker)delegate
                        {
                            lblStatus.Text = "Extracting updated video tracker and UI bundles...";
                            progress.Value = 50;
                        });

                        if (!Directory.Exists(targetDir))
                        {
                            Directory.CreateDirectory(targetDir);
                        }

                        // 3. Extract embedded payload zip
                        Assembly asm = Assembly.GetExecutingAssembly();
                        using (Stream stream = asm.GetManifestResourceStream("update_payload.zip"))
                        {
                            if (stream == null)
                            {
                                throw new Exception("Embedded update payload was not found.");
                            }

                            using (ZipArchive zip = new ZipArchive(stream, ZipArchiveMode.Read))
                            {
                                // Validate all entries in update payload upfront before writing any files
                                foreach (ZipArchiveEntry entry in zip.Entries)
                                {
                                    string testDest;
                                    if (!IsSafeZipEntry(entry.FullName, targetDir, out testDest))
                                    {
                                        throw new Exception(string.Format("Embedded update payload contains rejected entry: {0}", entry.FullName));
                                    }
                                    if (HasReparsePointInPath(testDest, targetDir))
                                    {
                                        throw new Exception(string.Format("Destination path lies beneath a directory reparse point or junction: {0}", entry.FullName));
                                    }
                                }

                                int extracted = ExtractArchiveSafely(zip, targetDir, (pct, entryName) =>
                                {
                                    form.Invoke((MethodInvoker)delegate { progress.Value = pct; });
                                }, strict: true);

                                if (extracted <= 0 && zip.Entries.Count > 0)
                                {
                                    throw new Exception("Extraction failed: no files could be extracted to the destination directory.");
                                }
                            }
                        }

                        // 4. Recursive unblock
                        UnblockDirectory(Path.Combine(targetDir, "frontend"));

                        form.Invoke((MethodInvoker)delegate
                        {
                            progress.Value = 100;
                            lblStatus.Text = "Update applied successfully! Launching Urban Flow...";
                            lblStatus.ForeColor = Color.FromArgb(46, 213, 115);
                            btnClose.Text = "Launch";
                            btnClose.Enabled = true;
                        });

                        Thread.Sleep(800);

                        // 5. Launch updated application via bundled Electron runtime (Smart App Control compliant)
                        if (!LaunchElectron(targetDir))
                        {
                            MessageBox.Show(
                                "Urban Flow update was successfully applied, but the Electron runtime was not found.\n\n" +
                                "Expected location:\n" + Path.Combine(targetDir, "frontend", "node_modules", "electron", "dist", "electron.exe") + "\n\n" +
                                "Please launch Urban Flow from your Desktop shortcut or reinstall using 'Urban Flow Setup.exe'.",
                                "Urban Flow Update",
                                MessageBoxButtons.OK,
                                MessageBoxIcon.Warning
                            );
                        }

                        form.Invoke((MethodInvoker)delegate { form.Close(); });
                    }
                    catch (Exception ex)
                    {
                        form.Invoke((MethodInvoker)delegate
                        {
                            progress.Value = 0;
                            lblStatus.Text = "Update Error: " + ex.Message;
                            lblStatus.ForeColor = Color.FromArgb(235, 77, 75);
                            btnClose.Text = "Close";
                            btnClose.Enabled = true;
                        });
                    }
                });
                updateThread.IsBackground = true;
                updateThread.Start();
            };

            Application.Run(form);
        }
    }
}

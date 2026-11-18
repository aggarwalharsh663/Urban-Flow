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
    static class Program
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

        [STAThread]
        static void Main()
        {
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
                                    string pPath = p.MainModule.FileName;
                                    if (pPath.IndexOf("Urban Flow", StringComparison.OrdinalIgnoreCase) >= 0)
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
                                int total = zip.Entries.Count;
                                int done = 0;
                                foreach (ZipArchiveEntry entry in zip.Entries)
                                {
                                    string destPath = Path.Combine(targetDir, entry.FullName);
                                    if (string.IsNullOrEmpty(entry.Name))
                                    {
                                        // Directory entry
                                        Directory.CreateDirectory(destPath);
                                    }
                                    else
                                    {
                                        string dir = Path.GetDirectoryName(destPath);
                                        if (!Directory.Exists(dir))
                                        {
                                            Directory.CreateDirectory(dir);
                                        }
                                        entry.ExtractToFile(destPath, true);
                                        UnblockFile(destPath);
                                    }
                                    done++;
                                    int pct = 50 + (int)((done / (float)total) * 40);
                                    form.Invoke((MethodInvoker)delegate { progress.Value = Math.Min(90, pct); });
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

                        // 5. Launch updated application
                        string exePath = Path.Combine(targetDir, "Urban Flow.exe");
                        if (File.Exists(exePath))
                        {
                            Process.Start(new ProcessStartInfo
                            {
                                FileName = exePath,
                                WorkingDirectory = targetDir,
                                UseShellExecute = true
                            });
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

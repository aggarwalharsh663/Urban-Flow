using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Urban Flow Setup")]
[assembly: AssemblyDescription("Urban Flow Adaptive Traffic Signal System Complete Standalone Installer")]
[assembly: AssemblyConfiguration("Release")]
[assembly: AssemblyCompany("Urban Flow")]
[assembly: AssemblyProduct("Urban Flow Desktop Application")]
[assembly: AssemblyCopyright("Copyright © 2026 Harsh Aggarwal")]
[assembly: AssemblyTrademark("Urban Flow")]
[assembly: AssemblyCulture("")]
[assembly: ComVisible(false)]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace UrbanFlowSetup
{
    [ComImport]
    [Guid("00021401-0000-0000-C000-000000000046")]
    internal class ShellLink { }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("000214F9-0000-0000-C000-000000000046")]
    internal interface IShellLinkW
    {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile, int cchMaxPath, out IntPtr pfd, uint fFlags);
        void GetIDList(out IntPtr ppidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cchMaxName);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cchMaxPath);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cchMaxPath);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
        void GetHotkey(out short pwHotkey);
        void SetHotkey(short wHotkey);
        void GetShowCmd(out int piShowCmd);
        void SetShowCmd(int iShowCmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cchIconPath, out int piIcon);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, uint dwReserved);
        void Resolve(IntPtr hwnd, uint fFlags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
    }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("0000010b-0000-0000-C000-000000000046")]
    internal interface IPersistFile
    {
        void GetClassID(out Guid pClassID);
        void IsDirty();
        void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, [MarshalAs(UnmanagedType.Bool)] bool fRemember);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
        void GetCurFile([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder ppszFileName);
    }

    public class SetupForm : Form
    {
        private ProgressBar progressBar;
        private Label lblStatus;
        private Label lblTitle;
        private Label lblDesc;
        private Button btnInstall;
        private CheckBox chkDesktopShortcut;
        private CheckBox chkLaunchNow;
        private TextBox txtInstallPath;

        public static string ExpectedPayloadSha256 = "";

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool DeleteFile(string lpFileName);

        public static void UnblockFile(string path)
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

        public static void UnblockDirectory(string dirPath)
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

        public static bool FixedTimeHexEquals(string a, string b)
        {
            if (a == null || b == null || a.Length != b.Length)
                return false;
            int diff = 0;
            for (int i = 0; i < a.Length; i++)
            {
                diff |= char.ToUpperInvariant(a[i]) ^ char.ToUpperInvariant(b[i]);
            }
            return diff == 0;
        }

        public SetupForm(string initialPath = null)
        {
            InitializeComponent();

            if (!string.IsNullOrWhiteSpace(initialPath))
            {
                txtInstallPath.Text = initialPath.Trim('"', ' ');
            }
        }

        private void InitializeComponent()
        {
            this.Text = "Urban Flow Setup - Complete Standalone Installer";
            this.Size = new Size(580, 430);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.MinimizeBox = true;
            this.BackColor = Color.FromArgb(12, 14, 18);
            this.ForeColor = Color.FromArgb(240, 242, 245);

            try
            {
                this.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            }
            catch { }

            PictureBox picLogo = new PictureBox();
            picLogo.Location = new Point(30, 22);
            picLogo.Size = new Size(54, 54);
            picLogo.SizeMode = PictureBoxSizeMode.Zoom;
            try
            {
                using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("urban_flow_emblem.png"))
                {
                    if (stream != null) picLogo.Image = Image.FromStream(stream);
                }
            }
            catch { }
            if (picLogo.Image == null && this.Icon != null)
            {
                picLogo.Image = this.Icon.ToBitmap();
            }
            this.Controls.Add(picLogo);

            lblTitle = new Label();
            lblTitle.Text = "Urban Flow Setup";
            lblTitle.Font = new Font("Segoe UI", 18, FontStyle.Bold);
            lblTitle.ForeColor = Color.FromArgb(245, 190, 40);
            lblTitle.Location = new Point(96, 20);
            lblTitle.Size = new Size(430, 32);
            this.Controls.Add(lblTitle);

            lblDesc = new Label();
            lblDesc.Text = "Install Urban Flow Adaptive Traffic Signal System with local AI models, video tracking & Python runtime on this PC.";
            lblDesc.Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);
            lblDesc.ForeColor = Color.FromArgb(160, 170, 185);
            lblDesc.Location = new Point(98, 54);
            lblDesc.Size = new Size(430, 38);
            this.Controls.Add(lblDesc);

            Label lblPathTag = new Label();
            lblPathTag.Text = "Installation Directory:";
            lblPathTag.Font = new Font("Segoe UI", 9, FontStyle.Bold);
            lblPathTag.ForeColor = Color.FromArgb(226, 232, 240);
            lblPathTag.Location = new Point(32, 120);
            lblPathTag.Size = new Size(200, 22);
            this.Controls.Add(lblPathTag);

            string defaultDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs",
                "Urban Flow"
            );

            txtInstallPath = new TextBox();
            txtInstallPath.Text = defaultDir;
            txtInstallPath.Font = new Font("Segoe UI", 9.5f);
            txtInstallPath.Location = new Point(32, 145);
            txtInstallPath.Size = new Size(400, 28);
            txtInstallPath.BackColor = Color.FromArgb(23, 27, 38);
            txtInstallPath.ForeColor = Color.White;
            txtInstallPath.BorderStyle = BorderStyle.FixedSingle;
            this.Controls.Add(txtInstallPath);

            Button btnBrowse = new Button();
            btnBrowse.Text = "Browse...";
            btnBrowse.Font = new Font("Segoe UI", 9);
            btnBrowse.Location = new Point(440, 144);
            btnBrowse.Size = new Size(95, 29);
            btnBrowse.FlatStyle = FlatStyle.Flat;
            btnBrowse.BackColor = Color.FromArgb(30, 41, 59);
            btnBrowse.ForeColor = Color.FromArgb(226, 232, 240);
            btnBrowse.Click += (s, e) =>
            {
                using (FolderBrowserDialog fbd = new FolderBrowserDialog())
                {
                    fbd.SelectedPath = txtInstallPath.Text;
                    if (fbd.ShowDialog() == DialogResult.OK)
                    {
                        txtInstallPath.Text = Path.Combine(fbd.SelectedPath, "Urban Flow");
                    }
                }
            };
            this.Controls.Add(btnBrowse);

            chkDesktopShortcut = new CheckBox();
            chkDesktopShortcut.Text = "Create Desktop shortcut";
            chkDesktopShortcut.Font = new Font("Segoe UI", 9.5f);
            chkDesktopShortcut.ForeColor = Color.FromArgb(226, 232, 240);
            chkDesktopShortcut.Checked = true;
            chkDesktopShortcut.Location = new Point(32, 190);
            chkDesktopShortcut.Size = new Size(300, 25);
            this.Controls.Add(chkDesktopShortcut);

            chkLaunchNow = new CheckBox();
            chkLaunchNow.Text = "Launch Urban Flow after installation completes";
            chkLaunchNow.Font = new Font("Segoe UI", 9.5f);
            chkLaunchNow.ForeColor = Color.FromArgb(226, 232, 240);
            chkLaunchNow.Checked = true;
            chkLaunchNow.Location = new Point(32, 220);
            chkLaunchNow.Size = new Size(400, 25);
            this.Controls.Add(chkLaunchNow);

            progressBar = new ProgressBar();
            progressBar.Location = new Point(32, 265);
            progressBar.Size = new Size(502, 18);
            progressBar.Style = ProgressBarStyle.Continuous;
            progressBar.Visible = false;
            this.Controls.Add(progressBar);

            lblStatus = new Label();
            lblStatus.Text = "Ready to install.";
            lblStatus.Font = new Font("Segoe UI", 9);
            lblStatus.ForeColor = Color.FromArgb(160, 170, 185);
            lblStatus.Location = new Point(32, 290);
            lblStatus.Size = new Size(500, 22);
            this.Controls.Add(lblStatus);

            btnInstall = new Button();
            btnInstall.Text = "Install Urban Flow";
            btnInstall.Font = new Font("Segoe UI", 10.5f, FontStyle.Bold);
            btnInstall.Location = new Point(364, 325);
            btnInstall.Size = new Size(170, 40);
            btnInstall.FlatStyle = FlatStyle.Flat;
            btnInstall.BackColor = Color.FromArgb(245, 190, 40);
            btnInstall.ForeColor = Color.FromArgb(12, 14, 18);
            btnInstall.Cursor = Cursors.Hand;
            btnInstall.Click += BtnInstall_Click;
            this.Controls.Add(btnInstall);
        }

        public static bool IsSafeZipEntry(string entryFullName, string targetDir, out string canonicalDestPath)
        {
            canonicalDestPath = null;
            if (string.IsNullOrEmpty(entryFullName)) return false;
            if (entryFullName.IndexOf('\0') >= 0) return false;
            if (entryFullName.Contains("..") || entryFullName.StartsWith("/") || entryFullName.StartsWith("\\"))
                return false;
            if (Path.IsPathRooted(entryFullName) || entryFullName.Contains(":"))
                return false;

            string normalizedEntry = entryFullName.Replace(Path.AltDirectorySeparatorChar, Path.DirectorySeparatorChar);
            string canonicalRoot = Path.GetFullPath(targetDir);
            if (!canonicalRoot.EndsWith(Path.DirectorySeparatorChar.ToString()))
                canonicalRoot += Path.DirectorySeparatorChar;

            string combinedPath = Path.Combine(canonicalRoot, normalizedEntry);
            string fullDest = Path.GetFullPath(combinedPath);
            if (!fullDest.StartsWith(canonicalRoot, StringComparison.OrdinalIgnoreCase))
                return false;

            canonicalDestPath = fullDest;
            return true;
        }

        private static void CloseExistingProcesses(string targetDir)
        {
            try
            {
                string[] procNames = new string[] { "Urban Flow", "electron", "python", "pythonw", "node" };
                foreach (string name in procNames)
                {
                    foreach (Process p in Process.GetProcessesByName(name))
                    {
                        try
                        {
                            bool shouldKill = false;
                            try
                            {
                                if (name.Equals("Urban Flow", StringComparison.OrdinalIgnoreCase))
                                {
                                    shouldKill = true;
                                }
                                else if (p.MainModule != null && !string.IsNullOrEmpty(p.MainModule.FileName))
                                {
                                    string path = p.MainModule.FileName;
                                    if (path.IndexOf("Urban Flow", StringComparison.OrdinalIgnoreCase) >= 0 ||
                                        (!string.IsNullOrEmpty(targetDir) && path.StartsWith(targetDir, StringComparison.OrdinalIgnoreCase)))
                                    {
                                        shouldKill = true;
                                    }
                                }
                            }
                            catch
                            {
                                if (name.Equals("Urban Flow", StringComparison.OrdinalIgnoreCase))
                                    shouldKill = true;
                            }

                            if (shouldKill)
                            {
                                try { p.CloseMainWindow(); p.WaitForExit(600); } catch { }
                                if (!p.HasExited)
                                {
                                    p.Kill();
                                    p.WaitForExit(1000);
                                }
                            }
                        }
                        catch { }
                    }
                }
            }
            catch { }
        }

        private void BtnInstall_Click(object sender, EventArgs e)
        {
            string rawPath = txtInstallPath.Text.Trim().Trim('"', ' ', '\t');
            if (string.IsNullOrEmpty(rawPath))
            {
                MessageBox.Show("Please specify an installation path.", "Invalid Path", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            string targetDir = Path.GetFullPath(rawPath);
            btnInstall.Enabled = false;
            txtInstallPath.Enabled = false;
            chkDesktopShortcut.Enabled = false;
            chkLaunchNow.Enabled = false;
            progressBar.Visible = true;
            progressBar.Value = 0;

            bool createShortcut = chkDesktopShortcut.Checked;
            bool launch = chkLaunchNow.Checked;

            Thread worker = new Thread(() =>
            {
                bool success = PerformInstallationCore(targetDir, createShortcut, launch, (pct, status) =>
                {
                    try
                    {
                        if (this.InvokeRequired)
                        {
                            this.Invoke((MethodInvoker)delegate
                            {
                                if (pct >= 0)
                                {
                                    progressBar.Value = Math.Min(100, Math.Max(0, pct));
                                    lblStatus.Text = status;
                                    if (pct == 100)
                                    {
                                        lblStatus.ForeColor = Color.FromArgb(46, 213, 115);
                                    }
                                }
                                else
                                {
                                    progressBar.Visible = false;
                                    lblStatus.Text = status;
                                    lblStatus.ForeColor = Color.FromArgb(239, 68, 68);
                                    btnInstall.Enabled = true;
                                    txtInstallPath.Enabled = true;
                                }
                            });
                        }
                    }
                    catch { }
                });

                try
                {
                    if (this.InvokeRequired)
                    {
                        this.Invoke((MethodInvoker)delegate
                        {
                            if (success)
                            {
                                MessageBox.Show(
                                    "Urban Flow has been successfully installed!\n\nAll components, local AI models, and video analysis engines are ready to run.\n\nLocation: " + targetDir,
                                    "Urban Flow Installed",
                                    MessageBoxButtons.OK,
                                    MessageBoxIcon.Information
                                );
                                this.Close();
                            }
                            else
                            {
                                MessageBox.Show(
                                    "Installation encountered an error.\nPlease check 'install.log' in the installation directory for details.",
                                    "Error",
                                    MessageBoxButtons.OK,
                                    MessageBoxIcon.Error
                                );
                            }
                        });
                    }
                }
                catch { }
            });

            worker.IsBackground = true;
            worker.Start();
        }

        public static bool PerformInstallationCore(string targetDir, bool createShortcut, bool launch, Action<int, string> progress)
        {
            string logFile = Path.Combine(targetDir, "install.log");
            try
            {
                if (progress != null) progress(0, "Closing existing Urban Flow instances...");
                CloseExistingProcesses(targetDir);
                Thread.Sleep(300);

                if (progress != null) progress(2, "Preparing installation directory...");
                if (!Directory.Exists(targetDir))
                {
                    Directory.CreateDirectory(targetDir);
                }

                try
                {
                    File.WriteAllText(logFile, string.Format("[{0}] Starting Urban Flow extraction to: {1}\r\n", DateTime.UtcNow.ToString("o"), targetDir));
                }
                catch { }

                Assembly asm = Assembly.GetExecutingAssembly();
                using (Stream zipStream = asm.GetManifestResourceStream("urban_flow_payload.zip"))
                {
                    if (zipStream == null)
                    {
                        throw new FileNotFoundException("Embedded installation payload 'urban_flow_payload.zip' not found in executable.");
                    }

                    using (ZipArchive archive = new ZipArchive(zipStream, ZipArchiveMode.Read))
                    {
                        int total = archive.Entries.Count;
                        int count = 0;

                        foreach (ZipArchiveEntry entry in archive.Entries)
                        {
                            count++;
                            string fullDestPath;
                            if (!IsSafeZipEntry(entry.FullName, targetDir, out fullDestPath))
                            {
                                continue;
                            }

                            if (string.IsNullOrEmpty(entry.Name))
                            {
                                if (!Directory.Exists(fullDestPath))
                                    Directory.CreateDirectory(fullDestPath);
                            }
                            else
                            {
                                string dir = Path.GetDirectoryName(fullDestPath);
                                if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                                    Directory.CreateDirectory(dir);

                                bool extracted = false;
                                for (int attempt = 0; attempt < 3; attempt++)
                                {
                                    try
                                    {
                                        if (File.Exists(fullDestPath))
                                        {
                                            try { File.SetAttributes(fullDestPath, FileAttributes.Normal); } catch { }
                                        }
                                        entry.ExtractToFile(fullDestPath, true);
                                        extracted = true;
                                        break;
                                    }
                                    catch (IOException)
                                    {
                                        Thread.Sleep(150 * (attempt + 1));
                                    }
                                    catch (UnauthorizedAccessException)
                                    {
                                        Thread.Sleep(150 * (attempt + 1));
                                    }
                                }

                                if (!extracted)
                                {
                                    try
                                    {
                                        string tmp = fullDestPath + ".tmp." + Guid.NewGuid().ToString("N");
                                        entry.ExtractToFile(tmp, true);
                                        if (File.Exists(fullDestPath))
                                        {
                                            try { File.Delete(fullDestPath); } catch { }
                                        }
                                        File.Move(tmp, fullDestPath);
                                        extracted = true;
                                    }
                                    catch
                                    {
                                        if (File.Exists(fullDestPath))
                                        {
                                            try
                                            {
                                                FileInfo fi = new FileInfo(fullDestPath);
                                                if (fi.Length == entry.Length)
                                                    extracted = true;
                                            }
                                            catch { }
                                        }
                                    }
                                }

                                UnblockFile(fullDestPath);
                            }

                            if (count % 100 == 0 || count == total)
                            {
                                int pct = (int)((count * 95.0) / total);
                                if (progress != null)
                                    progress(pct, string.Format("Extracting components ({0}%)... {1}", pct, entry.Name));
                            }
                        }
                    }
                }

                if (progress != null) progress(96, "Configuring system security permissions...");
                UnblockDirectory(targetDir);

                if (createShortcut)
                {
                    if (progress != null) progress(98, "Creating Desktop shortcut...");
                    CreateShortcuts(targetDir);
                }

                try
                {
                    File.AppendAllText(logFile, string.Format("[{0}] Installation completed successfully.\r\n", DateTime.UtcNow.ToString("o")));
                }
                catch { }

                if (progress != null) progress(100, "Installation completed successfully!");

                if (launch)
                {
                    LaunchApp(targetDir);
                }

                return true;
            }
            catch (Exception ex)
            {
                try
                {
                    File.AppendAllText(logFile, string.Format("[{0}] ERROR: {1}\r\n{2}\r\n", DateTime.UtcNow.ToString("o"), ex.Message, ex.StackTrace));
                }
                catch { }
                if (progress != null) progress(-1, "Installation error: " + ex.Message);
                return false;
            }
        }

        private static void CreateShortcuts(string targetDir)
        {
            try
            {
                string desktopPath = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                string shortcutPath = Path.Combine(desktopPath, "Urban Flow.lnk");
                string exePath = Path.Combine(targetDir, "Urban Flow.exe");
                string electronExe = Path.Combine(targetDir, "frontend", "node_modules", "electron", "dist", "electron.exe");
                string frontendDir = Path.Combine(targetDir, "frontend");
                string iconPath = Path.Combine(targetDir, "frontend", "public", "favicon.ico");

                IShellLinkW link = (IShellLinkW)new ShellLink();
                link.SetDescription("Urban Flow - Adaptive Traffic Signal System");

                if (File.Exists(exePath))
                {
                    link.SetPath(exePath);
                    link.SetWorkingDirectory(targetDir);
                    if (File.Exists(iconPath))
                    {
                        link.SetIconLocation(iconPath, 0);
                    }
                }
                else if (File.Exists(electronExe))
                {
                    link.SetPath(electronExe);
                    link.SetArguments("\"" + frontendDir + "\"");
                    link.SetWorkingDirectory(targetDir);
                    if (File.Exists(iconPath))
                    {
                        link.SetIconLocation(iconPath, 0);
                    }
                }

                IPersistFile file = (IPersistFile)link;
                file.Save(shortcutPath, false);
            }
            catch { }
        }

        private static void LaunchApp(string targetDir)
        {
            try
            {
                string exePath = Path.Combine(targetDir, "Urban Flow.exe");
                string electronExe = Path.Combine(targetDir, "frontend", "node_modules", "electron", "dist", "electron.exe");
                string frontendDir = Path.Combine(targetDir, "frontend");

                if (File.Exists(exePath))
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = exePath,
                        WorkingDirectory = targetDir,
                        UseShellExecute = true
                    });
                }
                else if (File.Exists(electronExe))
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = electronExe,
                        Arguments = "\"" + frontendDir + "\"",
                        WorkingDirectory = targetDir,
                        UseShellExecute = true
                    });
                }
            }
            catch { }
        }

        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            string targetPath = null;
            bool silent = false;
            bool disableLaunch = false;

            if (args != null)
            {
                foreach (string arg in args)
                {
                    if (string.Equals(arg, "/S", StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(arg, "--silent", StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(arg, "-s", StringComparison.OrdinalIgnoreCase))
                    {
                        silent = true;
                    }
                    else if (string.Equals(arg, "--no-launch", StringComparison.OrdinalIgnoreCase))
                    {
                        disableLaunch = true;
                    }
                    else if (!arg.StartsWith("-") && !arg.StartsWith("/"))
                    {
                        targetPath = arg;
                    }
                }
            }

            if (silent)
            {
                if (string.IsNullOrWhiteSpace(targetPath))
                {
                    targetPath = Path.Combine(
                        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                        "Programs",
                        "Urban Flow"
                    );
                }

                bool ok = PerformInstallationCore(targetPath, true, !disableLaunch, (pct, status) =>
                {
                    try { Console.WriteLine(string.Format("[{0}%] {1}", pct, status)); } catch { }
                });

                Environment.Exit(ok ? 0 : 1);
                return;
            }

            Application.Run(new SetupForm(targetPath));
        }
    }
}

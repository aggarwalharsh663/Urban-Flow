using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
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

        [STAThread]
        static void Main()
        {
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

                string frontendDir = Path.Combine(appDir, "frontend");
                string electronExe = Path.Combine(frontendDir, "node_modules", "electron", "dist", "electron.exe");

                if (!File.Exists(electronExe))
                {
                    MessageBox.Show(
                        "Urban Flow application files are incomplete.\n\n" +
                        "Missing: " + electronExe + "\n\n" +
                        "Please run 'Urban Flow Setup.exe' again to install all required components.",
                        "Urban Flow - Missing Component",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Warning
                    );
                    return;
                }

                // Unblock Electron executable before launch
                UnblockFile(electronExe);

                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = electronExe;
                psi.Arguments = ".";
                psi.WorkingDirectory = frontendDir;
                psi.WindowStyle = ProcessWindowStyle.Normal;
                psi.CreateNoWindow = false;
                psi.UseShellExecute = false;

                Process.Start(psi);
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

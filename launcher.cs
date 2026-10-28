using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace UrbanFlowLauncher
{
    static class Program
    {
        [STAThread]
        static void Main()
        {
            try
            {
                string appDir = AppDomain.CurrentDomain.BaseDirectory;
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

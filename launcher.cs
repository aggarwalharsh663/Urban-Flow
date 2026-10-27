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

                ProcessStartInfo psi = new ProcessStartInfo();
                if (File.Exists(electronExe))
                {
                    psi.FileName = electronExe;
                    psi.Arguments = ".";
                    psi.WorkingDirectory = frontendDir;
                }
                else
                {
                    psi.FileName = "cmd.exe";
                    psi.Arguments = "/c npm run app";
                    psi.WorkingDirectory = frontendDir;
                }
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;

                Process.Start(psi);
            }
            catch (Exception ex)
            {
                MessageBox.Show("Failed to launch Urban Flow:\n" + ex.Message, "Urban Flow Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }
}

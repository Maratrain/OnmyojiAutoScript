// OAS launcher (mirrors AzurPilot's alas-launcher.exe):
//   1. hide-start the python backend (toolkit\python.exe server.py)
//   2. show a dark splash while polling the API until ready
//   3. open the oasx (Flutter) window
//   4. when the oasx window closes, stop the backend we started
// Build: deploy\launcher\build-launcher.bat  (csc, .NET Framework)
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

namespace OasLauncher
{
    internal static class Program
    {
        private static string _root;
        private static int _port;
        private const int ReadyTimeoutMs = 180000;

        [STAThread]
        private static int Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            bool createdNew = false;
            Mutex mutex = null;
            try
            {
                mutex = new Mutex(true, "OnmyojiAutoScript.OasLauncher.Mutex", out createdNew);
            }
            catch (Exception)
            {
                createdNew = true;
            }
            if (!createdNew)
            {
                MessageBox.Show("OAS 启动器已在运行。", "OnmyojiAutoScript",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return 0;
            }
            try
            {
                return Run();
            }
            catch (Exception e)
            {
                MessageBox.Show("启动器发生未处理异常：" + e.Message, "OnmyojiAutoScript",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            finally
            {
                if (mutex != null)
                {
                    try { mutex.ReleaseMutex(); }
                    catch (Exception) { }
                    mutex.Dispose();
                }
            }
        }

        private static int Run()
        {
            _root = FindRepoRoot();
            if (_root == null)
            {
                MessageBox.Show(
                    "未找到 OAS 根目录（缺少 server.py）。请把 oas-launcher.exe 放在 OnmyojiAutoScript 目录中。",
                    "OnmyojiAutoScript", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            _port = ReadPort();

            bool external = ProbeBackend();
            Process backend = null;
            string error;
            if (!external)
            {
                backend = StartBackend(out error);
                if (backend == null)
                {
                    MessageBox.Show("无法启动后端进程：" + error, "OnmyojiAutoScript",
                        MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return 1;
                }
            }

            string oasxPath = ResolveOasxPath();
            if (oasxPath == null)
            {
                StopBackend(backend);
                return 1;
            }

            string iconPath = Path.Combine(_root, "deploy", "launcher", "logo.ico");
            Process oasx = null;
            string launchError = null;
            bool ready = external;

            using (SplashForm splash = new SplashForm(iconPath))
            {
                if (external)
                {
                    splash.Status = "后端已在运行，正在打开 OASX…";
                    splash.Show();
                    Application.DoEvents();
                    oasx = TryLaunch(oasxPath, out launchError);
                    splash.Close();
                }
                else
                {
                    splash.Status = "正在启动后端服务…";
                    Stopwatch sw = Stopwatch.StartNew();
                    System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
                    timer.Interval = 500;
                    timer.Tick += delegate
                    {
                        if (ProbeBackend())
                        {
                            ready = true;
                            timer.Stop();
                            splash.Status = "后端已就绪，正在打开 OASX…";
                            Application.DoEvents();
                            oasx = TryLaunch(oasxPath, out launchError);
                            splash.Close();
                        }
                        else if (backend.HasExited || sw.ElapsedMilliseconds > ReadyTimeoutMs)
                        {
                            timer.Stop();
                            splash.Status = "启动失败";
                            splash.Close();
                        }
                    };
                    timer.Start();
                    Application.Run(splash);
                    timer.Dispose();
                }
            }

            if (!ready)
            {
                string why = backend.HasExited
                    ? "后端进程启动失败或已退出，请查看 log 目录中的日志。"
                    : "后端启动超时（180 秒），请查看 log 目录中的日志，或手动运行 oas-backend.bat 检查错误。";
                MessageBox.Show(why, "OnmyojiAutoScript",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                StopBackend(backend);
                return 1;
            }

            if (oasx == null)
            {
                MessageBox.Show("无法启动 OASX 窗口：" + launchError, "OnmyojiAutoScript",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                StopBackend(backend);
                return 1;
            }

            // Wait for the user to close oasx, then take the backend down with it.
            oasx.WaitForExit();
            StopBackend(backend);
            return 0;
        }

        /// <summary>
        /// Walk up from the exe location until a directory containing server.py is
        /// found, so the exe also works from a deploy\launcher subfolder.
        /// </summary>
        private static string FindRepoRoot()
        {
            string dir = Path.GetDirectoryName(Application.ExecutablePath);
            for (int i = 0; i < 4 && dir != null; i++)
            {
                if (File.Exists(Path.Combine(dir, "server.py"))) return dir;
                dir = Path.GetDirectoryName(dir);
            }
            return null;
        }

        private static int ReadPort()
        {
            try
            {
                string yaml = File.ReadAllText(Path.Combine(_root, "config", "deploy.yaml"));
                Match m = Regex.Match(yaml, @"WebuiPort:\s*(\d+)");
                if (m.Success)
                {
                    int p = int.Parse(m.Groups[1].Value);
                    if (p > 0 && p < 65536) return p;
                }
            }
            catch (Exception)
            {
            }
            return 22270;
        }

        private static bool ProbeBackend()
        {
            return HttpGet("http://127.0.0.1:" + _port + "/home/test", 1200) != null;
        }

        private static string HttpGet(string url, int timeoutMs)
        {
            try
            {
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
                req.Timeout = timeoutMs;
                req.ReadWriteTimeout = timeoutMs;
                req.Proxy = null;
                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                {
                    using (StreamReader reader = new StreamReader(resp.GetResponseStream()))
                    {
                        return reader.ReadToEnd();
                    }
                }
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static string FindPython()
        {
            string local = Path.Combine(_root, "toolkit", "python.exe");
            if (File.Exists(local)) return local;
            return "python.exe";
        }

        private static Process StartBackend(out string error)
        {
            error = null;
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = FindPython();
                psi.Arguments = "server.py";
                psi.WorkingDirectory = _root;
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                // Same PATH setup as oas-backend.bat, so script subprocesses can find adb/git.
                string extra =
                    Path.Combine(_root, "toolkit") + ";" +
                    Path.Combine(_root, "toolkit", "Scripts") + ";" +
                    Path.Combine(_root, "toolkit", "Git", "mingw64", "bin") + ";" +
                    Path.Combine(_root, "toolkit", "Lib", "site-packages", "adbutils", "binaries") + ";";
                psi.EnvironmentVariables["PATH"] = extra + psi.EnvironmentVariables["PATH"];
                return Process.Start(psi);
            }
            catch (Exception e)
            {
                error = e.Message;
                return null;
            }
        }

        private static void StopBackend(Process backend)
        {
            if (backend == null) return;
            try
            {
                if (!backend.HasExited)
                {
                    HttpGet("http://127.0.0.1:" + _port + "/home/kill_server", 1500);
                    for (int i = 0; i < 24 && !backend.HasExited; i++) Thread.Sleep(250);
                    if (!backend.HasExited) KillTree(backend.Id);
                }
            }
            catch (Exception)
            {
            }
        }

        private static void KillTree(int pid)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo("taskkill.exe", "/T /F /PID " + pid);
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                Process.Start(psi).WaitForExit(5000);
            }
            catch (Exception)
            {
            }
        }

        private static Process TryLaunch(string path, out string error)
        {
            error = null;
            try
            {
                ProcessStartInfo pi = new ProcessStartInfo(path);
                pi.WorkingDirectory = Path.GetDirectoryName(path);
                return Process.Start(pi);
            }
            catch (Exception e)
            {
                error = e.Message;
                return null;
            }
        }

        private static string ResolveOasxPath()
        {
            string ini = Path.Combine(_root, "config", "launcher.ini");
            string saved = ReadIniValue(ini, "oasx_path");
            if (saved != null && File.Exists(saved)) return saved;

            string cand = Path.Combine(_root, "oasx", "oasx.exe");
            if (File.Exists(cand))
            {
                WriteIniValue(ini, "oasx_path", cand);
                return cand;
            }

            // oasx usually sits next to the OAS repo, e.g. D:\oasx_v0.3.12_windows.
            try
            {
                string parent = Path.GetDirectoryName(_root);
                if (parent != null)
                {
                    string[] dirs = Directory.GetDirectories(parent, "oasx*");
                    Array.Sort(dirs, StringComparer.OrdinalIgnoreCase);
                    foreach (string dir in dirs)
                    {
                        string c = Path.Combine(dir, "oasx.exe");
                        if (File.Exists(c))
                        {
                            WriteIniValue(ini, "oasx_path", c);
                            return c;
                        }
                    }
                }
            }
            catch (Exception)
            {
            }

            using (OpenFileDialog dlg = new OpenFileDialog())
            {
                dlg.Title = "选择 oasx.exe（OAS 前端窗口程序）";
                dlg.Filter = "oasx.exe|oasx.exe|可执行程序 (*.exe)|*.exe";
                if (dlg.ShowDialog() == DialogResult.OK)
                {
                    WriteIniValue(ini, "oasx_path", dlg.FileName);
                    return dlg.FileName;
                }
            }
            return null;
        }

        private static string ReadIniValue(string path, string key)
        {
            try
            {
                if (!File.Exists(path)) return null;
                string[] lines = File.ReadAllLines(path);
                foreach (string line in lines)
                {
                    string t = line.Trim();
                    int eq = t.IndexOf('=');
                    if (eq <= 0) continue;
                    if (t.Substring(0, eq).Trim() == key)
                        return t.Substring(eq + 1).Trim();
                }
            }
            catch (Exception)
            {
            }
            return null;
        }

        private static void WriteIniValue(string path, string key, string value)
        {
            try
            {
                StringBuilder sb = new StringBuilder();
                if (File.Exists(path))
                {
                    string[] lines = File.ReadAllLines(path);
                    foreach (string line in lines)
                    {
                        string t = line.Trim();
                        int eq = t.IndexOf('=');
                        if (eq > 0 && t.Substring(0, eq).Trim() == key) continue;
                        sb.AppendLine(line);
                    }
                }
                sb.AppendLine(key + "=" + value);
                string dir = Path.GetDirectoryName(path);
                if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
                File.WriteAllText(path, sb.ToString());
            }
            catch (Exception)
            {
            }
        }

        /// <summary>
        /// Dark borderless splash, styled after AzurPilot's launcher window
        /// (44px title strip with a drag zone and close button).
        /// </summary>
        private sealed class SplashForm : Form
        {
            private readonly Label _statusLabel;
            private readonly Label _closeLabel;

            public SplashForm(string iconPath)
            {
                FormBorderStyle = FormBorderStyle.None;
                StartPosition = FormStartPosition.CenterScreen;
                Size = new Size(430, 190);
                BackColor = Color.FromArgb(32, 33, 36);
                Text = "OnmyojiAutoScript";
                TopMost = true;
                if (iconPath != null && File.Exists(iconPath))
                {
                    try { Icon = new Icon(iconPath); }
                    catch (Exception) { }
                }

                Panel top = new Panel();
                top.Dock = DockStyle.Top;
                top.Height = 44;
                top.BackColor = Color.FromArgb(44, 45, 50);
                Controls.Add(top);
                top.BringToFront();

                Label title = new Label();
                title.Text = "OnmyojiAutoScript";
                title.Bounds = new Rectangle(16, 0, 320, 44);
                title.ForeColor = Color.FromArgb(235, 235, 240);
                title.Font = new Font("Segoe UI", 10f, FontStyle.Bold);
                title.TextAlign = ContentAlignment.MiddleLeft;
                top.Controls.Add(title);

                _closeLabel = new Label();
                _closeLabel.Text = "×";
                _closeLabel.Size = new Size(32, 44);
                _closeLabel.Location = new Point(top.Width - 32, 0);
                _closeLabel.TextAlign = ContentAlignment.MiddleCenter;
                _closeLabel.ForeColor = Color.FromArgb(160, 160, 165);
                _closeLabel.Font = new Font("Segoe UI", 12f);
                _closeLabel.Cursor = Cursors.Hand;
                _closeLabel.MouseEnter += delegate { _closeLabel.ForeColor = Color.White; };
                _closeLabel.MouseLeave += delegate { _closeLabel.ForeColor = Color.FromArgb(160, 160, 165); };
                _closeLabel.Click += delegate { Close(); };
                top.Controls.Add(_closeLabel);

                if (iconPath != null && File.Exists(iconPath))
                {
                    try
                    {
                        PictureBox logo = new PictureBox();
                        using (Icon big = new Icon(iconPath, 44, 44))
                        {
                            logo.Image = big.ToBitmap();
                        }
                        logo.Size = new Size(44, 44);
                        logo.Location = new Point(18, 64);
                        logo.SizeMode = PictureBoxSizeMode.Zoom;
                        Controls.Add(logo);
                    }
                    catch (Exception)
                    {
                    }
                }

                _statusLabel = new Label();
                _statusLabel.Bounds = new Rectangle(78, 66, 330, 24);
                _statusLabel.ForeColor = Color.FromArgb(205, 205, 210);
                _statusLabel.Font = new Font("Segoe UI", 9.5f);
                _statusLabel.TextAlign = ContentAlignment.MiddleLeft;
                Controls.Add(_statusLabel);

                Label hint = new Label();
                hint.Text = "后端在后台运行，关闭 OASX 窗口后会自动退出";
                hint.Bounds = new Rectangle(78, 94, 330, 36);
                hint.ForeColor = Color.FromArgb(140, 140, 146);
                hint.Font = new Font("Segoe UI", 8.25f);
                hint.TextAlign = ContentAlignment.TopLeft;
                Controls.Add(hint);

                ProgressBar progress = new ProgressBar();
                progress.Style = ProgressBarStyle.Marquee;
                progress.MarqueeAnimationSpeed = 30;
                progress.Bounds = new Rectangle(18, 148, 394, 8);
                Controls.Add(progress);
            }

            public string Status
            {
                set
                {
                    if (_statusLabel != null) _statusLabel.Text = value;
                }
            }

            protected override void WndProc(ref Message m)
            {
                const int WM_NCHITTEST = 0x84;
                const int HTCLIENT = 1;
                const int HTCAPTION = 2;
                if (m.Msg == WM_NCHITTEST)
                {
                    base.WndProc(ref m);
                    if ((int)m.Result == HTCLIENT)
                    {
                        Point p = PointToClient(Cursor.Position);
                        if (!_closeLabel.Bounds.Contains(p))
                        {
                            m.Result = (IntPtr)HTCAPTION;
                        }
                    }
                    return;
                }
                base.WndProc(ref m);
            }
        }
    }
}

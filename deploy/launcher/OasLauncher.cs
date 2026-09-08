// OAS launcher (mirrors AzurPilot's alas-launcher.exe):
//   1. hide-start the python backend (toolkit\python.exe server.py)
//   2. show a light "morning mist glass" splash while polling the API until ready
//   3. open the oasx (Flutter) window
//   4. when the oasx window closes, stop the backend we started
// Build: deploy\launcher\build-launcher.bat  (csc, .NET Framework)
// UI: 方案B 晨雾玻璃 — 进度条样式参考 AzurPilot 启动器（细圆角渐变条 + 右侧大百分比）
using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
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

        private enum StepState { Pending, Active, Done, Failed }

        [STAThread]
        private static int Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            // --splash-demo：仅展示启动画面用于检查 UI，不启动任何进程。
            if (args.Length == 1 && args[0] == "--splash-demo")
            {
                RunSplashDemo();
                return 0;
            }

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
                MessageBox.Show("OAS 启动器已在运行。", "OAS 启动器",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return 0;
            }
            try
            {
                return Run();
            }
            catch (Exception e)
            {
                MessageBox.Show("启动器发生未处理异常：" + e.Message, "OAS 启动器",
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

        /// <summary>演示模式：轮播各启动阶段，用于离线检查启动画面 UI。</summary>
        private static void RunSplashDemo()
        {
            string iconPath = Path.Combine(
                Path.GetDirectoryName(Application.ExecutablePath) ?? "", "logo.ico");
            if (!File.Exists(iconPath)) iconPath = null;

            using (SplashForm splash = new SplashForm(iconPath, 22288))
            {
                splash.SetStep(0, StepState.Active);
                splash.SetConnection(false);
                splash.Status = "正在启动后端服务…";
                splash.Show();
                DateTime start = DateTime.UtcNow;
                int phase = 0;
                while (splash.Visible)
                {
                    Application.DoEvents();
                    Thread.Sleep(30);
                    double t = (DateTime.UtcNow - start).TotalSeconds;
                    int want = t < 2.5 ? 0 : t < 4.5 ? 1 : t < 6.5 ? 2 : 3;
                    if (want != phase)
                    {
                        phase = want;
                        if (want == 1)
                        {
                            splash.SetStep(0, StepState.Done);
                            splash.SetStep(1, StepState.Active);
                            splash.Status = "正在等待后端就绪…";
                        }
                        else if (want == 2)
                        {
                            splash.SetStep(1, StepState.Done);
                            splash.SetStep(2, StepState.Active);
                            splash.SetConnection(true);
                            splash.Status = "后端已就绪，正在打开 OASX…";
                        }
                        else if (want == 3)
                        {
                            splash.SetStep(2, StepState.Done);
                            splash.Status = "启动完成，OASX 窗口已打开";
                        }
                    }
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
                    "OAS 启动器", MessageBoxButtons.OK, MessageBoxIcon.Error);
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
                    MessageBox.Show("无法启动后端进程：" + error, "OAS 启动器",
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

            using (SplashForm splash = new SplashForm(iconPath, _port))
            {
                if (external)
                {
                    splash.SetStep(0, StepState.Done);
                    splash.SetStep(1, StepState.Done);
                    splash.SetStep(2, StepState.Active);
                    splash.SetConnection(true);
                    splash.Status = "后端已在运行，正在打开 OASX…";
                    splash.Show();
                    Application.DoEvents();
                    oasx = TryLaunch(oasxPath, out launchError);
                    splash.Close();
                }
                else
                {
                    splash.SetStep(0, StepState.Done);
                    splash.SetStep(1, StepState.Active);
                    splash.SetConnection(false);
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
                            splash.SetConnection(true);
                            splash.SetStep(1, StepState.Done);
                            splash.SetStep(2, StepState.Active);
                            splash.Status = "后端已就绪，正在打开 OASX…";
                            splash.Refresh();
                            Application.DoEvents();
                            oasx = TryLaunch(oasxPath, out launchError);
                            splash.Close();
                        }
                        else if (backend.HasExited || sw.ElapsedMilliseconds > ReadyTimeoutMs)
                        {
                            timer.Stop();
                            if (backend.HasExited)
                            {
                                splash.SetStep(0, StepState.Failed);
                                splash.Status = "后端进程已退出，启动失败";
                            }
                            else
                            {
                                splash.SetStep(1, StepState.Failed);
                                splash.Status = "后端启动超时，启动失败";
                            }
                            splash.Refresh();
                            Thread.Sleep(600);
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
                MessageBox.Show(why, "OAS 启动器",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                StopBackend(backend);
                return 1;
            }

            if (oasx == null)
            {
                MessageBox.Show("无法启动 OASX 窗口：" + launchError, "OAS 启动器",
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
        /// 晨雾玻璃启动画面：浅色渐变 + 柔光 + 玻璃卡片；进度条为
        /// AzurPilot 式细圆角渐变条，右侧显示大号百分比，随步骤平滑推进。
        /// </summary>
        private sealed class SplashForm : Form
        {
            private const int W = 480;
            private const int H = 316;

            // 方案B 晨雾玻璃 palette
            private static readonly Color Bg1 = Color.FromArgb(0xEA, 0xF0, 0xF8);
            private static readonly Color Bg2 = Color.FromArgb(0xF6, 0xF4, 0xFF);
            private static readonly Color Acc = Color.FromArgb(0x5B, 0x7C, 0xFA);
            private static readonly Color Acc2 = Color.FromArgb(0x7C, 0x5B, 0xFA);
            private static readonly Color Ok = Color.FromArgb(0x18, 0xB2, 0x6B);
            private static readonly Color Bad = Color.FromArgb(0xE5, 0x48, 0x4D);
            private static readonly Color Tx = Color.FromArgb(0x23, 0x2A, 0x3B);
            private static readonly Color Tx2 = Color.FromArgb(0x5A, 0x63, 0x78);
            private static readonly Color Tx3 = Color.FromArgb(0x9A, 0xA3, 0xB8);
            private static readonly Color Hair = Color.FromArgb(23, 30, 40, 70);
            private static readonly Color Stroke = Color.FromArgb(191, 255, 255, 255);
            private static readonly Color Glass = Color.FromArgb(150, 255, 255, 255);
            private static readonly Color Glass2 = Color.FromArgb(110, 255, 255, 255);

            private static readonly Font FBrand = UiFont(14f, FontStyle.Bold);
            private static readonly Font FSub = UiFont(10f, FontStyle.Regular);
            private static readonly Font FStatus = UiFont(14f, FontStyle.Bold);
            private static readonly Font FPercent = UiFont(17f, FontStyle.Bold);
            private static readonly Font FText = UiFont(11.5f, FontStyle.Regular);
            private static readonly Font FTextB = UiFont(11.5f, FontStyle.Bold);
            private static readonly Font FSmall = UiFont(9.5f, FontStyle.Regular);
            private static readonly Font FSmallB = UiFont(9.5f, FontStyle.Bold);
            private static readonly Font FMono = MonoFont(10f);

            private readonly string _host;
            private string _status = "正在启动后端服务…";
            private bool _connected;
            private readonly StepState[] _steps =
                { StepState.Pending, StepState.Pending, StepState.Pending };
            private static readonly string[] StepNames =
                { "启动后端服务", "等待接口就绪", "打开 OASX 窗口" };

            private readonly Stopwatch _clock = Stopwatch.StartNew();
            private readonly System.Windows.Forms.Timer _anim;
            private readonly Image _logo;
            private readonly Rectangle _closeRect;
            private bool _hoverClose;
            private float _targetPercent;
            private float _displayPercent;

            public SplashForm(string iconPath, int port)
            {
                _host = "127.0.0.1:" + port;
                FormBorderStyle = FormBorderStyle.None;
                StartPosition = FormStartPosition.CenterScreen;
                ClientSize = new Size(W, H);
                Text = "OAS 启动器";
                TopMost = true;
                DoubleBuffered = true;
                if (iconPath != null && File.Exists(iconPath))
                {
                    try { Icon = new Icon(iconPath); }
                    catch (Exception) { }
                }
                using (GraphicsPath p = Round(new RectangleF(0, 0, W, H), 13))
                {
                    Region = new Region(p);
                }
                _closeRect = new Rectangle(W - 34, 0, 34, 44);
                _logo = LoadShikigamiLogo();

                _anim = new System.Windows.Forms.Timer { Interval = 33 };
                _anim.Tick += delegate
                {
                    _displayPercent += (_targetPercent - _displayPercent) * 0.16f;
                    if (Math.Abs(_targetPercent - _displayPercent) < 0.1f)
                        _displayPercent = _targetPercent;
                    Invalidate();
                };
                _anim.Start();
            }

            public string Status
            {
                set { _status = value; Invalidate(); }
            }

            /// <summary>直接设定目标百分比（0-100），显示值按帧平滑逼近。</summary>
            public void SetPercent(float value)
            {
                _targetPercent = Math.Max(0f, Math.Min(100f, value));
            }

            /// <summary>按步骤推进百分比：Active 给出起步值，Done 推进到步骤终点。</summary>
            public void SetStep(int index, StepState state)
            {
                if (index >= 0 && index < _steps.Length)
                {
                    _steps[index] = state;
                    if (state == StepState.Done)
                        SetPercent((index + 1) * 100f / _steps.Length);
                    else if (state == StepState.Active)
                        SetPercent(index * 100f / _steps.Length + 8f);
                    Invalidate();
                }
            }

            public void SetConnection(bool ready)
            {
                _connected = ready;
                Invalidate();
            }

            protected override void OnHandleCreated(EventArgs e)
            {
                base.OnHandleCreated(e);
                // Extend the DWM frame by 1px so the borderless window keeps a system shadow.
                MARGINS m = new MARGINS { cyBottomHeight = 1 };
                try { DwmExtendFrameIntoClientArea(Handle, ref m); }
                catch (Exception) { }
            }

            protected override void OnFormClosed(FormClosedEventArgs e)
            {
                _anim.Dispose();
                if (_logo != null) _logo.Dispose();
                base.OnFormClosed(e);
            }

            protected override void OnMouseMove(MouseEventArgs e)
            {
                bool hover = _closeRect.Contains(e.Location);
                if (hover != _hoverClose)
                {
                    _hoverClose = hover;
                    Invalidate(_closeRect);
                }
                base.OnMouseMove(e);
            }

            protected override void OnMouseLeave(EventArgs e)
            {
                if (_hoverClose)
                {
                    _hoverClose = false;
                    Invalidate(_closeRect);
                }
                base.OnMouseLeave(e);
            }

            protected override void OnMouseClick(MouseEventArgs e)
            {
                if (e.Button == MouseButtons.Left && _hoverClose) Close();
                base.OnMouseClick(e);
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
                        if (!_closeRect.Contains(p))
                        {
                            m.Result = (IntPtr)HTCAPTION;
                        }
                    }
                    return;
                }
                base.WndProc(ref m);
            }

            protected override void OnPaint(PaintEventArgs e)
            {
                base.OnPaint(e);
                Graphics g = e.Graphics;
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
                double t = _clock.ElapsedMilliseconds / 1000.0;

                DrawBackground(g);
                DrawCaption(g, t);
                DrawProgressCard(g);
                DrawStepsCard(g, t);
                DrawHint(g);
            }

            private static void DrawBackground(Graphics g)
            {
                using (LinearGradientBrush lg = new LinearGradientBrush(
                    new Point(0, 0), new Point(190, H), Bg1, Bg2))
                {
                    g.FillRectangle(lg, 0, 0, W, H);
                }
                Glow(g, W * 0.80f, -40, 400, 260, Acc2, 38);
                Glow(g, 10, H + 50, 470, 260, Color.FromArgb(56, 152, 255), 38);
                Glow(g, W * 0.55f, H + 70, 330, 200, Ok, 20);
            }

            private void DrawCaption(Graphics g, double t)
            {
                using (SolidBrush b = new SolidBrush(Color.FromArgb(115, Color.White)))
                    g.FillRectangle(b, 0, 0, W, 44);
                using (Pen p = new Pen(Hair)) g.DrawLine(p, 0, 44, W, 44);

                // 品牌图标：oasx 式神头像（圆角缩放 + 白色描边 + 底部柔光）
                if (_logo != null)
                {
                    RectangleF lr = new RectangleF(14, 9, 26, 26);
                    Glow(g, lr.X + lr.Width / 2f, lr.Bottom - 2, 30, 10, Acc, 70);
                    using (GraphicsPath lp = Round(lr, 7))
                    {
                        var lclip = g.Save();
                        g.SetClip(lp);
                        var prevIp = g.InterpolationMode;
                        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                        g.DrawImage(_logo, lr);
                        g.InterpolationMode = prevIp;
                        g.Restore(lclip);
                        using (Pen pen = new Pen(Color.FromArgb(200, Color.White), 1.5f))
                            g.DrawPath(pen, lp);
                    }
                }

                using (SolidBrush b = new SolidBrush(Tx))
                using (StringFormat sf = new StringFormat { LineAlignment = StringAlignment.Center })
                {
                    g.DrawString("OAS", FBrand, b, new RectangleF(46, 0, 60, 44), sf);
                }
                using (SolidBrush b = new SolidBrush(Tx3))
                using (StringFormat sf = new StringFormat { LineAlignment = StringAlignment.Center })
                {
                    g.DrawString("启动器", FSub, b, new RectangleF(94, 1, 70, 44), sf);
                }

                // 右侧连接状态胶囊
                string connText = _connected ? "已连接 " : "正在连接 ";
                float cw1 = g.MeasureString(connText, FText).Width;
                float cw2 = g.MeasureString(_host, FMono).Width;
                float pw = 12 + 7 + 6 + cw1 + cw2 + 12;
                RectangleF pr = new RectangleF(W - 34 - 10 - pw, 10, pw, 24);
                using (GraphicsPath pp = Round(pr, 12))
                {
                    using (SolidBrush b = new SolidBrush(Color.FromArgb(166, Color.White))) g.FillPath(b, pp);
                    using (Pen p = new Pen(Hair)) g.DrawPath(p, pp);
                }
                Color dotColor = _connected ? Ok : Acc;
                if (!_connected)
                {
                    using (SolidBrush b = new SolidBrush(Color.FromArgb(
                        (int)(110 + 90 * Math.Sin(t * 2 * Math.PI * 1.3)), dotColor)))
                        g.FillEllipse(b, pr.X + 11, pr.Y + 8.5f, 7, 7);
                }
                else
                {
                    using (SolidBrush b = new SolidBrush(Color.FromArgb(60, dotColor)))
                        g.FillEllipse(b, pr.X + 9.5f, pr.Y + 7, 10, 10);
                    using (SolidBrush b = new SolidBrush(dotColor))
                        g.FillEllipse(b, pr.X + 11, pr.Y + 8.5f, 7, 7);
                }
                using (SolidBrush b = new SolidBrush(Tx2))
                using (SolidBrush mb = new SolidBrush(Tx3))
                using (StringFormat sf = new StringFormat { LineAlignment = StringAlignment.Center })
                {
                    g.DrawString(connText, FText, b, new RectangleF(pr.X + 22, pr.Y, cw1 + 4, pr.Height), sf);
                    g.DrawString(_host, FMono, mb, new RectangleF(pr.X + 22 + cw1 + 4, pr.Y, cw2 + 4, pr.Height), sf);
                }

                // 关闭按钮（悬停红底白叉）
                if (_hoverClose)
                {
                    using (GraphicsPath cp = Round(new RectangleF(_closeRect.X + 4, 5, _closeRect.Width - 8, 34), 8))
                    using (SolidBrush b = new SolidBrush(Bad))
                        g.FillPath(b, cp);
                }
                float cx = _closeRect.X + _closeRect.Width / 2f, cy = 22;
                using (Pen p = new Pen(_hoverClose ? Color.White : Tx2, 1.6f))
                {
                    p.StartCap = LineCap.Round;
                    p.EndCap = LineCap.Round;
                    g.DrawLine(p, cx - 4.5f, cy - 4.5f, cx + 4.5f, cy + 4.5f);
                    g.DrawLine(p, cx - 4.5f, cy + 4.5f, cx + 4.5f, cy - 4.5f);
                }
            }

            /// <summary>进度卡片：状态文字在左，大号百分比在右，下方细圆角渐变进度条。</summary>
            private void DrawProgressCard(Graphics g)
            {
                RectangleF card = new RectangleF(16, 58, W - 32, 88);
                Card(g, card, Glass);

                using (SolidBrush b = new SolidBrush(Tx))
                using (StringFormat sf = new StringFormat { LineAlignment = StringAlignment.Center })
                {
                    g.DrawString(_status, FStatus, b, new RectangleF(18, 78, W - 160, 30), sf);
                }

                int pct = (int)Math.Round(_displayPercent);
                Color pc = pct >= 100 ? Ok : Acc;
                using (SolidBrush b = new SolidBrush(pc))
                using (StringFormat sf = new StringFormat
                    { Alignment = StringAlignment.Far, LineAlignment = StringAlignment.Center })
                {
                    g.DrawString(pct + "%", FPercent, b, new RectangleF(W - 128, 76, 110, 32), sf);
                }

                RectangleF track = new RectangleF(18, 124, W - 36, 6);
                using (GraphicsPath tp = Round(track, 3))
                {
                    using (SolidBrush tb = new SolidBrush(Color.FromArgb(18, 30, 40, 70)))
                        g.FillPath(tb, tp);
                    float fw = track.Width * _displayPercent / 100f;
                    if (fw < track.Height) fw = _displayPercent <= 0f ? 0f : track.Height;
                    if (fw > 0.5f)
                    {
                        RectangleF fr = new RectangleF(track.X, track.Y, fw, track.Height);
                        using (GraphicsPath fp = Round(fr, 3))
                        // 渐变锚定在整个轨道上，填充推进时颜色保持稳定
                        using (LinearGradientBrush lg = new LinearGradientBrush(track, Acc, Acc2, 0f))
                            g.FillPath(lg, fp);
                    }
                }
            }

            private void DrawStepsCard(Graphics g, double t)
            {
                RectangleF card = new RectangleF(16, 158, W - 32, 112);
                Card(g, card, Glass2);

                using (SolidBrush b = new SolidBrush(Tx3))
                {
                    g.DrawString("启动步骤", FSmallB, b, new RectangleF(18, 166, 100, 14));
                }

                using (StringFormat far = new StringFormat
                    { Alignment = StringAlignment.Far, LineAlignment = StringAlignment.Center })
                using (StringFormat mid = new StringFormat { LineAlignment = StringAlignment.Center })
                {
                    for (int i = 0; i < _steps.Length; i++)
                    {
                        float ry = 188 + i * 25;
                        StepState s = _steps[i];

                        DrawStepDot(g, 30, ry + 9, s, t);

                        Color tc = s == StepState.Active ? Tx : s == StepState.Pending ? Tx3 : Tx2;
                        using (SolidBrush b = new SolidBrush(tc))
                            g.DrawString(StepNames[i], s == StepState.Active ? FTextB : FText, b,
                                new RectangleF(46, ry, 300, 18), mid);

                        string tag = s == StepState.Done ? "完成"
                            : s == StepState.Active ? "进行中"
                            : s == StepState.Failed ? "失败" : "等待";
                        Color tagc = s == StepState.Done ? Ok
                            : s == StepState.Active ? Acc
                            : s == StepState.Failed ? Bad : Tx3;
                        using (SolidBrush b = new SolidBrush(tagc))
                            g.DrawString(tag, FSmall, b, new RectangleF(W - 96, ry, 66, 18), far);
                    }
                }
            }

            private static void DrawStepDot(Graphics g, float cx, float cy, StepState s, double t)
            {
                if (s == StepState.Pending)
                {
                    RectangleF r = new RectangleF(cx - 4, cy - 4, 8, 8);
                    using (GraphicsPath p = Round(r, 4))
                    {
                        using (SolidBrush b = new SolidBrush(Color.White)) g.FillPath(b, p);
                        using (Pen pen = new Pen(Color.FromArgb(150, Tx3))) g.DrawPath(pen, p);
                    }
                    return;
                }
                Color c = s == StepState.Done ? Ok : s == StepState.Active ? Acc : Bad;
                if (s != StepState.Failed)
                {
                    int ringA = s == StepState.Active
                        ? (int)(95 + 85 * Math.Sin(t * 2 * Math.PI * 1.3))
                        : 60;
                    using (SolidBrush b = new SolidBrush(Color.FromArgb(Math.Max(0, ringA), c)))
                        g.FillEllipse(b, cx - 7, cy - 7, 14, 14);
                }
                using (SolidBrush b = new SolidBrush(c))
                    g.FillEllipse(b, cx - 4, cy - 4, 8, 8);
            }

            private static void DrawHint(Graphics g)
            {
                using (SolidBrush b = new SolidBrush(Tx3))
                using (StringFormat sf = new StringFormat
                    { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center })
                {
                    g.DrawString("后端在后台运行 · 关闭 OASX 窗口后自动退出", FSmall, b,
                        new RectangleF(0, H - 30, W, 20), sf);
                }
            }

            /// <summary>加载 oasx 式神头像：exe 同目录 logo.png → 仓库 deploy\launcher\logo.png。</summary>
            private static Image LoadShikigamiLogo()
            {
                try
                {
                    string dir = Path.GetDirectoryName(Application.ExecutablePath);
                    string p = dir != null ? Path.Combine(dir, "logo.png") : null;
                    if (p == null || !File.Exists(p))
                    {
                        string root = FindRepoRoot();
                        if (root != null)
                            p = Path.Combine(root, "deploy", "launcher", "logo.png");
                    }
                    if (p == null || !File.Exists(p)) return null;
                    using (Bitmap raw = new Bitmap(p))
                        return new Bitmap(raw, 104, 104);
                }
                catch (Exception)
                {
                    return null;
                }
            }

            /// <summary>玻璃卡片：多层柔和投影 + 半透明白底 + 亮边描边。</summary>
            private static void Card(Graphics g, RectangleF r, Color fill)
            {
                for (int i = 3; i >= 1; i--)
                {
                    RectangleF sr = new RectangleF(r.X - i, r.Y - i + 3, r.Width + i * 2, r.Height + i * 2);
                    using (GraphicsPath sp = Round(sr, 14 + i))
                    using (SolidBrush sb = new SolidBrush(Color.FromArgb(24 - i * 6, 60, 80, 140)))
                        g.FillPath(sb, sp);
                }
                using (GraphicsPath p = Round(r, 14))
                {
                    using (SolidBrush b = new SolidBrush(fill)) g.FillPath(b, p);
                    using (Pen pen = new Pen(Stroke)) g.DrawPath(pen, p);
                }
            }

            private static void Glow(Graphics g, float cx, float cy, float rw, float rh, Color c, int alpha)
            {
                using (GraphicsPath path = new GraphicsPath())
                {
                    path.AddEllipse(cx - rw / 2, cy - rh / 2, rw, rh);
                    using (PathGradientBrush pgb = new PathGradientBrush(path))
                    {
                        pgb.CenterColor = Color.FromArgb(alpha, c);
                        pgb.SurroundColors = new[] { Color.FromArgb(0, c) };
                        g.FillPath(pgb, path);
                    }
                }
            }

            private static GraphicsPath Round(RectangleF r, float rad)
            {
                GraphicsPath p = new GraphicsPath();
                float d = rad * 2;
                p.AddArc(r.X, r.Y, d, d, 180, 90);
                p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
                p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
                p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
                p.CloseFigure();
                return p;
            }

            private static Font UiFont(float size, FontStyle style)
            {
                return new Font("Microsoft YaHei UI", size, style, GraphicsUnit.Point);
            }

            private static Font MonoFont(float size)
            {
                return new Font("Consolas", size, FontStyle.Regular, GraphicsUnit.Point);
            }

            [StructLayout(LayoutKind.Sequential)]
            private struct MARGINS
            {
                public int cxLeftWidth;
                public int cxRightWidth;
                public int cyTopHeight;
                public int cyBottomHeight;
            }

            [DllImport("dwmapi.dll")]
            private static extern int DwmExtendFrameIntoClientArea(IntPtr hwnd, ref MARGINS margins);
        }
    }
}

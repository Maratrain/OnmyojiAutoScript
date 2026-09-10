# OAS 整合包发布打包脚本
# 将仓库源码（含 .git，保留用户端在线更新能力）+ 本机 toolkit 运行时
# + oasx 前端打成一个 zip，可直接作为 GitHub Release 资产上传。
#
# 用法:
#   powershell -ExecutionPolicy Bypass -File dev_tools\build_release.ps1 -Version v1.0.0
param(
    # 版本号，用于命名 zip 和 release 标签（如 v1.0.0）；留空则用日期
    [string]$Version = "",
    # 本机 oasx（Flutter GUI）所在目录，要求其中包含 oasx.exe
    [string]$OasxPath = "D:\oasx_new_ui",
    # 打包输出目录，默认为仓库的上一级目录
    [string]$OutRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$SourceUrl = "https://github.com/Maratrain/OnmyojiAutoScript"
$Branch = "mine"

if (-not $Version) { $Version = "v" + (Get-Date -Format "yyyyMMdd") }
if (-not $OutRoot) { $OutRoot = Split-Path -Parent $RepoRoot }

Write-Host "=== OAS 发布打包 ==="

# ---- 前置检查 ----
$dirty = git -C $RepoRoot status --porcelain
if ($dirty) {
    Write-Warning "工作区有未提交的修改，以下内容不会进入发布包："
    $dirty | ForEach-Object { Write-Warning "  $_" }
}
$localHead = git -C $RepoRoot rev-parse HEAD
$remoteHead = git -C $RepoRoot rev-parse "origin/$Branch"
if ($localHead -ne $remoteHead) {
    throw "本地 HEAD 与 origin/$Branch 不一致，请先 push 后再打包，否则用户端在线更新会拉到不同代码"
}
if (-not (Test-Path (Join-Path $RepoRoot "toolkit\python.exe"))) {
    throw "仓库根目录下未找到 toolkit\python.exe，请先在本机完成一次完整安装"
}
if (-not (Test-Path (Join-Path $OasxPath "oasx.exe"))) {
    throw "未找到 oasx: $OasxPath\oasx.exe 不存在，可用 -OasxPath 参数指定其它目录"
}

$BuildDir = Join-Path $OutRoot ("oas_release_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
$PkgName = "OnmyojiAutoScript"
$PkgDir = Join-Path $BuildDir $PkgName
New-Item -ItemType Directory -Path $PkgDir -Force | Out-Null

# ---- 1. 克隆仓库源码（个人配置、log、toolkit 均不在 git 追踪内，天然隔离） ----
Write-Host "[1/4] 克隆仓库源码..."
git clone --single-branch --branch $Branch -q $RepoRoot $PkgDir
if ($LASTEXITCODE -ne 0) { throw "git clone 失败" }
# origin 指向 GitHub 仓库，保证用户端界面里的“更新”按钮可用
git -C $PkgDir remote set-url origin $SourceUrl
if ($LASTEXITCODE -ne 0) { throw "设置 origin 失败" }

# ---- 2. 复制 toolkit 运行时（内嵌 Python + Git + 依赖 + adb） ----
Write-Host "[2/4] 复制 toolkit 运行时（约 800MB，需要几分钟）..."
robocopy (Join-Path $RepoRoot "toolkit") (Join-Path $PkgDir "toolkit") /E /NFL /NDL /NJH /NJS /MT:16 | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制 toolkit 失败，robocopy 退出码 $LASTEXITCODE" }

# ---- 3. 复制根目录启动器（未被 git 追踪，需从本机复制）与 oasx ----
Write-Host "[3/4] 复制启动器与 oasx..."
foreach ($f in @("oas.exe", "oas-launcher.exe", "oas-backend.bat", "console.bat")) {
    Copy-Item (Join-Path $RepoRoot $f) (Join-Path $PkgDir $f)
}
robocopy $OasxPath (Join-Path $PkgDir "oasx") /E /XD logs /NFL /NDL /NJH /NJS /MT:8 | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制 oasx 失败，robocopy 退出码 $LASTEXITCODE" }

# 使用说明
@"
OnmyojiAutoScript 整合包
========================

1. 将整个文件夹解压到任意路径（建议纯英文路径）
2. 双击 oas-launcher.exe 启动：会自动拉起后端并打开 oasx 界面
3. 遇到问题可用 console.bat 打开调试控制台（adb / git / python / pip）
4. 界面内的“更新”按钮可在线更新脚本（源指向 GitHub 仓库）

模拟器需开启 ADB 调试，首次使用在 oasx 中选择模拟器 serial 即可。
"@ | Out-File -FilePath (Join-Path $PkgDir "使用说明.txt") -Encoding utf8

# ---- 4. 压缩 zip ----
Write-Host "[4/4] 压缩 zip（需要几分钟）..."
$ZipPath = Join-Path $BuildDir ("OnmyojiAutoScript-easy-install-" + $Version + ".zip")
# 优先用系统自带的 bsdtar（Git Bash 环境下 PATH 里的 GNU tar 不支持打包 zip）
$Tar = Join-Path $env:WINDIR "System32\tar.exe"
if (Test-Path $Tar) {
    & $Tar -a -cf $ZipPath -C $BuildDir $PkgName
    if ($LASTEXITCODE -ne 0) { throw "压缩失败" }
} else {
    Compress-Archive -Path $PkgDir -DestinationPath $ZipPath -CompressionLevel Optimal
}

$size = "{0:N0} MB" -f ((Get-Item $ZipPath).Length / 1MB)
$gh = "C:\Program Files\GitHub CLI\gh.exe"
Write-Host ""
Write-Host "打包完成: $ZipPath ($size)"
Write-Host "构建目录（确认发布成功后可手动删除）: $BuildDir"
Write-Host ""
Write-Host "发布方式二选一:"
Write-Host "  网页: 仓库 Releases -> Draft a new release -> 新建标签 $Version -> 上传 zip -> Publish"
Write-Host ("  命令行: & '{0}' release create {1} '{2}' --title '{1}' --notes '整合包，解压后双击 oas-launcher.exe 即可使用'" -f $gh, $Version, $ZipPath)

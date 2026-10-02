# 大肥鱼诊断工具：记录「文档」窗口是谁打开的
# 运行 20 分钟，写入 logs\boot_watch.log；由大肥鱼开机自启时自动拉起。
$ErrorActionPreference = "SilentlyContinue"
$base = Split-Path -Parent $PSScriptRoot
$global:LOG = Join-Path $base "logs\boot_watch.log"
$global:DIR = Join-Path $base "logs"
$global:WIN = @{}
$global:seen = @{}

function Log([string]$m) {
    try { "{0:HH:mm:ss.fff} {1}" -f (Get-Date), $m | Out-File -FilePath $global:LOG -Append -Encoding utf8 } catch {}
}

$lock = Join-Path $global:DIR "boot_watch.pid"
Set-Content -LiteralPath $lock -Value $PID -Encoding ascii
Log "=== 监视开始 pid=$PID（记录新进程与资源管理器窗口） ==="

Register-CimIndicationEvent -Query "SELECT * FROM __InstanceCreationEvent WITHIN 1 WHERE TargetInstance ISA 'Win32_Process'" -SourceIdentifier dfy_proc | Out-Null

Add-Type -Namespace DFY -Name W -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
public delegate bool EnumProc(IntPtr h, IntPtr l);
[DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int n);
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, System.Text.StringBuilder s, int n);
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
'@

$names = @{}
foreach ($p in Get-Process) { $names[[int]$p.Id] = $p.ProcessName }

$cb = [DFY.W+EnumProc]{
    param($h, $l)
    try {
        if ([DFY.W]::IsWindowVisible($h)) {
            $cls = New-Object System.Text.StringBuilder 256
            [DFY.W]::GetClassName($h, $cls, 256) | Out-Null
            if ($cls.ToString() -in @("CabinetWClass", "ExploreWClass")) {
                $t = New-Object System.Text.StringBuilder 512
                [DFY.W]::GetWindowText($h, $t, 512) | Out-Null
                $global:WIN[[int64]$h] = $t.ToString()
            }
        }
    } catch {}
    return $true
}

$deadline = (Get-Date).AddMinutes(20)
while ((Get-Date) -lt $deadline) {
    while ($true) {
        $ev = Get-Event -SourceIdentifier dfy_proc -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $ev) { break }
        Remove-Event -EventIdentifier $ev.EventIdentifier | Out-Null
        $ti = $ev.SourceEventArgs.NewEvent.TargetInstance
        $ppid = [int]$ti.ParentProcessId
        $pname = if ($names.ContainsKey($ppid)) { $names[$ppid] } else { "?" }
        $names[[int]$ti.ProcessId] = [string]$ti.Name
        Log ("PROC {0} (pid {1}, 父: {2}/{3}) :: {4}" -f $ti.Name, $ti.ProcessId, $pname, $ppid, $ti.CommandLine)
    }
    $global:WIN = @{}
    [DFY.W]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
    foreach ($k in @($global:WIN.Keys)) {
        if (-not $global:seen.ContainsKey($k)) {
            Log ("WINDOW 出现: [{0}] hwnd={1}" -f $global:WIN[$k], $k)
        }
    }
    foreach ($k in @($global:seen.Keys)) {
        if (-not $global:WIN.ContainsKey($k)) {
            Log ("WINDOW 关闭: [{0}] hwnd={1}" -f $global:seen[$k], $k)
        }
    }
    $global:seen = @{}
    foreach ($k in @($global:WIN.Keys)) { $global:seen[$k] = $global:WIN[$k] }
    Start-Sleep -Milliseconds 400
}

Log "=== 监视结束 ==="
Remove-Item -LiteralPath $lock -ErrorAction SilentlyContinue

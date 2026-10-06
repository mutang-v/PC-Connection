"""读取只读系统指标。依赖 psutil。"""
import os
import platform
import socket
import time
from collections import deque
import psutil


class MetricsCollector:
    """采集 CPU/内存/磁盘/网络等只读指标，并维护最近一段时间的趋势历史。"""

    def __init__(self, trend_len: int = 30):
        # 趋势历史：最近 trend_len 个采样点的 CPU / 内存使用率
        self.trend_len = trend_len
        self.cpu_trend = deque(maxlen=trend_len)
        self.mem_trend = deque(maxlen=trend_len)
        self._last_net = None
        self._last_time = None
        # 进程 CPU 使用率采样基线：进程标识 -> (上次累计cpu时间, 上次采样时刻)
        self._proc_cpu_base: dict = {}
        self._proc_cpu_base_time: float = 0.0

    @staticmethod
    def _system_disk_path():
        return os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/"

    def stats(self):
        now = time.time()
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        try:
            disk = psutil.disk_usage(self._system_disk_path())
        except Exception:
            disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()
        rx = tx = 0.0
        if self._last_net is not None and self._last_time is not None:
            elapsed = max(now - self._last_time, 0.001)
            rx = max(0, net.bytes_recv - self._last_net.bytes_recv) / elapsed
            tx = max(0, net.bytes_sent - self._last_net.bytes_sent) / elapsed
        self._last_net, self._last_time = net, now

        # 记录趋势
        self.cpu_trend.append(round(cpu, 1))
        self.mem_trend.append(round(mem.percent, 1))

        # 各分区占用
        partitions = self.disk_partitions()

        return {
            "time": time.strftime("%H:%M:%S"),
            "host": socket.gethostname(),
            "os": platform.system(),
            "cpu": round(cpu, 1),
            "cpu_trend": list(self.cpu_trend),
            "mem_pct": round(mem.percent, 1),
            "mem_trend": list(self.mem_trend),
            "mem_used": round(mem.used / 1024**3, 1),
            "mem_total": round(mem.total / 1024**3, 1),
            "mem_available": round(mem.available / 1024**3, 1),
            "disk_pct": round(disk.percent, 1),
            "disk_used": round(disk.used / 1024**3, 1),
            "disk_total": round(disk.total / 1024**3, 1),
            "partitions": partitions,
            "rx_mbps": round(rx * 8 / 1_000_000, 2),
            "tx_mbps": round(tx * 8 / 1_000_000, 2),
            "uptime": int(time.time() - psutil.boot_time()),
            "battery": self.battery(),
        }

    @staticmethod
    def battery() -> dict:
        """返回电脑电池/充电状态（台式机或读不到时返回 plausible null）。"""
        try:
            bat = psutil.sensors_battery()
            if bat is None:
                return {"present": False, "percent": None, "plugged": None, "secsleft": None}
            secs = bat.secsleft
            if isinstance(secs, psutil._common.BatteryTime):
                secs = None
            mins_left = round(secs / 60) if isinstance(secs, (int, float)) and secs > 0 else None
            return {
                "present": True,
                "percent": int(bat.percent),
                "plugged": bool(bat.power_plugged),
                "secsleft": secs,
                "mins_left": mins_left,
            }
        except Exception:  # noqa: BLE001
            return {"present": False, "percent": None, "plugged": None, "secsleft": None}

    def alerts(self, thresholds=None) -> dict:
        """基于当前状态与趋势生成告警。thresholds 可覆盖默认阈值。"""
        t = thresholds or {
            "cpu_high": 90, "mem_high": 90, "disk_high": 90,
            "battery_low": 20, "cpu_spike": 95,
        }
        alerts = []
        cpu = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory()
        try:
            disk = psutil.disk_usage(self._system_disk_path())
        except Exception:
            disk = psutil.disk_usage("/")
        if cpu >= t["cpu_spike"]:
            alerts.append({"level": "critical", "kind": "cpu", "message": f"CPU 使用率异常偏高：{cpu:.0f}%"})
        elif cpu >= t["cpu_high"]:
            alerts.append({"level": "warning", "kind": "cpu", "message": f"CPU 使用率偏高：{cpu:.0f}%"})
        if mem.percent >= t["mem_high"]:
            alerts.append({"level": "warning", "kind": "memory", "message": f"内存使用率偏高：{mem.percent:.0f}%"})
        if disk.percent >= t["disk_high"]:
            alerts.append({"level": "warning", "kind": "disk", "message": f"系统盘空间不足：{disk.percent:.0f}%"})
        bat = self.battery()
        if bat.get("present") and bat.get("percent") is not None and not bat.get("plugged"):
            if bat["percent"] <= t["battery_low"]:
                alerts.append({"level": "critical", "kind": "battery", "message": f"电量不足：{bat['percent']}%（未充电）"})
        # 近 5 点 CPU 持续高位（超过 80% 的尖峰）
        recent = list(self.cpu_trend)[-5:]
        if len(recent) >= 5 and all(x >= 80 for x in recent):
            alerts.append({"level": "warning", "kind": "cpu_sustained", "message": "CPU 已持续高位运行"})
        return {"ok": True, "alerts": alerts, "count": len(alerts), "current": {
            "cpu": round(cpu, 1), "mem": round(mem.percent, 1),
            "disk": round(disk.percent, 1), "battery": bat,
        }}

    @staticmethod
    def top_processes(limit=6, key="memory_mb"):
        """按内存(默认)或 CPU 排序返回 top 进程（含 pid，便于结束）。"""
        processes = []
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                info = proc.info
                mem_info = info.get("memory_info")
                rss = mem_info.rss if mem_info else 0
                processes.append({
                    "pid": int(info.get("pid") or 0),
                    "name": info.get("name") or "未知进程",
                    "memory_mb": round(rss / 1024**2, 1),
                    "cpu_pct": 0.0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        processes.sort(key=lambda p: p["memory_mb"], reverse=True)
        return processes[:limit]

    def cpu_processes(self, limit=8):
        """返回 CPU 占用最高的进程（按真实使用率百分比）。

        通过比较两次采样之间的累计 CPU 时间差来计算使用率，
        因此第一次调用会作为基线返回 0%，之后的调用会返回可用的百分比。
        """
        now = time.time()
        elapsed = now - self._proc_cpu_base_time
        base = self._proc_cpu_base
        # 若从未采样过，或距上次采样过久（> 10s），重新建立基线
        if not base or elapsed <= 0 or elapsed > 10:
            self._proc_cpu_base = self._snapshot_cpu_times()
            self._proc_cpu_base_time = now
            return []
        nproc = max(psutil.cpu_count() or 1, 1)
        cur = self._snapshot_cpu_times()
        scaled = max(elapsed * nproc, 2.0)
        out = []
        for pid, (name, total) in cur.items():
            b = base.get(pid)
            if b is None:
                continue
            delta = max(0.0, total - b[1])
            pct = min(100.0, delta / scaled * 100.0)
            out.append({"pid": pid, "name": name, "cpu_pct": round(pct, 1)})
        self._proc_cpu_base = cur
        self._proc_cpu_base_time = now
        out.sort(key=lambda p: p["cpu_pct"], reverse=True)
        # 附带内存，方便展示
        mem_index = {p["name"]: p["memory_mb"] for p in self.top_processes(limit=50)}
        for p in out:
            p["memory_mb"] = round(mem_index.get(p["name"], 0.0), 1)
        return out[:limit]

    @staticmethod
    def _snapshot_cpu_times() -> dict:
        snap = {}
        for proc in psutil.process_iter(["pid", "name", "cpu_times"]):
            try:
                info = proc.info
                times = info.get("cpu_times")
                if not times:
                    continue
                total = (times.user or 0) + (times.system or 0)
                snap[int(info["pid"])] = ((info.get("name") or "未知进程"), total)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, KeyError):
                continue
        return snap

    @staticmethod
    def disk_partitions():
        """返回各磁盘分区占用（仅本地固定磁盘，过滤 0 容量）。"""
        parts = []
        for part in psutil.disk_partitions(all=False):
            if os.name == "nt" and not part.fstype:
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            total = usage.total / 1024**3
            # 过滤光驱/虚拟光驱等：无介质时 total 可能不足 1GB 且空闲为 0
            if total < 0.5:
                continue
            parts.append({
                "mountpoint": part.mountpoint,
                "total_gb": round(total, 1),
                "used_gb": round(usage.used / 1024**3, 1),
                "free_gb": round(usage.free / 1024**3, 1),
                "percent": round(usage.percent, 1),
            })
        parts.sort(key=lambda p: p["mountpoint"])
        return parts

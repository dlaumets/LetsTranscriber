"""Server metrics collectors for the monitor bot."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcMem:
    total_kb: int
    available_kb: int
    swap_total_kb: int
    swap_free_kb: int


def _read_meminfo() -> ProcMem:
    data: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        data[key.strip()] = int(value.strip().split()[0])
    return ProcMem(
        total_kb=data.get("MemTotal", 0),
        available_kb=data.get("MemAvailable", 0),
        swap_total_kb=data.get("SwapTotal", 0),
        swap_free_kb=data.get("SwapFree", 0),
    )


def _fmt_mb(kb: int) -> str:
    return f"{kb / 1024:.0f} MB"


def _run(cmd: list[str], timeout: int = 5) -> str:
    if not shutil.which(cmd[0]):
        return ""
    wrapped = cmd
    if shutil.which("timeout") and timeout > 0:
        wrapped = ["timeout", str(timeout), *cmd]
    try:
        result = subprocess.run(
            wrapped,
            capture_output=True,
            text=True,
            timeout=timeout + 2,
            check=False,
        )
        return (result.stdout or result.stderr or "").strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _docker_stats_rows() -> list[str]:
    out = _run(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}",
        ],
        timeout=6,
    )
    return [line for line in out.splitlines() if line.strip()]


def _docker_stats_map() -> dict[str, str]:
    rows: dict[str, str] = {}
    for row in _docker_stats_rows():
        parts = row.split("\t")
        if len(parts) >= 3:
            rows[parts[0]] = row
    return rows


def collect_server() -> str:
    mem = _read_meminfo()
    used_kb = mem.total_kb - mem.available_kb
    swap_used_kb = mem.swap_total_kb - mem.swap_free_kb
    load = Path("/proc/loadavg").read_text().split()[:3]
    cpu_count = os_cpu_count()
    disk = _run(["df", "-h", "/", "--output=size,used,avail,pcent", "-x", "tmpfs"])
    uptime = _run(["uptime", "-p"]) or _run(["uptime"])

    lines = [
        "🖥 <b>Сервер</b>",
        f"CPU: {cpu_count} ядер · load {load[0]} {load[1]} {load[2]}",
        f"RAM: {_fmt_mb(used_kb)} / {_fmt_mb(mem.total_kb)} ({pct(used_kb, mem.total_kb)}%)",
        f"Swap: {_fmt_mb(swap_used_kb)} / {_fmt_mb(mem.swap_total_kb)}",
    ]
    if disk:
        lines.append(f"Диск /: {disk.splitlines()[-1].strip()}")
    if uptime:
        lines.append(f"Uptime: {uptime.replace('up ', '')}")
    return "\n".join(lines)


def os_cpu_count() -> int:
    try:
        return len(Path("/proc/cpuinfo").read_text().split("processor\t:")) or 1
    except OSError:
        return 1


def pct(used: int, total: int) -> int:
    if total <= 0:
        return 0
    return round(used * 100 / total)


def collect_docker() -> str:
    rows = _docker_stats_rows()
    if not rows:
        return "🐳 <b>Docker</b>\nнет данных (таймаут или docker недоступен)"
    lines = ["🐳 <b>Docker</b>"]
    for row in rows:
        name, cpu, mem, mem_pct = row.split("\t", 3)
        short = name.replace("letstranscriber-", "").removesuffix("-1")
        lines.append(f"• <code>{short}</code>: CPU {cpu}, RAM {mem} ({mem_pct})")
    return "\n".join(lines)


def collect_cpv(units: list[str]) -> str:
    return collect_systemd(units).replace("⚙️ <b>Systemd</b>", "📋 <b>CPV Bot</b>")


def collect_systemd(units: list[str]) -> str:
    lines = ["⚙️ <b>Systemd</b>"]
    for unit in units:
        props = _run(
            [
                "systemctl",
                "show",
                unit,
                "--property=ActiveState,SubState,MemoryCurrent,CPUUsageNSec",
                "--no-pager",
            ]
        )
        if not props:
            lines.append(f"• <code>{unit}</code>: не найден")
            continue
        data = dict(line.split("=", 1) for line in props.splitlines() if "=" in line)
        raw_mem = data.get("MemoryCurrent", "0") or "0"
        mem = 0 if raw_mem.startswith("[") else int(raw_mem)
        raw_cpu = data.get("CPUUsageNSec", "0") or "0"
        cpu_ns = 0 if raw_cpu.startswith("[") else int(raw_cpu)
        state = data.get("ActiveState", "?")
        lines.append(
            f"• <code>{unit}</code>: {state}, "
            f"RAM {_fmt_mb(mem // 1024)}, CPU {cpu_ns / 1e9:.1f}s"
        )
    return "\n".join(lines)


def collect_vpn(iface: str = "awg0") -> str:
    if not Path(f"/sys/class/net/{iface}").exists():
        return f"🔒 <b>VPN ({iface})</b>\nинтерфейс не найден"

    rx = Path(f"/sys/class/net/{iface}/statistics/rx_bytes").read_text().strip()
    tx = Path(f"/sys/class/net/{iface}/statistics/tx_bytes").read_text().strip()
    wg = _run(["wg", "show", iface])
    lines = [
        f"🔒 <b>VPN ({iface})</b>",
        f"Трафик: ↓ {_fmt_bytes(int(rx))} · ↑ {_fmt_bytes(int(tx))}",
    ]
    if wg:
        peers = [line for line in wg.splitlines() if line.strip().startswith("peer:")]
        lines.append(f"Пиров: {len(peers)}")
        for line in wg.splitlines():
            if "latest handshake:" in line or "transfer:" in line:
                lines.append(f"  {line.strip()}")
    return "\n".join(lines)


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


def collect_transcriber(api_url: str = "http://127.0.0.1:8000") -> str:
    lines = ["🎙 <b>LetsTranscriber</b>"]
    health = _run(["curl", "-sf", "--max-time", "3", f"{api_url}/v1/health"], timeout=4)
    if health:
        try:
            data = json.loads(health)
            lines.append(
                f"API: ok · модель {'загружена' if data.get('model_loaded') else 'не в памяти'}"
            )
            lines.append(
                f"Очередь: {data.get('queue_size', 0)} · preset: {data.get('current_preset') or '—'}"
            )
        except json.JSONDecodeError:
            lines.append(f"API: {health[:120]}")
    else:
        lines.append("API: недоступен")

    stats = _docker_stats_map()
    for cname in ("letstranscriber-api-1", "letstranscriber-bot-1", "letstranscriber-db-1"):
        row = stats.get(cname)
        if not row:
            continue
        name, cpu, mem, _mem_pct = row.split("\t", 3)
        short = name.replace("letstranscriber-", "").removesuffix("-1")
        lines.append(f"• <code>{short}</code>: CPU {cpu}, RAM {mem}")
    return "\n".join(lines)


def collect_all(transcriber_api: str) -> str:
    stats = _docker_stats_rows()
    docker_text = _format_docker_rows(stats)

    parts = [
        collect_server(),
        "",
        collect_transcriber_from_stats(transcriber_api, stats),
        "",
        docker_text,
        "",
        collect_systemd(["cpv-bot.service", "cpv-api.service"]),
        "",
        collect_vpn(),
    ]
    return "\n\n".join(parts)


def _format_docker_rows(rows: list[str]) -> str:
    if not rows:
        return "🐳 <b>Docker</b>\nнет данных (таймаут или docker недоступен)"
    lines = ["🐳 <b>Docker</b>"]
    for row in rows:
        name, cpu, mem, mem_pct = row.split("\t", 3)
        short = name.replace("letstranscriber-", "").removesuffix("-1")
        lines.append(f"• <code>{short}</code>: CPU {cpu}, RAM {mem} ({mem_pct})")
    return "\n".join(lines)


def collect_transcriber_from_stats(api_url: str, stats_rows: list[str]) -> str:
    lines = ["🎙 <b>LetsTranscriber</b>"]
    health = _run(["curl", "-sf", "--max-time", "3", f"{api_url}/v1/health"], timeout=4)
    if health:
        try:
            data = json.loads(health)
            lines.append(
                f"API: ok · модель {'загружена' if data.get('model_loaded') else 'не в памяти'}"
            )
            lines.append(
                f"Очередь: {data.get('queue_size', 0)} · preset: {data.get('current_preset') or '—'}"
            )
        except json.JSONDecodeError:
            lines.append(f"API: {health[:120]}")
    else:
        lines.append("API: недоступен")

    stats = {row.split("\t", 1)[0]: row for row in stats_rows}
    for cname in ("letstranscriber-api-1", "letstranscriber-bot-1", "letstranscriber-db-1"):
        row = stats.get(cname)
        if not row:
            continue
        name, cpu, mem, _mem_pct = row.split("\t", 3)
        short = name.replace("letstranscriber-", "").removesuffix("-1")
        lines.append(f"• <code>{short}</code>: CPU {cpu}, RAM {mem}")
    return "\n".join(lines)

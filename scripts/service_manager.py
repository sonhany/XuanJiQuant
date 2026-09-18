"""统一服务管理器 — 合并 API + Web + Supervisor 为单进程。

替代原来的 3 个 Windows Scheduled Task:
  - XuanJiQuant-API-Service
  - XuanJiQuant-Web-Service
  - XuanJiQuant-Service-Supervisor

功能:
  1. 启动 API 子进程 (node server/index.mjs)
  2. 启动 Web 子进程 (vite)
  3. 每 60s 检查子进程健康，自动重启
  4. SIGTERM/SIGINT 时优雅关闭所有子进程
  5. 写日志到 logs/service-manager-{timestamp}.log
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)

SERVICE_HOST = ROOT / "scripts" / "service_host.cmd"
CHECK_INTERVAL = 60  # seconds
RESTART_DELAY = 3    # seconds before restart


@dataclass
class ChildProcess:
    name: str
    service: str  # 'api' or 'web'
    process: subprocess.Popen | None = None
    restart_count: int = 0
    max_restarts: int = 100
    last_exit: int = 0
    last_error: str = ""

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> bool:
        if self.alive:
            return True
        if self.restart_count >= self.max_restarts:
            logging.error(f"[{self.name}] max restarts ({self.max_restarts}) reached, not restarting")
            return False
        try:
            log_out = LOGS / f"{self.service}-out.log"
            log_err = LOGS / f"{self.service}-err.log"
            fh_out = open(log_out, "a", encoding="utf-8")
            fh_err = open(log_err, "a", encoding="utf-8")
            self.process = subprocess.Popen(
                [str(SERVICE_HOST), self.service],
                cwd=str(ROOT),
                stdout=fh_out,
                stderr=fh_err,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.restart_count += 1
            logging.info(f"[{self.name}] started (pid={self.process.pid}, restart #{self.restart_count})")
            return True
        except Exception as e:
            self.last_error = str(e)
            logging.error(f"[{self.name}] start failed: {e}")
            return False

    def stop(self) -> None:
        if self.process is None:
            return
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
            logging.info(f"[{self.name}] stopped (pid={self.process.pid})")
        except subprocess.TimeoutExpired:
            self.process.kill()
            logging.warning(f"[{self.name}] force-killed (pid={self.process.pid})")
        except Exception as e:
            logging.warning(f"[{self.name}] stop error: {e}")
        finally:
            self.process = None

    def check_health(self) -> bool:
        if not self.alive:
            self.last_exit = self.process.returncode if self.process else -1
            logging.warning(f"[{self.name}] exited with code {self.last_exit}")
            time.sleep(RESTART_DELAY)
            return self.start()
        return True


def _setup_logging() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS / f"service-manager-{ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def _write_status(children: list[ChildProcess]) -> None:
    status_file = LOGS / "service-manager-status.json"
    status = {}
    for c in children:
        status[c.name] = {
            "pid": c.process.pid if c.process else None,
            "alive": c.alive,
            "restarts": c.restart_count,
            "last_exit": c.last_exit,
            "last_error": c.last_error,
        }
    status["_updated"] = datetime.now().isoformat()
    status_file.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    _setup_logging()
    logging.info("=" * 60)
    logging.info("XuanJiQuant Service Manager starting")
    logging.info(f"  Project: {ROOT}")
    logging.info(f"  Service host: {SERVICE_HOST}")
    logging.info(f"  Check interval: {CHECK_INTERVAL}s")
    logging.info("=" * 60)

    if not SERVICE_HOST.exists():
        logging.error(f"service_host.cmd not found: {SERVICE_HOST}")
        return 1

    children = [
        ChildProcess(name="XuanJiQuant-API", service="api"),
        ChildProcess(name="XuanJiQuant-Web", service="web"),
    ]

    # Graceful shutdown
    def shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        logging.info(f"Received {sig_name}, shutting down...")
        for c in children:
            c.stop()
        _write_status(children)
        logging.info("Service Manager stopped")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Start all services
    for c in children:
        if not c.start():
            logging.error(f"Failed to start {c.name}, aborting")
            return 1

    _write_status(children)

    # Supervisor loop
    logging.info(f"Supervisor loop started (check every {CHECK_INTERVAL}s)")
    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            for c in children:
                if not c.check_health():
                    logging.error(f"{c.name} unrecoverable, continuing without it")
            _write_status(children)
        except KeyboardInterrupt:
            shutdown(signal.SIGINT, None)
        except Exception as e:
            logging.error(f"Supervisor loop error: {e}", exc_info=True)
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    sys.exit(main())

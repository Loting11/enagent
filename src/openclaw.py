import json
import os
import pty
import select
import shutil
import subprocess
import time


DEFAULT_CLI_PATH = "openclaw"
CLI_CANDIDATES = (
    "openclaw",
    "/home/ubuntu/.local/bin/openclaw",
    "/usr/local/bin/openclaw",
    "/Users/zhouti/.local/opt/node-v24.17.0-darwin-arm64/bin/openclaw",
)


class OpenClawError(Exception):
    pass


def resolve_cli_path(configured_path=""):
    if configured_path:
        return configured_path
    for path in CLI_CANDIDATES:
        if not path:
            continue
        if os.path.isabs(path) and os.path.exists(path) and os.access(path, os.X_OK):
            return path
        found = shutil.which(path)
        if found:
            return found
    return DEFAULT_CLI_PATH


def cli_available(configured_path=""):
    path = resolve_cli_path(configured_path)
    if os.path.isabs(path):
        return os.path.exists(path) and os.access(path, os.X_OK)
    return shutil.which(path) is not None


class OpenClawClient:
    def __init__(
        self,
        cli_path=None,
        channel=None,
        account_id=None,
        enabled=None,
        runner=None,
    ):
        configured_cli = cli_path if cli_path is not None else os.getenv("OPENCLAW_CLI_PATH", "")
        self.cli_path = resolve_cli_path(configured_cli)
        self.channel = channel if channel is not None else os.getenv("OPENCLAW_CHANNEL", "openclaw-weixin")
        self.account_id = account_id if account_id is not None else os.getenv("OPENCLAW_ACCOUNT_ID", "")
        raw_enabled = enabled if enabled is not None else os.getenv("OPENCLAW_ENABLED", "")
        self.enabled = str(raw_enabled).lower() in ("1", "true", "yes", "on")
        self.runner = runner or subprocess.run

    @property
    def configured(self):
        return bool(self.enabled and self.cli_path and self.account_id)

    def _run(self, args, timeout=30):
        command = [self.cli_path, *args]
        try:
            result = self.runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise OpenClawError(
                "服务器未安装 OpenClaw，或 CLI 路径不可执行。请先在服务器安装 OpenClaw，或将 OPENCLAW_CLI_PATH 指向正确路径。"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise OpenClawError("OpenClaw 命令执行超时") from exc

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "未知错误").strip()
            raise OpenClawError(f"OpenClaw 执行失败：{message[:500]}")
        return result.stdout.strip()

    def status(self):
        return self._run(["channels", "status", "--probe"], timeout=60)

    def login_command(self, account_id=""):
        if not cli_available(self.cli_path):
            raise OpenClawError(
                "服务器未安装 OpenClaw，暂时不能生成微信登录二维码。请先完成服务器 OpenClaw 安装。"
            )
        args = [self.cli_path, "channels", "login", "--channel", self.channel]
        if account_id:
            args.extend(["--account", account_id])
        return args

    def send_text(self, target, text, account_id=None):
        send_account_id = account_id or self.account_id
        if not (self.enabled and self.cli_path and send_account_id):
            raise OpenClawError("OpenClaw 微信入口尚未启用或缺少账号 ID")
        args = ["message", "send", "--account", send_account_id, "--target", str(target), "--message", str(text)]
        if self.channel:
            args.extend(["--channel", self.channel])
        output = self._run(args)
        try:
            return json.loads(output) if output.startswith("{") else {"ok": True, "output": output}
        except json.JSONDecodeError:
            return {"ok": True, "output": output}


class OpenClawLoginSession:
    def __init__(self, command):
        self.command = command
        self.started_at = time.time()
        self.output = ""
        self.error = ""
        self.master_fd = None
        self.process = None
        self._start()

    def _start(self):
        master_fd, slave_fd = pty.openpty()
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                text=False,
            )
            self.master_fd = master_fd
        except Exception:
            os.close(master_fd)
            raise
        finally:
            os.close(slave_fd)

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    @property
    def returncode(self):
        return None if self.process is None else self.process.poll()

    def read_available(self):
        if self.master_fd is None:
            return self.output
        chunks = []
        while True:
            ready, _, _ = select.select([self.master_fd], [], [], 0)
            if not ready:
                break
            try:
                data = os.read(self.master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            chunks.append(data.decode("utf-8", errors="replace"))
        if chunks:
            self.output += "".join(chunks)
            if len(self.output) > 20000:
                self.output = self.output[-20000:]
        return self.output

    def stop(self):
        if self.running:
            self.process.terminate()
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

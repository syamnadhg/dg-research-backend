"""Wave 13 (low) — gRPC's fork support is off, so no forked child runs gRPC.

⛔ WHAT THE OWNER'S LOGS SHOWED. Three FATAL lines in the machine's err logs
(08-25, 09-16, 09-29):

    F0929 07:37:34 ev_poll_posix.cc:659] Check failed: wakeup_fd_->ConsumeWakeup().ok()

The worker kept running each time, so the process that aborted was not the
worker. The 09-16 and 09-29 ones fell in the very second the worker launched
the browser (a burst of subprocess forks while the Firestore client's threads
were busy). grpcio ships fork support ON: every fork re-starts gRPC's poller
inside the child, in the moment before the child execs its program, and that
poller raced the exec and aborted the half-born child.

⭐ Driven for real: a child Python imports research (which sets the gRPC
defaults), then starts a real gRPC server and a held-open stream on an
OS-chosen local port, then forks plain `sh -c 'exit 0'` children. A child that
ran any gRPC code before its exec says so on its stderr (GRPC_VERBOSITY=INFO).
Before the fix, most of them did.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

_CHILD = r"""
import subprocess, sys, threading, time
sys.argv = ['research.py']
import research  # sets the gRPC defaults before gRPC is first imported
import grpc
from concurrent import futures

def watch(req, ctx):
    while ctx.is_active():
        time.sleep(0.02)
        yield b"t"

handler = grpc.method_handlers_generic_handler(
    "t.T", {"W": grpc.unary_stream_rpc_method_handler(watch)})
server = grpc.server(futures.ThreadPoolExecutor(4))
server.add_generic_rpc_handlers((handler,))
port = server.add_insecure_port("127.0.0.1:0")
server.start()
channel = grpc.insecure_channel(f"127.0.0.1:{port}")
stream = channel.unary_stream("/t.T/W")(b"w")
next(stream)
threading.Thread(target=lambda: [None for _ in stream], daemon=True).start()
talking = 0
for _ in range(200):
    r = subprocess.run(["/bin/sh", "-c", "exit 0"], capture_output=True)
    if r.stderr:
        talking += 1
        sample = r.stderr.decode(errors="replace")[:200]
print("CHILDREN_THAT_RAN_GRPC", talking)
if talking:
    print("SAMPLE", sample)
stream.cancel()
server.stop(0)
"""


def _child_env(**over):
    env = dict(os.environ)
    env.pop("GRPC_ENABLE_FORK_SUPPORT", None)
    env["DG_ALERT_AI_COPY"] = "0"
    env.update(over)
    return env


@pytest.mark.skipif(sys.platform != "darwin",
                    reason="the owner's crash is macOS's: Linux's subprocess uses vfork "
                           "(no fork handlers run) and Windows does not fork")
def test_no_forked_child_runs_grpc_before_its_exec():
    out = subprocess.run([sys.executable, "-c", _CHILD], cwd=str(REPO),
                         env=_child_env(GRPC_VERBOSITY="INFO"), capture_output=True,
                         text=True, encoding="utf-8", errors="replace", timeout=240)
    assert "CHILDREN_THAT_RAN_GRPC" in out.stdout, (out.stdout[-1500:], out.stderr[-1500:])
    assert "CHILDREN_THAT_RAN_GRPC 0\n" in out.stdout, out.stdout[-1500:]


def _setting_after_import(preset):
    env = _child_env(**({} if preset is None else {"GRPC_ENABLE_FORK_SUPPORT": preset}))
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys, os; sys.argv = ['research.py']; import research; "
         "sys.stdout.write(os.environ.get('GRPC_ENABLE_FORK_SUPPORT', '<unset>') "
         "+ ' grpc-loaded=' + str('grpc' in sys.modules))"],
        cwd=str(REPO), env=env, capture_output=True, text=True, encoding="utf-8",
        timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip()


def test_fork_support_is_off_before_grpc_loads_and_an_operators_value_is_obeyed():
    """Set before gRPC is first imported (it reads the setting once, at load),
    and `setdefault`: somebody who needs it on can still export it."""
    assert _setting_after_import(None) == "0 grpc-loaded=False"
    assert _setting_after_import("1") == "1 grpc-loaded=False"

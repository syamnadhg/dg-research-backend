@echo off
REM Manual debug helper. NOT wired into the Scheduled Task.
REM
REM The supervisor (installed via `python research.py --resurrect`)
REM invokes pythonw directly with --env-file; see `_arm_supervisor_quiet_windows`
REM in research.py for the Scheduled Task action that gets installed.
REM
REM Env vars (Vision tier, CUA config, Anthropic key) live in
REM <script_dir>\.dg-supervisor.env. To change them, edit that file —
REM do NOT add `set "VAR=value"` lines here.
REM
REM Use this CMD only to run the supervisor manually from a console —
REM e.g. for debugging an env-file change without waiting for the
REM Scheduled Task's PT5M trigger to re-fire.
cd /d "%~dp0.."
python research.py --daemon-loop --env-file ".dg-supervisor.env"

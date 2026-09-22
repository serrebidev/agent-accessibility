# -*- coding: UTF-8 -*-
# globalPlugins/addtl/freebuffBackend.py
#
# Freebuff Desktop backend for agentDesktopAccessibility.
#
# Freebuff stores one SQLite database per project under
# ~/.config/freebuff-desktop/projects/<name>-<projectId>/desktop-v2.db and
# names the active thread in ~/.config/freebuff-desktop/state.json
# (workspace.activeId). NVDA's embedded Python has no sqlite3, so the reads
# go through freebuffStore.py under the system Python — the same arrangement
# the OpenCode backend uses.
#
# Freebuff registers no URL scheme at all, so thread switching is a
# best-effort activation of the matching object in the renderer's
# accessibility tree (see TranscriptBackend._activateByTitle).

import glob
import json
import os
import subprocess

from logHandler import log

from .transcriptBackend import TranscriptBackend

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "freebuff-desktop")
_HELPER_TIMEOUT_S = 15


class FreebuffBackend(TranscriptBackend):

	appLabel = "Freebuff"
	threadNoun = "thread"
	logPrefix = "freebuffAccessibility"

	def __init__(self, plugin=None):
		super().__init__(plugin)
		self._pythonExe = None
		log.info("Freebuff backend loaded")

	# ------------------------------------------------------------------
	# System Python discovery (cached)
	# ------------------------------------------------------------------

	def _getPythonExe(self):
		if self._pythonExe:
			return self._pythonExe
		candidates = ["python", "python3", "py"]
		for pattern in (
			os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python", "Python3*", "python.exe"),
			os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Python", "Python3*", "python.exe"),
		):
			candidates.extend(sorted(glob.glob(pattern), reverse=True))
		for exe in candidates:
			if not exe:
				continue
			test_cmd = [exe, "-c", "import sqlite3"]
			if exe == "py":
				test_cmd = ["py", "-3", "-c", "import sqlite3"]
			try:
				proc = subprocess.run(
					test_cmd,
					capture_output=True,
					timeout=10,
					creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
				)
			except Exception:
				continue
			if proc.returncode == 0:
				self._pythonExe = exe
				self._dbg("python: using", exe)
				return exe
		self._dbg("python: none found")
		return None

	# ------------------------------------------------------------------
	# freebuffStore.py
	# ------------------------------------------------------------------

	def _runHelper(self, list_mode=False):
		helper = os.path.join(os.path.dirname(__file__), "freebuffStore.py")
		if not os.path.isfile(helper):
			self._dbg("helper missing:", helper)
			return {}
		python_exe = self._getPythonExe()
		if not python_exe:
			return {}
		cmd = [python_exe, helper, _CONFIG_DIR]
		if list_mode:
			cmd.append("--list")
		try:
			proc = subprocess.run(
				cmd,
				capture_output=True,
				encoding="utf-8",
				timeout=_HELPER_TIMEOUT_S,
				creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
			)
		except Exception as e:
			self._dbg("helper error:", e)
			return {}
		if proc.returncode != 0:
			self._dbg("helper exit", proc.returncode, (proc.stderr or "")[:300])
			return {}
		try:
			return json.loads((proc.stdout or "").strip() or "{}")
		except ValueError as e:
			self._dbg("helper json error:", e)
			return {}

	# ------------------------------------------------------------------
	# TranscriptBackend hooks
	# ------------------------------------------------------------------

	def loadMessages(self):
		if not os.path.isdir(_CONFIG_DIR):
			self._dbg("config dir missing:", _CONFIG_DIR)
			return [], ""
		data = self._runHelper()
		messages = data.get("messages") or []
		thread_id = data.get("thread_id") or ""
		self._dbg("loadMessages: thread=%s messages=%d" % (thread_id, len(messages)))
		return messages, thread_id

	def loadThreads(self):
		data = self._runHelper(list_mode=True)
		threads = []
		for thread in data.get("threads") or []:
			project_path = (thread.get("projectPath") or "").rstrip("/\\")
			threads.append({
				"id": thread.get("id") or "",
				"title": (thread.get("title") or "").strip(),
				# basename() is empty for a drive root like "C:", so fall back
				# to the path itself rather than labelling the thread "()".
				"detail": (os.path.basename(project_path) or project_path) if project_path else "",
				"sort": thread.get("updatedAt") or 0,
			})
		threads.sort(key=lambda thread: thread["sort"], reverse=True)
		return threads

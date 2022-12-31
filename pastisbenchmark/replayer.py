# built-in imports
from enum import Enum, auto
from pathlib import Path
from typing import Generator, Optional
import os
import subprocess
import logging
import re
from datetime import datetime

# third-party
from pastisbroker.workspace import Workspace, WorkspaceStatus
from libpastis.types import SeedInjectLoc, SeedType
from tritondse.trace import QBDITrace, TraceException
from tritondse import CoverageStrategy


class ReplayType(Enum):
    qbdi = auto()
    llvm_profile = auto()


class Replayer(object):

    QBDI_REPLAY_DIR = "replays_qbdi"
    LLVMPROFILE_REPLAY_DIR = "replays_llvmprof"
    REPLAY_FAILS_LOG = "replay_fails.log"

    def __init__(self, program: Path, workspace: Path, type: ReplayType, injloc: SeedInjectLoc,
                 stream: bool = False, full: bool = False, timeout: int = 15, *args):
        self.workspace = Workspace(workspace)
        self.type = type
        self.stream = stream
        self._full = full
        self.program = Path(program)
        self._inject_loc = injloc
        self._timeout = timeout
        self._args = list(args)
        self._fails = []

        # initiatialize directories
        self._init_directories()

        # set longjmp ENV var if applicable
        self._set_longjump_plt()

    def _init_directories(self):
        if not self.corpus_replay_dir.exists():
            self.corpus_replay_dir.mkdir()

    def _set_longjump_plt(self):
        try:
            proc = subprocess.Popen(['objdump', '-D', self.program.absolute()], stdout=subprocess.PIPE)
            out, err = proc.communicate()
            for line in out.split(b"\n"):
                if b"<longjmp@plt>:" in line:
                    addr = line.split()[0]
                    logging.info(f"lonjmp address found at: {addr}")
                    os.environ["TT_LONGJMP_ADDR"] = str(int(addr, 16))
        except:
            return 0

    @property
    def corpus_replay_dir(self) -> Path:
        if self.type == ReplayType.qbdi:
            return self.workspace.root / self.QBDI_REPLAY_DIR
        else:
            return self.workspace.root / self.LLVMPROFILE_REPLAY_DIR

    def iter(self) -> Generator[Path, None, None]:
        yield from self.workspace.iter_initial_corpus_directory()
        yield from self.workspace.iter_corpus_directory(SeedType.INPUT)

    def replay(self, input: Path) -> bool:
        if self.type == ReplayType.qbdi:
            return self._replay_qbdi(input)
        else:
            return self._replay_llvm_profile(input)

    def _replay_qbdi(self, input: Path) -> bool:
        out_file = self.corpus_replay_dir / (input.name + ".trace")

        if out_file.exists():
            # The trace has already been generated
            return True

        args = self._args[:]

        # If inject on argv try replacing the right argv
        if self._inject_loc == SeedInjectLoc.ARGV:
            if "@@" in args:
                idx = args.index("@@")
                args[idx] = str(input.absolute())

        try:
            return QBDITrace.run(CoverageStrategy.EDGE,
                                 str(self.program.absolute()),
                                 args=args,
                                 output_path=str(out_file.absolute()),
                                 stdin_file=input if self._inject_loc == SeedInjectLoc.STDIN else None,
                                 dump_trace=self._full,
                                 cwd=self.program.parent,
                                 timeout=self._timeout)
        except TraceException as e:
            self._fails.append(input)
            return False

    def _replay_llvm_profile(self, input: Path) -> bool:
        pass


    def start(self):
        # TODO: Start monitoring folders (and status file)
        pass

    def save_fails(self):
        with open(self.workspace.root / self.REPLAY_FAILS_LOG, "w") as f:
            f.write("\n".join(self._fails))

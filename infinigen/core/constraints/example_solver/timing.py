# Copyright (C) 2024, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the LICENSE file in the root directory
# of this source tree.

import csv
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TIMING_ENV_VAR = "INFINIGEN_PROFILE_TIMING"
TIMING_CSV_NAME = "indoor_solver_timing.csv"


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


PROFILE_TIMING_ENABLED = _env_truthy(TIMING_ENV_VAR)

FIELDNAMES = [
    "iteration",
    "attempt_index",
    "attempt_count",
    "move_gen_func",
    "move_type",
    "generator_class",
    "move_names",
    "retry",
    "proposal_succeeded",
    "proposal_accepted",
    "apply_duration",
    "evaluate_duration",
    "revert_duration",
    "accept_duration",
    "garbage_collect_duration",
    "total_step_duration",
    "attempt_duration",
    "initial_evaluate_duration",
    "elapsed_since_optim_start",
    "addition_sample_placeholder_duration",
    "addition_generator_init_duration",
    "addition_spawn_placeholder_duration",
    "addition_placeholder_finalize_duration",
    "addition_parse_scene_duration",
    "addition_state_update_duration",
    "addition_constraint_duration",
]

_CURRENT_PROPOSAL_ROW = ContextVar("indoor_solver_timing_row", default=None)
_CURRENT_OUTPUT_FOLDER = None


def current_output_folder() -> Optional[Path]:
    return _CURRENT_OUTPUT_FOLDER


def callable_name(func) -> str:
    return getattr(func, "__name__", func.__class__.__name__)


def move_type_name(move) -> Optional[str]:
    return move.__class__.__name__ if move is not None else None


def generator_class_name(move) -> Optional[str]:
    if move is None or not hasattr(move, "gen_class"):
        return None
    gen_class = move.gen_class
    return getattr(gen_class, "__name__", str(gen_class))


def move_names(move) -> Optional[str]:
    names = getattr(move, "names", None)
    if names is None:
        return None
    return ";".join(str(name) for name in names)


@contextmanager
def proposal_context(row):
    if row is None:
        yield
        return

    token = _CURRENT_PROPOSAL_ROW.set(row)
    try:
        yield
    finally:
        _CURRENT_PROPOSAL_ROW.reset(token)


def add_current_duration(field: str, duration: float) -> None:
    row = _CURRENT_PROPOSAL_ROW.get()
    if row is None:
        return
    row[field] = row.get(field, 0.0) + duration


class SolverTimingLogger:
    def __init__(self, output_folder):
        global _CURRENT_OUTPUT_FOLDER

        self.enabled = PROFILE_TIMING_ENABLED
        self.path = None
        self._file = None
        self._writer = None

        _CURRENT_OUTPUT_FOLDER = Path(output_folder) if output_folder is not None else None

        if not self.enabled:
            return

        if output_folder is None:
            logger.warning(
                "%s is set but solver output_folder is None; disabling solver timing",
                TIMING_ENV_VAR,
            )
            self.enabled = False
            return

        self.path = Path(output_folder) / TIMING_CSV_NAME
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("w", newline="")
            self._writer = csv.DictWriter(self._file, fieldnames=FIELDNAMES)
            self._writer.writeheader()
            self._file.flush()
            logger.info("Writing indoor solver timing CSV to %s", self.path)
        except OSError:
            logger.exception("Failed to open indoor solver timing CSV at %s", self.path)
            self.enabled = False
            self.close()

    def make_attempt_row(self, iteration, attempt_index, move_gen_func, move, retry):
        return {
            "iteration": iteration,
            "attempt_index": attempt_index,
            "move_gen_func": move_gen_func,
            "move_type": move_type_name(move),
            "generator_class": generator_class_name(move),
            "move_names": move_names(move),
            "retry": retry,
            "proposal_succeeded": False,
            "proposal_accepted": False,
            "apply_duration": 0.0,
            "evaluate_duration": 0.0,
            "revert_duration": 0.0,
            "accept_duration": 0.0,
            "garbage_collect_duration": 0.0,
            "total_step_duration": 0.0,
            "attempt_duration": 0.0,
            "initial_evaluate_duration": 0.0,
            "elapsed_since_optim_start": 0.0,
        }

    def write_rows(self, rows, step_fields):
        if not self.enabled:
            return

        attempt_count = len(rows)
        for row in rows:
            row.setdefault("attempt_count", attempt_count)
            for key, value in step_fields.items():
                row[key] = value
            self._writer.writerow({field: row.get(field, "") for field in FIELDNAMES})

        self._file.flush()

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None
            self._writer = None

    def __del__(self):
        self.close()

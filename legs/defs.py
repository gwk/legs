# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

from typing import Dict, List, NamedTuple, Tuple


class Mode(NamedTuple):
  name: str
  start: int
  invalid: int
  invalid_name: str
  incomplete_name: str


ModeTransitions = Dict[Tuple[str, str], Tuple[str, str]]
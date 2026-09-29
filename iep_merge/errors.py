"""Conflict types raised by the three-way merge."""


class MergeConflict(Exception):
    """Raised when two revisions cannot be merged automatically."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

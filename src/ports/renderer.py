import io
from abc import ABC, abstractmethod
from typing import Any


class ITreeRenderer(ABC):
    @abstractmethod
    def render_tree(
        self,
        nodes: list[dict[str, Any]],
        edges: list[tuple[str, str]],
        title: str = "Project Tech Tree",
        mode: str = "lr",
    ) -> io.BytesIO:
        """Renders tech tree dependency graph into an image byte buffer."""

"""
パイプラインの 1 ステップと、その列（Plan）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class Step:
    """
    kind = "cmd": Siril コマンド。args を空白で連結して送る
    kind = "py" : Python 側の処理（ステージング、クリーンアップなど）。func(ctx) を呼ぶ
    """

    kind: str
    description: str
    args: list[str] = field(default_factory=list)
    func: Optional[Callable[[Any], None]] = None
    weight: float = 1.0
    phase: str = ""  # 進捗表示用の大分類（マスター作成 / g01 / 仕上げ …）

    @property
    def command_text(self) -> str:
        return " ".join(self.args) if self.kind == "cmd" else f"# [python] {self.description}"

    @staticmethod
    def cmd(description: str, *args: str, weight: float = 1.0, phase: str = "") -> "Step":
        return Step(kind="cmd", description=description, args=[a for a in args if a], weight=weight, phase=phase)

    @staticmethod
    def py(description: str, func: Callable[[Any], None], weight: float = 0.5, phase: str = "") -> "Step":
        return Step(kind="py", description=description, func=func, weight=weight, phase=phase)


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    outputs: list[Path] = field(default_factory=list)  # 期待される結果ファイル（拡張子なしの basename）
    summary: list[str] = field(default_factory=list)  # 人間向けの要約（Analyze / ログ用）

    @property
    def total_weight(self) -> float:
        return sum(s.weight for s in self.steps) or 1.0

    def to_ssf(self, header: str = "") -> str:
        """Siril スクリプト形式のテキスト。python ステップはコメントになる"""
        lines = ["# Kasane が生成したコマンド列", "# " + header.replace("\n", "\n# ") if header else "", ""]
        phase = None
        for s in self.steps:
            if s.phase != phase:
                phase = s.phase
                lines.append(f"\n# ===== {phase} =====")
            lines.append(s.command_text)
        return "\n".join(l for l in lines if l is not None) + "\n"

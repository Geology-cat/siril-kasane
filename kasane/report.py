"""
品質レポート

Siril の .seq ファイルから登録データ（FWHM / wFWHM / 真円度 / 背景 / 星数）と採否を読み取り、
CSV とログ用の要約を作る。

.seq の形式（Siril 1.4）:
  S 'name' start_index nb_images nb_selected fixed_len reference_image version variable_size fz drizzle
  L nb_layers
  I index included
  R<layer> fwhm wfwhm roundness quality background nb_stars H h00 h01 ... h22   ← フレーム順
  M<layer>-<frame> stats...
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .model import FrameInfo


@dataclass
class RegRow:
    fwhm: float
    wfwhm: float
    roundness: float
    quality: float
    background: float
    nb_stars: int


@dataclass
class SeqData:
    name: str = ""
    start_index: int = 1
    nb_images: int = 0
    reference: int = -1  # 0 始まり
    included: list[int] = field(default_factory=list)  # 1 始まりの index
    reg: dict[int, RegRow] = field(default_factory=dict)  # index(1 始まり) → RegRow（最初に見つかった layer）


def parse_seq(path: Path) -> SeqData:
    d = SeqData()
    reg_layer: Optional[str] = None
    pos = 0
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        tag = parts[0]
        if tag == "S":
            # S 'name' start nb nb_sel fixed ref ...
            try:
                d.name = parts[1].strip("'")
                d.start_index = int(parts[2])
                d.nb_images = int(parts[3])
                d.reference = int(parts[6])
            except (IndexError, ValueError):
                pass
        elif tag == "I":
            try:
                if int(parts[2]) == 1:
                    d.included.append(int(parts[1]))
            except (IndexError, ValueError):
                pass
        elif tag.startswith("R") and len(parts) >= 7:
            if reg_layer is None:
                reg_layer = tag
            if tag != reg_layer:
                continue
            pos += 1
            try:
                d.reg[d.start_index + pos - 1] = RegRow(
                    fwhm=float(parts[1]),
                    wfwhm=float(parts[2]),
                    roundness=float(parts[3]),
                    quality=float(parts[4]),
                    background=float(parts[5]),
                    nb_stars=int(float(parts[6])),
                )
            except ValueError:
                continue
    return d


@dataclass
class ReportRow:
    index: int
    name: str
    path: str
    included: bool
    reference: bool
    reg: Optional[RegRow]


@dataclass
class QualityReport:
    title: str
    rows: list[ReportRow]
    csv_path: Optional[Path] = None

    @property
    def n_total(self) -> int:
        return len(self.rows)

    @property
    def n_included(self) -> int:
        return sum(1 for r in self.rows if r.included)

    def excluded(self) -> list[ReportRow]:
        return [r for r in self.rows if not r.included]

    def summary_lines(self) -> list[str]:
        lines = [f"{self.title}: 採用 {self.n_included} / {self.n_total} 枚"]
        ref = next((r for r in self.rows if r.reference), None)
        if ref is not None:
            lines.append(f"  参照フレーム: {ref.name}" + (f"（wFWHM {ref.reg.wfwhm:.2f}）" if ref.reg else ""))
        wf = [r.reg.wfwhm for r in self.rows if r.reg and r.included]
        if wf:
            lines.append(f"  採用フレームの wFWHM: 最良 {min(wf):.2f} / 中央 {sorted(wf)[len(wf) // 2]:.2f} / 最悪 {max(wf):.2f} px")
        for r in self.excluded():
            detail = ""
            if r.reg:
                detail = f"  wFWHM {r.reg.wfwhm:.2f}  真円度 {r.reg.roundness:.3f}  星数 {r.reg.nb_stars}"
            lines.append(f"  除外: {r.name}{detail}")
        return lines


CSV_HEADER = ["index", "file", "included", "reference", "fwhm", "wfwhm", "roundness", "quality", "background", "nb_stars", "path"]


def build_report(
    title: str,
    reg_seq: Path,
    out_seq: Optional[Path],
    frames: list[FrameInfo],
    csv_path: Optional[Path] = None,
) -> QualityReport:
    """
    reg_seq : 登録データを持つ .seq（register -2pass の入力側、例 pp_light_.seq）
    out_seq : seqapplyreg / register の出力 .seq（採否の判定用、例 r_pp_light_.seq）。None なら reg_seq の I 行を使う
    frames  : シーケンスの index 順に並んだ元フレーム
    """
    reg = parse_seq(reg_seq)
    if not reg.reg and out_seq and out_seq.exists():
        # 1-pass register は出力側にだけ登録データを書くことがある
        alt = parse_seq(out_seq)
        if alt.reg:
            reg.reg = alt.reg
            reg.reference = alt.reference
    included = set(parse_seq(out_seq).included) if out_seq and out_seq.exists() else set(reg.included)
    rows: list[ReportRow] = []
    n = max(reg.nb_images, len(frames))
    for i in range(1, n + 1):
        f = frames[i - 1] if i - 1 < len(frames) else None
        rows.append(
            ReportRow(
                index=i,
                name=f.name if f else f"#{i}",
                path=str(f.path) if f else "",
                included=i in included,
                reference=(i - 1) == reg.reference,
                reg=reg.reg.get(i),
            )
        )
    rep = QualityReport(title=title, rows=rows)
    if csv_path is not None:
        write_csv(rep, csv_path)
        rep.csv_path = csv_path
    return rep


def write_csv(rep: QualityReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_HEADER)
        for r in rep.rows:
            g = r.reg
            w.writerow([
                r.index, r.name, int(r.included), int(r.reference),
                f"{g.fwhm:.4f}" if g else "", f"{g.wfwhm:.4f}" if g else "", f"{g.roundness:.4f}" if g else "",
                f"{g.quality:.4f}" if g else "", f"{g.background:.6f}" if g else "", g.nb_stars if g else "",
                r.path,
            ])


def read_csv(path: Path) -> QualityReport:
    rows: list[ReportRow] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            reg = None
            if rec.get("wfwhm"):
                reg = RegRow(
                    fwhm=float(rec["fwhm"] or 0), wfwhm=float(rec["wfwhm"] or 0), roundness=float(rec["roundness"] or 0),
                    quality=float(rec["quality"] or 0), background=float(rec["background"] or 0),
                    nb_stars=int(float(rec["nb_stars"] or 0)),
                )
            rows.append(ReportRow(
                index=int(rec["index"]), name=rec["file"], path=rec.get("path", ""),
                included=rec["included"] == "1", reference=rec["reference"] == "1", reg=reg,
            ))
    return QualityReport(title=path.stem.replace("quality_", ""), rows=rows, csv_path=path)

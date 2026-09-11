"""
Light のグループ化と Dark / Flat / Bias / Dark Flat の自動マッチング

グループキー: (露出, ISO/Gain, Filter, Binning, 画像サイズ)
マッチング規則（WBPP 準拠）:
  Dark      : サイズ・Binning 一致は必須。露出一致 > Gain 一致 > 温度最近傍。露出が一致しなければ最近傍 + 警告
  Flat      : サイズ・Binning 一致は必須。Filter 一致（Light に Filter があるとき）> Gain 一致
  Bias      : サイズ・Binning 一致は必須。Gain 一致
  Dark Flat : サイズ・Binning 一致は必須。露出は Flat の露出に一致 > Gain 一致
DSLR（RAW）はサイズ・温度・Filter が取れないので、露出と ISO のみで判定する。

セッション（複数夜）:
  Light はセッション × キーでキャリブレーション単位（LightGroup）に分け、同じキーのグループは
  planner が merge して 1 本にスタックする。Flat はセッション一致を強く優先し、Dark は弱く優先する。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional

from .model import FrameInfo, FrameKind, GroupKey, LightGroup, MasterSource, Project, session_label

EXPOSURE_TOLERANCE = 0.05  # 秒。露出一致とみなす許容差

SESSION_MODES: dict[str, str] = {
    "auto": "自動",
    "folder": "フォルダごと",
    "date": "撮影日ごと",
    "none": "分けない",
}
SESSION_MODES_HELP = (
    "セッション（撮影夜）の分け方。\n"
    "自動: Light のフォルダが複数ならフォルダ、撮影日が複数なら撮影日（正午区切り）で分ける\n"
    "セッションごとにその夜の Flat / Dark でキャリブレーションし、同じ条件の Light は結合して 1 本にスタックします"
)

# フォルダでセッションを決めるとき、読み飛ばす「種別フォルダ」名（小文字）
_TYPE_DIR_NAMES = {
    "light", "lights", "dark", "darks", "flat", "flats", "bias", "biases", "offset", "offsets",
    "darkflat", "darkflats", "flatdark", "flatdarks", "raw", "raws", "fits", "fit", "cal", "calibration",
    "calib", "master", "masters", "sub", "subs", "subframes",
}


def session_key_folder(frame: FrameInfo) -> str:
    """種別フォルダ（lights など）を読み飛ばした親フォルダのパスをセッションキーにする"""
    d = Path(frame.path).parent
    while d.name.lower() in _TYPE_DIR_NAMES and d.parent != d:
        d = d.parent
    return str(d)


def session_key_date(frame: FrameInfo) -> Optional[str]:
    """撮影日時 - 12 時間の日付（夜をまたいでも同じ日になる）"""
    if frame.date_obs is None:
        return None
    return (frame.date_obs - timedelta(hours=12)).date().isoformat()


def effective_session_mode(project: Project) -> str:
    """auto のときに実際に使うモードを決める"""
    mode = project.session_mode
    if mode != "auto":
        return mode
    if not project.lights:
        return "none"
    folders = {session_key_folder(f) for f in project.lights}
    if len(folders) > 1:
        return "folder"
    dates = {session_key_date(f) for f in project.lights} - {None}
    if len(dates) > 1:
        return "date"
    return "none"


def assign_sessions(project: Project) -> str:
    """全フレームの session_key を設定し、実際に使ったモードを返す"""
    mode = effective_session_mode(project)
    for f in project.all_frames():
        if mode == "folder":
            f.session_key = session_key_folder(f)
        elif mode == "date":
            f.session_key = session_key_date(f)
        else:
            f.session_key = None
    return mode


def _round_exp(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value, 2)


def make_key(frame: FrameInfo) -> GroupKey:
    return GroupKey(
        exposure=_round_exp(frame.exposure),
        iso_or_gain=frame.iso_or_gain,
        filter=frame.filter,
        binning=frame.binning,
        size=frame.size,
    )


def group_lights(lights: list[FrameInfo]) -> list[LightGroup]:
    """Light を (キー, セッション) ごとにまとめる。順序はキー → セッションで安定させる"""
    buckets: dict[tuple[GroupKey, Optional[str]], list[FrameInfo]] = defaultdict(list)
    for f in lights:
        buckets[(make_key(f), f.session_key)].append(f)
    keys = sorted(
        buckets,
        key=lambda ks: (ks[0].filter or "", ks[0].exposure or 0, ks[0].iso_or_gain or 0, ks[0].binning or 0, ks[1] or ""),
    )
    groups: list[LightGroup] = []
    for i, (key, session) in enumerate(keys, start=1):
        frames = sorted(buckets[(key, session)], key=lambda f: str(f.path))
        groups.append(LightGroup(group_id=f"g{i:02d}", key=key, frames=frames, session=session))
    return groups


# ---- 候補の評価 --------------------------------------------------------------


@dataclass
class _Candidate:
    frames: list[FrameInfo]
    key: GroupKey
    score: float
    notes: list[str]


TEMP_BIN = 5.0  # ℃。Dark を温度で分けるときのビン幅


def _temp_bin(frame: FrameInfo) -> Optional[float]:
    if frame.temperature is None:
        return None
    return round(frame.temperature / TEMP_BIN) * TEMP_BIN


def _bucket(frames: list[FrameInfo], with_temp: bool = False) -> list[tuple[GroupKey, Optional[str], list[FrameInfo]]]:
    """(キー, セッション, フレーム列) のリスト。with_temp のときは温度ビンでも分ける（Dark 用）"""
    buckets: dict[tuple, list[FrameInfo]] = defaultdict(list)
    for f in frames:
        buckets[(make_key(f), f.session_key, _temp_bin(f) if with_temp else None)].append(f)
    return [(key, session, fs) for (key, session, _tb), fs in buckets.items()]


def _session_score(group: LightGroup, session: Optional[str], bonus: float, notes: list[str], warn: bool) -> float:
    """セッション一致のボーナス。両方に情報があって不一致なら（warn のとき）注記を付ける"""
    if group.session is None or session is None:
        return 0.0
    if group.session == session:
        return bonus
    if warn:
        notes.append(f"セッション不一致（{session_label(session)}）")
    return 0.0


def _same(a, b) -> bool:
    """どちらかが None（不明）なら「一致とみなす」。両方あるときだけ比較"""
    if a is None or b is None:
        return True
    return a == b


def _exp_match(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return True
    return abs(a - b) <= EXPOSURE_TOLERANCE


def _median_temp(frames: list[FrameInfo]) -> Optional[float]:
    temps = sorted(f.temperature for f in frames if f.temperature is not None)
    if not temps:
        return None
    return temps[len(temps) // 2]


def match_dark(group: LightGroup, pool: list[FrameInfo]) -> MasterSource:
    if not pool:
        return MasterSource(mode="none", note="Dark が投入されていません")
    light_temp = _median_temp(group.frames)
    best: Optional[_Candidate] = None
    for key, session, frames in _bucket(pool, with_temp=True):
        if not _same(key.size, group.key.size) or not _same(key.binning, group.key.binning):
            continue
        score = 0.0
        notes: list[str] = []
        score += _session_score(group, session, 5, notes, warn=False)
        if _exp_match(key.exposure, group.key.exposure):
            score += 100
        else:
            # 露出が違うときは近いものを優先しつつ警告
            diff = abs((key.exposure or 0) - (group.key.exposure or 0))
            score += max(0.0, 50 - diff)
            notes.append(f"露出不一致 {key.exposure:g}s ≠ {group.key.exposure:g}s")
        if _same(key.iso_or_gain, group.key.iso_or_gain):
            score += 30
        else:
            notes.append("Gain/ISO 不一致")
        dark_temp = _median_temp(frames)
        if light_temp is not None and dark_temp is not None:
            dt = abs(light_temp - dark_temp)
            score += max(0.0, 10 - dt)
            if dt > 3:
                notes.append(f"温度差 {dt:.1f}℃")
        cand = _Candidate(frames, key, score, notes)
        if best is None or cand.score > best.score:
            best = cand
    if best is None:
        return MasterSource(mode="none", note="サイズ / Binning が一致する Dark がありません")
    return MasterSource(mode="frames", frames=best.frames, auto=True, note="、".join(best.notes))


def match_flat(group: LightGroup, pool: list[FrameInfo]) -> MasterSource:
    if not pool:
        return MasterSource(mode="none", note="Flat が投入されていません")
    best: Optional[_Candidate] = None
    for key, session, frames in _bucket(pool):
        if not _same(key.size, group.key.size) or not _same(key.binning, group.key.binning):
            continue
        score = 0.0
        notes: list[str] = []
        score += _session_score(group, session, 40, notes, warn=True)
        if group.key.filter is not None:
            if key.filter is not None and key.filter.lower() == group.key.filter.lower():
                score += 100
            elif key.filter is None:
                score += 20
                notes.append("Flat に Filter 情報なし")
            else:
                notes.append(f"Filter 不一致 {key.filter} ≠ {group.key.filter}")
        else:
            score += 50
        if _same(key.iso_or_gain, group.key.iso_or_gain):
            score += 10
        cand = _Candidate(frames, key, score, notes)
        if best is None or cand.score > best.score:
            best = cand
    if best is None:
        return MasterSource(mode="none", note="サイズ / Binning が一致する Flat がありません")
    if group.key.filter is not None and best.score < 20:
        return MasterSource(mode="none", note=f"Filter {group.key.filter} に対応する Flat がありません")
    return MasterSource(mode="frames", frames=best.frames, auto=True, note="、".join(best.notes))


def match_bias(group: LightGroup, pool: list[FrameInfo]) -> MasterSource:
    if not pool:
        return MasterSource(mode="none", note="Bias が投入されていません")
    best: Optional[_Candidate] = None
    for key, session, frames in _bucket(pool):
        if not _same(key.size, group.key.size) or not _same(key.binning, group.key.binning):
            continue
        score = 0.0
        notes: list[str] = []
        score += _session_score(group, session, 5, notes, warn=False)
        if _same(key.iso_or_gain, group.key.iso_or_gain):
            score += 30
        else:
            notes.append("Gain/ISO 不一致")
        cand = _Candidate(frames, key, score, notes)
        if best is None or cand.score > best.score:
            best = cand
    if best is None:
        return MasterSource(mode="none", note="サイズ / Binning が一致する Bias がありません")
    return MasterSource(mode="frames", frames=best.frames, auto=True, note="、".join(best.notes))


def match_darkflat(group: LightGroup, flat: MasterSource, pool: list[FrameInfo]) -> MasterSource:
    if not pool:
        return MasterSource(mode="none", note="Dark Flat が投入されていません")
    flat_exp = None
    if flat.mode == "frames" and flat.frames:
        flat_exp = _round_exp(flat.frames[0].exposure)
    best: Optional[_Candidate] = None
    for key, session, frames in _bucket(pool):
        if not _same(key.size, group.key.size) or not _same(key.binning, group.key.binning):
            continue
        score = 0.0
        notes: list[str] = []
        score += _session_score(group, session, 10, notes, warn=False)
        if flat_exp is not None:
            if _exp_match(key.exposure, flat_exp):
                score += 100
            else:
                notes.append(f"Flat の露出 {flat_exp:g}s と不一致（{key.exposure:g}s）")
        if _same(key.iso_or_gain, group.key.iso_or_gain):
            score += 30
        cand = _Candidate(frames, key, score, notes)
        if best is None or cand.score > best.score:
            best = cand
    if best is None:
        return MasterSource(mode="none", note="サイズ / Binning が一致する Dark Flat がありません")
    return MasterSource(mode="frames", frames=best.frames, auto=True, note="、".join(best.notes))


# ---- プロジェクト全体 ----------------------------------------------------------


def _global_source(project: Project, kind: FrameKind) -> Optional[MasterSource]:
    """グローバル設定が frames / library 以外のとき、全グループ共通の MasterSource を返す"""
    mode = getattr(project, f"{kind.value}_mode")
    if mode == "master_file":
        path = getattr(project, f"{kind.value}_master_path")
        if path is None:
            return MasterSource(mode="none", note="マスターファイルが未指定です")
        return MasterSource(mode="master_file", master_path=path, auto=False)
    if mode == "constant":
        return MasterSource(mode="constant", constant=project.bias_constant, auto=False)
    if mode == "offset_keyword":
        return MasterSource(mode="offset_keyword", auto=False)
    if mode == "none":
        return MasterSource(mode="none", auto=False)
    return None  # frames / library


def _from_library(result: MasterSource) -> MasterSource:
    """ライブラリのフレーム（1 マスター = 1 フレーム）へのマッチ結果を master_file に変換する"""
    if result.mode != "frames" or not result.frames:
        return MasterSource(mode="none", note=result.note or "ライブラリに合うマスターがありません")
    f = result.frames[0]
    note = "ライブラリ: " + f.name + (f"（{result.note}）" if result.note else "")
    return MasterSource(mode="master_file", master_path=f.path, auto=True, note=note)


def _resolve(project: Project, g: LightGroup, kind: FrameKind, ov: dict, library_frames: dict, matcher) -> MasterSource:
    """上書き > グローバル固定 > 投入フレーム > ライブラリ（モードが library か、フレームが無くフォールバック有効のとき）"""
    src = ov.get(kind.value) or _global_source(project, kind)
    if src is not None:
        return src
    mode = getattr(project, f"{kind.value}_mode")
    pool = project.pool(kind)
    lib = library_frames.get(kind, [])
    if mode == "library":
        return _from_library(matcher(lib)) if lib else MasterSource(mode="none", note="ライブラリが空です")
    result = matcher(pool)
    if result.mode == "none" and not pool and lib and project.settings.library.auto_fallback:
        return _from_library(matcher(lib))
    return result


def build_groups(project: Project, library_dir: Optional[Path] = None) -> list[LightGroup]:
    """Light をグループ化し、各グループにマスターを割り当てる。project.groups を更新して返す"""
    assign_sessions(project)
    groups = group_lights(project.lights)
    library_frames: dict[FrameKind, list[FrameInfo]] = {}
    if library_dir is not None:
        from .library import MasterLibrary

        lib = MasterLibrary(library_dir)
        for kind in (FrameKind.DARK, FrameKind.FLAT, FrameKind.BIAS, FrameKind.DARKFLAT):
            library_frames[kind] = lib.frames(kind)
    for g in groups:
        ov = project.overrides.get(g.group_id, {})
        g.dark = _resolve(project, g, FrameKind.DARK, ov, library_frames, lambda pool: match_dark(g, pool))
        g.flat = _resolve(project, g, FrameKind.FLAT, ov, library_frames, lambda pool: match_flat(g, pool))
        g.bias = _resolve(project, g, FrameKind.BIAS, ov, library_frames, lambda pool: match_bias(g, pool))
        g.darkflat = _resolve(project, g, FrameKind.DARKFLAT, ov, library_frames,
                              lambda pool: match_darkflat(g, g.flat, pool))
    project.groups = groups
    return groups


def classify_by_image_type(frames: list[FrameInfo]) -> dict[FrameKind, list[FrameInfo]]:
    """FITS の IMAGETYP で種別を振り分ける。不明なものは light に入れず "unknown" 扱いで返さない"""
    out: dict[FrameKind, list[FrameInfo]] = {k: [] for k in FrameKind}
    for f in frames:
        if f.image_type in ("light", "dark", "flat", "bias", "darkflat"):
            kind = FrameKind(f.image_type)
            f.kind = kind
            out[kind].append(f)
    return out

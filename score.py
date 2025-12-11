from dataclasses import dataclass
from typing import List, Tuple, Optional


# ==========================================================
# Drum Score Player v0.7.2
# テキスト譜面ルール ＋ CHECK ブロック無視
# ==========================================================


@dataclass
class NoteEvent:
    start_step: int
    length_steps: int
    symbol: str       # 'x','o','X','O','rest' など
    dynamic: str = "mf"


@dataclass
class Track:
    name: str
    events: List[NoteEvent]


@dataclass
class Score:
    tempo: int
    time_signature: Tuple[int, int]
    pulses_per_beat: int
    tracks: List[Track]
    title: Optional[str] = None

    # ================================
    # 小節関連
    # ================================
    @property
    def beats_per_bar(self) -> int:
        return self.time_signature[0]

    @property
    def bar_steps(self) -> int:
        return self.beats_per_bar * self.pulses_per_beat

    @property
    def bars(self) -> int:
        """
        スコア全体の「小節数」。
        すべてのトラックの中で最も長いものに合わせて計算する。
        """
        bar_steps = self.bar_steps
        if bar_steps <= 0:
            return 1

        max_len = 0
        for track in self.tracks:
            if not track.events:
                continue
            last = track.events[-1].start_step + track.events[-1].length_steps
            max_len = max(max_len, last)

        if max_len <= 0:
            return 1

        # ceiling((max_len) / bar_steps)
        return max(1, (max_len + bar_steps - 1) // bar_steps)

    @property
    def total_steps(self) -> int:
        """
        画面上の全体長。bars * bar_steps で小節単位にそろえる。
        """
        return self.bars * self.bar_steps

    # ================================
    # テキスト → Score パース
    # ================================
    @classmethod
    def from_text(cls, text: str) -> "Score":
        """
        v0.7.2 テキストフォーマット:

          FILENAME=◯◯◯       ← Score では使わない（GUI側で利用）
          TITLE=◯◯◯          ← 任意
          TEMPO=80
          TIME=4/4
          PULSES_PER_BEAT=4

          HH: x1 x1 x1 x1 ...
          SD: -4 x4 -4 x4 ...
          BD: ...

        - トークン:
            音符: xN, oN, XN, ON
            休符: -N, rN, RN, _N
            N はステップ数（正の整数）

        - 強弱:
            トークン末尾に ^pp, ^p, ^mp, ^mf, ^f, ^ff
            例: x1^f, o2^pp, -4^p

        - "|" は小節区切りマーカーとして許可されるが、ステップには数えない。

        - ファイル末尾などに置く検算ブロック:

            %%CHECK:
              Track01_Total = 64
              Track02_Total = 64
              Track03_Total = 64
              Bars_Total    = 4
              Steps_Per_Bar = 16
            %%ENDCHECK

          は、パーサ側では完全に無視する。
        """
        print("[INFO] Score.from_text: parsing text score...")

        tempo: Optional[int] = None
        time_sig: Optional[Tuple[int, int]] = None
        pulses_per_beat: Optional[int] = None
        tracks: List[Track] = []
        title: Optional[str] = None

        lines = text.splitlines()
        current_track_name: Optional[str] = None
        current_track_tokens: List[str] = []

        # CHECK ブロック無視用フラグ
        in_check_block = False

        # ----------------------------
        # トラックを確定
        # ----------------------------
        def flush_current_track():
            nonlocal current_track_name, current_track_tokens, tracks

            if current_track_name is None:
                return

            if time_sig is None or pulses_per_beat is None:
                raise ValueError("TIME または PULSES_PER_BEAT が不足しています。")

            bar_steps = time_sig[0] * pulses_per_beat
            tokens = current_track_tokens
            events: List[NoteEvent] = []
            current_step = 0

            for token_raw in tokens:
                token = token_raw.strip()
                if not token:
                    continue

                # 小節区切りは完全無視
                if token == "|":
                    continue

                # 強弱
                dynamic = "mf"
                if "^" in token:
                    base, dyn = token.split("^", 1)
                    token = base.strip()
                    dyn = dyn.strip()
                    if dyn not in ("pp", "p", "mp", "mf", "f", "ff"):
                        raise ValueError(f"未知の強弱記号 '{dyn}' in '{token_raw}'")
                    dynamic = dyn

                if not token:
                    continue

                kind = token[0]
                length_str = token[1:]
                if not length_str.isdigit():
                    raise ValueError(f"トークン '{token_raw}' の長さが整数ではありません。")

                length = int(length_str)
                if length <= 0:
                    raise ValueError(f"トークン '{token_raw}' の長さが正の整数ではありません。")

                if kind in ("x", "X", "o", "O"):
                    symbol = kind
                elif kind in ("-", "r", "R", "_"):
                    symbol = "rest"
                else:
                    raise ValueError(f"未知のトークン種 '{kind}' in '{token_raw}'")

                events.append(
                    NoteEvent(
                        start_step=current_step,
                        length_steps=length,
                        symbol=symbol,
                        dynamic=dynamic,
                    )
                )

                current_step += length

            # 小節チェック
            if bar_steps <= 0:
                raise ValueError("1小節あたりのステップ数(bar_steps) が 0 以下です。")

            if current_step % bar_steps != 0:
                full_bars = current_step // bar_steps
                remainder = current_step % bar_steps
                raise ValueError(
                    f"トラック {current_track_name}: 合計 {current_step} ステップは "
                    f"1小節 {bar_steps} の整数倍ではありません。"
                    f" → {full_bars}小節分 + 余り {remainder}"
                )

            if current_step == 0:
                print(f"[WARN] トラック {current_track_name}: イベントがありません（空トラック）。")
            else:
                bars = current_step // bar_steps
                if bars > 1:
                    print(
                        f"[INFO] トラック {current_track_name}: "
                        f"{current_step} ステップ = {bars} 小節分として解釈します。"
                    )

            # 開始ステップでソートして追加
            events.sort(key=lambda e: e.start_step)
            tracks.append(Track(current_track_name, events))

            current_track_name = None
            current_track_tokens = []

        # ================================
        # 行解析
        # ================================
        for raw in lines:
            # 行末コメント除去
            raw_no_comment = raw.split("#", 1)[0]
            line = raw_no_comment.strip()
            if not line:
                continue

            # CHECK ブロック開始
            if line.startswith("%%CHECK:"):
                in_check_block = True
                continue

            # CHECK ブロック終了
            if line.startswith("%%ENDCHECK"):
                in_check_block = False
                continue

            # CHECK ブロック内は完全無視
            if in_check_block:
                continue

            # ヘッダー
            if line.startswith("FILENAME="):
                # Score 側では使わない
                continue
            if line.startswith("TITLE="):
                title = line.split("=", 1)[1].strip()
                continue
            if line.startswith("TEMPO="):
                tempo = int(line.split("=", 1)[1])
                continue
            if line.startswith("TIME="):
                ts = line.split("=", 1)[1]
                a, b = ts.split("/")
                time_sig = (int(a), int(b))
                continue
            if line.startswith("PULSES_PER_BEAT="):
                pulses_per_beat = int(line.split("=", 1)[1])
                continue

            # トラック行
            if ":" in line:
                # 既存トラックを確定
                flush_current_track()
                name, data = line.split(":", 1)
                current_track_name = name.strip()
                current_track_tokens = data.strip().split()
                continue

            # トラック継続行
            if current_track_name is not None:
                current_track_tokens.extend(line.split())
                continue

            # それ以外の行は無視
            continue

        # 最後のトラックをフラッシュ
        flush_current_track()

        if tempo is None or time_sig is None or pulses_per_beat is None:
            raise ValueError("TEMPO, TIME, PULSES_PER_BEAT のいずれかが不足しています。")

        print(
            f"[INFO] Score.from_text: parsed tempo={tempo}, "
            f"time={time_sig}, pulses={pulses_per_beat}, tracks={len(tracks)}"
        )

        return cls(
            tempo=tempo,
            time_signature=time_sig,
            pulses_per_beat=pulses_per_beat,
            tracks=tracks,
            title=title,
        )

    # ------------------------
    # デフォルト譜面生成（簡易テスト用）
    # ------------------------
    @classmethod
    def create_default_score(cls) -> "Score":
        """
        アプリ初回起動時などに使うデフォルト譜面。
        4小節 = 64ステップになるように組んだ
        「ちょっとだけプロっぽい」デモパターン。
        """
        text = """FILENAME=DefaultGroove_Showcase.txt
TITLE=Default Groove Showcase
TEMPO=96
TIME=4/4
PULSES_PER_BEAT=4

# Bar1: 基本の16分HH＋キック＆バックビート
# Bar2: HHの強弱バリエーション
# Bar3: SDのロール気味フィル
# Bar4: BDのフィルで締め

HH: x1 x1 x1 x1  x1 x1 x1 x1  x1 x1 x1 x1  x1 x1 x1 x1
    x1^f x1^p x1^p x1^p  x1^f x1^p x1^p x1^p  x1^f x1^p x1^p x1^p  x1^f x1^p x1^p x1^p
    x2 x2 x2 x2  x2 x2 x2 x2
    x4 x4 x4 x4

SD: -4 x1 -3  -4 x1 -3
    -1 x1^pp -2  -1 x1^mf -2  -1 x1^pp -2  -1 x1^f -2
    x1^p x1^p x1^p x1^p  x2^mf x2^mf  x1^f x1^f x1^f x1^f  x2^ff x2^ff
    -12 x1^f x1^f x1^ff x1^ff

BD: x1 -3 x1 -3 x1 -3 x1 -3
    x4 -4 x4 -4
    -2 x1 -1 x1 -4 x1 -2 x1 -2 x1
    x2 x2 x2 x2 -8

%%CHECK:
  Track01_Total = 64
  Track02_Total = 64
  Track03_Total = 64
  Bars_Total    = 4
  Steps_Per_Bar = 16
%%ENDCHECK
"""
        return cls.from_text(text)

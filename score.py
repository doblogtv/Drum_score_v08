from dataclasses import dataclass
from typing import List, Tuple, Optional


# ==========================================================
# Drum Score v0.7 テキスト譜面ルール（再掲）
# ----------------------------------------------------------
# ・1行目以降にメタ情報（順不同）
#     FILENAME=◯◯◯   ← 任意（アプリ側で保存名などに使用）
#     TITLE=◯◯◯      ← 任意（GUIに表示）
#     TEMPO=80
#     TIME=4/4
#     PULSES_PER_BEAT=4
#
# ・トラック行
#     HH: x1 x1 x1 x1 ...
#     SD: -4 x1 -3 ...
#     BD: ...
#
# ・記号
#   - 音符: xN, oN, XN, ON
#   - 休符: -N, rN, RN, _N
#   - N は「ステップ数」（正の整数）
#
# ・強弱
#   - 末尾に ^pp, ^p, ^mp, ^mf, ^f, ^ff を付ける
#     例: x1^f, o2^pp, -4^p
#   - 強弱を省略した場合は "mf"
#
# ・コメント
#   - 行頭が "#" の行は丸ごとコメントとして無視
#   - 行の途中に "#" があれば、それ以降はコメントとして無視
#     例: HH: x1 x1  x1 x1  # ここから先はコメント扱い
#
# ・小節区切り
#   - "|" は「見やすさのための小節区切りマーカー」
#   - パーサは "|" トークンを完全に無視（ステップ長には影響しない）
#
# ・整合性チェック
#   - 1小節のステップ数 = TIME.num * PULSES_PER_BEAT
#     例: TIME=4/4, PULSES_PER_BEAT=4 → bar_steps = 16
#   - 各トラックごとに
#       合計ステップ数 % bar_steps == 0
#     でなければエラーにする
#     （"◯小節分 + 余り△ステップ" というメッセージ付き）
#
# ・Score 側の bar 情報
#   - bar_steps: 1小節あたりのステップ数
#   - bars: すべてのトラックの中で最も長いものの「小節数」
#   - total_steps: bars * bar_steps
# ==========================================================


@dataclass
class NoteEvent:
    """
    1つの音符イベント（開始ステップと長さ）

    symbol:
      'x','o','X','O' → 音符
      'rest'          → 休符
    dynamic:
      'pp','p','mp','mf','f','ff' など（デフォルト: 'mf'）
    """
    start_step: int
    length_steps: int
    symbol: str
    dynamic: str = "mf"  # 強弱


@dataclass
class Track:
    name: str              # 例: "HH", "SD", "BD"
    events: List[NoteEvent]


@dataclass
class Score:
    tempo: int
    time_signature: Tuple[int, int]
    pulses_per_beat: int
    tracks: List[Track]
    title: Optional[str] = None  # 譜面タイトル

    # ------------------------
    # 基本プロパティ
    # ------------------------
    @property
    def beats_per_bar(self) -> int:
        return self.time_signature[0]

    @property
    def bar_steps(self) -> int:
        """
        1小節あたりのステップ数（例: 4/4, PULSES_PER_BEAT=4 → 16）
        """
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
            if last > max_len:
                max_len = last

        if max_len <= 0:
            return 1

        # 小数切り上げで「何小節ぶんあるか」を求める
        return max(1, (max_len + bar_steps - 1) // bar_steps)

    @property
    def total_steps(self) -> int:
        """
        画面上での「全体の長さ」。
        bars * bar_steps として、小節単位でそろえる。
        """
        return self.bars * self.bar_steps

    # ---------- v3 フォーマット パーサ（小節整数倍チェック＋"|"無視） ----------
    @classmethod
    def from_text(cls, text: str) -> "Score":
        """
        フォーマット（v3）:
          FILENAME=◯◯◯   ← 任意（Score では使わない）
          TITLE=◯◯◯      ← 任意・あればGUIに表示
          TEMPO=80
          TIME=4/4
          PULSES_PER_BEAT=4

          HH: x1 x1 x1 x1 ...
          SD: -4 x4 -4 x4
          BD:
           x1 -1 -1 -1
           x1 -1 -1 -1

        ・トークンは「記号+数値(+^強弱)」
          - xN, oN, ON, XN : Nステップぶん伸びる音符
          - -N, rN, RN, _N : Nステップぶんの休符
          - 強弱は ^p, ^f, ^mf などを末尾に付ける
            例: x1^p, o2^ff, -4^p

        ・"|" は小節区切りの目印として許可するが、
          パーサ上は「完全に無視」し、ステップ長に影響させない。

        ・各トラックごとに
            合計ステップ数 % bar_steps == 0
          でなければエラーにする。
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

        # --------------------------------------------------
        # トラック1本ぶんを確定させて Track にする関数
        # --------------------------------------------------
        def flush_current_track():
            nonlocal current_track_name, current_track_tokens, tracks, time_sig, pulses_per_beat

            if current_track_name is None:
                return

            if time_sig is None or pulses_per_beat is None:
                raise ValueError("ヘッダー情報 (TIME, PULSES_PER_BEAT) が不足しています。")

            tokens = current_track_tokens
            events: List[NoteEvent] = []
            current_step = 0

            for token_raw in tokens:
                token = token_raw.strip()
                if not token:
                    continue

                # "|" は完全無視
                if token == "|":
                    continue

                dynamic = "mf"
                if "^" in token:
                    base, dyn = token.split("^", 1)
                    token = base.strip()
                    dyn = dyn.strip()
                    if dyn in ("pp", "p", "mp", "mf", "f", "ff"):
                        dynamic = dyn
                    else:
                        raise ValueError(f"未知の強弱記号 '{dyn}' in '{token_raw}'")

                if not token:
                    continue

                kind = token[0]
                length_str = token[1:]
                if not length_str.isdigit():
                    raise ValueError(f"トークン '{token_raw}' の長さが数値ではありません。")
                length = int(length_str)
                if length <= 0:
                    raise ValueError(f"トークン '{token_raw}' の長さは正の整数である必要があります。")

                if kind in ("x", "X", "o", "O"):
                    events.append(
                        NoteEvent(
                            start_step=current_step,
                            length_steps=length,
                            symbol=kind,
                            dynamic=dynamic,
                        )
                    )
                elif kind in ("-", "r", "R", "_"):
                    events.append(
                        NoteEvent(
                            start_step=current_step,
                            length_steps=length,
                            symbol="rest",
                            dynamic=dynamic,
                        )
                    )
                else:
                    raise ValueError(f"未知のトークン種別 '{kind}' in '{token_raw}'")

                current_step += length

            bar_steps = time_sig[0] * pulses_per_beat

            if current_step % bar_steps != 0:
                full_bars = current_step // bar_steps
                remainder = current_step % bar_steps
                raise ValueError(
                    f"トラック {current_track_name}: 合計 {current_step} ステップは "
                    f"1小節 {bar_steps} の整数倍ではありません。"
                    f" → {full_bars}小節分 + 余り {remainder} ステップになっています。"
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

            # ★ ここでソートしてから 1 回だけ append する
            events.sort(key=lambda e: e.start_step)
            tracks.append(Track(name=current_track_name, events=events))

            current_track_name = None
            current_track_tokens = []



        # ---- 行走査 ----
        for raw_line in lines:
            # 行末コメントを除去
            # 例: "HH: x1 x1 x1  # comment" → "HH: x1 x1 x1"
            line_no_comment = raw_line.split("#", 1)[0]
            line = line_no_comment.strip()
            if not line:
                continue

            # ヘッダー類
            if line.startswith("FILENAME="):
                # Score では使わない（GUI側でファイル名に利用）
                continue
            if line.startswith("TITLE="):
                title = line.split("=", 1)[1].strip()
                continue
            if line.startswith("TEMPO="):
                tempo = int(line.split("=", 1)[1])
                continue
            if line.startswith("TIME="):
                ts_str = line.split("=", 1)[1].strip()
                num_str, den_str = ts_str.split("/")
                time_sig = (int(num_str), int(den_str))
                continue
            if line.startswith("PULSES_PER_BEAT="):
                pulses_per_beat = int(line.split("=", 1)[1])
                continue

            # トラック行 or 継続行
            if ":" in line:
                # 旧トラックをフラッシュ
                flush_current_track()

                name, pat = line.split(":", 1)
                current_track_name = name.strip()
                current_track_tokens = []
                pattern = pat.strip()
                if pattern:
                    current_track_tokens.extend(pattern.split())

            else:
                # 直前に開始したトラックの継続行として扱う
                if current_track_name is not None:
                    current_track_tokens.extend(line.split())
                else:
                    # どのトラックにも属していない謎行 → 無視
                    continue

        # 最終トラックをフラッシュ
        flush_current_track()

        if tempo is None or time_sig is None or pulses_per_beat is None:
            raise ValueError("ヘッダー情報 (TEMPO, TIME, PULSES_PER_BEAT) が不足しています。")

        print(
            f"[INFO] Score.from_text: parsed tempo={tempo}, "
            f"time={time_sig[0]}/{time_sig[1]}, pulses={pulses_per_beat}, tracks={len(tracks)}"
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
        tempo = 100
        time_sig = (4, 4)
        pulses_per_beat = 4
        bar_steps = time_sig[0] * pulses_per_beat  # 16

        # HH: 16ステップ全部を x1 で埋める（1小節）
        hh_events: List[NoteEvent] = []
        for s in range(bar_steps):
            hh_events.append(
                NoteEvent(start_step=s, length_steps=1, symbol="x", dynamic="mf")
            )

        # SD: 2拍目と4拍目にだけスネア、その間は休符で埋めて 16 ステップにそろえる
        sd_events: List[NoteEvent] = []
        # 1拍目: 4ステップ休符
        sd_events.append(NoteEvent(start_step=0, length_steps=4, symbol="rest", dynamic="mf"))
        # 2拍目: スネア1ステップ＋残り3ステップ休符
        sd_events.append(NoteEvent(start_step=4, length_steps=1, symbol="o", dynamic="f"))
        sd_events.append(NoteEvent(start_step=5, length_steps=3, symbol="rest", dynamic="mf"))
        # 3拍目: 4ステップ休符
        sd_events.append(NoteEvent(start_step=8, length_steps=4, symbol="rest", dynamic="mf"))
        # 4拍目: スネア1ステップ＋残り3ステップ休符
        sd_events.append(NoteEvent(start_step=12, length_steps=1, symbol="o", dynamic="f"))
        sd_events.append(NoteEvent(start_step=13, length_steps=3, symbol="rest", dynamic="mf"))

        # BD: 1拍目と3拍目にキック、それ以外は休符で埋めて16ステップ
        bd_events: List[NoteEvent] = []
        bd_events.append(NoteEvent(start_step=0, length_steps=1, symbol="o", dynamic="mf"))
        bd_events.append(NoteEvent(start_step=1, length_steps=3, symbol="rest", dynamic="mf"))
        bd_events.append(NoteEvent(start_step=8, length_steps=1, symbol="o", dynamic="mf"))
        bd_events.append(NoteEvent(start_step=9, length_steps=7, symbol="rest", dynamic="mf"))

        tracks = [
            Track("HH", hh_events),
            Track("SD", sd_events),
            Track("BD", bd_events),
        ]

        return cls(
            tempo=tempo,
            time_signature=time_sig,
            pulses_per_beat=pulses_per_beat,
            tracks=tracks,
            title="Default Pattern",
        )

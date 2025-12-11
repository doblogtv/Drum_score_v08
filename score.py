import re
from dataclasses import dataclass
from typing import List, Tuple, Optional


# ==========================================================
# Drum Score Player v0.8.0
# テキスト譜面ルール ＋ CHECK ブロック検証
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
        v0.8.0 テキストフォーマット:

          FILENAME=◯◯◯       ← Score では使わない（GUI側で利用）
          TITLE=◯◯◯          ← 任意
          TEMPO=80           ← 任意（省略時は 120 とみなす）
          TIME=4/4
          PULSES_PER_BEAT=4

          HH: x+++ x+++ x+++ x+++    ← 4 分音符4つ（PPB=4の場合）
          HH: 1+++++++++++++++       ← 全音符（音色省略で x 扱い）
          SD: o2+++++++  -4---- ...  ← 2 分音符や 4 分休符の指定も可

        - トークン:
            音符: x, o, X, O  （末尾に "+" を付ければ任意長に伸ばせる）
            休符: -, r, R, _, . （同上。"." は不足分のパディングにも利用）
            音価指定: 1,2,4,8,16,32,64 を使用し、必要に応じて音色プレフィックス
                      を付与（例: o2+++++++ はオープンの 2 分音符）。
            `+` はトークン末尾のみ許可。音価指定に期待長-1 個の `+` を添えると、
            小節内の長さを視覚的に確認できる。

        - 強弱:
            トークン末尾に ^pp, ^p, ^mp, ^mf, ^f, ^ff
            例: x^f, o^pp, -^p
            "." には強弱を付けられない。

        - ファイル末尾などに置く検算ブロック:

            %%CHECK:
              Track01_Total = 64
              Track02_Total = 64
              Track03_Total = 64
            %%ENDCHECK

          は必須。派生値（Bars_Total / Steps_Per_Bar など）は書かない。
          記載された数値と解析結果が一致しない場合はエラーを返す。
        """
        print("[INFO] Score.from_text: parsing text score...")

        tempo: Optional[int] = None
        time_sig: Optional[Tuple[int, int]] = None
        pulses_per_beat: Optional[int] = None
        tracks: List[Track] = []
        title: Optional[str] = None

        lines = text.splitlines()

        # 行ごとのトラック情報を保持
        track_events_map: dict[str, List[NoteEvent]] = {}
        track_total_steps: dict[str, int] = {}

        # CHECK ブロックの解析
        in_check_block = False
        check_values: dict[str, int] = {}
        check_block_found = False

        def split_dynamic(token_raw: str) -> Tuple[str, str]:
            """トークンから強弱を切り出す。"""

            if "^" in token_raw:
                base, dyn = token_raw.split("^", 1)
                base = base.strip()
                dyn = dyn.strip()
                if dyn not in ("pp", "p", "mp", "mf", "f", "ff"):
                    raise ValueError(f"未知の強弱記号 '{dyn}' in '{token_raw}'")
                if base == ".":
                    raise ValueError("'.' に強弱は付けられません。")
            else:
                base = token_raw.strip()
                dyn = "mf"

            return base, dyn

        duration_pattern = re.compile(r"^(?P<prefix>[xXoO\-rR_]?)?(?P<note_value>64|32|16|8|4|2|1)$")

        def note_value_to_steps(note_value: int) -> int:
            """拍子記号と PPB から音価をステップ数へ換算する。"""

            numerator = pulses_per_beat * time_sig[1]
            if note_value <= 0:
                raise ValueError(f"音価 {note_value} は 0 以下です。")

            if numerator % note_value != 0:
                raise ValueError(
                    f"TIME={time_sig[0]}/{time_sig[1]}, PPB={pulses_per_beat} では "
                    f"音価 1/{note_value} を整数ステップに変換できません。PPB を見直してください。"
                )

            return numerator // note_value

        def parse_token(token_raw: str) -> Tuple[str, str, int]:
            """
            拍指定を含む新フォーマットを解釈し、
            (symbol, dyn, length_steps) を返す。

            - `1,2,4,8,16,32,64` は音価指定。先頭/末尾に x,o などを付けて音色を明示できる。
              例: `1+++++++++`（全音符）、`o2+++++++`（オープンの 2 分音符）。
            - `+` はトークン末尾のみに置ける持続マーカー。音価指定トークンでは
              「期待長-1」と同数の `+` を書くと視覚的に長さを確認できる。
            - 従来の `x` や `-` など 1 ステップトークンも継続して使用可能で、
              `x+++` のように `+` を付ければ任意ステップに伸ばせる。
            """

            token = token_raw.strip()
            if not token:
                raise ValueError("空のトークンは無効です。")

            plus_count = len(token) - len(token.rstrip("+"))
            core = token.rstrip("+")

            base, dyn = split_dynamic(core)
            if not base:
                raise ValueError(f"'+' だけのトークンは使用できません: '{token_raw}'")

            if base == "|":
                raise ValueError("'|' は小節区切りとしても使用できません。固定長のみ許可します。")

            if base == "." and dyn != "mf":
                raise ValueError("'.' に強弱は付けられません。")

            m = duration_pattern.match(base)

            if m:
                note_value = int(m.group("note_value"))
                prefix = m.group("prefix") or ""

                length_steps = note_value_to_steps(note_value)

                if plus_count not in (0, length_steps - 1):
                    raise ValueError(
                        f"{token_raw}: '+' の数 {plus_count} が音価 1/{note_value} の長さ {length_steps} と一致しません。"
                        f"（期待 {length_steps - 1} 個）"
                    )

                if prefix in {"-", "r", "R", "_"}:
                    symbol = "rest"
                elif prefix in {"x", "X", "o", "O"}:
                    symbol = prefix
                else:
                    # 音色を省略した場合は標準の "x" を鳴らす
                    symbol = "x"
            else:
                allowed = {"x", "X", "o", "O", "-", "r", "R", "_", "."}
                if base not in allowed:
                    raise ValueError(f"未知のトークン '{token_raw}'")

                symbol = "rest" if base in {"-", "r", "R", "_", "."} else base
                length_steps = 1 + plus_count

            return symbol, dyn, length_steps

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
                check_block_found = True
                in_check_block = True
                continue

            # CHECK ブロック終了
            if line.startswith("%%ENDCHECK"):
                in_check_block = False
                continue

            # CHECK ブロック内を解析
            if in_check_block:
                if "=" not in line:
                    raise ValueError("CHECK ブロックの行は 'KEY = VALUE' 形式である必要があります。")

                key, value_str = line.split("=", 1)
                key = key.strip()
                value_str = value_str.strip()

                if not value_str.isdigit():
                    raise ValueError(f"CHECK ブロックの数値が整数ではありません: '{line}'")

                check_values[key] = int(value_str)
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
                if time_sig is None or pulses_per_beat is None:
                    raise ValueError("TIME と PULSES_PER_BEAT をトラックより前に記述してください。")

                name, data = line.split(":", 1)
                track_name = name.strip()
                if not track_name:
                    raise ValueError("トラック名が空です。")

                tokens = data.strip().split()
                bar_steps = time_sig[0] * pulses_per_beat
                if bar_steps <= 0:
                    raise ValueError("1小節あたりのステップ数(bar_steps) が 0 以下です。")

                if track_name not in track_events_map:
                    track_events_map[track_name] = []
                    track_total_steps[track_name] = 0

                line_events: List[Tuple[int, str, str, int]] = []
                line_length = 0

                for token_raw in tokens:
                    symbol, dyn, length_steps = parse_token(token_raw)
                    if length_steps <= 0:
                        raise ValueError(f"トークン '{token_raw}' の長さが 0 以下です。")

                    line_events.append((line_length, symbol, dyn, length_steps))
                    line_length += length_steps

                if line_length != bar_steps:
                    raise ValueError(
                        f"トラック {track_name}: 1 行の長さ {line_length} ステップが "
                        f"1小節 {bar_steps} ステップと一致しません。" "音価指定や '+' を見直してください。"
                    )

                start_offset = track_total_steps[track_name]
                events = track_events_map[track_name]

                for rel_start, symbol, dyn, length_steps in line_events:
                    start_step = start_offset + rel_start
                    if (
                        symbol == "rest"
                        and events
                        and events[-1].symbol == "rest"
                        and events[-1].start_step + events[-1].length_steps == start_step
                    ):
                        events[-1].length_steps += length_steps
                    else:
                        events.append(
                            NoteEvent(
                                start_step=start_step,
                                length_steps=length_steps,
                                symbol=symbol,
                                dynamic=dyn,
                            )
                        )

                track_total_steps[track_name] += line_length
                continue

            # それ以外は旧形式の継続行などとみなし、明示的に拒否
            raise ValueError(f"行の形式を解釈できません: '{line}'")

        if time_sig is None or pulses_per_beat is None:
            raise ValueError("TIME と PULSES_PER_BEAT は必須です。")

        if tempo is None:
            tempo = 120

        if not check_block_found:
            raise ValueError(
                "CHECK ブロックが見つかりません。譜面末尾に検算用のブロックを追加してください。"
            )

        if not track_events_map:
            raise ValueError("トラック定義が見つかりません。")

        bar_steps = time_sig[0] * pulses_per_beat
        if bar_steps <= 0:
            raise ValueError("1小節あたりのステップ数(bar_steps) が 0 以下です。")

        for track_name, events in track_events_map.items():
            total_steps = track_total_steps[track_name]

            if total_steps % bar_steps != 0:
                raise ValueError(
                    f"トラック {track_name}: 合計 {total_steps} ステップは "
                    f"1小節 {bar_steps} の整数倍ではありません。"
                )

            tracks.append(Track(track_name, events))

        score = cls(
            tempo=tempo,
            time_signature=time_sig,
            pulses_per_beat=pulses_per_beat,
            tracks=tracks,
            title=title,
        )

        # CHECK ブロックと実測値の突き合わせ
        if not check_values:
            raise ValueError("CHECK ブロックに検算用の数値がありません。'HH_Total = 64' のように記述してください。")

        errors = []
        track_total_keys = {f"{name}_Total" for name in track_total_steps}

        # 1. トラックごとの合計ステップ数
        for track_name, total in track_total_steps.items():
            key = f"{track_name}_Total"
            if key not in check_values:
                errors.append(f"CHECK ブロックに {key} の記載がありません。")
            elif check_values[key] != total:
                expected = check_values[key]
                errors.append(
                    f"{key}: CHECK={expected} と解析結果 {total} が一致しません。"
                )

        # 2. CHECK に存在するがトラックとして見つからない項目や派生値
        extra_keys = [key for key in check_values.keys() if key not in track_total_keys]
        for key in extra_keys:
            errors.append(f"CHECK ブロックの {key} は許可されていません。トラック名_Total のみ記述してください。")

        if errors:
            error_text = "\n".join(errors)
            raise ValueError(f"CHECK ブロックの検算に失敗しました:\n{error_text}")

        print(
            f"[INFO] Score.from_text: parsed tempo={tempo}, "
            f"time={time_sig}, pulses={pulses_per_beat}, tracks={len(tracks)}"
        )

        return score

    # ------------------------
    # デフォルト譜面生成（簡易テスト用）
    # ------------------------
    @classmethod
    def create_default_score(cls) -> "Score":
        """
        アプリ初回起動時などに使うデフォルト譜面。
        固定長 1 ステップトークンのみを利用した 4 小節（64 ステップ）。
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

HH: x x x x x x x x x x x x x x x x
HH: x^f x x x x^f x x x x^f x x x x^f x x x
HH: x x x x x x x x x x x x x x x x
HH: o o x x o o x x o o x x o o x x

SD: . . . . . x . . . x . . . x . .
SD: . . . . x . . . x . . . x . . .
SD: . . x x x x x x . . x x x x x x
SD: . . . . x x x x . . x x . . x x

BD: x . . . . . x . . . x . . . x .
BD: x . . . x . . . x . . . x . . .
BD: x . x . x . x . x . x . x . x .
BD: x x . . x x . . x . . . x . . .

%%CHECK:
  HH_Total = 64
  SD_Total = 64
  BD_Total = 64
%%ENDCHECK
"""
        return cls.from_text(text)

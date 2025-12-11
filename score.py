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

          HH: x x x x ... 16 トークンで 1 小節固定（不足は "."）
          HH: x x x x ... ← 2 小節目。行頭のトラック名は毎行必須。
          SD: - - - - ...

        - トークン:
            音符: x, o, X, O
            休符: -, r, R, _, .   （"." は 1 ステップのパディング）
            長さを表す数字や "|" は禁止。1 トークン = 1 ステップとする。

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

        # 行ごとのトラック情報を保持（1 行 = 1 小節固定）
        track_token_map: dict[str, List[Tuple[str, str]]] = {}

        # CHECK ブロックの解析
        in_check_block = False
        check_values: dict[str, int] = {}
        check_block_found = False

        def parse_token(token_raw: str) -> Tuple[str, str]:
            """
            固定長 1 ステップのトークンのみを受け付ける。
            数字や "|"、空トークンはすべて拒否する。
            """

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

            if not base:
                raise ValueError("空のトークンは無効です。")

            if base == "|":
                raise ValueError("'|' は小節区切りとしても使用できません。固定長のみ許可します。")

            if any(ch.isdigit() for ch in base):
                raise ValueError(f"固定長フォーマットでは数字を含むトークンは使用できません: '{token_raw}'")

            allowed = {"x", "X", "o", "O", "-", "r", "R", "_", "."}
            if base not in allowed:
                raise ValueError(f"未知のトークン '{token_raw}'")

            symbol = "rest" if base in {"-", "r", "R", "_", "."} else base
            return symbol, dyn

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

                if len(tokens) != bar_steps:
                    raise ValueError(
                        f"トラック {track_name}: 1 行のトークン数 {len(tokens)} が "
                        f"1小節 {bar_steps} と一致しません。'.' でパディングしてください。"
                    )

                parsed_tokens: List[Tuple[str, str]] = []
                for token_raw in tokens:
                    parsed_tokens.append(parse_token(token_raw))

                track_token_map.setdefault(track_name, []).extend(parsed_tokens)
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

        if not track_token_map:
            raise ValueError("トラック定義が見つかりません。")

        bar_steps = time_sig[0] * pulses_per_beat
        if bar_steps <= 0:
            raise ValueError("1小節あたりのステップ数(bar_steps) が 0 以下です。")

        track_total_steps: dict[str, int] = {}
        for track_name, tokens in track_token_map.items():
            total_steps = len(tokens)
            track_total_steps[track_name] = total_steps

            if total_steps % bar_steps != 0:
                raise ValueError(
                    f"トラック {track_name}: 合計 {total_steps} ステップは "
                    f"1小節 {bar_steps} の整数倍ではありません。"
                )

            events: List[NoteEvent] = []
            idx = 0

            while idx < len(tokens):
                symbol, dyn = tokens[idx]

                if symbol != "rest":
                    # 叩く音符は常に 1 ステップ固定でトリガーする
                    events.append(
                        NoteEvent(
                            start_step=idx,
                            length_steps=1,
                            symbol=symbol,
                            dynamic=dyn,
                        )
                    )
                    idx += 1
                    continue

                # 休符は「できるだけまとめて、拍をまたがない」ルールに従い、
                # 同一拍内の連続休符を 1 つのイベントにまとめる。
                beat_remaining = pulses_per_beat - (idx % pulses_per_beat)
                rest_len = 0
                while idx + rest_len < len(tokens) and rest_len < beat_remaining:
                    next_symbol, _ = tokens[idx + rest_len]
                    if next_symbol != "rest":
                        break
                    rest_len += 1

                events.append(
                    NoteEvent(
                        start_step=idx,
                        length_steps=rest_len,
                        symbol="rest",
                        dynamic=dyn,
                    )
                )
                idx += rest_len

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

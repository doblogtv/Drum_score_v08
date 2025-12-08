# exporter.py
import wave
import struct
from typing import Dict, Tuple, List

from score import Score
from synth import DrumSynth


def dynamic_to_level(dyn: str) -> int:
    """
    DrumApp.dynamic_to_level と同じロジックをここにコピー。
    強弱記号 → レベル(0〜3) の対応。
    """
    if dyn in ("pp", "p"):
        return 1
    if dyn in ("mp", "mf"):
        return 2
    if dyn in ("f", "ff"):
        return 3
    # 未指定や不明は mf 相当
    return 2


def render_score_to_wav(
    score: Score,
    synth: DrumSynth,
    filepath: str,
    loop_count: int = 1,
) -> None:
    """
    Score と DrumSynth から、オフラインで 1本の WAV を合成して保存する。

    - tempo / pulses_per_beat を使って「1ステップの時間」を計算
    - 各ステップで HH/SD/BD のレベル(0〜3)を求め、
      DrumSynth.combo_files から該当コンボWAVを取得
    - サンプル単位でタイムライン上にミックスしていく
    - loop_count 回ぶんパターンを繰り返して収録
    """
    print("[INFO] WAV export: start")
    if loop_count < 1:
        loop_count = 1

    sr = synth.sr
    step_sec = 60.0 / (score.tempo * score.pulses_per_beat)
    hit_samples = synth.hit_samples
    hit_sec = hit_samples / sr

    pattern_steps = score.total_steps  # 1ループ分の総ステップ数
    total_steps = pattern_steps * loop_count

    # 全体の長さ（秒）をざっくり見積もる
    total_duration_sec = total_steps * step_sec + hit_sec
    total_samples = int(total_duration_sec * sr) + 1

    print(f"[INFO]  tempo={score.tempo}, pulses={score.pulses_per_beat}")
    print(f"[INFO]  pattern_steps={pattern_steps}, loop_count={loop_count}")
    print(f"[INFO]  total_steps={total_steps}, total_duration_sec≈{total_duration_sec:.3f}")

    # 出力用バッファ（float）
    mix: List[float] = [0.0] * total_samples

    # --------------------------------------------------
    # トラックごとに「開始ステップ → NoteEvent」のマップを作る
    # （最大3トラック = HH, SD, BD 想定）
    # --------------------------------------------------
    track_maps: List[Dict[int, List]] = []
    for track in score.tracks[:3]:
        m: Dict[int, List] = {}
        for ev in track.events:
            if ev.symbol == "rest":
                continue
            m.setdefault(ev.start_step, []).append(ev)
        track_maps.append(m)

    # --------------------------------------------------
    # DrumSynth.combo_files からコンボWAVを読み込んでキャッシュ
    # key: (hh_level, sd_level, bd_level)
    # value: List[float]  （-1.0〜1.0）
    # --------------------------------------------------
    combo_cache: Dict[Tuple[int, int, int], List[float]] = {}

    def load_combo_wave(key: Tuple[int, int, int]) -> List[float]:
        if key in combo_cache:
            return combo_cache[key]
        path = synth.combo_files.get(key)
        if not path:
            combo_cache[key] = []
            return combo_cache[key]

        wf = wave.open(path, "rb")
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        fr = wf.getframerate()
        nframes = wf.getnframes()
        frames = wf.readframes(nframes)
        wf.close()

        if ch != 1 or sw != 2 or fr != sr:
            raise ValueError(f"Unexpected combo wav format: {path}")

        data: List[float] = []
        for i in range(nframes):
            s = struct.unpack_from("<h", frames, i * 2)[0]
            data.append(s / 32768.0)

        combo_cache[key] = data
        return data

    # --------------------------------------------------
    # ステップごとにコンボをミックス
    # --------------------------------------------------
    for global_step in range(total_steps):
        pattern_step = global_step % pattern_steps

        # HH / SD / BD のレベル (0〜3)
        hh_level = 0
        sd_level = 0
        bd_level = 0

        for t_index, track_map in enumerate(track_maps):
            events = track_map.get(pattern_step)
            if not events:
                continue

            # 同じステップに複数イベントがあった場合は最初だけ使う
            ev = events[0]
            level = dynamic_to_level(ev.dynamic)

            if t_index == 0:
                hh_level = level
            elif t_index == 1:
                sd_level = level
            elif t_index == 2:
                bd_level = level

        # 全て0なら何も鳴らさない
        if hh_level == 0 and sd_level == 0 and bd_level == 0:
            continue

        key = (hh_level, sd_level, bd_level)
        wav_data = load_combo_wave(key)
        if not wav_data:
            continue

        # このステップの開始サンプル位置
        start_sample = int(global_step * step_sec * sr)

        # 波形をミックス
        for i, v in enumerate(wav_data):
            idx = start_sample + i
            if idx >= total_samples:
                break
            mix[idx] += v

    # --------------------------------------------------
    # 正規化（クリップ防止）
    # --------------------------------------------------
    peak = max(abs(v) for v in mix) or 1.0
    if peak > 1.0:
        norm = 0.98 / peak
        mix = [v * norm for v in mix]
        print(f"[INFO]  normalized (peak={peak:.3f})")
    else:
        print(f"[INFO]  no normalization needed (peak={peak:.3f})")

    # --------------------------------------------------
    # WAV ファイルとして書き出し
    # --------------------------------------------------
    wf_out = wave.open(filepath, "wb")
    wf_out.setnchannels(1)
    wf_out.setsampwidth(2)
    wf_out.setframerate(sr)

    for v in mix:
        s = int(max(-32767, min(32767, v * 32767)))
        wf_out.writeframes(struct.pack("<h", s))

    wf_out.close()
    print(f"[INFO] WAV export: done -> {filepath}")

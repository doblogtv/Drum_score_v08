# exporter.py
import wave
import struct
from typing import Dict, Tuple, List, Callable
import tempfile
import os

from score import Score
from synth import DrumSynth


def dynamic_to_level(dyn: str) -> int:
    """
    強弱 → レベル変換
    pp/p -> 1, mp/mf -> 2, f/ff -> 3, それ以外は 2
    """
    if dyn in ("pp", "p"):
        return 1
    if dyn in ("mp", "mf"):
        return 2
    if dyn in ("f", "ff"):
        return 3
    return 2


def _load_combo_waves(synth: DrumSynth) -> Dict[Tuple[int, int, int], List[float]]:
    """
    DrumSynth が生成した combo WAV を読み込んで
    key -> [-1.0..1.0] の float 配列にして返す
    """
    combo_waves: Dict[Tuple[int, int, int], List[float]] = {}

    for key, path in synth.combo_files.items():
        if path is None:
            combo_waves[key] = []
            continue

        with wave.open(path, "rb") as wf:
            n_channels = wf.getnchannels()
            sr = wf.getframerate()
            n_frames = wf.getnframes()
            sampwidth = wf.getsampwidth()

            if n_channels != 1:
                raise ValueError("combo WAV はモノラルを想定しています。")
            if sr != synth.sr:
                raise ValueError("combo WAV のサンプリングレートが DrumSynth.sr と一致しません。")
            if sampwidth != 2:
                raise ValueError("combo WAV は16bit PCMを想定しています。")

            raw = wf.readframes(n_frames)
            ints = struct.unpack("<{}h".format(n_frames), raw)
            floats = [v / 32768.0 for v in ints]
            combo_waves[key] = floats

    return combo_waves


def render_score_to_wav(
    score: Score,
    synth: DrumSynth,
    filepath: str,
    loop_count: int = 1,
) -> float:
    """
    Score と DrumSynth からオフラインで WAV を合成して保存する。

    - ループ回数 loop_count 分だけシーケンスを連結
    - return: 実際に書き出したおおよその再生時間（秒）
      （動画側で目安として使える）

    タイミング仕様は GUI 再生と合わせる：
      step_duration_sec = 60 / (tempo * pulses_per_beat)
    """
    if loop_count <= 0:
        loop_count = 1

    sr = synth.sr
    pulses = score.pulses_per_beat
    tempo = score.tempo
    total_steps_one_loop = score.total_steps

    if pulses <= 0 or tempo <= 0 or total_steps_one_loop <= 0:
        raise ValueError("Score のヘッダー情報が不正です。")

    step_duration_sec = 60.0 / (tempo * pulses)

    total_steps_all = total_steps_one_loop * loop_count
    total_duration_sec = total_steps_all * step_duration_sec

    # 最終のヒット分を少し余裕を持って確保
    total_samples = int(total_duration_sec * sr) + synth.hit_samples + 2

    print(
        f"[INFO] WAV export: tempo={tempo}, pulses={pulses}, "
        f"steps(one loop)={total_steps_one_loop}, loops={loop_count}, "
        f"duration≈{total_duration_sec:.2f} sec"
    )

    # コンボ波形を読み込む
    combo_waves = _load_combo_waves(synth)

    # 1ループぶんの「各ステップの (hh, sd, bd) レベル」を前計算
    step_levels: List[Tuple[int, int, int]] = []
    for step in range(total_steps_one_loop):
        hh_level = 0
        sd_level = 0
        bd_level = 0

        for i, track in enumerate(score.tracks[:3]):  # HH, SD, BD の3トラック想定
            level = 0
            for ev in track.events:
                if ev.symbol == "rest":
                    continue
                if ev.start_step == step:
                    level = dynamic_to_level(ev.dynamic)
                    break

            if i == 0:
                hh_level = level
            elif i == 1:
                sd_level = level
            elif i == 2:
                bd_level = level

        step_levels.append((hh_level, sd_level, bd_level))

    # ミックスバッファ
    mix = [0.0] * total_samples

    # ループごとに足し込み
    for loop_idx in range(loop_count):
        base_step_index = loop_idx * total_steps_one_loop
        for local_step, combo_key in enumerate(step_levels):
            hh_level, sd_level, bd_level = combo_key
            if hh_level == 0 and sd_level == 0 and bd_level == 0:
                continue

            wave_data = combo_waves.get(combo_key)
            if not wave_data:
                continue

            global_step = base_step_index + local_step
            start_sample = int(global_step * step_duration_sec * sr)

            for n, v in enumerate(wave_data):
                idx = start_sample + n
                if idx >= total_samples:
                    break
                mix[idx] += v

    # 正規化
    max_amp = max(abs(v) for v in mix) if mix else 0.0
    if max_amp > 0:
        if max_amp > 0.99:
            scale = 0.99 / max_amp
            mix = [v * scale for v in mix]
    else:
        print("[WARN] WAV export: 無音データになっています。")

    # 16bit PCM で書き出し
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        ints = [max(-32768, min(32767, int(v * 32767))) for v in mix]
        pcm = struct.pack("<{}h".format(len(ints)), *ints)
        wf.writeframes(pcm)

    print(f"[INFO] WAV export: saved to {filepath}")
    return total_duration_sec


def render_score_to_movie(
    score: Score,
    synth: DrumSynth,
    loop_count: int,
    capture_frame: Callable[[int], "object"],  # step_index -> PIL.Image.Image 相当
    movie_path: str,
    fps: int = 30,
) -> None:
    """
    - score / synth / loop_count からオフラインで音声WAVを作る
    - capture_frame(step_index) を呼びながらフレーム列を集める
    - moviepy で音声と合成して mp4 を書き出す

    capture_frame は「譜面上の step_index (0〜total_steps_one_loop-1) を受け取って、
    その状態の画像(PIL.Image)を返す」関数。
    Tk / ImageGrab 依存は gui_app 側に閉じ込める。
    """
    from moviepy.editor import ImageSequenceClip, AudioFileClip
    import numpy as np

    if loop_count <= 0:
        loop_count = 1

    pulses = score.pulses_per_beat
    tempo = score.tempo
    if pulses <= 0 or tempo <= 0:
        raise ValueError("Score のヘッダー情報 (TEMPO, PULSES_PER_BEAT) が不正です。")

    step_duration_sec = 60.0 / (tempo * pulses)
    total_steps_one_loop = score.total_steps
    if total_steps_one_loop <= 0:
        raise ValueError("有効なステップ数がありません。")

    total_steps_all = total_steps_one_loop * loop_count
    total_duration_sec = total_steps_all * step_duration_sec

    # 一時WAV作成
    tmp_fd, tmp_wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(tmp_fd)

    try:
        audio_duration = render_score_to_wav(
            score=score,
            synth=synth,
            filepath=tmp_wav_path,
            loop_count=loop_count,
        )

        # 念のため、譜面側/音声側の duration の短い方に合わせる
        effective_duration = min(total_duration_sec, audio_duration)
        frame_count = max(1, int(effective_duration * fps))

        print(
            f"[INFO] Movie: duration≈{effective_duration:.2f} sec, "
            f"fps={fps}, frames={frame_count}"
        )

        frames = []
        for i in range(frame_count):
            t = i / fps  # [sec]
            global_step = int(t / step_duration_sec)
            if global_step >= total_steps_all:
                break
            step_index = global_step % total_steps_one_loop

            img = capture_frame(step_index)
            frames.append(np.array(img))

        if not frames:
            raise RuntimeError("フレームが1枚も生成されませんでした。")

        clip = ImageSequenceClip(frames, fps=fps)
        audio_clip = AudioFileClip(tmp_wav_path)
        clip = clip.set_audio(audio_clip)

        clip.write_videofile(
            movie_path,
            codec="libx264",
            audio_codec="aac",
            fps=fps,
        )

        audio_clip.close()
        clip.close()
    finally:
        # 一時WAVは削除
        try:
            os.remove(tmp_wav_path)
        except Exception:
            pass

    print(f"[INFO] Movie: saved to {movie_path}")

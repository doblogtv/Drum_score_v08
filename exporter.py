# exporter.py
import wave
import struct
from typing import Callable, List
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


def render_score_to_wav(
    score: Score,
    synth: DrumSynth,
    filepath: str,
    loop_count: int = 1,
) -> float:
    """
    Score と DrumSynth からオフラインで WAV を合成して保存する。

    - GUI 再生と同じタイミングで、ステップごとに
      HH / SD / BD の波形をミックスする
    - loop_count 回だけ譜面を連結
    - return: 書き出した再生時間の目安（秒）
    """
    if loop_count <= 0:
        loop_count = 1

    pulses = score.pulses_per_beat
    tempo = score.tempo
    total_steps_one_loop = score.total_steps
    if pulses <= 0 or tempo <= 0 or total_steps_one_loop <= 0:
        raise ValueError("Score のヘッダー情報が不正です。")

    # DrumSynth のサンプルレート
    sr = getattr(synth, "sample_rate", 44100)

    step_duration_sec = 60.0 / (tempo * pulses)
    total_steps_all = total_steps_one_loop * loop_count
    total_duration_sec = total_steps_all * step_duration_sec

    # 各トラック用の波形（WAV があれば優先、無ければ内蔵シンセ）
    dyn_gain_map = synth.sound_settings.get(
        "dyn_gain",
        {0: 0.0, 1: 0.4, 2: 0.8, 3: 1.1},
    )

    hh_wave = getattr(synth, "wav_hh", None) or getattr(synth, "internal_hh", None)
    sd_wave = getattr(synth, "wav_sd", None) or getattr(synth, "internal_sd", None)
    bd_wave = getattr(synth, "wav_bd", None) or getattr(synth, "internal_bd", None)

    available_waves = [w for w in (hh_wave, sd_wave, bd_wave) if w is not None]
    if not available_waves:
        raise ValueError("DrumSynth に有効な波形がありません。")

    hit_len_max = max(len(w) for w in available_waves)
    total_samples = int(total_duration_sec * sr) + hit_len_max + 2

    print(
        f"[INFO] WAV export: tempo={tempo}, pulses={pulses}, "
        f"steps(one loop)={total_steps_one_loop}, loops={loop_count}, "
        f"duration≈{total_duration_sec:.2f} sec"
    )

    # ミックス用バッファ
    mix = [0.0] * total_samples

    # ループごとにミックス
    for loop_idx in range(loop_count):
        base_step_index = loop_idx * total_steps_one_loop
        for step in range(total_steps_one_loop):
            global_step = base_step_index + step
            start_sample = int(global_step * step_duration_sec * sr)

            # HH, SD, BD の 3 トラックのみ対象
            for i, track in enumerate(score.tracks[:3]):
                level = 0
                for ev in track.events:
                    if ev.symbol == "rest":
                        continue
                    if ev.start_step == step:
                        level = dynamic_to_level(ev.dynamic)
                        break

                if level <= 0:
                    continue

                if i == 0:
                    base_gain = synth.sound_settings.get("base_gain_hh", 0.4)
                    wave_data = hh_wave
                elif i == 1:
                    base_gain = synth.sound_settings.get("base_gain_sd", 0.3)
                    wave_data = sd_wave
                else:
                    base_gain = synth.sound_settings.get("base_gain_bd", 0.8)
                    wave_data = bd_wave

                if wave_data is None:
                    continue

                gain = base_gain * dyn_gain_map.get(level, 1.0)

                for n, v in enumerate(wave_data):
                    idx = start_sample + n
                    if idx >= total_samples:
                        break
                    mix[idx] += v * gain

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
    video_codec: str = "mpeg4",
    audio_codec: str = "aac",
) -> None:
    """
    - render_score_to_wav() で一時 WAV を作成
    - capture_frame(step_index) で譜面キャンバスをフレーム化
    - moviepy で音声と合成して動画を書き出す
    """
    try:
        from moviepy import ImageSequenceClip, AudioFileClip
    except ModuleNotFoundError as exc:  # pragma: no cover - 環境依存
        raise RuntimeError("moviepy が必要です。`pip install moviepy` を実行してください。") from exc

    try:
        import numpy as np
    except ModuleNotFoundError as exc:  # pragma: no cover - 環境依存
        raise RuntimeError("numpy が必要です。`pip install numpy` を実行してください。") from exc

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

    # 一時 WAV
    tmp_fd, tmp_wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(tmp_fd)

    try:
        audio_duration = render_score_to_wav(
            score=score,
            synth=synth,
            filepath=tmp_wav_path,
            loop_count=loop_count,
        )

        effective_duration = min(total_duration_sec, audio_duration)
        frame_count = max(1, int(effective_duration * fps))

        print(
            f"[INFO] Movie: duration≈{effective_duration:.2f} sec, "
            f"fps={fps}, frames={frame_count}"
        )

        frames: List["np.ndarray"] = []
        for i in range(frame_count):
            t = i / fps  # sec
            global_step = int(t / step_duration_sec)
            if global_step >= total_steps_all:
                break
            step_index = global_step % total_steps_one_loop

            img = capture_frame(step_index)
            frames.append(np.array(img))

        if not frames:
            raise RuntimeError("フレームが1枚も生成されませんでした。")

        video_clip = ImageSequenceClip(frames, fps=fps)
        audio_clip = AudioFileClip(tmp_wav_path)
        final_clip = video_clip.with_audio(audio_clip)

        final_clip.write_videofile(
            movie_path,
            codec=video_codec,
            audio_codec=audio_codec,
            fps=fps,
        )

        audio_clip.close()
        final_clip.close()
    finally:
        try:
            os.remove(tmp_wav_path)
        except Exception:
            pass

    print(f"[INFO] Movie: saved to {movie_path}")

import winsound
import wave
import struct
import math
import random
import tempfile
import os
from typing import Dict, Tuple, Optional, List


class DrumSynth:
    """
    HH / SD / BD の簡易ドラム音源を合成して、
    3トラックの組み合わせごとに WAV を事前生成しておくクラス。

    強弱レベル：
      各トラックについて level ∈ {0,1,2,3}
        0 = 鳴らさない
        1 = 弱（pp/p）
        2 = 中（mp/mf）
        3 = 強（f/ff）

    combo_files のキー:
        (hh_level, sd_level, bd_level)
    """

    def __init__(self, sr: int = 44100, hit_ms: int = 260, sound_settings: Optional[dict] = None):
        self.sr = sr
        self.hit_ms = hit_ms
        self.hit_samples = int(sr * hit_ms / 1000.0)

        # サウンド設定（外部から変更可能）
        if sound_settings is None:
            sound_settings = {}
        self.base_gain_hh = sound_settings.get("base_gain_hh", 0.4)
        self.base_gain_sd = sound_settings.get("base_gain_sd", 0.3)
        self.base_gain_bd = sound_settings.get("base_gain_bd", 0.8)

        # 強弱倍率
        self.dyn_gain: Dict[int, float] = sound_settings.get("dyn_gain", {
            0: 0.0,
            1: 0.4,
            2: 0.8,
            3: 1.1,
        })
        # dyn_gain に 0〜3 が必ずあるように補完
        for k, v in {0: 0.0, 1: 0.4, 2: 0.8, 3: 1.1}.items():
            self.dyn_gain.setdefault(k, v)

        print("[INFO] DrumSynth: building combo waveforms...")

        # 各ドラムの生波形（-1.0〜1.0）
        self.hh = self._make_hihat()
        self.sd = self._make_snare()
        self.bd = self._make_kick()

        self.combo_files: Dict[Tuple[int, int, int], Optional[str]] = {}
        self._build_combos()

        print("[INFO] DrumSynth: combo waveforms ready.")

    # ------- パラメータ更新 -------
    def update_params(self, sound_settings: dict):
        """サウンド設定を更新し、コンボWAVを再生成"""
        self.base_gain_hh = sound_settings.get("base_gain_hh", self.base_gain_hh)
        self.base_gain_sd = sound_settings.get("base_gain_sd", self.base_gain_sd)
        self.base_gain_bd = sound_settings.get("base_gain_bd", self.base_gain_bd)
        dyn_gain = sound_settings.get("dyn_gain")
        if dyn_gain:
            self.dyn_gain.update(dyn_gain)

        # 既存WAV削除
        for path in self.combo_files.values():
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
        self.combo_files.clear()
        print("[INFO] DrumSynth: rebuilding combo waveforms with new settings...")
        self._build_combos()
        print("[INFO] DrumSynth: combo waveforms updated.")

    # ------- 基本的なエンベロープ --------
    def _adsr_env(self, length: int, attack: float, decay: float) -> List[float]:
        env = [0.0] * length
        attack_samples = max(1, int(self.sr * attack))
        decay_samples = max(1, int(self.sr * decay))
        total = attack_samples + decay_samples
        if total > length:
            total = length
            decay_samples = total - attack_samples

        for i in range(attack_samples):
            env[i] = i / attack_samples

        for i in range(decay_samples):
            idx = attack_samples + i
            if idx >= length:
                break
            env[idx] = max(0.0, 1.0 - i / decay_samples)

        return env

    # ------- 各ドラムの合成 --------
    def _make_kick(self) -> List[float]:
        """
        ソフトなクリック付きキック。
        ・120Hz → 60Hz のピッチダウン
        ・ごく短い 1kHz クリックを弱めに足す
        """
        length = self.hit_samples
        env = self._adsr_env(length, attack=0.005, decay=0.25)

        data = []
        start_freq = 120.0
        end_freq = 60.0

        click_duration = int(self.sr * 0.004)
        click_freq = 1200.0

        for n in range(length):
            t = n / self.sr

            f = start_freq + (end_freq - start_freq) * (n / length)
            phase = 2.0 * math.pi * f * t

            base = math.sin(phase)
            base += 0.3 * math.sin(3.0 * phase)

            if n < click_duration:
                click_env = 1.0 - (n / click_duration)
                click = math.sin(2.0 * math.pi * click_freq * t) * click_env
            else:
                click = 0.0

            s = (base * 0.95 + click * 0.15) * env[n]
            data.append(s)

        return data

    def _make_snare(self) -> List[float]:
        """ノイズ＋中域トーンのスネア"""
        length = self.hit_samples
        env = self._adsr_env(length, attack=0.001, decay=0.18)
        data = []
        tone_freq = 180.0
        for n in range(length):
            t = n / self.sr
            noise = (random.random() * 2.0 - 1.0) * 0.7
            tone = math.sin(2.0 * math.pi * tone_freq * t) * 0.3
            s = (noise + tone) * env[n]
            data.append(s)
        return data

    def _make_hihat(self) -> List[float]:
        """高域ノイズのハイハット"""
        length = self.hit_samples
        env = self._adsr_env(length, attack=0.0005, decay=0.10)
        data = []
        for n in range(length):
            noise = (random.random() * 2.0 - 1.0)
            s = noise * env[n]
            data.append(s * 0.05)
        return data

    # ------- コンボWAV生成（強弱対応版） --------
    def _build_combos(self):
        """
        各トラックの level ∈ {0,1,2,3} に対して、
        (hh_level, sd_level, bd_level) ごとに 1つの WAV を生成。
        (0,0,0) は何も鳴らさないので None。
        """
        for hh_level in range(4):
            for sd_level in range(4):
                for bd_level in range(4):
                    if hh_level == 0 and sd_level == 0 and bd_level == 0:
                        self.combo_files[(hh_level, sd_level, bd_level)] = None
                        continue

                    mix = [0.0] * self.hit_samples

                    if hh_level > 0:
                        g = self.base_gain_hh * self.dyn_gain[hh_level]
                        for i, v in enumerate(self.hh):
                            mix[i] += v * g

                    if sd_level > 0:
                        g = self.base_gain_sd * self.dyn_gain[sd_level]
                        for i, v in enumerate(self.sd):
                            mix[i] += v * g

                    if bd_level > 0:
                        g = self.base_gain_bd * self.dyn_gain[bd_level]
                        for i, v in enumerate(self.bd):
                            mix[i] += v * g

                    max_amp = max(abs(x) for x in mix) or 1.0
                    if max_amp > 1.0:
                        norm = 0.98 / max_amp
                    else:
                        norm = 0.98

                    frames = []
                    for x in mix:
                        s = int(max(-32767, min(32767, x * norm * 32767)))
                        frames.append(struct.pack("<h", s))
                    pcm = b"".join(frames)

                    fd, path = tempfile.mkstemp(suffix=".wav", prefix="drum_combo_dyn_")
                    os.close(fd)
                    wf = wave.open(path, "wb")
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(self.sr)
                    wf.writeframes(pcm)
                    wf.close()

                    self.combo_files[(hh_level, sd_level, bd_level)] = path

    def play_combo(self, hh_level: int, sd_level: int, bd_level: int):
        """レベル三つに対応するコンボWAVを非同期再生"""
        key = (hh_level, sd_level, bd_level)
        path = self.combo_files.get(key)
        if not path:
            return
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)

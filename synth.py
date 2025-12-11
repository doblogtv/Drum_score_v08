import numpy as np
import simpleaudio as sa
import wave
import os


class DrumSynth:
    """
    ● WAV 読み込み対応
    ● polyphonic（重ね鳴り）対応
    ● 休符では発音停止しない
    ● 次の同じ音が来ても上書きしない
    """

    def __init__(self, sound_settings=None):
        self.sound_settings = sound_settings or {
            "base_gain_hh": 0.4,
            "base_gain_sd": 0.3,
            "base_gain_bd": 0.8,
            "dyn_gain": {0: 0.0, 1: 0.4, 2: 0.8, 3: 1.1},
        }

        # サンプルレート（WAV も基本この SR を想定）
        self.sample_rate = 44100

        # 各楽器の WAV サンプル（外部読み込み用）
        self.wav_hh = None
        self.wav_sd = None
        self.wav_bd = None

        # simpleaudio で polyphonic 再生するためのハンドル
        self.active_voices = []  # ← 再生中オブジェクトを保持（上書きしない）

        # 内蔵合成（WAV が無い時のバックアップ音源）
        self._build_internal_synth()

    # -----------------------------------------------------------
    # WAV 読み込み
    # -----------------------------------------------------------
    def load_wav(self, path: str, target: str):
        """
        target : "HH", "SD", "BD"
        """
        if not os.path.isfile(path):
            print(f"[ERROR] WAV not found: {path}")
            return

        with wave.open(path, "rb") as wf:
            sr = wf.getframerate()
            if sr != self.sample_rate:
                print(
                    f"[WARN] WAV {path} has different sample rate ({sr}), "
                    f"expected {self.sample_rate}. ピッチを変えずのリサンプルは未実装です。"
                )
            frames = wf.readframes(wf.getnframes())
            data = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
            data /= 32767.0  # 正規化（-1.0〜1.0）

        if target.upper() == "HH":
            self.wav_hh = data
        elif target.upper() == "SD":
            self.wav_sd = data
        elif target.upper() == "BD":
            self.wav_bd = data

        print(f"[INFO] Loaded WAV for {target}: {path}")

    # -----------------------------------------------------------
    # 内蔵シンセ（WAV が無い場合の fallback）
    # -----------------------------------------------------------
    def _build_internal_synth(self):
        """
        内蔵音源を作る。
        - HH / SD：0.2 秒ぐらいのノイズ＋エンベロープ
        - BD：0.35〜0.4 秒の低音キック（ピッチダウン＋ADSR）
        """

        # ---- HH / SD 共通の時間軸（0.2 秒くらい）
        t = np.linspace(0, 0.2, int(self.sample_rate * 0.2), endpoint=False)

        # ハイハット（ノイズ＋速い減衰）
        noise_hh = np.random.uniform(-1, 1, len(t))
        env_hh = np.exp(-t * 60.0)  # かなり速く減衰
        self.internal_hh = (noise_hh * env_hh * 0.5).astype(np.float32)

        # スネア（ノイズ＋少しゆっくり目の減衰）
        noise_sd = np.random.uniform(-1, 1, len(t))
        env_sd = np.exp(-t * 35.0)
        self.internal_sd = (noise_sd * env_sd * 0.6).astype(np.float32)

        # ---- BD 用の時間軸（0.35〜0.4 秒）
        bd_duration = 0.38  # 固定長（テンポ・音価に依存しない）
        n_bd = int(self.sample_rate * bd_duration)
        t_bd = np.linspace(0, bd_duration, n_bd, endpoint=False)

        # キックの基音周波数（かなり低め）
        f_start = 90.0   # 最初ちょっと高め
        f_end = 50.0     # 少し低く下がる
        # 線形に周波数を落としていく（軽いピッチダウン）
        freq_env = np.linspace(f_start, f_end, n_bd)

        # 周波数→位相積分
        phase = 2.0 * np.pi * np.cumsum(freq_env) / self.sample_rate
        tone = np.sin(phase)

        # 簡易 ADSR エンベロープ
        attack_time = 0.005   # 5 ms
        decay_time = 0.15     # 150 ms
        sustain_level = 0.35
        release_time = bd_duration - (attack_time + decay_time)
        if release_time < 0:
            release_time = 0.05  # 万一マイナスなら最低 50ms は確保

        attack_samps = int(self.sample_rate * attack_time)
        decay_samps = int(self.sample_rate * decay_time)
        release_samps = n_bd - attack_samps - decay_samps
        if release_samps < 0:
            release_samps = 0

        env_bd = np.zeros(n_bd, dtype=np.float32)

        # Attack
        if attack_samps > 0:
            env_bd[:attack_samps] = np.linspace(0.0, 1.0, attack_samps, endpoint=False)
        # Decay
        if decay_samps > 0:
            env_bd[attack_samps:attack_samps + decay_samps] = np.linspace(
                1.0, sustain_level, decay_samps, endpoint=False
            )
        # Release
        if release_samps > 0:
            env_bd[attack_samps + decay_samps:] = np.linspace(
                sustain_level, 0.0, release_samps, endpoint=False
            )

        bd = tone * env_bd

        # ちょっとだけクリップ防止のために余裕を持たせる
        self.internal_bd = (bd * 0.9).astype(np.float32)

    # -----------------------------------------------------------
    # 1音鳴らす（polyphonic）
    # -----------------------------------------------------------
    def _play_sample(self, waveform: np.ndarray, volume: float):
        """
        simpleaudio を使って polyphonic に再生する
        """
        if waveform is None:
            return

        # 音量調整
        w = waveform * volume
        w = np.clip(w, -1.0, 1.0)
        w16 = (w * 32767).astype(np.int16)

        play_obj = sa.play_buffer(
            w16,
            num_channels=1,
            bytes_per_sample=2,
            sample_rate=self.sample_rate,
        )

        # 再生オブジェクトを保持 → 上書きせず、自然減衰に任せる
        self.active_voices.append(play_obj)

        # 終了したものを間引いてもいい（メモリ対策）※任意
        alive = []
        for obj in self.active_voices:
            if obj.is_playing():
                alive.append(obj)
        self.active_voices = alive

    # -----------------------------------------------------------
    # 発音（毎ステップ呼び出される）
    # -----------------------------------------------------------
    def play_combo(self, hh_level, sd_level, bd_level):
        """
        ● 休符では発音を止めない
        ● 各楽器は新しい音が来たらその都度 polyphonic で重ねる
        """

        dyn_gain = self.sound_settings["dyn_gain"]

        # ハイハット
        if hh_level > 0:
            vol = self.sound_settings["base_gain_hh"] * dyn_gain.get(hh_level, 1.0)
            if self.wav_hh is not None:
                self._play_sample(self.wav_hh, vol)
            else:
                self._play_sample(self.internal_hh, vol)

        # スネア
        if sd_level > 0:
            vol = self.sound_settings["base_gain_sd"] * dyn_gain.get(sd_level, 1.0)
            if self.wav_sd is not None:
                self._play_sample(self.wav_sd, vol)
            else:
                self._play_sample(self.internal_sd, vol)

        # バスドラム
        if bd_level > 0:
            vol = self.sound_settings["base_gain_bd"] * dyn_gain.get(bd_level, 1.0)
            if self.wav_bd is not None:
                # 外部 WAV を使う場合も、長さはそのまま・ピッチもそのまま
                self._play_sample(self.wav_bd, vol)
            else:
                self._play_sample(self.internal_bd, vol)

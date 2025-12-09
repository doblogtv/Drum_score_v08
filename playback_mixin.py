# playback_mixin.py
import winsound


class PlaybackMixin:
    """
    再生制御まわりの処理をまとめた Mixin。
    DrumApp 側に以下の属性がある前提：
      - self.root
      - self.score
      - self.synth
      - self.loop_var (tk.BooleanVar)
      - self.is_playing
      - self.current_step
      - self.play_after_id
      - self.play_button
      - self.track_mute_vars
      - highlight_step / clear_highlight (ScoreDrawMixin 側で提供)
    """

    # ----------------------------
    # 強弱記号 → レベル変換
    # ----------------------------
    def dynamic_to_level(self, dyn: str) -> int:
        if dyn in ("pp", "p"):
            return 1
        if dyn in ("mp", "mf"):
            return 2
        if dyn in ("f", "ff"):
            return 3
        return 2

    # ----------------------------
    # 再生関連
    # ----------------------------
    def on_play_button(self):
        if self.is_playing:
            self.stop_playback()
        else:
            self.start_playback_from_beginning()

    def start_playback_from_beginning(self):
        if self.play_after_id is not None:
            try:
                self.root.after_cancel(self.play_after_id)
            except Exception:
                pass
            self.play_after_id = None

        self.is_playing = True
        self.current_step = 0
        self.play_button.config(text="■ 停止")
        print("[INFO] Start playback.")
        self.clear_highlight()
        winsound.PlaySound(None, 0)

        self.play_step()
        self.schedule_next_step()

    def stop_playback(self, silent: bool = False):
        if self.play_after_id is not None:
            try:
                self.root.after_cancel(self.play_after_id)
            except Exception:
                pass
            self.play_after_id = None

        self.is_playing = False
        self.play_button.config(text="▶ 再生")
        self.clear_highlight()
        winsound.PlaySound(None, 0)
        if not silent:
            print("[INFO] Stop playback.")

    def schedule_next_step(self):
        if not self.is_playing:
            return
        step_ms = int(60_000 / (self.score.tempo * self.score.pulses_per_beat))
        self.play_after_id = self.root.after(step_ms, self.advance_step)

    def advance_step(self):
        if not self.is_playing:
            return

        self.current_step += 1
        if self.current_step >= self.score.total_steps:
            if self.loop_var.get():
                self.current_step = 0
            else:
                print("[INFO] Playback finished.")
                self.stop_playback(silent=True)
                return

        self.play_step()
        self.schedule_next_step()

    def play_step(self):
        step = self.current_step
        self.highlight_step(step)

        hh_level = 0
        sd_level = 0
        bd_level = 0

        for i, track in enumerate(self.score.tracks):
            if i >= 3:
                break

            level = 0
            for ev in track.events:
                if ev.symbol == "rest":
                    continue
                if ev.start_step == step:
                    level = self.dynamic_to_level(ev.dynamic)
                    break

            mute_var = self.track_mute_vars.get(track.name)
            if mute_var is not None and mute_var.get():
                level = 0

            if i == 0:
                hh_level = level
            elif i == 1:
                sd_level = level
            elif i == 2:
                bd_level = level

        if hh_level == 0 and sd_level == 0 and bd_level == 0:
            return

        self.synth.play_combo(hh_level, sd_level, bd_level)

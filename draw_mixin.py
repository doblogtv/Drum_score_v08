# draw_mixin.py
import tkinter as tk
from typing import List


class ScoreDrawMixin:
    """
    スコア描画とハイライトまわりの処理をまとめた Mixin。
    DrumApp 側に以下の属性がある前提：
      - self.canvas
      - self.score
      - self.window_width, self.window_height
      - self.margin_left, self.margin_right, self.margin_top, self.margin_bottom
      - self.TIME_AREA_WIDTH
      - self.track_mute_buttons
      - self.current_filename
    """

    def redraw_all(self):
        # 以前のミュートボタンを削除
        for btn in self.track_mute_buttons:
            try:
                btn.destroy()
            except Exception:
                pass
        self.track_mute_buttons.clear()

        self.canvas.delete("all")
        self.draw_bar_grid()
        self.draw_tracks()

    # ----------------------------
    # 音符種別判定
    # ----------------------------
    def _classify_note_type(self, length_steps: int) -> str:
        ppb = self.score.pulses_per_beat
        if ppb <= 0:
            return "quarter"

        ratio = length_steps / ppb

        if ratio >= 3.5:
            return "whole"
        elif ratio >= 1.5:
            return "half"
        elif ratio >= 0.75:
            return "quarter"
        elif ratio >= 0.375:
            return "eighth"
        elif ratio >= 0.1875:
            return "sixteenth"
        elif ratio >= 0.09375:
            return "thirtysecond"
        else:
            return "sixtyfourth"

    # ----------------------------
    # 音符記号の描画
    # ----------------------------
    def _draw_note_symbol(self, x_left: float, y: float,
                          length_steps: int, step_width: float,
                          dynamic: str = "mf"):
        note_type = self._classify_note_type(length_steps)

        head_w = min(step_width * 0.8, 18)
        head_h = head_w * 0.7
        head_x_center = x_left + head_w * 0.6
        head_y_center = y

        if note_type == "whole":
            self.canvas.create_oval(
                head_x_center - head_w / 2,
                head_y_center - head_h / 2,
                head_x_center + head_w / 2,
                head_y_center + head_h / 2,
                fill="white",
                outline="black",
                width=2,
            )
            if dynamic != "mf":
                self.canvas.create_text(
                    head_x_center,
                    head_y_center - head_h * 1.5,
                    text=dynamic,
                    font=("Arial", 8),
                    fill="black",
                )
            return

        if note_type == "half":
            fill_color = "white"
        else:
            fill_color = "black"

        self.canvas.create_oval(
            head_x_center - head_w / 2,
            head_y_center - head_h / 2,
            head_x_center + head_w / 2,
            head_y_center + head_h / 2,
            fill=fill_color,
            outline="black",
            width=2,
        )

        stem_height = head_h * 3.0
        stem_x = head_x_center + head_w * 0.45
        stem_y_top = head_y_center - stem_height
        stem_y_bottom = head_y_center

        self.canvas.create_line(
            stem_x,
            stem_y_bottom,
            stem_x,
            stem_y_top,
            width=2,
            fill="black",
        )

        if note_type == "quarter":
            n_flags = 0
        elif note_type == "eighth":
            n_flags = 1
        elif note_type == "sixteenth":
            n_flags = 2
        elif note_type == "thirtysecond":
            n_flags = 3
        else:
            n_flags = 4

        flag_length = head_w * 1.1
        for i in range(n_flags):
            offset = i * (head_h * 0.4)
            y0 = stem_y_top + offset
            y1 = y0 + head_h * 0.4
            x0 = stem_x
            x1 = stem_x + flag_length
            self.canvas.create_line(
                x0,
                y0,
                x1,
                y1,
                width=2,
                fill="black",
            )

        if dynamic != "mf":
            self.canvas.create_text(
                head_x_center,
                head_y_center - head_h * 1.5,
                text=dynamic,
                font=("Arial", 8, "normal"),
                fill="black",
            )

    # ----------------------------
    # 休符記号の描画
    # ----------------------------
    def _draw_rest_symbol(self, x_left: float, y: float,
                          length_steps: int, step_width: float):
        note_type = self._classify_note_type(length_steps)

        span = length_steps * step_width
        cx = x_left + span * 0.5

        base = min(step_width * 1.4, 22)
        h = base * 0.9

        line_y = y

        if note_type == "whole":
            rect_w = base * 0.9
            rect_h = h * 0.45

            self.canvas.create_line(
                cx - rect_w * 0.8,
                line_y,
                cx + rect_w * 0.8,
                line_y,
                width=2,
                fill="black",
            )
            self.canvas.create_rectangle(
                cx - rect_w * 0.5,
                line_y,
                cx + rect_w * 0.5,
                line_y + rect_h,
                fill="black",
                outline="black",
            )
            return

        if note_type == "half":
            rect_w = base * 0.9
            rect_h = h * 0.45

            self.canvas.create_line(
                cx - rect_w * 0.8,
                line_y,
                cx + rect_w * 0.8,
                line_y,
                width=2,
                fill="black",
            )
            self.canvas.create_rectangle(
                cx - rect_w * 0.5,
                line_y - rect_h,
                cx + rect_w * 0.5,
                line_y,
                fill="black",
                outline="black",
            )
            return

        if note_type == "quarter":
            top_y = line_y - h * 0.9
            mid1_y = line_y - h * 0.25
            mid2_y = line_y + h * 0.15
            bottom_y = line_y + h * 0.9

            x0 = cx - base * 0.25
            x1 = cx + base * 0.05
            x2 = cx - base * 0.15
            x3 = cx + base * 0.22

            self.canvas.create_line(x0, top_y, x1, mid1_y, width=2)
            self.canvas.create_line(x1, mid1_y, x2, mid2_y, width=2)
            self.canvas.create_line(x2, mid2_y, x3, bottom_y, width=2)
            return

        top_y = line_y - h * 0.9
        mid1_y = line_y - h * 0.25
        mid2_y = line_y + h * 0.10
        bottom_y = line_y + h * 0.7

        x0 = cx - base * 0.23
        x1 = cx + base * 0.05
        x2 = cx - base * 0.12
        x3 = cx + base * 0.20

        self.canvas.create_line(x0, top_y, x1, mid1_y, width=2)
        self.canvas.create_line(x1, mid1_y, x2, mid2_y, width=2)
        self.canvas.create_line(x2, mid2_y, x3, bottom_y, width=2)

        if note_type == "eighth":
            n_flags = 1
        elif note_type == "sixteenth":
            n_flags = 2
        elif note_type == "thirtysecond":
            n_flags = 3
        else:
            n_flags = 4

        r = base * 0.13
        flag_x = x0
        start_y = top_y - r * 0.4
        gap = r * 1.45

        for i in range(n_flags):
            cy = start_y + i * gap
            self.canvas.create_oval(
                flag_x - r,
                cy - r,
                flag_x + r,
                cy + r,
                fill="black",
                outline="black",
            )

    # ----------------------------
    # グリッド・トラック描画
    # ----------------------------
    def draw_bar_grid(self):
        time_area_width = self.TIME_AREA_WIDTH

        x0 = self.margin_left + time_area_width
        x1 = self.window_width - self.margin_right
        y_top = self.margin_top
        y_bottom = self.window_height - self.margin_bottom

        self.canvas.create_line(x0, y_top, x1, y_top, width=2)
        self.canvas.create_line(x0, y_bottom, x1, y_bottom, width=2)

        bar_width = x1 - x0
        total_steps = self.score.total_steps
        if total_steps <= 0:
            return
        step_width = bar_width / total_steps

        bar_steps = self.score.bar_steps
        pulses = self.score.pulses_per_beat
        bars = self.score.bars

        # ステップごとの縦線（拍・小節を強調）
        for step in range(total_steps + 1):
            x = x0 + step * step_width
            if bar_steps > 0 and step % bar_steps == 0:
                self.canvas.create_line(x, y_top, x, y_bottom, width=3, fill="#000000")
            elif pulses > 0 and step % pulses == 0:
                self.canvas.create_line(x, y_top, x, y_bottom, width=1, fill="#888888")
            else:
                self.canvas.create_line(x, y_top, x, y_bottom, width=1, fill="#eeeeee")

        beats_per_bar = self.score.beats_per_bar

        mid_x = (x0 + x1) / 2
        title_y = y_top - 60
        filename_y = y_top - 42

        if self.score.title:
            self.canvas.create_text(
                mid_x,
                title_y,
                text=self.score.title,
                font=("Arial", 14, "bold"),
            )
            if self.current_filename:
                self.canvas.create_text(
                    mid_x,
                    filename_y,
                    text=self.current_filename,
                    font=("Arial", 9),
                    fill="#555555",
                )
        else:
            if self.current_filename:
                self.canvas.create_text(
                    mid_x,
                    title_y,
                    text=self.current_filename,
                    font=("Arial", 11, "bold"),
                    fill="#555555",
                )

        # 拍カウント
        for bar_index in range(bars):
            for beat in range(beats_per_bar):
                step_index = bar_index * bar_steps + (beat + 0.5) * pulses
                if step_index > total_steps:
                    continue
                beat_x = x0 + step_index * step_width
                self.canvas.create_text(
                    beat_x, y_top - 18, text=str(beat + 1), font=("Arial", 10)
                )

        # 小節番号
        for bar_index in range(bars):
            bar_start_step = bar_index * bar_steps
            bar_end_step = min((bar_index + 1) * bar_steps, total_steps)
            bar_center_step = (bar_start_step + bar_end_step) / 2
            bar_x = x0 + bar_center_step * step_width
            self.canvas.create_text(
                bar_x,
                y_top - 30,
                text=f"Bar {bar_index + 1}",
                font=("Arial", 9, "bold"),
                fill="#444444",
            )

        num, den = self.score.time_signature

        ts_x = self.margin_left + 25
        ts_center_y = (y_top + y_bottom) / 2
        self.canvas.create_text(ts_x, ts_center_y - 10, text=str(num), font=("Arial", 16, "bold"))
        self.canvas.create_text(ts_x, ts_center_y + 10, text=str(den), font=("Arial", 16, "bold"))

        n_tracks = len(self.score.tracks)
        for i, _track in enumerate(self.score.tracks):
            ratio = (i + 1) / (n_tracks + 1) if n_tracks > 0 else 0.5
            y = y_top + (y_bottom - y_top) * ratio
            self.canvas.create_line(x0, y, x1, y, width=1, dash=(2, 4), fill="#dddddd")

        tempo_text = (
            f"TEMPO={self.score.tempo}, "
            f"PULSES={self.score.pulses_per_beat}, "
            f"STEPS={self.score.total_steps}, "
            f"BARS={self.score.bars}"
        )
        self.canvas.create_text(
            mid_x,
            y_bottom + 25,
            text=tempo_text,
            font=("Arial", 10),
        )

    def draw_tracks(self):
        time_area_width = self.TIME_AREA_WIDTH
        x0 = self.margin_left + time_area_width
        x1 = self.window_width - self.margin_right
        y_top = self.margin_top
        y_bottom = self.window_height - self.margin_bottom

        bar_width = x1 - x0
        total_steps = self.score.total_steps
        if total_steps <= 0:
            return
        step_width = bar_width / total_steps

        n_tracks = len(self.score.tracks)

        track_ctrl_x = self.margin_left + time_area_width - 5

        for t_index, track in enumerate(self.score.tracks):
            if n_tracks > 0:
                ratio = (t_index + 1) / (n_tracks + 1)
            else:
                ratio = 0.5
            y = y_top + (y_bottom - y_top) * ratio

            var = self.track_mute_vars.get(track.name)
            if var is None:
                var = tk.BooleanVar(value=False)
                self.track_mute_vars[track.name] = var
            chk = tk.Checkbutton(
                self.canvas,
                text=track.name,
                variable=var,
                anchor="w",
                padx=0,
                pady=0,
            )
            self.track_mute_buttons.append(chk)
            self.canvas.create_window(
                track_ctrl_x,
                y,
                window=chk,
                anchor="e",
            )

            for ev in track.events:
                x_left = x0 + ev.start_step * step_width
                x_right = x0 + (ev.start_step + ev.length_steps) * step_width

                self.canvas.create_line(
                    x_left,
                    y,
                    x_right,
                    y,
                    width=4,
                    fill="#dddddd" if ev.symbol == "rest" else "#cccccc",
                )

                if ev.symbol == "rest":
                    self._draw_rest_symbol(
                        x_left=x_left,
                        y=y,
                        length_steps=ev.length_steps,
                        step_width=step_width,
                    )
                else:
                    self._draw_note_symbol(
                        x_left=x_left,
                        y=y,
                        length_steps=ev.length_steps,
                        step_width=step_width,
                        dynamic=ev.dynamic,
                    )

    # ----------------------------
    # ハイライト
    # ----------------------------
    def highlight_step(self, step_index: int):
        self.clear_highlight()

        time_area_width = self.TIME_AREA_WIDTH
        x0 = self.margin_left + time_area_width
        x1 = self.window_width - self.margin_right
        y_top = self.margin_top
        y_bottom = self.window_height - self.margin_bottom

        bar_width = x1 - x0
        total_steps = self.score.total_steps
        if total_steps <= 0:
            return
        step_width = bar_width / total_steps

        x_left = x0 + step_index * step_width
        x_right = x_left + step_width

        self.highlight_line_id = self.canvas.create_rectangle(
            x_left,
            y_top,
            x_right,
            y_bottom,
            fill="#ffeeaa",
            outline="",
        )

    def clear_highlight(self):
        if getattr(self, "highlight_line_id", None) is not None:
            self.canvas.delete(self.highlight_line_id)
            self.highlight_line_id = None

# gui_app.py
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional, Dict, List
import os
import json

from score import Score
from synth import DrumSynth
from exporter import render_score_to_wav  # ★ 追加：WAV出力専用モジュール

APP_VERSION = "0.7"
CONFIG_FILE = os.path.join(os.getcwd(), "drum_app_config.json")


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(config: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class DrumApp:
    TIME_AREA_WIDTH = 90  # TIME表記＋トラック名＋ミュートエリア

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"Drum Score Player v{APP_VERSION}")

        self.config_data = load_config()

        # 保存ディレクトリ（テキスト譜）
        default_data_dir = os.path.join(os.getcwd(), "data")
        self.save_dir = self.config_data.get("save_dir", default_data_dir)
        os.makedirs(self.save_dir, exist_ok=True)

        # ムービー出力ディレクトリ
        default_movie_dir = os.path.join(os.getcwd(), "Mov")
        self.movie_output_dir = self.config_data.get("movie_output_dir", default_movie_dir)
        os.makedirs(self.movie_output_dir, exist_ok=True)

        # ループ収録回数（ムービー出力・WAV出力用）
        self.loop_record_count: int = int(self.config_data.get("loop_record_count", 1))

        self.window_width = 800
        self.window_height = 380

        self.margin_left = 20
        self.margin_right = 40
        # ★ タイトルが上に切れないように全体の描画位置を少し下げる
        self.margin_top = 100
        self.margin_bottom = 80  # 下にテンポ表示用のスペース

        # 再生制御
        self.is_playing = False
        self.current_step = 0
        self.highlight_line_id = None
        self.play_after_id: Optional[str] = None

        # ループON/OFF
        self.loop_var = tk.BooleanVar(value=False)

        # Score とサウンド設定
        self.score: Score = Score.create_default_score()
        self.sound_settings = self.config_data.get(
            "sound_settings",
            {
                "base_gain_hh": 0.4,
                "base_gain_sd": 0.3,
                "base_gain_bd": 0.8,
                "dyn_gain": {
                    0: 0.0,
                    1: 0.4,
                    2: 0.8,
                    3: 1.1,
                },
            },
        )

        # ドラムシンセ
        self.synth = DrumSynth(sound_settings=self.sound_settings)

        # 最後に読み込んだファイルパス
        self.last_filepath: Optional[str] = self.config_data.get("last_file")

        # 画面上に表示する現在のファイル名（タイトルの下に表示）
        self.current_filename: Optional[str] = None

        # テキスト貼り付けウインドウ
        self.text_input_window: Optional[tk.Toplevel] = None
        self.text_input_text: Optional[tk.Text] = None

        # トラック毎ミュート
        self.track_mute_vars: Dict[str, tk.BooleanVar] = {}
        self.track_mute_buttons: List[tk.Checkbutton] = []
        self.rebuild_track_mute_vars()

        # geometry 復元
        main_geo = self.config_data.get("main_geometry")
        if main_geo:
            self.root.geometry(main_geo)
        else:
            self.root.geometry(f"{self.window_width}x{self.window_height}+100+100")

        # GUI 構築
        self._build_gui()

        # テキスト譜ウインドウは常時表示
        self.open_text_input_window()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.redraw_all()

    # ----------------------------
    # トラックミュート用 BooleanVar 再構築
    # ----------------------------
    def rebuild_track_mute_vars(self):
        new_vars: Dict[str, tk.BooleanVar] = {}
        for track in self.score.tracks:
            if track.name in self.track_mute_vars:
                new_vars[track.name] = self.track_mute_vars[track.name]
            else:
                new_vars[track.name] = tk.BooleanVar(value=False)
        self.track_mute_vars = new_vars

    # ----------------------------
    # GUI セットアップ
    # ----------------------------
    def _build_gui(self):
        top_frame = tk.Frame(self.root)
        top_frame.pack(side=tk.TOP, fill=tk.X, pady=5)

        self.play_button = tk.Button(top_frame, text="▶ 再生", command=self.on_play_button)
        self.play_button.pack(side=tk.LEFT, padx=5)

        load_button = tk.Button(top_frame, text="📂 ファイルから読み込み", command=self.on_load_button)
        load_button.pack(side=tk.LEFT, padx=5)

        loop_check = tk.Checkbutton(
            top_frame,
            text="Loop 再生",
            variable=self.loop_var,
        )
        loop_check.pack(side=tk.LEFT, padx=5)

        # ★ WAV 出力ボタン（オフライン合成）
        wav_button = tk.Button(top_frame, text="🎧 WAV出力", command=self.on_export_wav)
        wav_button.pack(side=tk.LEFT, padx=5)

        # 🎬 ムービー出力ボタン（現状はスタブのまま）
        export_button = tk.Button(top_frame, text="🎬 出力", command=self.on_export_movie)
        export_button.pack(side=tk.LEFT, padx=5)

        settings_button = tk.Button(top_frame, text="⚙ 設定", command=self.open_settings_window)
        settings_button.pack(side=tk.LEFT, padx=5)

        self.info_label = tk.Label(
            top_frame,
            text="Ready",
        )
        self.info_label.pack(side=tk.LEFT, padx=15)

        self.canvas = tk.Canvas(
            self.root,
            width=self.window_width,
            height=self.window_height,
            bg="white",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self.on_canvas_resize)

    # ----------------------------
    # キャンバスサイズ変更
    # ----------------------------
    def on_canvas_resize(self, event):
        if event.width > 100:
            self.window_width = event.width
        if event.height > 100:
            self.window_height = event.height
        self.redraw_all()

    # ----------------------------
    # テキスト貼り付けウインドウ
    # ----------------------------
    def open_text_input_window(self):
        if self.text_input_window is not None and tk.Toplevel.winfo_exists(self.text_input_window):
            self.text_input_window.lift()
            return

        win = tk.Toplevel(self.root)
        self.text_input_window = win
        win.title("テキスト譜")

        text_geo = self.config_data.get("text_geometry")
        if text_geo:
            win.geometry(text_geo)
        else:
            win.geometry("600x400+950+100")

        # 上に「読み込み」ボタン
        btn_frame = tk.Frame(win)
        btn_frame.pack(side=tk.TOP, fill=tk.X)
        load_btn = tk.Button(btn_frame, text="読み込み", command=self.on_text_input_load)
        load_btn.pack(side=tk.LEFT, padx=5, pady=5)

        # テキストエリア
        text_widget = tk.Text(win, wrap="none")
        text_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.text_input_text = text_widget

        # 閉じるボタンは無効化（常時表示）
        def ignore_close():
            pass

        win.protocol("WM_DELETE_WINDOW", ignore_close)

    def on_text_input_load(self):
        if self.text_input_text is None:
            return

        text = self.text_input_text.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("情報", "テキストが空です。")
            return

        # FILENAME= からファイル名を拾う
        filename = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("FILENAME="):
                filename = line.split("=", 1)[1].strip()
                if filename:
                    break

        filepath = None
        if filename:
            if not filename.lower().endswith(".txt"):
                filename += ".txt"
            try:
                os.makedirs(self.save_dir, exist_ok=True)
            except Exception:
                pass
            filepath = os.path.join(self.save_dir, filename)
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(text)
                print(f"[INFO] Text score saved to file: {filepath}")
            except Exception as e:
                messagebox.showerror("保存エラー", f"テキストファイルの保存に失敗しました。\n{e}")
                filepath = None

        try:
            score = Score.from_text(text)
        except Exception as e:
            print("[ERROR] Score Load Failed (Text Input)")
            print(e)
            messagebox.showerror("読み込みエラー", f"譜面の読み込みに失敗しました。\n{e}")
            return

        self.score = score
        self.rebuild_track_mute_vars()
        self.stop_playback(silent=True)

        if filepath:
            filename_only = os.path.basename(filepath)
            self.info_label.config(text=f"読み込み: {filename_only}")
            self.last_filepath = filepath
            self.current_filename = filename_only
        else:
            disp = self.score.title if self.score.title else "(テキスト入力)"
            self.info_label.config(text=f"読み込み: {disp}")
            # FILENAME= が無い場合はファイル名表示なし
            self.current_filename = None

        self.redraw_all()

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
    # 描画系
    # ----------------------------
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
                # 小節線（太く）
                self.canvas.create_line(x, y_top, x, y_bottom, width=3, fill="#000000")
            elif pulses > 0 and step % pulses == 0:
                # 拍線（中くらい）
                self.canvas.create_line(x, y_top, x, y_bottom, width=1, fill="#888888")
            else:
                # 細かいグリッド
                self.canvas.create_line(x, y_top, x, y_bottom, width=1, fill="#eeeeee")

        beats_per_bar = self.score.beats_per_bar

        # 上部中央タイトル＆ファイル名
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

        # 拍カウント（各小節ごとに 1〜拍数）
        for bar_index in range(bars):
            for beat in range(beats_per_bar):
                step_index = bar_index * bar_steps + (beat + 0.5) * pulses
                if step_index > total_steps:
                    continue
                beat_x = x0 + step_index * step_width
                self.canvas.create_text(
                    beat_x, y_top - 18, text=str(beat + 1), font=("Arial", 10)
                )

        # 小節番号（Bar 1, Bar 2, ...）→ 拍カウントより少し下
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

        # TIME 表記は左エリアの左側に固定
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

        # ミュートボタン＋トラック名を TIMEエリアの右側に配置
        track_ctrl_x = self.margin_left + time_area_width - 5  # 右寄せ

        for t_index, track in enumerate(self.score.tracks):
            if n_tracks > 0:
                ratio = (t_index + 1) / (n_tracks + 1)
            else:
                ratio = 0.5
            y = y_top + (y_bottom - y_top) * ratio

            # ミュートボタン＋トラック名（Checkbuttonのtextにトラック名）
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
            # キャンバスに埋め込み
            self.canvas.create_window(
                track_ctrl_x,
                y,
                window=chk,
                anchor="e",  # 右側で揃える
            )

            # イベント描画
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
        import winsound
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
        import winsound
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

            # ミュート適用
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
        if self.highlight_line_id is not None:
            self.canvas.delete(self.highlight_line_id)
            self.highlight_line_id = None

    # ----------------------------
    # ファイル読み込み
    # ----------------------------
    def on_load_button(self):
        initial_dir = None
        if self.last_filepath:
            initial_dir = os.path.dirname(self.last_filepath)
        elif os.path.isdir(self.save_dir):
            initial_dir = self.save_dir

        filepath = filedialog.askopenfilename(
            title="テキスト譜ファイルを選択（v3 数値音価）",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=initial_dir if initial_dir else None,
        )
        if not filepath:
            return

        print(f"[INFO] Loading score from file: {filepath}")

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()
            # テキスト譜ウインドウにも内容を反映
            if self.text_input_text is not None:
                self.text_input_text.delete("1.0", "end")
                self.text_input_text.insert("1.0", text)

            score = Score.from_text(text)
        except Exception as e:
            print("[ERROR] Score Load Failed (File)")
            print(e)
            messagebox.showerror("読み込みエラー", f"譜面の読み込みに失敗しました。\n{e}")
            return

        self.score = score
        self.rebuild_track_mute_vars()
        self.stop_playback(silent=True)

        filename_only = os.path.basename(filepath)
        display_title = score.title if score.title else filename_only

        self.info_label.config(text=f"読み込み: {display_title}")
        self.last_filepath = filepath
        self.current_filename = filename_only

        self.redraw_all()

    # ----------------------------
    # WAV 出力（オフライン合成）
    # ----------------------------
    def on_export_wav(self):
        if self.is_playing:
            messagebox.showinfo("情報", "再生中はWAV出力できません。停止してから実行してください。")
            return

        # 保存先ファイル名の初期値
        if self.current_filename:
            base, _ = os.path.splitext(self.current_filename)
            default_name = base + ".wav"
        elif self.score.title:
            base = self.score.title.replace(" ", "_")
            default_name = base + ".wav"
        else:
            default_name = "drum_score.wav"

        initial_dir = self.movie_output_dir if os.path.isdir(self.movie_output_dir) else os.getcwd()

        filepath = filedialog.asksaveasfilename(
            title="WAVファイルとして保存",
            initialdir=initial_dir,
            initialfile=default_name,
            defaultextension=".wav",
            filetypes=[("WAV files", "*.wav"), ("All files", "*.*")],
        )
        if not filepath:
            return

        try:
            render_score_to_wav(
                score=self.score,
                synth=self.synth,
                filepath=filepath,
                loop_count=self.loop_record_count if self.loop_record_count > 0 else 1,
            )
            messagebox.showinfo("情報", f"WAVを保存しました。\n{filepath}")
        except Exception as e:
            print("[ERROR] WAV export failed.")
            print(e)
            messagebox.showerror("エラー", f"WAV出力に失敗しました。\n{e}")

    # ----------------------------
    # ムービー出力（スタブ）
    # ----------------------------
    def on_export_movie(self):
        """
        ここでは UI だけ実装。
        実際のムービー出力は、今後 exporter.py 側に
        機能を追加していく想定。
        """
        if self.is_playing:
            messagebox.showinfo("情報", "再生中はムービー出力できません。停止してから実行してください。")
            return

        msg = (
            "ムービー出力機能は、現在 UI と設定項目だけ実装された状態です。\n\n"
            "・出力先フォルダ: \n"
            f"    {self.movie_output_dir}\n"
            f"・Loop 再生回数（予定）: {self.loop_record_count} 回分\n\n"
            "実際に動画を書き出すには、\n"
            " 1) exporter.py 側でオフライン描画＋音声mux処理を実装\n"
            " 2) Canvas をフレームごとに画像として保存\n"
            " 3) moviepy などで音声と合成\n"
            "が必要なので、次のステップで一緒に詰めていきましょう。"
        )
        print("[INFO] Movie export requested (stub only).")
        messagebox.showinfo("ムービー出力（未実装）", msg)

    # ----------------------------
    # 設定ウインドウ
    # ----------------------------
    def open_settings_window(self):
        win = tk.Toplevel(self.root)
        win.title("設定")

        hh_gain = tk.DoubleVar(value=self.sound_settings.get("base_gain_hh", 0.4))
        sd_gain = tk.DoubleVar(value=self.sound_settings.get("base_gain_sd", 0.3))
        bd_gain = tk.DoubleVar(value=self.sound_settings.get("base_gain_bd", 0.8))
        save_dir_var = tk.StringVar(value=self.save_dir)
        movie_dir_var = tk.StringVar(value=self.movie_output_dir)
        loop_record_var = tk.IntVar(value=self.loop_record_count)

        def add_row(label_text, var, row_idx, kind="str"):
            lbl = tk.Label(win, text=label_text)
            lbl.grid(row=row_idx, column=0, padx=5, pady=5, sticky="e")
            if kind == "str":
                ent = tk.Entry(win, textvariable=var, width=30)
            else:
                ent = tk.Entry(win, textvariable=var, width=10)
            ent.grid(row=row_idx, column=1, padx=5, pady=5, sticky="w")
            return ent

        add_row("HH ベースゲイン", hh_gain, 0, kind="str")
        add_row("SD ベースゲイン", sd_gain, 1, kind="str")
        add_row("BD ベースゲイン", bd_gain, 2, kind="str")

        # 保存ディレクトリ
        ent_dir = add_row("譜面保存ディレクトリ", save_dir_var, 3, kind="str")

        def browse_dir():
            cur = save_dir_var.get() or os.getcwd()
            path = filedialog.askdirectory(
                parent=win,
                initialdir=cur,
                title="譜面の保存先フォルダを選択",
            )
            if path:
                save_dir_var.set(path)

        btn_browse = tk.Button(win, text="参照...", command=browse_dir)
        btn_browse.grid(row=3, column=2, padx=5, pady=5)

        # ムービー出力ディレクトリ
        ent_movie = add_row("ムービー出力フォルダ", movie_dir_var, 4, kind="str")

        def browse_movie_dir():
            cur = movie_dir_var.get() or os.getcwd()
            path = filedialog.askdirectory(
                parent=win,
                initialdir=cur,
                title="ムービー出力フォルダを選択",
            )
            if path:
                movie_dir_var.set(path)

        btn_browse_movie = tk.Button(win, text="参照...", command=browse_movie_dir)
        btn_browse_movie.grid(row=4, column=2, padx=5, pady=5)

        # ループ録画回数
        add_row("Loop録画回数（ムービー出力/WAV出力）", loop_record_var, 5, kind="int")

        def on_save():
            try:
                new_hh = float(hh_gain.get())
                new_sd = float(sd_gain.get())
                new_bd = float(bd_gain.get())
            except ValueError:
                messagebox.showerror("エラー", "ベースゲインには数値を入力してください。")
                return

            self.sound_settings["base_gain_hh"] = new_hh
            self.sound_settings["base_gain_sd"] = new_sd
            self.sound_settings["base_gain_bd"] = new_bd

            new_dir = save_dir_var.get().strip()
            if not new_dir:
                new_dir = os.path.join(os.getcwd(), "data")
            self.save_dir = new_dir
            try:
                os.makedirs(self.save_dir, exist_ok=True)
            except Exception:
                pass

            new_movie_dir = movie_dir_var.get().strip()
            if not new_movie_dir:
                new_movie_dir = os.path.join(os.getcwd(), "Mov")
            self.movie_output_dir = new_movie_dir
            try:
                os.makedirs(self.movie_output_dir, exist_ok=True)
            except Exception:
                pass

            try:
                lr = int(loop_record_var.get())
                if lr < 1:
                    lr = 1
            except ValueError:
                lr = 1
            self.loop_record_count = lr

            self.config_data["sound_settings"] = self.sound_settings
            self.config_data["save_dir"] = self.save_dir
            self.config_data["movie_output_dir"] = self.movie_output_dir
            self.config_data["loop_record_count"] = self.loop_record_count
            save_config(self.config_data)

            # サウンド設定を反映
            self.synth.update_params(self.sound_settings)

            messagebox.showinfo("情報", "設定を保存しました。")

        save_btn = tk.Button(win, text="保存", command=on_save)
        save_btn.grid(row=10, column=0, columnspan=3, pady=10)

    # ----------------------------
    # 終了処理
    # ----------------------------
    def on_close(self):
        try:
            self.config_data["main_geometry"] = self.root.winfo_geometry()
            if self.text_input_window is not None:
                self.config_data["text_geometry"] = self.text_input_window.winfo_geometry()
            if self.last_filepath:
                self.config_data["last_file"] = self.last_filepath
            self.config_data["sound_settings"] = self.sound_settings
            self.config_data["save_dir"] = self.save_dir
            self.config_data["movie_output_dir"] = self.movie_output_dir
            self.config_data["loop_record_count"] = self.loop_record_count
            save_config(self.config_data)
        except Exception:
            pass
        print("[INFO] Application closed.")
        self.root.destroy()

# gui_app.py
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional, Dict, List
import os
import json

from score import Score
from synth import DrumSynth
from exporter import render_score_to_wav, render_score_to_movie  # WAV & Movie 出力専用モジュール

# 描画系 / 再生系の Mixin
from draw_mixin import ScoreDrawMixin
from playback_mixin import PlaybackMixin

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


class DrumApp(ScoreDrawMixin, PlaybackMixin):
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
            # タイトルが上に切れないように全体の描画位置を少し下げる
            self.margin_top = 100
            self.margin_bottom = 80  # 下にテンポ表示用のスペース

            # 再生制御
            self.is_playing = False
            self.current_step = 0
            self.highlight_line_id = None
            self.play_after_id: Optional[str] = None

            # ループON/OFF（再生用）→ 設定画面から操作
            loop_playback = bool(self.config_data.get("loop_playback", False))
            self.loop_var = tk.BooleanVar(value=loop_playback)

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

            # カスタムサンプルのパス
            self.sample_paths: Dict[str, str] = self.config_data.get(
                "sample_paths",
                {"HH": "", "SD": "", "BD": ""},
            )

            # ドラムシンセ
            self.synth = DrumSynth(sound_settings=self.sound_settings)
            # （あとで synth.py に update_sample_paths を実装）
            try:
                self.synth.update_sample_paths(self.sample_paths)
            except AttributeError:
                pass

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

            # ※ Loop 再生チェックはここから削除 → 設定画面へ移動

            # WAV 出力ボタン（オフライン合成）
            wav_button = tk.Button(top_frame, text="🎧 WAV出力", command=self.on_export_wav)
            wav_button.pack(side=tk.LEFT, padx=5)

            # ムービー出力ボタン（譜面キャンバスのみ録画）
            export_button = tk.Button(top_frame, text="🎬 出力", command=self.on_export_movie)
            export_button.pack(side=tk.LEFT, padx=5)

            settings_button = tk.Button(top_frame, text="🖊 設定", command=self.open_settings_window)
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
                self.last_filepath = filepath
                self.current_filename = filename_only
            else:
                self.current_filename = None

            # ステータスラベルにはファイル名を出さず、シンプルに
            self.info_label.config(text="読み込み完了")

            self.redraw_all()

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
            self.last_filepath = filepath
            self.current_filename = filename_only

            # ここもファイル名は出さずに
            self.info_label.config(text="読み込み完了")

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
        # ムービー出力（譜面キャンバスのみ）
        # ----------------------------
        def on_export_movie(self):
            """
            ・現在の Score をもとにオフラインで WAV を合成
            ・譜面キャンバスのみをキャプチャしてフレーム列を生成
            ・exporter.render_score_to_movie() で音声と合成して動画を書き出す

            必要ライブラリ:
              pip install pillow moviepy numpy
            """
            if self.is_playing:
                messagebox.showinfo("情報", "再生中はムービー出力できません。停止してから実行してください。")
                return

            # 依存ライブラリのチェック（Pillow）
            try:
                from PIL import ImageGrab
            except ImportError:
                messagebox.showerror(
                    "エラー",
                    "Pillow がインストールされていません。\n\n"
                    "  pip install pillow\n\n"
                    "を実行してから再試行してください。"
                )
                return

            # デフォルト拡張子を .wmv に（WMP で再生しやすい形式）
            if self.current_filename:
                base, _ = os.path.splitext(self.current_filename)
                default_name = base + ".wmv"
            elif self.score.title:
                base = self.score.title.replace(" ", "_")
                default_name = base + ".wmv"
            else:
                default_name = "drum_score_movie.wmv"

            initial_dir = self.movie_output_dir if os.path.isdir(self.movie_output_dir) else os.getcwd()

            movie_path = filedialog.asksaveasfilename(
                title="ムービーを書き出す",
                initialdir=initial_dir,
                initialfile=default_name,
                defaultextension=".wmv",
                filetypes=[
                    ("WMV files", "*.wmv"),
                    ("MP4 files", "*.mp4"),
                    ("AVI files", "*.avi"),
                    ("All files", "*.*"),
                ],
            )
            if not movie_path:
                return

            loop_count = self.loop_record_count if self.loop_record_count > 0 else 1

            # キャンバスのスクリーン座標（ここだけ録画 → メニューバー等は映らない）
            self.root.update_idletasks()
            x = self.canvas.winfo_rootx()
            y = self.canvas.winfo_rooty()
            w = self.canvas.winfo_width()
            h = self.canvas.winfo_height()

            # ffmpeg エラー回避のため width / height を偶数にそろえる
            if w % 2 == 1:
                w -= 1
            if h % 2 == 1:
                h -= 1

            bbox = (x, y, x + w, y + h)

            # capture_frame: step_index -> Image
            def capture_frame(step_index: int):
                self.highlight_step(step_index)
                self.root.update_idletasks()
                self.root.update()
                return ImageGrab.grab(bbox=bbox)

            # 念のため開始前にハイライトを消す
            self.clear_highlight()
            self.root.update_idletasks()
            self.root.update()

            try:
                render_score_to_movie(
                    score=self.score,
                    synth=self.synth,
                    loop_count=loop_count,
                    capture_frame=capture_frame,
                    movie_path=movie_path,
                    fps=30,
                    # Windows Media Player で再生しやすい設定（実際は ffmpeg 環境にも依存）
                    video_codec="wmv2",
                    audio_codec="aac",
                )
            except ImportError as e:
                # moviepy / numpy が無い場合など
                print("[ERROR] Movie export failed (ImportError).")
                print(e)
                messagebox.showerror(
                    "エラー",
                    "ムービー出力に必要なライブラリが不足しています。\n\n"
                    "  pip install moviepy numpy\n\n"
                    "を実行してから再試行してください。"
                )
                return
            except Exception as e:
                print("[ERROR] Movie export failed.")
                print(e)
                messagebox.showerror("エラー", f"ムービー出力中にエラーが発生しました。\n{e}")
                return
            finally:
                # 終了後はハイライトを消す
                self.clear_highlight()
                self.root.update_idletasks()
                self.root.update()

            messagebox.showinfo("情報", f"ムービーを書き出しました。\n{movie_path}")

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

            # カスタムサンプルパス用
            hh_wav_var = tk.StringVar(value=self.sample_paths.get("HH", ""))
            sd_wav_var = tk.StringVar(value=self.sample_paths.get("SD", ""))
            bd_wav_var = tk.StringVar(value=self.sample_paths.get("BD", ""))

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

            # 再生時の Loop チェック（ここへ移動）
            loop_chk = tk.Checkbutton(
                win,
                text="Loop再生（終端で先頭に戻る）",
                variable=self.loop_var,
            )
            loop_chk.grid(row=6, column=1, padx=5, pady=5, sticky="w")

            # 各トラックの WAV ファイル指定
            ent_hh_wav = add_row("HH WAVファイル", hh_wav_var, 7, kind="str")
            ent_sd_wav = add_row("SD WAVファイル", sd_wav_var, 8, kind="str")
            ent_bd_wav = add_row("BD WAVファイル", bd_wav_var, 9, kind="str")

            def browse_wav(var: tk.StringVar):
                cur = var.get() or os.getcwd()
                path = filedialog.askopenfilename(
                    parent=win,
                    initialdir=os.path.dirname(cur) if os.path.isfile(cur) else cur,
                    title="WAVファイルを選択",
                    filetypes=[("WAV files", "*.wav"), ("All files", "*.*")],
                )
                if path:
                    var.set(path)

            btn_browse_hh = tk.Button(win, text="参照...", command=lambda: browse_wav(hh_wav_var))
            btn_browse_hh.grid(row=7, column=2, padx=5, pady=5)

            btn_browse_sd = tk.Button(win, text="参照...", command=lambda: browse_wav(sd_wav_var))
            btn_browse_sd.grid(row=8, column=2, padx=5, pady=5)

            btn_browse_bd = tk.Button(win, text="参照...", command=lambda: browse_wav(bd_wav_var))
            btn_browse_bd.grid(row=9, column=2, padx=5, pady=5)

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

                # カスタムサンプルパスを保存
                self.sample_paths = {
                    "HH": hh_wav_var.get().strip(),
                    "SD": sd_wav_var.get().strip(),
                    "BD": bd_wav_var.get().strip(),
                }

                self.config_data["sound_settings"] = self.sound_settings
                self.config_data["save_dir"] = self.save_dir
                self.config_data["movie_output_dir"] = self.movie_output_dir
                self.config_data["loop_record_count"] = self.loop_record_count
                self.config_data["loop_playback"] = bool(self.loop_var.get())
                self.config_data["sample_paths"] = self.sample_paths
                save_config(self.config_data)

                # サウンド設定を反映
                self.synth.update_params(self.sound_settings)

                # カスタムサンプルも反映（synth.py に実装が必要）
                try:
                    self.synth.update_sample_paths(self.sample_paths)
                except AttributeError:
                    pass

                messagebox.showinfo("情報", "設定を保存しました。")

            save_btn = tk.Button(win, text="保存", command=on_save)
            save_btn.grid(row=12, column=0, columnspan=3, pady=10)

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
                self.config_data["loop_playback"] = bool(self.loop_var.get())
                self.config_data["sample_paths"] = self.sample_paths
                save_config(self.config_data)
            except Exception:
                pass
            print("[INFO] Application closed.")
            self.root.destroy()

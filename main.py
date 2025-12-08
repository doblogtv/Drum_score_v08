import tkinter as tk
from gui_app import DrumApp
from config import APP_VERSION


def main():
    print(f"[INFO] Drum Score Player v{APP_VERSION} starting...")
    root = tk.Tk()
    app = DrumApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

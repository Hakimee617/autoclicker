# -*- coding: utf-8 -*-
"""
dianji.py — 鼠标点击模拟器（悬浮窗版)
==========================================

"""

import ctypes
import ctypes.wintypes as wt
import random
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

# ============ Win32 API 封装 ============
user32 = ctypes.windll.user32

# 鼠标事件标志
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040

# 虚拟键码
VK_LBUTTON = 0x01
VK_HOME = 0x24
VK_END = 0x23
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

# 鼠标窗口消息（后台注入用）
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_MBUTTON = 0x0010

PICK_TIMEOUT = 60  # 拾取位置超时（秒）
START_HOTKEY = 'Ctrl+Alt+Home'  # 全局开始快捷键
STOP_HOTKEY = 'Ctrl+Alt+End'  # 全局紧急终止快捷键


# 按键 -> 按下/松开事件码映射
BUTTON_EVENTS = {
    'left': (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    'right': (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    'middle': (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

# 按键 -> (按下消息, 松开消息, 按下标志)
BUTTON_MSG = {
    'left': (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON),
    'right': (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON),
    'middle': (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON),
}


def enum_visible_windows():
    """枚举所有带标题且可见的顶层窗口，返回 [(hwnd, title), ...]"""
    results = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def callback(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if title:
            results.append((hwnd, title))
        return True

    user32.EnumWindows(callback, 0)
    results.sort(key=lambda item: item[1].lower())
    return results


def get_window_rect(hwnd):
    """获取窗口在屏幕上的矩形 (left, top, right, bottom)"""
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def is_window_valid(hwnd):
    """窗口句柄是否仍然有效可见"""
    return bool(hwnd) and user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd)


def get_cursor_pos():
    """获取当前鼠标屏幕坐标 (x, y)"""
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def screen_to_client(hwnd, x, y):
    """屏幕坐标 -> 客户区坐标（正确处理标题栏等非客户区）"""
    pt = wt.POINT(int(x), int(y))
    user32.ScreenToClient(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def inject_click(hwnd, x, y, button, duration, is_hold, interval, stop_event):
    """后台注入点击：向目标窗口直接发送鼠标消息，不移动物理鼠标。

    坐标 (x, y) 为屏幕坐标，内部自动转为客户区坐标。
    """
    cx, cy = screen_to_client(hwnd, x, y)
    lparam = ((cy & 0xFFFF) << 16) | (cx & 0xFFFF)
    down, up, mk = BUTTON_MSG[button]

    user32.PostMessageW(hwnd, down, mk, lparam)
    if is_hold:
        # 长按：按住 duration 秒，期间响应停止
        end = time.time() + duration
        while time.time() < end:
            if stop_event.is_set():
                break
            time.sleep(0.01)
    else:
        # 单击：极短按住（仅保证消息顺序），适合高频
        time.sleep(0.005)
        if stop_event.is_set():
            time.sleep(0.005)
    user32.PostMessageW(hwnd, up, 0, lparam)
    time.sleep(max(0.0, interval))


def click_at(x, y, button, duration, is_hold, interval, stop_event):
    """在 (x, y) 处执行一次点击。

    button: 'left' / 'right' / 'middle'
    is_hold: True=长按（按住 duration 秒）; False=单击（按下即松）
    """
    down_flag, up_flag = BUTTON_EVENTS[button]
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    user32.mouse_event(down_flag, 0, 0, 0, 0)

    if is_hold:
        # 长按：按住 duration 秒，期间响应停止
        end = time.time() + duration
        while time.time() < end:
            if stop_event.is_set():
                break
            time.sleep(0.01)
    else:
        # 单击：极短按住后松开（模拟真实单击）
        time.sleep(0.03)
        if stop_event.is_set():
            time.sleep(0.01)

    user32.mouse_event(up_flag, 0, 0, 0, 0)
    time.sleep(max(0.0, interval))


# ============ 悬浮窗 UI ============
class ClickerApp:
    def __init__(self, root):
        self.root = root
        self.stop_event = threading.Event()
        self.worker_thread = None
        self.drag_offset = None
        self.pick_offset = None      # 拾取点相对窗口左上角的偏移 (dx, dy)
        self.pick_hwnd = None        # 拾取时对应的窗口句柄
        self.pick_active = False     # 拾取进行中标记
        self.emergency = False       # 紧急终止标记

        root.overrideredirect(True)
        root.attributes('-topmost', True)
        root.attributes('-alpha', 0.96)
        root.configure(bg='#2b2b3a')
        root.geometry('370x690+80+80')

        self._build_ui()
        self._refresh_windows()
        self._bind_drag(root)

        # 启动紧急热键监听
        threading.Thread(target=self._hotkey_listener, daemon=True).start()

    # ---------- 界面构建 ----------
    def _build_ui(self):
        fg = '#e8e8f0'
        bg = '#2b2b3a'
        accent = '#7aa2f7'

        # 标题栏
        title_bar = tk.Frame(self.root, bg=accent, height=34)
        title_bar.pack(fill='x')
        title_bar.pack_propagate(False)
        tk.Label(title_bar, text='✦ 悬浮点击器 v5', bg=accent,
                 fg='white', font=('Microsoft YaHei UI', 10, 'bold')).pack(side='left', padx=10)
        btn_close = tk.Label(title_bar, text=' ✕ ', bg=accent, fg='white',
                             font=('Microsoft YaHei UI', 11), cursor='hand2')
        btn_close.pack(side='right', padx=6)
        btn_close.bind('<Button-1>', lambda e: self.root.destroy())
        btn_min = tk.Label(title_bar, text=' — ', bg=accent, fg='white',
                           font=('Microsoft YaHei UI', 11), cursor='hand2')
        btn_min.pack(side='right', padx=2)
        btn_min.bind('<Button-1>', lambda e: self.root.iconify())

        body = tk.Frame(self.root, bg=bg)
        body.pack(fill='both', expand=True, padx=12, pady=10)

        # --- 目标窗口选择 ---
        tk.Label(body, text='目标窗口', bg=bg, fg=fg,
                 font=('Microsoft YaHei UI', 9, 'bold')).pack(anchor='w')
        row = tk.Frame(body, bg=bg)
        row.pack(fill='x', pady=(2, 8))
        self.win_var = tk.StringVar()
        self.win_combo = ttk.Combobox(row, textvariable=self.win_var, state='readonly')
        self.win_combo.pack(side='left', fill='x', expand=True)
        btn_refresh = tk.Button(row, text='刷新', command=self._refresh_windows,
                                bg=accent, fg='white', relief='flat',
                                font=('Microsoft YaHei UI', 9))
        btn_refresh.pack(side='left', padx=(6, 0))

        # --- 点击参数区 ---
        tk.Label(body, text='点击参数', bg=bg, fg=fg,
                 font=('Microsoft YaHei UI', 9, 'bold')).pack(anchor='w', pady=(6, 0))

        # 注入方式：物理点击 / 后台注入
        inject_row = tk.Frame(body, bg=bg)
        inject_row.pack(fill='x', pady=(2, 0))
        tk.Label(inject_row, text='注入方式', bg=bg, fg='#c8ccd8',
                 font=('Microsoft YaHei UI', 9)).pack(side='left')
        self.click_method = tk.StringVar(value='physical')
        tk.Radiobutton(inject_row, text='物理点击', value='physical',
                       variable=self.click_method, bg=bg, fg=fg, selectcolor=bg,
                       activebackground=bg, activeforeground=accent,
                       font=('Microsoft YaHei UI', 9)).pack(side='left', padx=(8, 2))
        tk.Radiobutton(inject_row, text='后台注入(不占鼠标)', value='inject',
                       variable=self.click_method, bg=bg, fg=fg, selectcolor=bg,
                       activebackground=bg, activeforeground=accent,
                       font=('Microsoft YaHei UI', 9)).pack(side='left', padx=(4, 0))

        # 点击方式：单击 / 长按
        way_row = tk.Frame(body, bg=bg)
        way_row.pack(fill='x', pady=(2, 0))
        tk.Label(way_row, text='点击方式', bg=bg, fg='#c8ccd8',
                 font=('Microsoft YaHei UI', 9)).pack(side='left')
        self.click_type = tk.StringVar(value='single')
        tk.Radiobutton(way_row, text='单击', value='single', variable=self.click_type,
                       bg=bg, fg=fg, selectcolor=bg, activebackground=bg,
                       activeforeground=accent, font=('Microsoft YaHei UI', 9),
                       command=self._toggle_hold).pack(side='left', padx=(8, 2))
        tk.Radiobutton(way_row, text='长按', value='hold', variable=self.click_type,
                       bg=bg, fg=fg, selectcolor=bg, activebackground=bg,
                       activeforeground=accent, font=('Microsoft YaHei UI', 9),
                       command=self._toggle_hold).pack(side='left', padx=(4, 0))

        # 鼠标按键：左 / 右 / 中
        btn_row = tk.Frame(body, bg=bg)
        btn_row.pack(fill='x', pady=(2, 0))
        tk.Label(btn_row, text='鼠标按键', bg=bg, fg='#c8ccd8',
                 font=('Microsoft YaHei UI', 9)).pack(side='left')
        self.mouse_button = tk.StringVar(value='left')
        for text, val in [('左键', 'left'), ('右键', 'right'), ('中键', 'middle')]:
            tk.Radiobutton(btn_row, text=text, value=val, variable=self.mouse_button,
                           bg=bg, fg=fg, selectcolor=bg, activebackground=bg,
                           activeforeground=accent, font=('Microsoft YaHei UI', 9),
                           ).pack(side='left', padx=(8, 0))

        # 数字参数
        grid = tk.Frame(body, bg=bg)
        grid.pack(fill='x', pady=(2, 4))
        self._param_row(grid, 0, '点击次数', 'n_var', '100')
        self._param_row(grid, 1, '按住时长(秒)', 'dur_var', '0.5')
        self._param_row(grid, 2, '点击间隔(秒)', 'int_var', '0.2')
        self._toggle_hold()

        # --- 点击位置模式 ---
        tk.Label(body, text='点击位置', bg=bg, fg=fg,
                 font=('Microsoft YaHei UI', 9, 'bold')).pack(anchor='w', pady=(6, 0))
        self.pos_mode = tk.StringVar(value='random')
        modes = [('窗口内随机', 'random'), ('窗口中心', 'center'), ('鼠标拾取位置', 'pick')]
        for text, val in modes:
            tk.Radiobutton(body, text=text, value=val, variable=self.pos_mode,
                           bg=bg, fg=fg, selectcolor=bg, activebackground=bg,
                           activeforeground=accent, font=('Microsoft YaHei UI', 9),
                           command=self._toggle_pick_ui).pack(anchor='w')

        # 拾取区（仅“鼠标拾取位置”模式启用）
        self.pick_frame = tk.Frame(body, bg=bg)
        self.pick_frame.pack(fill='x', pady=(4, 0))
        btn_pick = tk.Button(self.pick_frame, text='拾取位置', command=self._start_pick,
                             bg='#e8a23c', fg='white', relief='flat',
                             font=('Microsoft YaHei UI', 9, 'bold'))
        btn_pick.pack(side='left')
        self.pick_status = tk.Label(self.pick_frame, text='未拾取', bg=bg, fg='#9aa0b5',
                                    font=('Microsoft YaHei UI', 9))
        self.pick_status.pack(side='left', padx=8)

        # --- 控制按钮 ---
        btns = tk.Frame(body, bg=bg)
        btns.pack(fill='x', pady=(10, 4))
        self.btn_start = tk.Button(btns, text='▶ 开始', command=self._start,
                                   bg='#4caf7d', fg='white', relief='flat', height=1,
                                   font=('Microsoft YaHei UI', 10, 'bold'))
        self.btn_start.pack(side='left', fill='x', expand=True, padx=(0, 4))
        self.btn_stop = tk.Button(btns, text='■ 停止', command=self._stop,
                                  bg='#e06060', fg='white', relief='flat', state='disabled',
                                  font=('Microsoft YaHei UI', 10, 'bold'))
        self.btn_stop.pack(side='left', fill='x', expand=True, padx=(4, 0))

        # --- 状态栏 + 热键提示 ---
        self.status = tk.Label(body, text='就绪', bg=bg, fg='#9aa0b5',
                               font=('Microsoft YaHei UI', 9), anchor='w')
        self.status.pack(fill='x', pady=(6, 0))
        tk.Label(body, text=f'开始：{START_HOTKEY}　终止：{STOP_HOTKEY}', bg=bg, fg='#e8a23c',
                 font=('Microsoft YaHei UI', 8)).pack(anchor='w', pady=(2, 0))

        self._toggle_pick_ui()

    def _param_row(self, parent, row, label, attr, default):
        tk.Label(parent, text=label, bg=parent['bg'], fg='#c8ccd8',
                 font=('Microsoft YaHei UI', 9)).grid(row=row, column=0, sticky='w', pady=2)
        var = tk.StringVar(value=default)
        entry = tk.Entry(parent, textvariable=var, width=10, bg='#3a3a4c', fg='#e8e8f0',
                         insertbackground='#e8e8f0', relief='flat')
        entry.grid(row=row, column=1, sticky='e', pady=2, padx=(8, 0))
        setattr(self, attr, var)
        setattr(self, attr.replace('_var', '_entry'), entry)

    # ---------- 交互逻辑 ----------
    def _toggle_hold(self):
        """长按模式启用“按住时长”，单击模式禁用"""
        state = 'normal' if self.click_type.get() == 'hold' else 'disabled'
        if hasattr(self, 'dur_entry'):
            self.dur_entry.configure(state=state)

    def _toggle_pick_ui(self):
        state = 'normal' if self.pos_mode.get() == 'pick' else 'disabled'
        for child in self.pick_frame.winfo_children():
            child.configure(state=state)

    def _refresh_windows(self):
        current = self.win_var.get()
        self._window_list = enum_visible_windows()
        titles = [t for _, t in self._window_list]
        self.win_combo['values'] = titles
        if current in titles:
            self.win_var.set(current)
        elif titles:
            self.win_var.set(titles[0])

    def _bind_drag(self, widget):
        def on_press(event):
            self.drag_offset = (event.x_root - self.root.winfo_x(),
                                event.y_root - self.root.winfo_y())

        def on_move(event):
            if self.drag_offset:
                x = event.x_root - self.drag_offset[0]
                y = event.y_root - self.drag_offset[1]
                self.root.geometry(f'+{x}+{y}')

        def on_release(_):
            self.drag_offset = None

        for w in (widget, self.root):
            w.bind('<ButtonPress-1>', on_press, add='+')
            w.bind('<B1-Motion>', on_move, add='+')
            w.bind('<ButtonRelease-1>', on_release, add='+')

    def _get_selected_hwnd(self):
        title = self.win_var.get()
        for hwnd, t in self._window_list:
            if t == title:
                return hwnd
        return None

    def _validate_inputs(self):
        try:
            n = int(self.n_var.get())
            dur = float(self.dur_var.get())
            interval = float(self.int_var.get())
            if n <= 0:
                raise ValueError('次数必须为正整数')
            if dur < 0 or interval < 0:
                raise ValueError('时长/间隔不能为负')
        except ValueError as e:
            messagebox.showerror('参数错误', str(e))
            return None
        return n, dur, interval

    # ---------- 物理鼠标拾取位置 ----------
    def _start_pick(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        hwnd = self._get_selected_hwnd()
        if not hwnd or not is_window_valid(hwnd):
            messagebox.showerror('错误', '目标窗口无效，请重新选择并刷新')
            return

        self.root.withdraw()
        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes('-topmost', True)
        tip.configure(bg='#2b2b3a')
        tk.Label(tip, text=f'请在目标窗口内点击左键选取位置（{PICK_TIMEOUT}秒）\n'
                           f'目标：{self.win_var.get()}',
                 bg='#2b2b3a', fg='#e8a23c', font=('Microsoft YaHei UI', 11, 'bold'),
                 justify='center').pack(padx=20, pady=12)
        tip.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = tip.winfo_reqwidth()
        h = tip.winfo_reqheight()
        tip.geometry(f'+{(sw - w) // 2}+{sh - h - 60}')

        self.pick_status.config(text='正在拾取…')
        self.pick_active = True
        threading.Thread(target=self._listen_pick, args=(tip, hwnd), daemon=True).start()

    def _listen_pick(self, tip, hwnd):
        start = time.time()
        prev_down = False
        picked = None
        while time.time() - start < PICK_TIMEOUT:
            down = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
            if down and not prev_down:
                x, y = get_cursor_pos()
                if is_window_valid(hwnd):
                    left, top, right, bottom = get_window_rect(hwnd)
                    if left <= x <= right and top <= y <= bottom:
                        picked = (x, y, left, top)
                        break
            prev_down = down
            time.sleep(0.02)

        self.root.after(0, lambda: self._finish_pick(tip, picked))

    def _finish_pick(self, tip, picked):
        try:
            tip.destroy()
        except Exception:
            pass
        self.root.deiconify()
        self.pick_active = False

        if picked:
            x, y, left, top = picked
            self.pick_offset = (x - left, y - top)
            self.pick_hwnd = self._get_selected_hwnd()
            self.pick_status.config(text=f'已拾取 ({x}, {y})')
            self.status.config(text=f'拾取位置：({x}, {y})')
        else:
            self.pick_offset = None
            self.pick_hwnd = None
            self.pick_status.config(text='未拾取（超时）')
            self.status.config(text='拾取超时，请重试')

    # ---------- 全局快捷键 ----------
    def _hotkey_listener(self):
        """全局监听 Ctrl+Alt+Home（开始）/ Ctrl+Alt+End（终止），轮询方式"""
        while True:
            try:
                ctrl = (user32.GetAsyncKeyState(VK_LCONTROL) & 0x8000 or
                        user32.GetAsyncKeyState(VK_RCONTROL) & 0x8000)
                alt = (user32.GetAsyncKeyState(VK_LMENU) & 0x8000 or
                       user32.GetAsyncKeyState(VK_RMENU) & 0x8000)
                home = user32.GetAsyncKeyState(VK_HOME) & 0x8000
                end = user32.GetAsyncKeyState(VK_END) & 0x8000
                if ctrl and alt and home:
                    self.root.after(0, self._hotkey_start)
                    time.sleep(0.5)  # 防抖，避免连续触发
                elif ctrl and alt and end:
                    self.root.after(0, self._emergency_stop)
                    time.sleep(0.5)  # 防抖，避免连续触发
            except Exception:
                pass
            time.sleep(0.05)

    def _hotkey_start(self):
        """全局开始键：若未在运行且不在拾取中，则触发开始"""
        if self.pick_active:
            self.status.config(text='拾取进行中，忽略开始键')
            return
        if self.worker_thread and self.worker_thread.is_alive():
            return
        self._start()

    def _emergency_stop(self):
        """紧急终止：立即停止所有点击"""
        self.emergency = True
        self.stop_event.set()
        self.status.config(text=f'⚠ 紧急终止（{STOP_HOTKEY}）')
        # 如果工作线程在跑，交给 _finish 复位按钮；否则直接复位
        if not (self.worker_thread and self.worker_thread.is_alive()):
            self._reset_buttons()

    def _reset_buttons(self):
        self.btn_start.config(state='normal')
        self.btn_stop.config(state='disabled')

    # ---------- 点击执行 ----------
    def _start(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        params = self._validate_inputs()
        if not params:
            return
        n, dur, interval = params

        hwnd = self._get_selected_hwnd()
        if not hwnd or not is_window_valid(hwnd):
            messagebox.showerror('错误', '目标窗口无效，请重新选择并刷新')
            return

        mode = self.pos_mode.get()
        if mode == 'pick' and not self.pick_offset:
            messagebox.showerror('错误', '请先拾取点击位置')
            return

        self.emergency = False
        self.stop_event.clear()
        self.btn_start.config(state='disabled')
        self.btn_stop.config(state='normal')
        method_label = '物理点击' if self.click_method.get() == 'physical' else '后台注入'
        self.status.config(text=f'{method_label} → {self.win_var.get()}')

        self.worker_thread = threading.Thread(
            target=self._work,
            args=(hwnd, n, dur, interval, mode),
            daemon=True)
        self.worker_thread.start()

    def _work(self, hwnd, n, dur, interval, mode):
        done = 0
        is_hold = (self.click_type.get() == 'hold')
        button = self.mouse_button.get()
        method = self.click_method.get()

        for i in range(n):
            if self.stop_event.is_set():
                break
            if not is_window_valid(hwnd):
                self.root.after(0, lambda: self.status.config(
                    text='目标窗口已关闭，自动停止'))
                break

            left, top, right, bottom = get_window_rect(hwnd)
            if right - left < 4 or bottom - top < 4:
                self.root.after(0, lambda: self.status.config(text='窗口尺寸异常，跳过'))
                time.sleep(interval)
                continue

            if mode == 'center':
                x, y = (left + right) // 2, (top + bottom) // 2
            elif mode == 'pick':
                if self.pick_offset and self.pick_hwnd == hwnd:
                    dx, dy = self.pick_offset
                    x, y = left + dx, top + dy
                else:
                    self.root.after(0, lambda: self.status.config(text='拾取目标失效，停止'))
                    break
            else:  # random —— 仅在窗口范围内随机
                x = random.randint(left + 2, right - 2)
                y = random.randint(top + 2, bottom - 2)

            if method == 'inject':
                inject_click(hwnd, x, y, button, dur, is_hold, interval, self.stop_event)
            else:
                click_at(x, y, button, dur, is_hold, interval, self.stop_event)
            done += 1
            if done % 5 == 0 or done == n:
                self.root.after(0, lambda d=done: self.status.config(
                    text=f'已完成 {d}/{n}'))

        self.root.after(0, self._finish, done, n)

    def _finish(self, done, total):
        self._reset_buttons()
        if self.emergency:
            self.status.config(text=f'⚠ 已紧急终止（{STOP_HOTKEY}）完成 {done}/{total}')
            self.emergency = False
        elif self.stop_event.is_set():
            self.status.config(text=f'已停止（完成 {done}/{total}）')
        else:
            self.status.config(text=f'完成 {done}/{total}')

    def _stop(self):
        self.stop_event.set()
        self.status.config(text='正在停止……')


def main():
    root = tk.Tk()
    app = ClickerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog, filedialog
import os
import sys
import json
import datetime
import csv
from typing import List, Dict, Tuple, Optional
import traceback


def get_app_base_path():
    """获取应用程序的基础路径（兼容EXE模式和开发模式）"""
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    data_dir = os.path.join(base_path, "data")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)

    return base_path, data_dir


class PasswordManager:
    """密码管理器"""

    def __init__(self, base_path, data_dir):
        self.base_path = base_path
        self.data_dir = data_dir
        self.PASSWORD_FILE = os.path.join(self.data_dir, "password_config.json")
        self.DEFAULT_PASSWORD = "123"
        self.load_password()

    def load_password(self):
        """加载密码配置"""
        try:
            if os.path.exists(self.PASSWORD_FILE):
                with open(self.PASSWORD_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.current_password = data.get("password", self.DEFAULT_PASSWORD)
            else:
                self.current_password = self.DEFAULT_PASSWORD
                self.save_password()
        except Exception as e:
            print(f"加载密码配置错误: {e}")
            self.current_password = self.DEFAULT_PASSWORD

    def save_password(self):
        """保存密码配置"""
        try:
            data = {"password": self.current_password}
            with open(self.PASSWORD_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"保存密码配置错误: {e}")

    def verify_password(self, password):
        """验证密码"""
        return password == self.current_password

    def change_password(self, old_password, new_password):
        """修改密码"""
        if not self.verify_password(old_password):
            return False, "旧密码不正确"

        if not new_password or len(new_password.strip()) == 0:
            return False, "新密码不能为空"

        self.current_password = new_password
        self.save_password()
        return True, "密码修改成功"


class ProcessData:
    """工艺数据类 - 存储工艺的状态和数据，包含批次列表"""

    def __init__(self, device_id: str, process_type: str, input_mode="integer",
                 password_manager=None, data_dir=None):
        self.device_id = device_id
        self.process_type = process_type
        self.input_mode = input_mode
        self.password_manager = password_manager
        self.data_dir = data_dir

        # 初始化路径
        self.base_path, _ = get_app_base_path()
        if self.data_dir:
            self.DATA_FILE = os.path.join(self.data_dir,
                                          f"counter_data_{device_id}_{process_type}.json")
        else:
            self.DATA_FILE = os.path.join(self.base_path,
                                          f"counter_data_{device_id}_{process_type}.json")

        self.DEFAULT_TARGET = 3000.0
        self.DEFAULT_LOWER_LIMIT = 0.0
        self.DEFAULT_UPPER_LIMIT = 5000.0

        # 数据状态
        self.batches = []  # 批次列表，每个元素为 {"batch_id": str, "value": float}
        self.operation_stack = []  # 操作栈（包含添加批次、重置、设置目标值等）
        self.over_target_upper = False  # 超过上限
        self.below_target_lower = False  # 低于下限
        self.TARGET = self.DEFAULT_TARGET  # 换液目标值
        self.LOWER_LIMIT = self.DEFAULT_LOWER_LIMIT  # 下限
        self.UPPER_LIMIT = self.DEFAULT_UPPER_LIMIT  # 上限
        self.has_decimal = False  # 是否有小数（用于显示格式）

        # 换液提醒标志
        self.liquid_change_reminded = False  # 是否已经提醒过需要换液

        self.load_data()
        self._update_total_from_batches()
        self.check_target_limits()

    @property
    def total(self):
        """累计值由所有批次片数求和得到"""
        return sum(b["value"] for b in self.batches)

    def format_number(self, num):
        """格式化数字显示"""
        if isinstance(num, (int, float)):
            if self.has_decimal or num != int(num):
                return f"{num:.2f}"
            else:
                return str(int(num))
        return str(num)

    def load_data(self):
        """加载保存的数据"""
        try:
            if os.path.exists(self.DATA_FILE):
                with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 兼容旧数据：如果没有batches字段，则直接清空批次（不再将旧total作为初始批次）
                    if "batches" in data:
                        self.batches = data["batches"]
                    else:
                        # 旧数据：忽略原有的total，从0开始
                        self.batches = []
                    self.TARGET = float(data.get("target", self.DEFAULT_TARGET))
                    self.LOWER_LIMIT = float(data.get("lower_limit", self.DEFAULT_LOWER_LIMIT))
                    self.UPPER_LIMIT = float(data.get("upper_limit", self.DEFAULT_UPPER_LIMIT))
                    self.input_mode = data.get("input_mode", "integer")

                    # 加载换液提醒标志
                    self.liquid_change_reminded = data.get("liquid_change_reminded", False)

                    # 检查是否有小数
                    self.has_decimal = any(b["value"] != int(b["value"]) for b in self.batches)
            else:
                self.TARGET = self.DEFAULT_TARGET
                self.LOWER_LIMIT = self.DEFAULT_LOWER_LIMIT
                self.UPPER_LIMIT = self.DEFAULT_UPPER_LIMIT
                self.batches = []
                self.liquid_change_reminded = False
        except Exception as e:
            print(f"加载数据错误 ({self.device_id}/{self.process_type}): {e}")
            self.batches = []
            self.TARGET = self.DEFAULT_TARGET
            self.LOWER_LIMIT = self.DEFAULT_LOWER_LIMIT
            self.UPPER_LIMIT = self.DEFAULT_UPPER_LIMIT
            self.liquid_change_reminded = False

    def save_data(self):
        """保存数据到文件"""
        try:
            data = {
                "batches": self.batches,
                "target": self.TARGET,
                "lower_limit": self.LOWER_LIMIT,
                "upper_limit": self.UPPER_LIMIT,
                "input_mode": self.input_mode,
                "device_id": self.device_id,
                "process_type": self.process_type,
                "liquid_change_reminded": self.liquid_change_reminded
            }
            with open(self.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存数据错误 ({self.device_id}/{self.process_type}): {e}")

    def add_batch(self, batch_id: str, value: float):
        """添加一个批次"""
        # 如果值有小数，标记累计值有小数
        if value != int(value):
            self.has_decimal = True

        # 记录操作
        self.operation_stack.append({
            "type": "add_batch",
            "batch": {"batch_id": batch_id, "value": value},
            "previous_total": self.total
        })

        # 添加批次
        self.batches.append({"batch_id": batch_id, "value": value})

        # 检查是否超过目标值范围
        self.check_target_limits()

        return self.total

    def undo_last_action(self):
        """撤销上一步操作"""
        if not self.operation_stack:
            return None

        last_operation = self.operation_stack.pop()
        undo_value = None

        if last_operation["type"] == "add_batch":
            # 移除最后一个添加的批次
            removed_batch = self.batches.pop()
            self._update_total_from_batches()
            self.check_decimal_status()
            self.check_target_limits()
            undo_value = removed_batch["value"]
        elif last_operation["type"] == "reset":
            # 重置：恢复之前的批次列表
            self.batches = last_operation["previous_batches"]
            self._update_total_from_batches()
            self.check_decimal_status()
            self.check_target_limits()
            # 重置时清除换液提醒标志
            self.liquid_change_reminded = False
            undo_value = 0
        elif last_operation["type"] == "set_target":
            self.TARGET = last_operation["previous_target"]
            self.check_target_limits()
            undo_value = last_operation["new_target"]
        elif last_operation["type"] == "set_lower_limit":
            self.LOWER_LIMIT = last_operation["previous_lower_limit"]
            self.check_target_limits()
            undo_value = last_operation["new_lower_limit"]
        elif last_operation["type"] == "set_upper_limit":
            self.UPPER_LIMIT = last_operation["previous_upper_limit"]
            self.check_target_limits()
            undo_value = last_operation["new_upper_limit"]

        return undo_value

    def check_decimal_status(self):
        """检查累计值是否有小数部分"""
        self.has_decimal = any(b["value"] != int(b["value"]) for b in self.batches)

    def _update_total_from_batches(self):
        """内部方法：更新has_decimal（无需操作栈）"""
        self.has_decimal = any(b["value"] != int(b["value"]) for b in self.batches)

    def reset_total(self):
        """重置累计值（清空所有批次）"""
        if self.total == 0:
            return False

        self.operation_stack.append({
            "type": "reset",
            "previous_batches": self.batches.copy()
        })

        previous_total = self.total
        self.batches = []
        self.has_decimal = False
        # 重置时清除换液提醒标志
        self.liquid_change_reminded = False
        self.check_target_limits()
        return previous_total

    def set_target(self, new_target):
        """设置换液目标值"""
        self.operation_stack.append({
            "type": "set_target",
            "previous_target": self.TARGET,
            "new_target": new_target
        })

        old_target = self.TARGET
        self.TARGET = new_target
        self.check_target_limits()
        return old_target

    def set_lower_limit(self, new_lower_limit):
        """设置下限"""
        self.operation_stack.append({
            "type": "set_lower_limit",
            "previous_lower_limit": self.LOWER_LIMIT,
            "new_lower_limit": new_lower_limit
        })

        old_lower_limit = self.LOWER_LIMIT
        self.LOWER_LIMIT = new_lower_limit
        self.check_target_limits()
        return old_lower_limit

    def set_upper_limit(self, new_upper_limit):
        """设置上限"""
        self.operation_stack.append({
            "type": "set_upper_limit",
            "previous_upper_limit": self.UPPER_LIMIT,
            "new_upper_limit": new_upper_limit
        })

        old_upper_limit = self.UPPER_LIMIT
        self.UPPER_LIMIT = new_upper_limit
        self.check_target_limits()
        return old_upper_limit

    def check_target_limits(self):
        """检查累计值是否在目标值范围内"""
        self.over_target_upper = self.total > self.UPPER_LIMIT
        self.below_target_lower = self.total >= self.LOWER_LIMIT and self.total < self.TARGET
        return self.over_target_upper, self.below_target_lower

    def check_liquid_change_reminder(self):
        """检查是否需要显示换液提醒"""
        # 如果超过上限，强制提醒
        if self.over_target_upper:
            return "强制", "已达到上限，请立即换液！"

        # 如果达到或超过下限但低于目标值，需要提醒换液
        if self.total >= self.LOWER_LIMIT and self.total < self.TARGET:
            if not self.liquid_change_reminded:
                self.liquid_change_reminded = True
                self.save_data()
                return "提醒", f"已达到换液片量 ({self.format_number(self.total)}/{self.format_number(self.TARGET)})，请及时换液！"
            else:
                return "提醒", f"仍需换液 ({self.format_number(self.total)}/{self.format_number(self.TARGET)})"

        # 重置提醒标志（当累计值低于下限时）
        if self.total < self.LOWER_LIMIT:
            self.liquid_change_reminded = False

        return None, None

    def get_status(self):
        """获取状态"""
        if self.over_target_upper:
            return "超上限"
        elif self.total >= self.LOWER_LIMIT and self.total < self.TARGET:
            return "需换液"
        else:
            return "正常"

    def is_out_of_range(self):
        """是否超出范围"""
        return self.over_target_upper or self.below_target_lower

    def can_undo(self):
        return len(self.operation_stack) > 0


class DeviceTab(tk.Frame):
    """设备选项卡 - 每个实例代表一个设备，使用表格显示该设备下所有工艺的批次"""

    def __init__(self, master, device_id: str, app_counter: int,
                 log_callback=None, delete_callback=None, password_manager=None, data_dir=None):
        super().__init__(master)
        self.device_id = device_id
        self.app_counter = app_counter
        self.log_callback = log_callback
        self.delete_callback = delete_callback
        self.password_manager = password_manager
        self.data_dir = data_dir

        # 输入范围配置
        self.range_config_file = os.path.join(data_dir, f"range_config_{device_id}.json")
        self.default_integer_min = 1
        self.default_integer_max = 50
        self.default_decimal_min = 0
        self.default_decimal_max = 3

        # 加载范围配置
        self.load_range_config()

        self.process_data = {}  # 存储工艺数据的字典 {process_type: ProcessData}
        self.batch_rows = {}  # 存储批次行ID与批次信息的映射 {row_id: (process_type, batch_index)}
        self.current_selected_process = None  # 当前选中行的工艺种类（用于扫码）

        self.setup_ui()
        self.load_existing_processes()

    def load_range_config(self):
        """加载范围配置"""
        try:
            if os.path.exists(self.range_config_file):
                with open(self.range_config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.integer_min = config.get("integer_min", self.default_integer_min)
                    self.integer_max = config.get("integer_max", self.default_integer_max)
                    self.decimal_min = config.get("decimal_min", self.default_decimal_min)
                    self.decimal_max = config.get("decimal_max", self.default_decimal_max)
            else:
                self.integer_min = self.default_integer_min
                self.integer_max = self.default_integer_max
                self.decimal_min = self.default_decimal_min
                self.decimal_max = self.default_decimal_max
                self.save_range_config()
        except Exception as e:
            print(f"加载范围配置错误: {e}")
            self.integer_min = self.default_integer_min
            self.integer_max = self.default_integer_max
            self.decimal_min = self.default_decimal_min
            self.decimal_max = self.default_decimal_max

    def save_range_config(self):
        """保存范围配置"""
        try:
            config = {
                "integer_min": self.integer_min,
                "integer_max": self.integer_max,
                "decimal_min": self.decimal_min,
                "decimal_max": self.decimal_max
            }
            with open(self.range_config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"保存范围配置错误: {e}")

    def setup_ui(self):
        """设置设备选项卡界面"""
        # 设备标题和操作按钮
        header_frame = tk.Frame(self, bd=2, relief=tk.GROOVE, padx=10, pady=5)
        header_frame.pack(fill="x", pady=(0, 10))

        tk.Label(header_frame, text=f"设备号: {self.device_id}",
                 font=("Arial", 14, "bold")).pack(side="left")

        # 批量操作区域 - 移除批量输入相关按钮
        batch_frame = tk.Frame(header_frame)
        batch_frame.pack(side="right", padx=(0, 10))

        # 范围设置按钮
        range_btn = tk.Button(
            batch_frame,
            text="设置范围",
            command=self.set_input_range,
            font=("Arial", 9),
            bg="#9C27B0",
            fg="white",
            width=8
        )
        range_btn.pack(side="left", padx=(10, 5))

        self.range_label = tk.Label(batch_frame, text="", font=("Arial", 9), fg="blue")
        self.range_label.pack(side="left", padx=(5, 10))

        # 初始化范围标签
        mode = "integer"
        if mode == "integer":
            range_text = f"整数范围: {self.integer_min}-{self.integer_max}"
        else:
            range_text = f"小数范围: {self.decimal_min}-{self.decimal_max}"
        self.range_label.config(text=range_text)

        # 扫码区域 - 移除按钮，只保留输入框
        scan_frame = tk.Frame(header_frame)
        scan_frame.pack(side="right", padx=(20, 0))
        tk.Label(scan_frame, text="扫描批次号:", font=("Arial", 10, "bold")).pack(side="left")
        self.scan_entry = tk.Entry(scan_frame, font=("Arial", 12), width=15, bg="#FFFFE0")
        self.scan_entry.pack(side="left", padx=5)
        self.scan_entry.bind("<Return>", self.on_scan)  # 扫描枪输入后回车触发
        # 扫码按钮已隐藏

        # 设备操作按钮
        btn_frame = tk.Frame(header_frame)
        btn_frame.pack(side="right")
        add_btn = tk.Button(
            btn_frame,
            text="+ 添加工艺",
            command=self.add_process,
            font=("Arial", 11, "bold"),
            bg="#4CAF50",
            fg="white",
            height=1,
            width=12
        )
        add_btn.pack(side="left", padx=(0, 5))

        # 清空按钮
        clear_btn = tk.Button(
            btn_frame,
            text="清空",
            command=self.clear_all_processes,
            font=("Arial", 11, "bold"),
            bg="#FFC107",  # 琥珀色
            fg="black",
            height=1,
            width=8
        )
        clear_btn.pack(side="left", padx=(0, 5))

        # 初始值按钮
        initial_btn = tk.Button(
            btn_frame,
            text="初始值",
            command=self.set_initial_value,
            font=("Arial", 11, "bold"),
            bg="#00BCD4",  # 青色
            fg="white",
            height=1,
            width=8
        )
        initial_btn.pack(side="left", padx=(0, 5))

        delete_btn = tk.Button(
            btn_frame,
            text="删除设备",
            command=self.delete_device,
            font=("Arial", 11),
            bg="#F44336",
            fg="white",
            height=1,
            width=10
        )
        delete_btn.pack(side="left")

        # 工艺表格区域
        table_frame = tk.LabelFrame(self, text="批次列表", padx=10, pady=10,
                                    font=("Arial", 12, "bold"))
        table_frame.pack(fill="both", expand=True, pady=(0, 10))

        self.create_process_table(table_frame)

    def create_process_table(self, parent):
        """创建批次表格（每行一个批次）"""
        # 创建主容器，设置固定高度
        table_container = tk.Frame(parent, height=450)
        table_container.pack(fill="both", expand=True, pady=5)
        table_container.pack_propagate(False)

        # 创建表格框架
        tree_frame = tk.Frame(table_container)
        tree_frame.pack(fill="both", expand=True)

        # 垂直滚动条
        scrollbar_y = ttk.Scrollbar(tree_frame)
        scrollbar_y.pack(side="right", fill="y")

        # 水平滚动条
        scrollbar_x = ttk.Scrollbar(tree_frame, orient="horizontal")
        scrollbar_x.pack(side="bottom", fill="x")

        # 设置表格样式
        style = ttk.Style()
        style.configure("Custom.Treeview",
                        background="#f8f8f8",
                        foreground="black",
                        rowheight=25,
                        fieldbackground="#f8f8f8",
                        font=("Arial", 9))
        style.configure("Custom.Treeview.Heading",
                        font=("Arial", 9, "bold"),
                        background="#e1e1e1",
                        foreground="black",
                        relief="flat")

        # 列定义
        columns = ("序号", "工艺种类", "批次号", "片数", "累计值", "下限", "换液目标值", "上限", "状态", "输入模式",
                   "操作")

        # 创建表格
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            yscrollcommand=scrollbar_y.set,
            xscrollcommand=scrollbar_x.set,
            selectmode="browse",
            style="Custom.Treeview"
        )

        # 调整列宽
        column_widths = [
            40,  # 序号
            100,  # 工艺种类
            120,  # 批次号
            70,  # 片数
            80,  # 累计值
            60,  # 下限
            90,  # 换液目标值
            60,  # 上限
            60,  # 状态
            80,  # 输入模式
            100  # 操作
        ]

        # 设置列标题和宽度
        for col, width in zip(columns, column_widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="center", minwidth=40)

        # 将表格放置在左侧
        self.tree.pack(side="left", fill="both", expand=True)

        # 配置滚动条
        scrollbar_y.config(command=self.tree.yview)
        scrollbar_x.config(command=self.tree.xview)

        # 绑定鼠标滚轮事件
        def on_mousewheel(event):
            self.tree.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self.tree.bind("<MouseWheel>", on_mousewheel)

        # 绑定事件
        self.tree.bind("<ButtonRelease-1>", self.on_table_select)
        self.tree.bind("<Button-1>", self.on_table_click)

        # 配置标签样式
        self.tree.tag_configure("out_of_range", foreground="red", font=("Arial", 9, "bold"))

    def on_table_select(self, event):
        """点击行时记录选中的工艺种类"""
        item = self.tree.identify_row(event.y)
        if item:
            values = self.tree.item(item, "values")
            if values:
                self.current_selected_process = values[1]  # 工艺种类在第2列

    def on_table_click(self, event):
        """处理表格点击事件（操作列弹出菜单）"""
        region = self.tree.identify("region", event.x, event.y)
        if region == "cell":
            column = self.tree.identify_column(event.x)
            item = self.tree.identify_row(event.y)
            if column == "#11":  # 操作列（第11列）
                values = self.tree.item(item, "values")
                if values:
                    process_type = values[1]
                    batch_id = values[2]
                    # 弹出该批次的操作菜单
                    self.show_batch_operations(process_type, batch_id, event)

    def show_batch_operations(self, process_type, batch_id, event):
        """显示批次操作菜单"""
        if process_type not in self.process_data:
            return

        process_data = self.process_data[process_type]
        menu = tk.Menu(self, tearoff=0)
        # 添加累计值显示（只读信息）
        menu.add_command(
            label=f"当前累计值: {process_data.format_number(process_data.total)}",
            state="disabled"  # 设为禁用状态，不可点击
        )
        menu.add_separator()

        menu.add_command(
            label=f"为 '{process_type}' 添加批次",
            command=lambda: self.add_batch_dialog(process_type)
        )
        menu.add_command(
            label=f"设置初始值",
            command=lambda: self.set_initial_value_for_process(process_type)
        )
        menu.add_command(
            label=f"撤销 '{process_type}' 上一步",
            command=lambda: self.undo_process(process_type)
        )
        menu.add_separator()
        menu.add_command(
            label=f"重置 '{process_type}' 所有批次",
            command=lambda: self.reset_process(process_type)
        )
        menu.add_command(
            label=f"设置 '{process_type}' 换液目标值",
            command=lambda: self.set_target_dialog(process_type)
        )
        menu.add_command(
            label=f"设置 '{process_type}' 下限",
            command=lambda: self.set_lower_limit_dialog(process_type)
        )
        menu.add_command(
            label=f"设置 '{process_type}' 上限",
            command=lambda: self.set_upper_limit_dialog(process_type)
        )
        menu.add_separator()
        menu.add_command(
            label=f"切换 '{process_type}' 输入模式",
            command=lambda: self.change_input_mode(process_type)
        )
        menu.add_command(
            label=f"删除 '{process_type}' 工艺",
            command=lambda: self.delete_single_process(process_type)
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def on_scan(self, event=None):
        """扫描枪输入处理（回车触发）"""
        batch_id = self.scan_entry.get().strip()
        if not batch_id:
            messagebox.showerror("错误", "扫描内容为空")
            return
        self.scan_entry.delete(0, tk.END)

        # 确定当前选中的工艺
        if not self.current_selected_process:
            messagebox.showerror("错误", "请先在表格中点击选中一个工艺")
            return
        process_type = self.current_selected_process
        if process_type not in self.process_data:
            messagebox.showerror("错误", f"工艺 '{process_type}' 不存在")
            return

        # 检查是否超过上限
        process_data = self.process_data[process_type]
        if process_data.over_target_upper:
            messagebox.showerror("禁止操作",
                                 f"工艺 '{process_type}' 已超过上限 ({process_data.format_number(process_data.UPPER_LIMIT)})，请立即换液！")
            return

        # 弹出输入片数对话框
        self.prompt_for_pieces(process_type, batch_id)

    def prompt_for_pieces(self, process_type, batch_id):
        """弹出输入片数对话框"""
        process_data = self.process_data[process_type]
        input_mode = process_data.input_mode

        # 检查是否需要显示换液提醒
        reminder_type, reminder_message = process_data.check_liquid_change_reminder()
        if reminder_type == "强制":
            messagebox.showerror("强制换液", reminder_message)
            return
        elif reminder_type == "提醒":
            messagebox.showwarning("换液提醒", reminder_message)

        dialog = tk.Toplevel()
        dialog.title("输入片数")
        dialog.geometry("300x200")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - dialog.winfo_width()) // 2
        y = (dialog.winfo_screenheight() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        info = f"工艺: {process_type}\n批次号: {batch_id}\n当前累计: {process_data.format_number(process_data.total)}"
        tk.Label(dialog, text=info, font=("Arial", 10), justify="left").pack(pady=10)

        tk.Label(dialog, text="请输入片数:", font=("Arial", 11)).pack()
        value_var = tk.StringVar()
        entry = tk.Entry(dialog, textvariable=value_var, font=("Arial", 12), width=15)
        entry.pack(pady=5)
        entry.focus_set()

        # 显示范围提示
        if input_mode == "integer":
            range_text = f"范围: {self.integer_min}~{self.integer_max} 整数"
        else:
            range_text = f"范围: {self.decimal_min}~{self.decimal_max} 小数(两位)"
        tk.Label(dialog, text=range_text, font=("Arial", 9), fg="gray").pack()

        def validate_and_add():
            try:
                value_str = value_var.get().strip()
                if not value_str:
                    messagebox.showerror("错误", "请输入片数", parent=dialog)
                    return
                if input_mode == "integer":
                    value = int(value_str)
                    if value < self.integer_min or value > self.integer_max:
                        messagebox.showerror("错误", f"请输入{self.integer_min}~{self.integer_max}之间的整数",
                                             parent=dialog)
                        return
                else:
                    value = float(value_str)
                    if len(value_str.split('.')[-1]) > 2:
                        messagebox.showerror("错误", "最多两位小数", parent=dialog)
                        return
                    if value < self.decimal_min or value > self.decimal_max:
                        messagebox.showerror("错误", f"请输入{self.decimal_min}~{self.decimal_max}之间的小数",
                                             parent=dialog)
                        return
                    value = round(value, 2)

                # 添加批次前检查是否会超过上限
                new_total = process_data.total + value
                if new_total > process_data.UPPER_LIMIT:
                    if not messagebox.askyesno("警告",
                                               f"添加后累计值({process_data.format_number(new_total)})将超过上限({process_data.format_number(process_data.UPPER_LIMIT)})，确定要继续吗？",
                                               parent=dialog):
                        return

                # 添加批次
                process_data.add_batch(batch_id, value)
                process_data.save_data()
                self.refresh_table()
                self.keep_processes_at_top()

                # 添加后再次检查是否需要显示换液提醒
                reminder_type, reminder_message = process_data.check_liquid_change_reminder()
                if reminder_type == "强制":
                    messagebox.showerror("强制换液", reminder_message)
                elif reminder_type == "提醒":
                    messagebox.showwarning("换液提醒", reminder_message)

                # 记录日志
                if self.log_callback:
                    self.log_callback({
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "device_id": self.device_id,
                        "process_type": process_type,
                        "action": "扫码添加",
                        "value": f"{batch_id}:{value}",
                        "total": process_data.total,
                        "target": process_data.TARGET,
                        "lower_limit": process_data.LOWER_LIMIT,
                        "upper_limit": process_data.UPPER_LIMIT,
                        "input_mode": process_data.input_mode
                    })

                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "输入无效的数字", parent=dialog)

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="确定", command=validate_and_add,
                  width=10, bg="#4CAF50", fg="white").pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", command=dialog.destroy,
                  width=10).pack(side="left", padx=5)

        dialog.bind("<Return>", lambda e: validate_and_add())

    def set_input_range(self):
        """设置输入范围"""
        if not self.verify_password("设置输入范围"):
            return

        range_dialog = tk.Toplevel()
        range_dialog.title("设置输入范围")
        range_dialog.geometry("400x300")
        range_dialog.resizable(False, False)
        range_dialog.transient(self)
        range_dialog.grab_set()
        range_dialog.update_idletasks()
        x = (range_dialog.winfo_screenwidth() - range_dialog.winfo_width()) // 2
        y = (range_dialog.winfo_screenheight() - range_dialog.winfo_height()) // 2
        range_dialog.geometry(f"+{x}+{y}")

        integer_frame = tk.LabelFrame(range_dialog, text="整数范围设置", padx=10, pady=10)
        integer_frame.pack(fill="x", padx=10, pady=5)
        tk.Label(integer_frame, text="最小值:", font=("Arial", 10)).grid(row=0, column=0, sticky="w", pady=5)
        integer_min_var = tk.StringVar(value=str(self.integer_min))
        integer_min_entry = tk.Entry(integer_frame, textvariable=integer_min_var, font=("Arial", 10), width=10)
        integer_min_entry.grid(row=0, column=1, sticky="w", padx=(5, 20), pady=5)
        tk.Label(integer_frame, text="最大值:", font=("Arial", 10)).grid(row=0, column=2, sticky="w", pady=5)
        integer_max_var = tk.StringVar(value=str(self.integer_max))
        integer_max_entry = tk.Entry(integer_frame, textvariable=integer_max_var, font=("Arial", 10), width=10)
        integer_max_entry.grid(row=0, column=3, sticky="w", padx=5, pady=5)

        decimal_frame = tk.LabelFrame(range_dialog, text="小数范围设置", padx=10, pady=10)
        decimal_frame.pack(fill="x", padx=10, pady=5)
        tk.Label(decimal_frame, text="最小值:", font=("Arial", 10)).grid(row=0, column=0, sticky="w", pady=5)
        decimal_min_var = tk.StringVar(value=str(self.decimal_min))
        decimal_min_entry = tk.Entry(decimal_frame, textvariable=decimal_min_var, font=("Arial", 10), width=10)
        decimal_min_entry.grid(row=0, column=1, sticky="w", padx=(5, 20), pady=5)
        tk.Label(decimal_frame, text="最大值:", font=("Arial", 10)).grid(row=0, column=2, sticky="w", pady=5)
        decimal_max_var = tk.StringVar(value=str(self.decimal_max))
        decimal_max_entry = tk.Entry(decimal_frame, textvariable=decimal_max_var, font=("Arial", 10), width=10)
        decimal_max_entry.grid(row=0, column=3, sticky="w", padx=5, pady=5)

        tk.Label(range_dialog, text="注意：范围设置仅影响批量输入和新建工艺的默认范围",
                 font=("Arial", 9), fg="gray").pack(pady=(10, 5))

        def validate_and_save():
            try:
                new_integer_min = int(integer_min_var.get())
                new_integer_max = int(integer_max_var.get())
                if new_integer_min >= new_integer_max:
                    messagebox.showerror("输入错误", "整数最小值必须小于最大值", parent=range_dialog)
                    return
                new_decimal_min = float(decimal_min_var.get())
                new_decimal_max = float(decimal_max_var.get())
                if new_decimal_min >= new_decimal_max:
                    messagebox.showerror("输入错误", "小数最小值必须小于最大值", parent=range_dialog)
                    return

                self.integer_min = new_integer_min
                self.integer_max = new_integer_max
                self.decimal_min = new_decimal_min
                self.decimal_max = new_decimal_max
                self.save_range_config()

                # 更新范围标签
                mode = "integer"  # 默认显示整数范围
                if mode == "integer":
                    range_text = f"整数范围: {self.integer_min}-{self.integer_max}"
                else:
                    range_text = f"小数范围: {self.decimal_min}-{self.decimal_max}"
                self.range_label.config(text=range_text)

                if self.log_callback:
                    self.log_callback({
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "device_id": self.device_id,
                        "process_type": "系统",
                        "action": "设置输入范围",
                        "value": f"整数:{self.integer_min}-{self.integer_max}, 小数:{self.decimal_min}-{self.decimal_max}",
                        "total": 0.0,
                        "target": 0.0,
                        "lower_limit": 0.0,
                        "upper_limit": 0.0,
                        "input_mode": ""
                    })
                messagebox.showinfo("成功", "输入范围设置已保存", parent=range_dialog)
                range_dialog.destroy()
            except ValueError:
                messagebox.showerror("输入错误", "请输入有效的数字", parent=range_dialog)

        button_frame = tk.Frame(range_dialog)
        button_frame.pack(pady=10)
        tk.Button(button_frame, text="保存", command=validate_and_save,
                  width=10, bg="#4CAF50", fg="white").pack(side="left", padx=5)
        tk.Button(button_frame, text="取消", command=range_dialog.destroy,
                  width=10).pack(side="left", padx=5)
        range_dialog.bind("<Return>", lambda e: validate_and_save())

    def add_process(self, process_type=None, input_mode="integer", from_file=False):
        """添加工艺（带批次号和片数输入）"""
        if not from_file and not self.verify_password("添加工艺种类"):
            return

        if not process_type:
            add_dialog = tk.Toplevel()
            add_dialog.title("添加工艺种类")
            add_dialog.geometry("400x350")  # 增加高度以容纳更多输入框
            add_dialog.resizable(False, False)
            add_dialog.transient(self)
            add_dialog.grab_set()
            add_dialog.update_idletasks()
            x = (add_dialog.winfo_screenwidth() - add_dialog.winfo_width()) // 2
            y = (add_dialog.winfo_screenheight() - add_dialog.winfo_height()) // 2
            add_dialog.geometry(f"+{x}+{y}")

            # 工艺种类名称
            tk.Label(add_dialog, text="工艺种类名称:", font=("Arial", 11)).pack(pady=(20, 5))
            process_var = tk.StringVar()
            process_entry = tk.Entry(add_dialog, textvariable=process_var, font=("Arial", 11), width=25)
            process_entry.pack(pady=5)
            process_entry.focus_set()

            # 输入模式选择
            tk.Label(add_dialog, text="输入模式:", font=("Arial", 11)).pack(pady=(15, 5))
            input_mode_var = tk.StringVar(value="integer")
            input_frame = tk.Frame(add_dialog)
            input_frame.pack()
            integer_range_text = f"整数 ({self.integer_min}-{self.integer_max})"
            decimal_range_text = f"小数 ({self.decimal_min}-{self.decimal_max}，两位小数)"
            tk.Radiobutton(input_frame, text=integer_range_text, variable=input_mode_var,
                           value="integer", font=("Arial", 10)).pack(side="left", padx=10)
            tk.Radiobutton(input_frame, text=decimal_range_text, variable=input_mode_var,
                           value="decimal", font=("Arial", 10)).pack(side="left", padx=10)

            # 批次号输入
            tk.Label(add_dialog, text="初始批次号:", font=("Arial", 11)).pack(pady=(15, 5))
            batch_var = tk.StringVar()
            batch_entry = tk.Entry(add_dialog, textvariable=batch_var, font=("Arial", 11), width=25)
            batch_entry.pack(pady=5)
            batch_entry.insert(0, f"批次_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}")  # 默认批次号

            # 片数输入
            tk.Label(add_dialog, text="初始片数:", font=("Arial", 11)).pack(pady=(15, 5))
            value_var = tk.StringVar()
            value_entry = tk.Entry(add_dialog, textvariable=value_var, font=("Arial", 11), width=15)
            value_entry.pack(pady=5)

            # 范围提示（根据选择的模式动态更新）
            range_label = tk.Label(add_dialog, text="", font=("Arial", 9), fg="gray")
            range_label.pack(pady=(5, 10))

            def update_range_label(*args):
                mode = input_mode_var.get()
                if mode == "integer":
                    range_text = f"整数范围: {self.integer_min}~{self.integer_max}"
                else:
                    range_text = f"小数范围: {self.decimal_min}~{self.decimal_max} (两位)"
                range_label.config(text=range_text)

            input_mode_var.trace("w", update_range_label)
            update_range_label()  # 初始化显示

            def validate_and_close():
                process_name = process_var.get().strip()
                if not process_name:
                    messagebox.showerror("输入错误", "请输入工艺种类名称", parent=add_dialog)
                    return
                if process_name in self.process_data:
                    messagebox.showerror("错误", f"工艺种类 '{process_name}' 已存在", parent=add_dialog)
                    return

                batch_id = batch_var.get().strip()
                if not batch_id:
                    messagebox.showerror("输入错误", "请输入批次号", parent=add_dialog)
                    return

                value_str = value_var.get().strip()
                if not value_str:
                    messagebox.showerror("输入错误", "请输入片数", parent=add_dialog)
                    return

                # 验证片数
                mode = input_mode_var.get()
                try:
                    if mode == "integer":
                        value = int(value_str)
                        if value < self.integer_min or value > self.integer_max:
                            messagebox.showerror("错误", f"请输入{self.integer_min}~{self.integer_max}之间的整数",
                                                 parent=add_dialog)
                            return
                    else:
                        value = float(value_str)
                        if len(value_str.split('.')[-1]) > 2:
                            messagebox.showerror("错误", "最多两位小数", parent=add_dialog)
                            return
                        if value < self.decimal_min or value > self.decimal_max:
                            messagebox.showerror("错误", f"请输入{self.decimal_min}~{self.decimal_max}之间的小数",
                                                 parent=add_dialog)
                            return
                        value = round(value, 2)
                except ValueError:
                    messagebox.showerror("错误", "请输入有效的数字", parent=add_dialog)
                    return

                # 创建工艺并添加初始批次
                self.create_process_data(process_name, mode, batch_id, value)
                add_dialog.destroy()

            button_frame = tk.Frame(add_dialog)
            button_frame.pack(pady=20)
            tk.Button(button_frame, text="确定", command=validate_and_close,
                      width=10, bg="#4CAF50", fg="white").pack(side="left", padx=5)
            tk.Button(button_frame, text="取消", command=add_dialog.destroy,
                      width=10).pack(side="left", padx=5)
            add_dialog.bind("<Return>", lambda e: validate_and_close())
            return
        else:
            # 从文件加载时，不添加初始批次
            self.create_process_data(process_type, input_mode)

    def create_process_data(self, process_type, input_mode, batch_id=None, value=None):
        """创建工艺数据，可选择添加初始批次"""
        process_data = ProcessData(
            self.device_id,
            process_type,
            input_mode,
            self.password_manager,
            self.data_dir
        )

        # 如果提供了批次号和片数，添加初始批次
        if batch_id and value is not None:
            process_data.add_batch(batch_id, value)
            process_data.save_data()

        self.process_data[process_type] = process_data

        # 重新加载所有批次行
        self.refresh_table()

        # 将新工艺的行移动到第一行
        self.move_new_process_to_top(process_type)

        if self.log_callback and not hasattr(self, 'loading_from_file'):
            log_value = f"{batch_id}:{value}" if batch_id and value is not None else input_mode
            self.log_callback({
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "device_id": self.device_id,
                "process_type": process_type,
                "action": "添加工艺",
                "value": log_value,
                "total": process_data.total,
                "target": process_data.TARGET,
                "lower_limit": process_data.LOWER_LIMIT,
                "upper_limit": process_data.UPPER_LIMIT,
                "input_mode": input_mode
            })

    def keep_processes_at_top(self):
        """将所有工艺的行保持在表格顶部"""
        # 获取所有行ID
        all_items = self.tree.get_children()
        if not all_items:
            return

        # 按工艺种类分组行
        process_rows = {}
        for item in all_items:
            values = self.tree.item(item, "values")
            if values:
                process_type = values[1]  # 工艺种类在第2列
                if process_type not in process_rows:
                    process_rows[process_type] = []
                process_rows[process_type].append(item)

        # 重新排序：每个工艺的第一行在前，所有行按工艺种类顺序排列
        reordered_items = []
        for process_type in sorted(process_rows.keys()):  # 按工艺种类名称排序
            reordered_items.extend(process_rows[process_type])

        # 重新排序树形视图中的项
        for index, item in enumerate(reordered_items):
            self.tree.move(item, '', index)

        # 重新编号
        self.renumber_table()

        # 选中第一个工艺的第一行
        if reordered_items:
            self.tree.selection_set(reordered_items[0])
            self.tree.focus(reordered_items[0])
            self.tree.see(reordered_items[0])

    def refresh_table(self):
        """重新加载表格中所有批次行，空工艺也显示一行"""
        # 清空现有行
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)
        self.batch_rows.clear()

        # 为每个工艺添加行
        for process_type, process_data in self.process_data.items():
            if len(process_data.batches) > 0:
                # 如果有批次，为每个批次添加一行
                for idx, batch in enumerate(process_data.batches):
                    self._add_batch_row(process_type, process_data, batch, idx)
            else:
                # 如果没有批次，添加一个空行（显示工艺信息但批次号和片数为空）
                self._add_empty_process_row(process_type, process_data)

        # 重新编号
        self.renumber_table()

    def move_new_process_to_top(self, new_process_type):
        """将新添加工艺的所有批次行移动到表格顶部"""
        # 获取所有行ID
        all_items = self.tree.get_children()
        if not all_items:
            return

        # 找出新工艺的所有行
        new_process_items = []
        other_items = []

        for item in all_items:
            values = self.tree.item(item, "values")
            if values and values[1] == new_process_type:  # 工艺种类在第2列
                new_process_items.append(item)
            else:
                other_items.append(item)

        # 重新排列：新工艺的行在前，其他行在后
        reordered_items = new_process_items + other_items

        # 重新排序树形视图中的项
        for index, item in enumerate(reordered_items):
            self.tree.move(item, '', index)

        # 重新编号
        self.renumber_table()

        # 选中新工艺的第一行
        if new_process_items:
            self.tree.selection_set(new_process_items[0])
            self.tree.focus(new_process_items[0])
            self.tree.see(new_process_items[0])

    def _add_empty_process_row(self, process_type, process_data):
        """为没有批次的工艺添加一个空行"""
        status_text = process_data.get_status()
        # 空行：批次号显示"--"，片数显示"--"，累计值显示0
        row_id = self.tree.insert("", "end", values=(
            "?",  # 序号稍后统一编号
            process_type,
            "--",  # 批次号显示为空
            "--",  # 片数显示为空
            process_data.format_number(0),  # 累计值显示0
            process_data.format_number(process_data.LOWER_LIMIT),
            process_data.format_number(process_data.TARGET),
            process_data.format_number(process_data.UPPER_LIMIT),
            status_text,
            "整数" if process_data.input_mode == "integer" else "小数",
            "操作 ▼"
        ))
        # 为空行也记录到batch_rows中，但batch_index设为None
        self.batch_rows[row_id] = (process_type, None)
        self.update_status_style(row_id, process_data)
        return row_id

    def _add_batch_row(self, process_type, process_data, batch, batch_index):
        """添加单个批次行到表格"""
        status_text = process_data.get_status()
        # 计算当前工艺的累计值（所有批次的总和）
        current_total = process_data.total
        row_id = self.tree.insert("", "end", values=(
            "?",  # 序号稍后统一编号
            process_type,
            batch["batch_id"],
            process_data.format_number(batch["value"]),  # 当前批次片数
            process_data.format_number(current_total),  # 累计值
            process_data.format_number(process_data.LOWER_LIMIT),
            process_data.format_number(process_data.TARGET),
            process_data.format_number(process_data.UPPER_LIMIT),
            status_text,
            "整数" if process_data.input_mode == "integer" else "小数",
            "操作 ▼"
        ))
        self.batch_rows[row_id] = (process_type, batch_index)
        self.update_status_style(row_id, process_data)
        return row_id

    def update_status_style(self, row_id, process_data):
        """更新状态样式（红色加粗）"""
        current_tags = list(self.tree.item(row_id, "tags"))
        if process_data.is_out_of_range():
            if "out_of_range" not in current_tags:
                current_tags.append("out_of_range")
        else:
            if "out_of_range" in current_tags:
                current_tags.remove("out_of_range")
        self.tree.item(row_id, tags=tuple(current_tags))
        self.tree.tag_configure("out_of_range", foreground="red", font=("Arial", 9, "bold"))

    def renumber_table(self):
        """重新为所有行分配序号"""
        for i, item in enumerate(self.tree.get_children(), 1):
            values = list(self.tree.item(item, "values"))
            values[0] = str(i)
            self.tree.item(item, values=values)

    def add_batch_dialog(self, process_type):
        """手动添加批次对话框（用于菜单）"""
        if process_type not in self.process_data:
            return
        process_data = self.process_data[process_type]

        # 检查是否超过上限
        if process_data.over_target_upper:
            messagebox.showerror("禁止操作",
                                 f"工艺 '{process_type}' 已超过上限 ({process_data.format_number(process_data.UPPER_LIMIT)})，请立即换液！")
            return

        dialog = tk.Toplevel()
        dialog.title(f"为 '{process_type}' 添加批次")
        dialog.geometry("350x250")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - dialog.winfo_width()) // 2
        y = (dialog.winfo_screenheight() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        tk.Label(dialog, text=f"当前累计: {process_data.format_number(process_data.total)}",
                 font=("Arial", 10)).pack(pady=10)

        tk.Label(dialog, text="批次号:", font=("Arial", 11)).pack()
        batch_var = tk.StringVar()
        batch_entry = tk.Entry(dialog, textvariable=batch_var, font=("Arial", 11), width=20)
        batch_entry.pack(pady=5)

        tk.Label(dialog, text="片数:", font=("Arial", 11)).pack()
        value_var = tk.StringVar()
        value_entry = tk.Entry(dialog, textvariable=value_var, font=("Arial", 11), width=15)
        value_entry.pack(pady=5)
        value_entry.focus_set()

        # 范围提示
        mode = process_data.input_mode
        if mode == "integer":
            range_text = f"整数范围: {self.integer_min}-{self.integer_max}"
        else:
            range_text = f"小数范围: {self.decimal_min}-{self.decimal_max} (两位)"
        tk.Label(dialog, text=range_text, font=("Arial", 9), fg="gray").pack()

        def validate_and_add():
            batch_id = batch_var.get().strip()
            if not batch_id:
                messagebox.showerror("错误", "请输入批次号", parent=dialog)
                return
            try:
                value_str = value_var.get().strip()
                if not value_str:
                    messagebox.showerror("错误", "请输入片数", parent=dialog)
                    return
                if mode == "integer":
                    value = int(value_str)
                    if value < self.integer_min or value > self.integer_max:
                        messagebox.showerror("错误", f"请输入{self.integer_min}~{self.integer_max}之间的整数",
                                             parent=dialog)
                        return
                else:
                    value = float(value_str)
                    if len(value_str.split('.')[-1]) > 2:
                        messagebox.showerror("错误", "最多两位小数", parent=dialog)
                        return
                    if value < self.decimal_min or value > self.decimal_max:
                        messagebox.showerror("错误", f"请输入{self.decimal_min}~{self.decimal_max}之间的小数",
                                             parent=dialog)
                        return
                    value = round(value, 2)

                # 添加批次前检查是否会超过上限
                new_total = process_data.total + value
                if new_total > process_data.UPPER_LIMIT:
                    if not messagebox.askyesno("警告",
                                               f"添加后累计值({process_data.format_number(new_total)})将超过上限({process_data.format_number(process_data.UPPER_LIMIT)})，确定要继续吗？",
                                               parent=dialog):
                        return

                process_data.add_batch(batch_id, value)
                process_data.save_data()
                self.refresh_table()
                self.keep_processes_at_top()

                # 添加后检查是否需要显示换液提醒
                reminder_type, reminder_message = process_data.check_liquid_change_reminder()
                if reminder_type == "强制":
                    messagebox.showerror("强制换液", reminder_message)
                elif reminder_type == "提醒":
                    messagebox.showwarning("换液提醒", reminder_message)

                if self.log_callback:
                    self.log_callback({
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "device_id": self.device_id,
                        "process_type": process_type,
                        "action": "手动添加批次",
                        "value": f"{batch_id}:{value}",
                        "total": process_data.total,
                        "target": process_data.TARGET,
                        "lower_limit": process_data.LOWER_LIMIT,
                        "upper_limit": process_data.UPPER_LIMIT,
                        "input_mode": process_data.input_mode
                    })

                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "输入无效的数字", parent=dialog)

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="确定", command=validate_and_add,
                  width=10, bg="#4CAF50", fg="white").pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", command=dialog.destroy,
                  width=10).pack(side="left", padx=5)

        dialog.bind("<Return>", lambda e: validate_and_add())

    def undo_process(self, process_type):
        """撤销单个工艺的上一步操作"""
        if process_type not in self.process_data:
            return
        process_data = self.process_data[process_type]
        if not process_data.can_undo():
            messagebox.showinfo("提示", "没有可撤销的操作")
            return

        undo_value = process_data.undo_last_action()
        process_data.save_data()
        self.refresh_table()

        if self.log_callback:
            self.log_callback({
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "device_id": self.device_id,
                "process_type": process_type,
                "action": "撤销",
                "value": undo_value,
                "total": process_data.total,
                "target": process_data.TARGET,
                "lower_limit": process_data.LOWER_LIMIT,
                "upper_limit": process_data.UPPER_LIMIT,
                "input_mode": process_data.input_mode
            })

    def set_initial_value(self):
        """为当前选中的工艺设置初始累计值"""
        # 检查是否选中了工艺
        if not self.current_selected_process:
            messagebox.showerror("错误", "请先在表格中点击选中一个工艺")
            return

        process_type = self.current_selected_process
        if process_type not in self.process_data:
            messagebox.showerror("错误", f"工艺 '{process_type}' 不存在")
            return

        # 验证密码
        if not self.verify_password(f"为工艺 '{process_type}' 设置初始值"):
            return

        process_data = self.process_data[process_type]

        # 检查是否已有批次
        if len(process_data.batches) > 0:
            if not messagebox.askyesno("确认",
                                       f"工艺 '{process_type}' 已有 {len(process_data.batches)} 个批次，累计值 {process_data.format_number(process_data.total)}。\n"
                                       f"设置初始值将清空所有现有批次，确定要继续吗？"):
                return

        dialog = tk.Toplevel()
        dialog.title(f"设置 '{process_type}' 初始累计值")
        dialog.geometry("350x200")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - dialog.winfo_width()) // 2
        y = (dialog.winfo_screenheight() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        info = f"工艺: {process_type}\n当前累计: {process_data.format_number(process_data.total)}"
        tk.Label(dialog, text=info, font=("Arial", 10), justify="left").pack(pady=10)

        tk.Label(dialog, text="请输入初始累计值:", font=("Arial", 11)).pack()
        value_var = tk.StringVar()
        entry = tk.Entry(dialog, textvariable=value_var, font=("Arial", 12), width=15)
        entry.pack(pady=10)
        entry.focus_set()

        # 显示范围提示
        mode = process_data.input_mode
        if mode == "integer":
            range_text = f"整数范围: {self.integer_min}~{self.integer_max}"
        else:
            range_text = f"小数范围: {self.decimal_min}~{self.decimal_max} (两位)"
        tk.Label(dialog, text=range_text, font=("Arial", 9), fg="gray").pack()

        def validate_and_set():
            try:
                value_str = value_var.get().strip()
                if not value_str:
                    messagebox.showerror("错误", "请输入初始累计值", parent=dialog)
                    return

                if mode == "integer":
                    value = int(value_str)
                    if value < 0:
                        messagebox.showerror("错误", "初始值不能为负数", parent=dialog)
                        return
                    if value < self.integer_min or value > self.integer_max:
                        if not messagebox.askyesno("警告",
                                                   f"输入的初始值 {value} 超出正常范围 ({self.integer_min}~{self.integer_max})，确定要继续吗？",
                                                   parent=dialog):
                            return
                else:
                    value = float(value_str)
                    if len(value_str.split('.')[-1]) > 2:
                        messagebox.showerror("错误", "最多两位小数", parent=dialog)
                        return
                    if value < 0:
                        messagebox.showerror("错误", "初始值不能为负数", parent=dialog)
                        return
                    if value < self.decimal_min or value > self.decimal_max:
                        if not messagebox.askyesno("警告",
                                                   f"输入的初始值 {value} 超出正常范围 ({self.decimal_min}~{self.decimal_max})，确定要继续吗？",
                                                   parent=dialog):
                            return
                    value = round(value, 2)

                # 清空现有批次
                old_batches = process_data.batches.copy()
                old_total = process_data.total

                # 记录操作（用于撤销）
                if old_batches:
                    process_data.operation_stack.append({
                        "type": "reset",
                        "previous_batches": old_batches
                    })

                # 清空批次
                process_data.batches = []

                # 添加一个特殊的初始批次，批次号固定为"样片"
                initial_batch_id = "样片"
                process_data.add_batch(initial_batch_id, value)
                process_data.save_data()

                # 重置换液提醒标志
                process_data.liquid_change_reminded = False
                process_data.check_target_limits()

                self.refresh_table()

                # 记录日志
                if self.log_callback:
                    self.log_callback({
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "device_id": self.device_id,
                        "process_type": process_type,
                        "action": "设置初始值",
                        "value": f"样片:{value}",
                        "total": value,
                        "target": process_data.TARGET,
                        "lower_limit": process_data.LOWER_LIMIT,
                        "upper_limit": process_data.UPPER_LIMIT,
                        "input_mode": process_data.input_mode
                    })

                    # 如果有旧的批次被清空，也记录一下
                    if old_batches:
                        self.log_callback({
                            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "device_id": self.device_id,
                            "process_type": process_type,
                            "action": "清空原有批次",
                            "value": f"清空了 {len(old_batches)} 个批次，原累计值 {process_data.format_number(old_total)}",
                            "total": value,
                            "target": process_data.TARGET,
                            "lower_limit": process_data.LOWER_LIMIT,
                            "upper_limit": process_data.UPPER_LIMIT,
                            "input_mode": process_data.input_mode
                        })

                # 检查是否需要显示换液提醒
                reminder_type, reminder_message = process_data.check_liquid_change_reminder()
                if reminder_type == "强制":
                    messagebox.showerror("强制换液", reminder_message, parent=dialog)
                elif reminder_type == "提醒":
                    messagebox.showwarning("换液提醒", reminder_message, parent=dialog)
                else:
                    messagebox.showinfo("成功",
                                        f"已为工艺 '{process_type}' 设置初始累计值: {process_data.format_number(value)}",
                                        parent=dialog)

                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "输入无效的数字", parent=dialog)

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="确定", command=validate_and_set,
                  width=10, bg="#4CAF50", fg="white").pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", command=dialog.destroy,
                  width=10).pack(side="left", padx=5)

        dialog.bind("<Return>", lambda e: validate_and_set())

    def set_initial_value_for_process(self, process_type):
        """为指定工艺设置初始值（菜单调用）"""
        self.current_selected_process = process_type
        self.set_initial_value()

    def clear_all_processes(self):
        """清空当前设备下所有工艺的所有批次（换液后使用），但保留工艺种类"""
        # 检查是否有工艺
        if not self.process_data:
            messagebox.showinfo("提示", "该设备下没有工艺")
            return

        # 验证密码
        if not self.verify_password("清空所有工艺的批次"):
            return

        # 计算总批次数量
        total_batches = sum(len(p.batches) for p in self.process_data.values())
        if total_batches == 0:
            messagebox.showinfo("提示", "所有工艺都没有批次记录")
            return

        # 确认清空
        if not messagebox.askyesno("确认清空",
                                   f"确定要清空设备 '{self.device_id}' 下所有工艺的批次吗？\n"
                                   f"将清空 {len(self.process_data)} 个工艺，共 {total_batches} 条批次记录\n"
                                   f"工艺种类将被保留"):
            return

        # 记录清空前每个工艺的累计值用于日志
        previous_totals = {}
        for process_type, process_data in self.process_data.items():
            previous_totals[process_type] = process_data.total

        # 清空所有工艺的批次，但保留工艺本身
        for process_type, process_data in self.process_data.items():
            # 记录操作（用于撤销）
            if process_data.total > 0:
                process_data.operation_stack.append({
                    "type": "reset",
                    "previous_batches": process_data.batches.copy()
                })

            # 清空批次，但保留工艺
            process_data.batches = []
            process_data.has_decimal = False
            process_data.liquid_change_reminded = False  # 重置换液提醒标志
            process_data.save_data()

        # 刷新表格 - 现在每个工艺会显示为空行（没有批次）
        self.refresh_table()

        # 将每个工艺的第一行（空行）保持在顶部
        self.keep_processes_at_top()

        # 记录日志
        if self.log_callback:
            # 为每个被清空的工艺记录日志
            for process_type, previous_total in previous_totals.items():
                if previous_total > 0:
                    self.log_callback({
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "device_id": self.device_id,
                        "process_type": process_type,
                        "action": "清空批次",
                        "value": f"清空所有批次",
                        "total": 0.0,
                        "target": self.process_data[process_type].TARGET,
                        "lower_limit": self.process_data[process_type].LOWER_LIMIT,
                        "upper_limit": self.process_data[process_type].UPPER_LIMIT,
                        "input_mode": self.process_data[process_type].input_mode
                    })

            # 添加一条汇总日志
            self.log_callback({
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "device_id": self.device_id,
                "process_type": "系统",
                "action": "批量清空",
                "value": f"清空了 {len(self.process_data)} 个工艺的批次，工艺种类已保留",
                "total": 0.0,
                "target": 0.0,
                "lower_limit": 0.0,
                "upper_limit": 0.0,
                "input_mode": ""
            })

        messagebox.showinfo("成功", f"已清空设备 '{self.device_id}' 下所有工艺的批次，工艺种类已保留")

    def reset_process(self, process_type):
        """重置单个工艺的所有批次"""
        if process_type not in self.process_data:
            return
        if not self.verify_password(f"重置工艺 '{process_type}' 的所有批次"):
            return

        process_data = self.process_data[process_type]
        if process_data.total == 0:
            messagebox.showinfo("提示", "累计值已经是0")
            return

        previous_total = process_data.reset_total()
        process_data.save_data()
        self.refresh_table()

        if self.log_callback:
            self.log_callback({
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "device_id": self.device_id,
                "process_type": process_type,
                "action": "重置",
                "value": previous_total,
                "total": 0.0,
                "target": process_data.TARGET,
                "lower_limit": process_data.LOWER_LIMIT,
                "upper_limit": process_data.UPPER_LIMIT,
                "input_mode": process_data.input_mode
            })

    def set_target_dialog(self, process_type):
        """设置单个工艺的换液目标值对话框"""
        if process_type not in self.process_data:
            return
        if not self.verify_password(f"设置工艺 '{process_type}' 的换液目标值"):
            return

        process_data = self.process_data[process_type]
        target_dialog = tk.Toplevel()
        target_dialog.title(f"设置 '{process_type}' 换液目标值")
        target_dialog.geometry("300x150")
        target_dialog.resizable(False, False)
        target_dialog.transient(self)
        target_dialog.grab_set()
        target_dialog.update_idletasks()
        x = (target_dialog.winfo_screenwidth() - target_dialog.winfo_width()) // 2
        y = (target_dialog.winfo_screenheight() - target_dialog.winfo_height()) // 2
        target_dialog.geometry(f"+{x}+{y}")

        tk.Label(target_dialog, text=f"当前换液目标值: {process_data.format_number(process_data.TARGET)}",
                 font=("Arial", 11)).pack(pady=10)
        tk.Label(target_dialog, text="请输入新的换液目标值:", font=("Arial", 11)).pack()

        target_var = tk.StringVar(value=f"{process_data.TARGET:.2f}")
        entry = tk.Entry(target_dialog, textvariable=target_var, font=("Arial", 11), width=15)
        entry.pack(pady=10)
        entry.select_range(0, tk.END)
        entry.focus_set()

        def validate_and_close():
            try:
                new_target = float(target_var.get())
                if new_target < 0:
                    messagebox.showerror("输入错误", "换液目标值不能小于0", parent=target_dialog)
                    return
                new_target = round(new_target, 2)
                old_target = process_data.set_target(new_target)
                process_data.save_data()
                self.refresh_table()

                if self.log_callback:
                    self.log_callback({
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "device_id": self.device_id,
                        "process_type": process_type,
                        "action": "设置换液目标值",
                        "value": f"{old_target:.2f}→{new_target:.2f}",
                        "total": process_data.total,
                        "target": new_target,
                        "lower_limit": process_data.LOWER_LIMIT,
                        "upper_limit": process_data.UPPER_LIMIT,
                        "input_mode": process_data.input_mode
                    })
                target_dialog.destroy()
            except ValueError:
                messagebox.showerror("输入错误", "请输入有效的数字", parent=target_dialog)

        button_frame = tk.Frame(target_dialog)
        button_frame.pack(pady=10)
        tk.Button(button_frame, text="确定", command=validate_and_close,
                  width=10, bg="#2196F3", fg="white").pack(side="left", padx=5)
        tk.Button(button_frame, text="取消", command=target_dialog.destroy,
                  width=10).pack(side="left", padx=5)
        target_dialog.bind("<Return>", lambda e: validate_and_close())

    def set_lower_limit_dialog(self, process_type):
        """设置单个工艺的下限对话框"""
        if process_type not in self.process_data:
            return
        if not self.verify_password(f"设置工艺 '{process_type}' 的下限"):
            return

        process_data = self.process_data[process_type]
        limit_dialog = tk.Toplevel()
        limit_dialog.title(f"设置 '{process_type}' 下限")
        limit_dialog.geometry("300x150")
        limit_dialog.resizable(False, False)
        limit_dialog.transient(self)
        limit_dialog.grab_set()
        limit_dialog.update_idletasks()
        x = (limit_dialog.winfo_screenwidth() - limit_dialog.winfo_width()) // 2
        y = (limit_dialog.winfo_screenheight() - limit_dialog.winfo_height()) // 2
        limit_dialog.geometry(f"+{x}+{y}")

        tk.Label(limit_dialog, text=f"当前下限: {process_data.format_number(process_data.LOWER_LIMIT)}",
                 font=("Arial", 11)).pack(pady=10)
        tk.Label(limit_dialog, text="请输入新的下限值:", font=("Arial", 11)).pack()

        limit_var = tk.StringVar(value=f"{process_data.LOWER_LIMIT:.2f}")
        entry = tk.Entry(limit_dialog, textvariable=limit_var, font=("Arial", 11), width=15)
        entry.pack(pady=10)
        entry.select_range(0, tk.END)
        entry.focus_set()

        def validate_and_close():
            try:
                new_lower_limit = float(limit_var.get())
                if new_lower_limit < 0:
                    messagebox.showerror("输入错误", "下限不能小于0", parent=limit_dialog)
                    return
                new_lower_limit = round(new_lower_limit, 2)
                old_lower_limit = process_data.set_lower_limit(new_lower_limit)
                process_data.save_data()
                self.refresh_table()

                if self.log_callback:
                    self.log_callback({
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "device_id": self.device_id,
                        "process_type": process_type,
                        "action": "设置下限",
                        "value": f"{old_lower_limit:.2f}→{new_lower_limit:.2f}",
                        "total": process_data.total,
                        "target": process_data.TARGET,
                        "lower_limit": new_lower_limit,
                        "upper_limit": process_data.UPPER_LIMIT,
                        "input_mode": process_data.input_mode
                    })
                limit_dialog.destroy()
            except ValueError:
                messagebox.showerror("输入错误", "请输入有效的数字", parent=limit_dialog)

        button_frame = tk.Frame(limit_dialog)
        button_frame.pack(pady=10)
        tk.Button(button_frame, text="确定", command=validate_and_close,
                  width=10, bg="#2196F3", fg="white").pack(side="left", padx=5)
        tk.Button(button_frame, text="取消", command=limit_dialog.destroy,
                  width=10).pack(side="left", padx=5)
        limit_dialog.bind("<Return>", lambda e: validate_and_close())

    def set_upper_limit_dialog(self, process_type):
        """设置单个工艺的上限对话框"""
        if process_type not in self.process_data:
            return
        if not self.verify_password(f"设置工艺 '{process_type}' 的上限"):
            return

        process_data = self.process_data[process_type]
        limit_dialog = tk.Toplevel()
        limit_dialog.title(f"设置 '{process_type}' 上限")
        limit_dialog.geometry("300x150")
        limit_dialog.resizable(False, False)
        limit_dialog.transient(self)
        limit_dialog.grab_set()
        limit_dialog.update_idletasks()
        x = (limit_dialog.winfo_screenwidth() - limit_dialog.winfo_width()) // 2
        y = (limit_dialog.winfo_screenheight() - limit_dialog.winfo_height()) // 2
        limit_dialog.geometry(f"+{x}+{y}")

        tk.Label(limit_dialog, text=f"当前上限: {process_data.format_number(process_data.UPPER_LIMIT)}",
                 font=("Arial", 11)).pack(pady=10)
        tk.Label(limit_dialog, text="请输入新的上限值:", font=("Arial", 11)).pack()

        limit_var = tk.StringVar(value=f"{process_data.UPPER_LIMIT:.2f}")
        entry = tk.Entry(limit_dialog, textvariable=limit_var, font=("Arial", 11), width=15)
        entry.pack(pady=10)
        entry.select_range(0, tk.END)
        entry.focus_set()

        def validate_and_close():
            try:
                new_upper_limit = float(limit_var.get())
                if new_upper_limit < 0:
                    messagebox.showerror("输入错误", "上限不能小于0", parent=limit_dialog)
                    return
                new_upper_limit = round(new_upper_limit, 2)
                old_upper_limit = process_data.set_upper_limit(new_upper_limit)
                process_data.save_data()
                self.refresh_table()

                if self.log_callback:
                    self.log_callback({
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "device_id": self.device_id,
                        "process_type": process_type,
                        "action": "设置上限",
                        "value": f"{old_upper_limit:.2f}→{new_upper_limit:.2f}",
                        "total": process_data.total,
                        "target": process_data.TARGET,
                        "lower_limit": process_data.LOWER_LIMIT,
                        "upper_limit": new_upper_limit,
                        "input_mode": process_data.input_mode
                    })
                limit_dialog.destroy()
            except ValueError:
                messagebox.showerror("输入错误", "请输入有效的数字", parent=limit_dialog)

        button_frame = tk.Frame(limit_dialog)
        button_frame.pack(pady=10)
        tk.Button(button_frame, text="确定", command=validate_and_close,
                  width=10, bg="#2196F3", fg="white").pack(side="left", padx=5)
        tk.Button(button_frame, text="取消", command=limit_dialog.destroy,
                  width=10).pack(side="left", padx=5)
        limit_dialog.bind("<Return>", lambda e: validate_and_close())

    def change_input_mode(self, process_type):
        """切换单个工艺的输入模式"""
        if process_type not in self.process_data:
            return
        if not self.verify_password(f"切换工艺 '{process_type}' 的输入模式"):
            return

        process_data = self.process_data[process_type]
        new_mode = "decimal" if process_data.input_mode == "integer" else "integer"
        old_mode = process_data.input_mode
        process_data.input_mode = new_mode
        process_data.save_data()
        self.refresh_table()

        if self.log_callback:
            self.log_callback({
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "device_id": self.device_id,
                "process_type": process_type,
                "action": "切换输入模式",
                "value": f"{old_mode}→{new_mode}",
                "total": process_data.total,
                "target": process_data.TARGET,
                "lower_limit": process_data.LOWER_LIMIT,
                "upper_limit": process_data.UPPER_LIMIT,
                "input_mode": new_mode
            })
        messagebox.showinfo("成功", f"已将 '{process_type}' 的输入模式切换为{new_mode}模式")

    def delete_single_process(self, process_type):
        """删除单个工艺及其所有批次"""
        if process_type not in self.process_data:
            return
        if not self.verify_password(f"删除工艺 '{process_type}'"):
            return
        if not messagebox.askyesno("确认删除", f"确定要删除工艺 '{process_type}' 及其所有批次吗？"):
            return

        # 删除数据文件
        data_file = os.path.join(self.data_dir, f"counter_data_{self.device_id}_{process_type}.json")
        try:
            if os.path.exists(data_file):
                os.remove(data_file)
        except Exception as e:
            print(f"删除数据文件失败: {e}")

        del self.process_data[process_type]
        self.refresh_table()

        if self.log_callback:
            self.log_callback({
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "device_id": self.device_id,
                "process_type": process_type,
                "action": "删除工艺",
                "value": "",
                "total": 0.0,
                "target": 0.0,
                "lower_limit": 0.0,
                "upper_limit": 0.0,
                "input_mode": ""
            })

    def delete_device(self):
        """删除整个设备"""
        if not self.verify_password("删除设备"):
            return
        if not messagebox.askyesno("确认删除", f"确定要删除设备 '{self.device_id}' 及其所有工艺吗？"):
            return
        if self.delete_callback:
            self.delete_callback(self.device_id)

    def load_existing_processes(self):
        """加载已存在的工艺（从文件）"""
        try:
            self.loading_from_file = True
            for filename in os.listdir(self.data_dir):
                if filename.startswith(f"counter_data_{self.device_id}_") and filename.endswith(".json"):
                    parts = filename.replace("counter_data_", "").replace(".json", "").split("_")
                    if len(parts) >= 2 and parts[0] == self.device_id:
                        process_type = "_".join(parts[1:])
                        data_file = os.path.join(self.data_dir, filename)
                        with open(data_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        input_mode = data.get("input_mode", "integer")
                        # 从文件加载时不添加初始批次，使用原有的批次数据
                        self.create_process_data(process_type, input_mode)  # 不传递批次参数
            delattr(self, 'loading_from_file')
        except Exception as e:
            print(f"加载工艺错误 (设备: {self.device_id}): {e}")
            traceback.print_exc()
            if hasattr(self, 'loading_from_file'):
                delattr(self, 'loading_from_file')

    def verify_password(self, action_name):
        """验证密码"""
        password = simpledialog.askstring("密码验证", f"请输入密码以{action_name}:", show='*')
        if password and self.password_manager and self.password_manager.verify_password(password):
            return True
        else:
            messagebox.showerror("密码错误", "密码不正确，操作取消")
            return False


class NotepadFrame(tk.Frame):
    """写字板区域（与原代码相同）"""

    def __init__(self, master, data_dir=None):
        super().__init__(master)
        self.data_dir = data_dir
        self.base_path, _ = get_app_base_path()
        self.setup_ui()
        if self.data_dir:
            self.NOTES_FILE = os.path.join(self.data_dir, "notepad_notes.txt")
        else:
            self.NOTES_FILE = os.path.join(self.base_path, "notepad_notes.txt")
        self.load_notes()

    def setup_ui(self):
        header_frame = tk.Frame(self)
        header_frame.pack(fill="x", pady=(0, 5))
        tk.Label(header_frame, text="写字板", font=("Arial", 12, "bold")).pack(side="left")
        btn_frame = tk.Frame(header_frame)
        btn_frame.pack(side="right")
        buttons = [
            ("保存", self.save_notes, "#4CAF50"),
            ("清空", self.clear_notes, "#F44336"),
            ("加载文件", self.load_file, "#2196F3"),
            ("另存为", self.save_as, "#FF9800")
        ]
        for text, command, color in buttons:
            tk.Button(
                btn_frame,
                text=text,
                command=command,
                font=("Arial", 9),
                width=8,
                bg=color,
                fg="white",
                relief="raised",
                bd=2
            ).pack(side="left", padx=2)

        text_frame = tk.Frame(self)
        text_frame.pack(fill="both", expand=True)
        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        self.text_area = tk.Text(
            text_frame,
            font=("Microsoft YaHei", 10),
            wrap="word",
            yscrollcommand=scrollbar.set,
            bg="#f8f8f8",
            relief="solid",
            bd=1,
            padx=10,
            pady=10
        )
        self.text_area.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.text_area.yview)
        self.status_bar = tk.Label(self, text="就绪", bd=1, relief=tk.SUNKEN, anchor=tk.W,
                                   font=("Arial", 9))
        self.status_bar.pack(fill="x", pady=(5, 0))

    def save_notes(self):
        try:
            content = self.text_area.get(1.0, tk.END)
            with open(self.NOTES_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            self.status_bar.config(text=f"已保存: {datetime.datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            messagebox.showerror("保存错误", f"保存失败: {e}")

    def load_notes(self):
        try:
            if os.path.exists(self.NOTES_FILE):
                with open(self.NOTES_FILE, "r", encoding="utf-8") as f:
                    content = f.read()
                self.text_area.delete(1.0, tk.END)
                self.text_area.insert(1.0, content)
                self.status_bar.config(text="已加载笔记")
        except Exception as e:
            print(f"加载笔记错误: {e}")

    def clear_notes(self):
        if messagebox.askyesno("确认", "确定要清空写字板内容吗？"):
            self.text_area.delete(1.0, tk.END)
            self.status_bar.config(text="已清空")

    def load_file(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.text_area.delete(1.0, tk.END)
                self.text_area.insert(1.0, content)
                self.status_bar.config(text=f"已加载: {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("加载错误", f"加载文件失败: {e}")

    def save_as(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile=f"notes_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        if file_path:
            try:
                content = self.text_area.get(1.0, tk.END)
                with open(file_path, "w", encoding="utf-8-sig") as f:
                    f.write(content)
                self.status_bar.config(text=f"已保存到: {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("保存错误", f"保存失败: {e}")


class MainApplication:
    """主应用程序（与原代码相同）"""

    def __init__(self, root):
        self.root = root
        self.root.title("多设备累计监控系统")
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        window_width = 1400
        window_height = 800
        x_position = (screen_width - window_width) // 2
        y_position = (screen_height - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")

        self.base_path, self.data_dir = get_app_base_path()
        print(f"程序路径: {self.base_path}")
        print(f"数据目录: {self.data_dir}")

        self.password_manager = PasswordManager(self.base_path, self.data_dir)

        self.log_entries: List[Dict] = []
        self.LOG_FILE = os.path.join(self.data_dir, "combined_logs.json")
        self.HISTORY_LOG_FILE = os.path.join(self.data_dir, "history_logs.json")
        self.load_logs()

        self.device_counter = 0
        self.device_tabs = {}  # {device_id: {"frame": frame, "tab": tab, ...}}
        self.device_colors = {}

        self.create_main_interface()
        self.load_existing_devices()
        if not self.device_tabs:
            self.create_initial_devices()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.display_logs()
        self.update_stats()

    def load_existing_devices(self):
        try:
            device_set = set()
            for filename in os.listdir(self.data_dir):
                if filename.startswith("counter_data_") and filename.endswith(".json"):
                    parts = filename.replace("counter_data_", "").replace(".json", "").split("_")
                    if parts:
                        device_set.add(parts[0])
            for device_id in device_set:
                self.create_device_tab(device_id)
        except Exception as e:
            print(f"加载已存在设备错误: {e}")
            traceback.print_exc()

    def create_device_tab(self, device_id):
        self.device_counter += 1
        tab_frame = tk.Frame(self.notebook)
        device_tab = DeviceTab(tab_frame, device_id, self.device_counter * 1000,
                               self.add_log_entry, self.delete_device,
                               self.password_manager, self.data_dir)
        device_tab.pack(fill="both", expand=True, padx=10, pady=10)

        color_index = self.get_color_for_device(device_id)
        tab_name = f"设备: {device_id}"
        self.notebook.add(tab_frame, text=tab_name)
        self.device_tabs[device_id] = {
            "frame": tab_frame,
            "tab": device_tab,
            "tab_name": tab_name,
            "color_index": color_index
        }
        try:
            style = ttk.Style()
            style_name = f"ColorTab{color_index}"
            style.configure(style_name, background=self.get_color_by_index(color_index))
            self.notebook.tab(tab_frame, style=style_name)
        except:
            pass

    def get_color_for_device(self, device_id):
        if device_id not in self.device_colors:
            hash_value = hash(device_id) % 20
            self.device_colors[device_id] = hash_value
        return self.device_colors[device_id]

    def get_color_by_index(self, index):
        colors = ["#E1F5FE", "#F3E5F5", "#E8F5E8", "#FFF3E0",
                  "#FCE4EC", "#F3F5F9", "#E0F7FA", "#F1F8E9",
                  "#FFF8E1", "#EDE7F6", "#E8EAF6", "#E0F2F1",
                  "#F1F8E9", "#F9FBE7", "#FFFDE7", "#FFF3E0",
                  "#FFEBEE", "#FCE4EC", "#F3E5F5", "#EDE7F6"]
        return colors[index % len(colors)]

    def verify_password(self, action_name, show_message=True):
        password = simpledialog.askstring("密码验证", f"请输入密码以{action_name}:", show='*')
        if password and self.password_manager.verify_password(password):
            return True
        else:
            if show_message:
                messagebox.showerror("密码错误", "密码不正确，操作取消")
            return False

    def change_password(self):
        if not self.verify_password("修改密码", show_message=False):
            messagebox.showerror("密码错误", "当前密码不正确，无法修改密码")
            return
        new_password = simpledialog.askstring("修改密码", "请输入新密码:", show='*')
        if not new_password or len(new_password.strip()) == 0:
            messagebox.showerror("输入错误", "新密码不能为空")
            return
        confirm_password = simpledialog.askstring("确认密码", "请再次输入新密码:", show='*')
        if new_password != confirm_password:
            messagebox.showerror("密码错误", "两次输入的密码不一致")
            return
        success, message = self.password_manager.change_password(self.password_manager.current_password, new_password)
        if success:
            messagebox.showinfo("成功", "密码修改成功")
        else:
            messagebox.showerror("错误", message)

    def create_main_interface(self):
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        top_frame = tk.Frame(main_frame)
        top_frame.pack(fill="x", pady=(0, 10))
        tk.Label(top_frame, text="设备监控系统", font=("Arial", 16, "bold")).pack(side="left")

        button_frame = tk.Frame(top_frame)
        button_frame.pack(side="right")
        change_pwd_btn = tk.Button(
            button_frame,
            text="修改密码",
            command=self.change_password,
            font=("Arial", 11),
            bg="#FF9800",
            fg="white",
            height=1,
            width=10,
            relief="raised",
            bd=2
        )
        change_pwd_btn.pack(side="left", padx=(0, 5))
        add_btn = tk.Button(
            button_frame,
            text="+ 添加设备",
            command=self.add_device,
            font=("Arial", 11, "bold"),
            bg="#4CAF50",
            fg="white",
            height=1,
            width=12,
            relief="raised",
            bd=2
        )
        add_btn.pack(side="left")

        middle_frame = tk.Frame(main_frame)
        middle_frame.pack(fill="both", expand=True, pady=(0, 10))

        left_frame = tk.Frame(middle_frame, width=900)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self.notebook = ttk.Notebook(left_frame)
        self.notebook.pack(fill="both", expand=True)

        right_frame = tk.Frame(middle_frame, width=450)
        right_frame.pack(side="right", fill="both", expand=False)
        self.create_log_area(right_frame)

        bottom_frame = tk.Frame(main_frame)
        bottom_frame.pack(fill="both", expand=True)
        self.create_notepad(bottom_frame)

    def create_log_area(self, parent):
        log_header = tk.Frame(parent)
        log_header.pack(fill="x", pady=(0, 5))
        tk.Label(log_header, text="综合操作日志", font=("Arial", 14, "bold")).pack(side="left")
        btn_frame = tk.Frame(log_header)
        btn_frame.pack(side="right")
        btn_row1 = tk.Frame(btn_frame)
        btn_row1.pack(side="top", pady=(0, 2))
        btn_row2 = tk.Frame(btn_frame)
        btn_row2.pack(side="top")
        log_buttons = [
            ("清空日志", self.clear_logs, "#F44336", btn_row1),
            ("导出日志", self.export_logs, "#4CAF50", btn_row1),
            ("导出历史", self.export_history_logs, "#FF9800", btn_row1),
            ("刷新", self.refresh_logs, "#2196F3", btn_row2),
            ("显示全部", self.show_all_logs, "#9C27B0", btn_row2)
        ]
        for text, command, color, row_frame in log_buttons:
            tk.Button(
                row_frame,
                text=text,
                command=command,
                font=("Arial", 9),
                width=8,
                bg=color,
                fg="white",
                relief="raised",
                bd=2
            ).pack(side="left", padx=2)

        log_frame = tk.LabelFrame(parent, text="日志内容", padx=10, pady=10,
                                  font=("Arial", 11, "bold"))
        log_frame.pack(fill="both", expand=True)
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            font=("Consolas", 9),
            width=50,
            height=15,
            state=tk.DISABLED
        )
        self.log_text.pack(fill="both", expand=True)

        stats_frame = tk.LabelFrame(parent, text="统计信息", padx=10, pady=10,
                                    font=("Arial", 11, "bold"))
        stats_frame.pack(fill="x", pady=(10, 0))
        self.stats_label = tk.Label(
            stats_frame,
            text="日志总数: 0\n活跃设备: 0\n历史日志: 0条\n设备数量: 0个",
            font=("Arial", 9),
            justify="left",
            anchor="w"
        )
        self.stats_label.pack(anchor="w", fill="x")

    def create_initial_devices(self):
        for i in range(2):
            self.add_device(initial=True)

    def add_device(self, initial=False):
        if not initial and not self.verify_password("添加设备"):
            return
        device_id = simpledialog.askstring("添加设备", "请输入设备号:")
        if not device_id:
            return
        if device_id in self.device_tabs:
            messagebox.showerror("错误", f"设备号 '{device_id}' 已存在")
            return
        self.create_device_tab(device_id)
        self.notebook.select(len(self.notebook.tabs()) - 1)
        self.add_log_entry({
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "device_id": device_id,
            "process_type": "系统",
            "action": "添加设备",
            "value": "",
            "total": 0.0,
            "target": 0.0,
            "lower_limit": 0.0,
            "upper_limit": 0.0,
            "input_mode": ""
        })
        self.update_stats()

    def delete_device(self, device_id):
        if device_id in self.device_tabs:
            for i, tab in enumerate(self.notebook.tabs()):
                if self.notebook.nametowidget(tab) == self.device_tabs[device_id]["frame"]:
                    self.notebook.forget(i)
                    break
            try:
                for filename in os.listdir(self.data_dir):
                    if filename.startswith(f"counter_data_{device_id}_") and filename.endswith(".json"):
                        os.remove(os.path.join(self.data_dir, filename))
            except Exception as e:
                print(f"删除数据文件失败: {e}")
            del self.device_tabs[device_id]
            self.add_log_entry({
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "device_id": device_id,
                "process_type": "系统",
                "action": "删除设备",
                "value": "",
                "total": 0.0,
                "target": 0.0,
                "lower_limit": 0.0,
                "upper_limit": 0.0,
                "input_mode": ""
            })
            self.update_stats()

    def create_notepad(self, parent):
        notepad_frame = tk.LabelFrame(parent, text="写字板", font=("Arial", 12, "bold"),
                                      bd=2, relief=tk.GROOVE, padx=10, pady=10)
        notepad_frame.pack(fill="both", expand=True)
        self.notepad = NotepadFrame(notepad_frame, self.data_dir)
        self.notepad.pack(fill="both", expand=True)

    def add_log_entry(self, log_entry: Dict):
        self.log_entries.append(log_entry)
        if len(self.log_entries) > 1000:
            self.save_history_logs(self.log_entries[:100])
            self.log_entries = self.log_entries[-900:]
        self.save_logs()
        self.display_logs()
        self.update_stats()

    def save_logs(self):
        try:
            with open(self.LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.log_entries, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            print(f"保存日志错误: {e}")

    def load_logs(self):
        try:
            if os.path.exists(self.LOG_FILE):
                with open(self.LOG_FILE, "r", encoding="utf-8") as f:
                    self.log_entries = json.load(f)
            else:
                self.log_entries = []
            self.history_logs = []
            if os.path.exists(self.HISTORY_LOG_FILE):
                with open(self.HISTORY_LOG_FILE, "r", encoding="utf-8") as f:
                    self.history_logs = json.load(f)
        except Exception as e:
            print(f"加载日志错误: {e}")
            self.log_entries = []
            self.history_logs = []

    def save_history_logs(self, old_logs):
        try:
            existing_history = []
            if os.path.exists(self.HISTORY_LOG_FILE):
                with open(self.HISTORY_LOG_FILE, "r", encoding="utf-8") as f:
                    existing_history = json.load(f)
            existing_history.extend(old_logs)
            if len(existing_history) > 5000:
                existing_history = existing_history[-5000:]
            with open(self.HISTORY_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(existing_history, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            print(f"保存历史日志错误: {e}")

    def display_logs(self, show_all=False):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        logs_to_show = self.log_entries if show_all else self.log_entries[-100:]
        for entry in logs_to_show:
            timestamp = entry.get("timestamp", "")
            device_id = entry.get("device_id", "")
            process_type = entry.get("process_type", "")
            value = entry.get("value", "")  # 格式如 "批量20260225183131_1:1"
            total = entry.get("total", "")

            # 从value字段中提取批次号和片数（如果有冒号）
            batch_id = ""
            pieces = ""
            if ":" in str(value):
                parts = str(value).split(":", 1)
                batch_id = parts[0]
                pieces = parts[1]
            else:
                batch_id = value

            # 格式化累计值
            try:
                total_formatted = self.format_number_for_display(total)
            except:
                total_formatted = str(total)

            # 构建新的日志格式：时间、设备号、工艺类型、批次号、片数、累计值
            log_line = f"[{timestamp}] {device_id} {process_type} “{batch_id}” {pieces} {total_formatted}\n"

            # 设置颜色（按设备区分）
            colors = ["black", "blue", "green", "red", "purple", "orange", "brown", "gray"]
            color_index = hash(device_id) % len(colors) if device_id else 0
            color = colors[color_index]
            self.log_text.insert(tk.END, log_line, color)

        self.log_text.config(state=tk.DISABLED)
        self.log_text.yview(tk.END)

        # 配置颜色标签
        colors = ["black", "blue", "green", "red", "purple", "orange", "brown", "gray"]
        for i, color in enumerate(colors):
            self.log_text.tag_config(color, foreground=color)

    def format_number_for_display(self, num):
        if num is None:
            return ""
        try:
            num_float = float(num)
            if num_float == int(num_float):
                return str(int(num_float))
            else:
                return f"{num_float:.2f}"
        except (ValueError, TypeError):
            return str(num)

    def show_all_logs(self):
        self.display_logs(show_all=True)

    def update_stats(self):
        total_logs = len(self.log_entries)
        unique_devices = set(entry.get("device_id", "") for entry in self.log_entries[-100:])
        active_devices = len(unique_devices)
        process_count = 0
        for device_id, device_info in self.device_tabs.items():
            process_count += len(device_info["tab"].process_data)
        history_logs_count = len(self.history_logs) if hasattr(self, 'history_logs') else 0
        stats_text = f"日志总数: {total_logs}\n"
        stats_text += f"活跃设备: {active_devices}\n"
        stats_text += f"设备数量: {len(self.device_tabs)}\n"
        stats_text += f"工艺数量: {process_count}\n"
        stats_text += f"历史日志: {history_logs_count}条\n"
        self.stats_label.config(text=stats_text)

    def clear_logs(self):
        if not self.verify_password("清空日志"):
            return
        if messagebox.askyesno("确认", "确定要清空所有日志吗？"):
            self.log_entries = []
            self.save_logs()
            self.display_logs()
            self.update_stats()

    def export_logs(self):
        if not self.verify_password("导出当前日志"):
            return
        if not self.log_entries:
            messagebox.showinfo("提示", "没有日志可导出")
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV文件", "*.csv"), ("JSON文件", "*.json"), ("文本文件", "*.txt")],
            initialfile=f"current_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        if not file_path:
            return
        if file_path.endswith('.csv'):
            self.export_to_csv(file_path, self.log_entries)
        elif file_path.endswith('.json'):
            self.export_to_json(file_path, self.log_entries)
        else:
            self.export_to_txt(file_path, self.log_entries)
        messagebox.showinfo("成功", f"当前日志已导出到:\n{file_path}")

    def export_history_logs(self):
        if not self.verify_password("导出历史日志"):
            return
        all_logs = []
        if hasattr(self, 'history_logs'):
            all_logs.extend(self.history_logs)
        all_logs.extend(self.log_entries)
        if not all_logs:
            messagebox.showinfo("提示", "没有历史日志可导出")
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV文件", "*.csv"), ("JSON文件", "*.json"), ("文本文件", "*.txt")],
            initialfile=f"all_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        if not file_path:
            return
        if file_path.endswith('.csv'):
            self.export_to_csv(file_path, all_logs)
        elif file_path.endswith('.json'):
            self.export_to_json(file_path, all_logs)
        else:
            self.export_to_txt(file_path, all_logs)
        messagebox.showinfo("成功", f"所有日志（含历史）已导出到:\n{file_path}")

    def export_to_csv(self, file_path: str, logs):
        """导出日志到CSV文件，包含时间、设备号、工艺类型、批次号、片数、累计值"""
        try:
            with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
                if logs:
                    # 定义需要保留的核心字段
                    core_fields = [
                        "timestamp",      # 时间
                        "device_id",      # 设备号
                        "process_type",   # 工艺类型
                        "value",          # 批次号（含片数）
                        "total"           # 累计值
                    ]

                    # 字段名到中文表头的映射
                    header_mapping = {
                        "timestamp": "时间",
                        "device_id": "设备号",
                        "process_type": "工艺类型",
                        "value": "批次号",
                        "pieces": "片数",  # 新增片数列
                        "total": "累计值"
                    }

                    # 创建中文表头列表（调整顺序）
                    chinese_headers = ["时间", "设备号", "工艺类型", "批次号", "片数", "累计值"]
                    
                    # 写入中文表头
                    writer = csv.writer(f)
                    writer.writerow(chinese_headers)

                    # 写入数据行
                    for row in logs:
                        # 提取字段值
                        timestamp = row.get("timestamp", "")
                        device_id = row.get("device_id", "")
                        process_type = row.get("process_type", "")
                        value = row.get("value", "")
                        total = row.get("total", "")

                        # 从value字段中分离批次号和片数
                        batch_id = ""
                        pieces = ""
                        if ":" in str(value):
                            parts = str(value).split(":", 1)
                            batch_id = parts[0]
                            pieces = parts[1]
                        else:
                            batch_id = value

                        # 格式化累计值
                        try:
                            total_float = float(total)
                            if total_float == int(total_float):
                                total_formatted = str(int(total_float))
                            else:
                                total_formatted = f"{total_float:.2f}"
                        except (ValueError, TypeError):
                            total_formatted = str(total)

                        # 写入行数据（按新顺序）
                        writer.writerow([
                            timestamp,
                            device_id,
                            process_type,
                            batch_id,
                            pieces,
                            total_formatted
                        ])

            messagebox.showinfo("成功", f"导出成功")
        except Exception as e:
            messagebox.showerror("导出错误", f"导出CSV失败: {e}")

    def export_to_txt(self, file_path: str, logs):
        try:
            with open(file_path, 'w', encoding='utf-8-sig') as f:
                for entry in logs:
                    timestamp = entry.get('timestamp', '')
                    device_id = entry.get('device_id', '')
                    process_type = entry.get('process_type', '')
                    value = entry.get('value', '')
                    total = entry.get('total', '')

                    # 从value字段中分离批次号和片数
                    batch_id = ""
                    pieces = ""
                    if ":" in str(value):
                        parts = str(value).split(":", 1)
                        batch_id = parts[0]
                        pieces = parts[1]
                    else:
                        batch_id = value

                    # 格式化累计值
                    try:
                        total_float = float(total)
                        if total_float == int(total_float):
                            total_formatted = str(int(total_float))
                        else:
                            total_formatted = f"{total_float:.2f}"
                    except (ValueError, TypeError):
                        total_formatted = str(total)

                    # 按新顺序写入：时间、设备号、工艺类型、批次号、片数、累计值
                    line = f"{timestamp}\t{device_id}\t{process_type}\t{batch_id}\t{pieces}\t{total_formatted}\n"
                    f.write(line)
        except Exception as e:
            messagebox.showerror("导出错误", f"导出TXT失败: {e}")

    def export_to_json(self, file_path: str, logs):
        """导出日志到JSON文件，只保留核心字段"""
        try:
            # 定义需要保留的核心字段
            core_fields = [
                "timestamp", "device_id", "process_type", "value", "total"
            ]

            # 过滤每条日志，只保留核心字段
            filtered_logs = []
            for entry in logs:
                filtered_entry = {}
                for field in core_fields:
                    if field in entry:
                        filtered_entry[field] = entry[field]
                
                # 添加片数字段
                value = filtered_entry.get("value", "")
                if ":" in str(value):
                    parts = str(value).split(":", 1)
                    filtered_entry["batch_id"] = parts[0]
                    filtered_entry["pieces"] = parts[1]
                else:
                    filtered_entry["batch_id"] = value
                    filtered_entry["pieces"] = ""
                
                filtered_logs.append(filtered_entry)

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(filtered_logs, f, indent=2, ensure_ascii=False, default=str)

            messagebox.showinfo("成功", f"JSON文件已导出，只保留核心字段")
        except Exception as e:
            messagebox.showerror("导出错误", f"导出JSON失败: {e}")

    def refresh_logs(self):
        self.display_logs()
        self.update_stats()

    def on_closing(self):
        password = simpledialog.askstring("密码验证", "请输入密码以退出程序:", show='*')
        if not password or not self.password_manager.verify_password(password):
            messagebox.showerror("密码错误", "密码不正确，无法退出程序")
            return
        for device_id, device_info in self.device_tabs.items():
            for process_type, process_data in device_info["tab"].process_data.items():
                process_data.save_data()
        self.notepad.save_notes()
        self.save_logs()
        if messagebox.askokcancel("退出", "确定要退出程序吗？"):
            self.root.destroy()


def main():
    root = tk.Tk()
    app = MainApplication(root)
    root.mainloop()


if __name__ == "__main__":
    main()

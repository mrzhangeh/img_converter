import os
import shutil
import zipfile
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image
from concurrent.futures import ThreadPoolExecutor
import tempfile
import threading
from queue import Queue
import time

class ZipToImageConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("ZIP 图片转 WebP/AVIF 工具")
        self.root.geometry("650x480")
        self.root.resizable(False, False)

        # 核心变量
        self.temp_dir = tempfile.mkdtemp(prefix="img_conv_")
        self.total_files = 0
        self.processed_files = 0
        self.progress_queue = Queue()  # 进度更新队列（线程安全）
        self.is_running = False

        # 创建界面
        self.create_widgets()

        # 启动进度更新线程
        self.update_thread = threading.Thread(target=self.process_progress_queue, daemon=True)
        self.update_thread.start()

    def create_widgets(self):
        # 输入ZIP路径
        tk.Label(self.root, text="输入 ZIP 文件:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.input_path_var = tk.StringVar()
        tk.Entry(self.root, textvariable=self.input_path_var, width=50).grid(row=0, column=1, padx=10, pady=10)
        tk.Button(self.root, text="浏览...", command=self.select_input).grid(row=0, column=2, padx=10, pady=10)

        # 输出ZIP路径
        tk.Label(self.root, text="输出 ZIP 文件:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.output_path_var = tk.StringVar()
        tk.Entry(self.root, textvariable=self.output_path_var, width=50).grid(row=1, column=1, padx=10, pady=10)
        tk.Button(self.root, text="浏览...", command=self.select_output).grid(row=1, column=2, padx=10, pady=10)

        # 转换格式选择
        tk.Label(self.root, text="转换格式:").grid(row=2, column=0, padx=10, pady=10, sticky="w")
        self.format_var = tk.StringVar(value="WebP")
        format_options = ttk.Combobox(
            self.root,
            textvariable=self.format_var,
            values=["WebP", "AVIF"],
            state="readonly",
            width=10
        )
        format_options.grid(row=2, column=1, padx=10, pady=10, sticky="w")
        format_options.bind("<<ComboboxSelected>>", self.update_output_suffix)  # 格式变更时更新输出文件名

        # 压缩质量设置（数字输入框）
        tk.Label(self.root, text="压缩质量 (1-100):").grid(row=3, column=0, padx=10, pady=10, sticky="w")
        self.quality_var = tk.StringVar(value="80")  # 用字符串存储便于验证
        quality_frame = tk.Frame(self.root)
        quality_frame.grid(row=3, column=1, padx=10, pady=10, sticky="w")
        self.quality_entry = tk.Entry(quality_frame, textvariable=self.quality_var, width=5)
        self.quality_entry.pack(side=tk.LEFT)
        # 输入验证
        self.quality_entry.bind("<FocusOut>", self.validate_quality)
        self.quality_entry.bind("<Return>", self.validate_quality)
        tk.Label(quality_frame, text="（数值越高质量越好，体积越大）").pack(side=tk.LEFT, padx=5)

        # 进度条和百分比
        progress_frame = tk.Frame(self.root)
        progress_frame.grid(row=4, column=0, columnspan=3, padx=10, pady=10, sticky="we")
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.progress_label = tk.Label(progress_frame, text="0%")
        self.progress_label.pack(side=tk.LEFT, padx=5)

        # 状态显示（显示当前处理的文件名）
        tk.Label(self.root, text="处理状态:").grid(row=5, column=0, padx=10, pady=5, sticky="w")
        self.status_var = tk.StringVar(value="就绪")
        self.status_entry = tk.Entry(self.root, textvariable=self.status_var, state="readonly", width=60)
        self.status_entry.grid(row=5, column=1, columnspan=2, padx=10, pady=5, sticky="we")

        # 控制按钮
        button_frame = tk.Frame(self.root)
        button_frame.grid(row=6, column=0, columnspan=3, pady=20)
        self.start_btn = tk.Button(button_frame, text="开始转换", command=self.start_process, height=2, width=15)
        self.start_btn.pack(side=tk.LEFT, padx=10)
        self.cancel_btn = tk.Button(button_frame, text="取消", command=self.cancel_process, height=2, width=15, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=10)

        # 布局权重
        self.root.grid_columnconfigure(1, weight=1)
        progress_frame.grid_columnconfigure(0, weight=1)

    def select_input(self):
        path = filedialog.askopenfilename(
            title="选择输入 ZIP 文件",
            filetypes=[("ZIP 文件", "*.zip")]
        )
        if path:
            self.input_path_var.set(path)
            if not self.output_path_var.get():
                self.update_output_suffix()  # 自动生成输出路径

    def select_output(self):
        format_suffix = self.format_var.get().lower()
        path = filedialog.asksaveasfilename(
            title=f"保存 {format_suffix.upper()} 格式 ZIP",
            defaultextension=".zip",
            filetypes=[("ZIP 文件", "*.zip")]
        )
        if path:
            self.output_path_var.set(path)

    def update_output_suffix(self, event=None):
        """格式变更或输入文件变更时更新输出文件名"""
        input_path = self.input_path_var.get()
        if not input_path:
            return
        dirname, filename = os.path.split(input_path)
        name, ext = os.path.splitext(filename)
        format_suffix = self.format_var.get().lower()
        self.output_path_var.set(os.path.join(dirname, f"{name}_{format_suffix}{ext}"))

    def validate_quality(self, event=None):
        """验证质量输入是否为1-100的数字"""
        try:
            value = int(self.quality_var.get())
            if 1 <= value <= 100:
                self.quality_entry.config(bg="white")
                return True
            else:
                raise ValueError
        except ValueError:
            self.quality_entry.config(bg="#ffcccc")  # 错误背景色
            messagebox.showwarning("输入错误", "请输入1-100之间的整数")
            self.quality_var.set("80")  # 重置为默认值
            return False

    def process_progress_queue(self):
        """后台处理进度队列，更新UI（主线程安全）"""
        while True:
            if not self.progress_queue.empty():
                item = self.progress_queue.get()
                if item["type"] == "progress":
                    self.progress_var.set(item["value"])
                    self.progress_label.config(text=f"{int(item['value'])}%")
                elif item["type"] == "status":
                    self.status_var.set(item["text"])
                elif item["type"] == "complete":
                    self.status_var.set("转换完成！")
                    self.start_btn.config(state=tk.NORMAL)
                    self.cancel_btn.config(state=tk.DISABLED)
                    self.is_running = False
                    messagebox.showinfo("成功", f"已生成 {self.format_var.get()} 格式文件：\n{item['path']}")
                elif item["type"] == "error":
                    self.status_var.set("转换失败")
                    self.start_btn.config(state=tk.NORMAL)
                    self.cancel_btn.config(state=tk.DISABLED)
                    self.is_running = False
                    messagebox.showerror("错误", item["text"])
                self.progress_queue.task_done()
            time.sleep(0.1)  # 减少CPU占用

    def convert_image(self, input_path, output_path, target_format):
        """转换单张图片（保留透明通道）"""
        if not self.is_running:  # 检查是否已取消
            return
        try:
            # 发送当前处理文件状态
            self.progress_queue.put({
                "type": "status",
                "text": f"处理中：{os.path.basename(input_path)}"
            })

            with Image.open(input_path) as img:
                # 保留透明通道（WebP和AVIF均支持）
                save_kwargs = {"quality": int(self.quality_var.get())}
                
                # AVIF额外参数（可选，提升压缩效率）
                if target_format == "AVIF":
                    save_kwargs["lossless"] = False  # 有损压缩（默认）

                img.save(output_path, target_format, **save_kwargs)

            # 转换成功，更新进度
            self.processed_files += 1
            progress = (self.processed_files / self.total_files) * 100
            self.progress_queue.put({"type": "progress", "value": progress})

        except Exception as e:
            self.progress_queue.put({
                "type": "error",
                "text": f"转换 {os.path.basename(input_path)} 失败：\n{str(e)}"
            })
            self.is_running = False

    def background_process(self):
        """后台执行转换全流程（子线程中运行）"""
        input_zip = self.input_path_var.get()
        output_zip = self.output_path_var.get()
        target_format = self.format_var.get()
        format_ext = target_format.lower()

        try:
            # 1. 验证输入
            if not os.path.exists(input_zip):
                self.progress_queue.put({"type": "error", "text": "输入文件不存在"})
                return

            # 2. 解压ZIP
            self.progress_queue.put({"type": "status", "text": "正在解压文件..."})
            with zipfile.ZipFile(input_zip, 'r') as zf:
                zf.extractall(self.temp_dir)

            # 3. 收集图片文件
            image_extensions = ('.jpg', '.jpeg', '.png')
            image_files = []
            for root, _, files in os.walk(self.temp_dir):
                for file in files:
                    if file.lower().endswith(image_extensions):
                        input_path = os.path.join(root, file)
                        name, ext = os.path.splitext(file)
                        output_path = os.path.join(root, f"{name}.{format_ext}")
                        image_files.append((input_path, output_path))

            if not image_files:
                self.progress_queue.put({"type": "error", "text": "未找到JPG/PNG图片文件"})
                return

            # 4. 初始化进度
            self.total_files = len(image_files)
            self.processed_files = 0
            self.progress_queue.put({"type": "progress", "value": 0})
            self.progress_queue.put({
                "type": "status",
                "text": f"准备转换 {self.total_files} 张图片..."
            })

            # 5. 多线程转换（根据CPU核心数）
            max_workers = min(os.cpu_count() or 4, self.total_files)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for input_path, output_path in image_files:
                    if not self.is_running:  # 检查是否取消
                        executor.shutdown(wait=False)
                        return
                    executor.submit(self.convert_image, input_path, output_path, target_format)

            if not self.is_running:
                return

            # 6. 删除原图片
            for input_path, _ in image_files:
                if os.path.exists(input_path):
                    os.remove(input_path)

            # 7. 压缩为新ZIP
            self.progress_queue.put({"type": "status", "text": "正在压缩输出文件..."})
            with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(self.temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, self.temp_dir)
                        zf.write(file_path, arcname)

            # 8. 完成
            self.progress_queue.put({
                "type": "complete",
                "path": output_zip
            })

        except Exception as e:
            self.progress_queue.put({
                "type": "error",
                "text": f"处理失败：\n{str(e)}"
            })

        finally:
            # 清理临时文件
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)

    def start_process(self):
        """启动转换（在子线程中运行，避免UI卡死）"""
        # 验证质量输入
        if not self.validate_quality():
            return

        # 验证路径
        if not self.input_path_var.get():
            messagebox.showerror("错误", "请选择输入ZIP文件")
            return
        if not self.output_path_var.get():
            messagebox.showerror("错误", "请选择输出ZIP路径")
            return

        # 初始化状态
        self.is_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.temp_dir = tempfile.mkdtemp(prefix="img_conv_")  # 重新创建临时目录

        # 启动后台线程
        threading.Thread(target=self.background_process, daemon=True).start()

    def cancel_process(self):
        """取消转换"""
        if messagebox.askyesno("确认", "确定要取消转换吗？"):
            self.is_running = False
            self.status_var.set("正在取消...")
            self.cancel_btn.config(state=tk.DISABLED)

    def on_close(self):
        """关闭窗口时清理资源"""
        self.is_running = False  # 停止后台任务
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.root.destroy()

if __name__ == "__main__":
    # 检查格式支持
    try:
        Image.init()
        support_avif = "AVIF" in Image.SAVE or hasattr(Image, "AVIF")
        if not support_avif:
            messagebox.showwarning("提示", "未检测到AVIF支持，可能无法转换AVIF格式。\n建议安装pillow-avif-plugin：pip install pillow-avif-plugin")
    except Exception as e:
        messagebox.showwarning("初始化警告", f"图片库初始化警告：{str(e)}")

    root = tk.Tk()
    app = ZipToImageConverter(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
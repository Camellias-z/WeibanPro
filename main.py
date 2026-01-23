import sys
import os
import time
import configparser
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                            QComboBox, QProgressBar, QSpinBox,
                            QCheckBox, QGroupBox, QTextEdit, QGridLayout, 
                            QDialog, QFrame, QScrollArea, QGraphicsDropShadowEffect)
from PyQt5.QtGui import QTextCursor
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPropertyAnimation, QEasingCurve, QRect, QSize, QPoint
from PyQt5.QtGui import QIcon, QPixmap, QColor, QFont
import WBCore as WeiBanHelper
import ddddocr

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# ==========================================
# 自定义控件：果冻按钮 (JellyButton)
# ==========================================
class JellyButton(QPushButton):
    def __init__(self, text, parent=None, color="#3B82F6"):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.color = color
        self._animation = QPropertyAnimation(self, b"geometry")
        self._animation.setDuration(500)
        self._animation.setEasingCurve(QEasingCurve.OutElastic)
        
        # 基础样式
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border-radius: 8px;
                font-weight: 700;
                font-size: 17px;
                padding: 12px 24px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {self.adjust_color(color, 1.1)};
            }}
            QPushButton:pressed {{
                background-color: {self.adjust_color(color, 0.9)};
            }}
            QPushButton:disabled {{
                background-color: #94A3B8;
                color: #F1F5F9;
            }}
        """)
        
        # 阴影效果
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

    def adjust_color(self, hex_color, factor):
        """调整颜色亮度"""
        color = QColor(hex_color)
        h, s, l, a = color.getHsl()
        l = min(int(l * factor), 255)
        color.setHsl(h, s, l, a)
        return color.name()

    def mousePressEvent(self, event):
        # 按下时缩小
        self._animation.stop()
        rect = self.geometry()
        center = rect.center()
        # 缩小 5%
        new_width = int(rect.width() * 0.95)
        new_height = int(rect.height() * 0.95)
        new_x = center.x() - new_width // 2
        new_y = center.y() - new_height // 2
        
        self.setGeometry(new_x, new_y, new_width, new_height)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # 松开时回弹
        self._animation.setStartValue(self.geometry())
        # 恢复原始大小 (需要父布局重新计算或恢复到 layout 建议的大小，这里简单恢复到 geometry)
        # 更好的做法是动画结束后 updateGeometry，但在布局中直接用 geometry 动画会有冲突
        # 这里为了简单效果，我们假设按钮大小相对固定，或者依赖布局刷新
        # 实际上，在布局中使用 geometry 动画需要小心。
        # 替代方案：不改变 geometry，而是改变绘制的 scale，但 QPushButton 难做。
        # 妥协方案：动画结束后调用 update() 让布局恢复
        
        # 获取布局给出的建议位置（由于布局可能限制了 geometry，我们用 current geometry 放大回去）
        rect = self.geometry()
        center = rect.center()
        target_width = int(rect.width() / 0.95)
        target_height = int(rect.height() / 0.95)
        target_x = center.x() - target_width // 2
        target_y = center.y() - target_height // 2
        
        self._animation.setEndValue(QRect(target_x, target_y, target_width, target_height))
        self._animation.start()
        super().mouseReleaseEvent(event)

# ==========================================
# 业务逻辑线程 (WorkerThread) - 从 GUI.py 迁移
# ==========================================
class WorkerThread(QThread):
    update_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)
    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(str, str)
    retake_question_signal = pyqtSignal(str, str, int, int, int)  # 项目名, 考试名, 最高分, 已考次数, 剩余次数
    
    def __init__(self, account, password, school_name, auto_verify, project_index, exam_time, exam_threshold, weiban_instance=None, parent_window=None):
        super().__init__()
        self.account = account
        self.password = password
        self.school_name = school_name
        self.auto_verify = auto_verify
        self.project_index = project_index
        self.exam_time = exam_time
        self.exam_threshold = exam_threshold
        self.completed_courses = set()
        self.weiban_instance = weiban_instance
        self.parent_window = parent_window
        self.retake_result = False  # 存储重考选择结果
        self.retake_event = None  # 将在 run() 方法中初始化
    
    def run(self):
        try:
            self.update_signal.emit("正在初始化...")
            self.status_signal.emit("正在初始化...", "blue")
            
            import builtins
            from loguru import logger
            
            self.original_print = builtins.print
            
            def custom_print(*args, **kwargs):
                """
                简化版 print 重定向：
                - 不再做花哨的 HTML 着色
                - 直接把原始文本发到 UI，保持和控制台输出一致
                """
                message = ' '.join(str(arg) for arg in args)
                self.update_signal.emit(message)
                self.original_print(*args, **kwargs)
            
            builtins.print = custom_print
            
            # 添加 loguru 日志处理器，将日志转发到 UI（简洁文本版）
            def loguru_sink(message):
                """loguru 日志处理器，将日志以纯文本形式转发到 UI"""
                try:
                    record = message.record
                    log_message = str(record["message"])
                    level = record["level"].name
                    # 保持输出简单清晰，只加上级别前缀
                    if level in ("INFO", "SUCCESS"):
                        text = log_message
                    else:
                        text = f"[{level}] {log_message}"
                    self.update_signal.emit(text)
                except Exception as e:
                    # 兜底：直接输出原始 message 文本
                    self.update_signal.emit(str(message))
            
            # 添加自定义处理器（不移除默认处理器，这样控制台也能看到日志）
            # 先移除可能存在的自定义处理器（通过 id 标识）
            if hasattr(self, '_loguru_handler_id'):
                try:
                    logger.remove(self._loguru_handler_id)
                except:
                    pass
            # 添加新的处理器并保存 ID
            self._loguru_handler_id = logger.add(loguru_sink, format="{message}", level="DEBUG")
            
            if self.weiban_instance:
                instance = self.weiban_instance
                self.update_signal.emit("使用已登录的会话...")
            else:
                instance = WeiBanHelper.WeibanHelper(
                    account=self.account, 
                    password=self.password, 
                    school_name=self.school_name,
                    auto_verify=self.auto_verify,
                    project_index=self.project_index
                )
            
            self.progress_signal.emit(10)
            
            if instance.project_list and self.project_index < len(instance.project_list):
                instance.userProjectId = instance.project_list[self.project_index]['userProjectId']
                current_project_name = instance.project_list[self.project_index]['projectName']
                self.update_signal.emit(f"当前项目: {current_project_name}")
            else:
                self.status_signal.emit("项目无效", "red")
                self.finished_signal.emit(False, "项目编号无效或未找到项目")
                return
            
            def progress_callback(progress):
                self.progress_signal.emit(progress)
            
            # 使用线程安全的方式等待重考结果
            from threading import Event
            self.retake_event = Event()
            self.retake_result = False
            
            def retake_callback(project_name, exam_plan_name, max_score, exam_finish_num, exam_odd_num):
                """重考回调函数，通过信号询问用户"""
                # 重置事件和结果
                self.retake_event.clear()
                self.retake_result = False
                # 发送信号到主线程
                self.retake_question_signal.emit(project_name, exam_plan_name, max_score, exam_finish_num, exam_odd_num)
                # 等待结果（阻塞直到主线程设置结果）
                self.retake_event.wait(timeout=300)  # 最多等待5分钟
                return self.retake_result
            
            instance.progress_callback = progress_callback
            instance.retake_callback = retake_callback
            
            self.update_signal.emit("开始刷课...")
            self.status_signal.emit("正在刷课...", "blue")
            self.progress_signal.emit(20)
            
            result = instance.run()
            
            if self.exam_time > 0:
                self.update_signal.emit("准备自动答题...")
                self.status_signal.emit("准备答题中...", "blue")
                
                instance.finish_exam_time = self.exam_time
                instance.exam_threshold = self.exam_threshold
                
                self.update_signal.emit("开始自动答题...")
                self.status_signal.emit("自动答题中...", "blue")
                self.progress_signal.emit(80)
                
                result = instance.autoExam()
            
            self.progress_signal.emit(100)
            self.status_signal.emit("任务完成", "green")
            self.update_signal.emit("任务完成！")
            self.finished_signal.emit(True, "任务完成")
            
        except Exception as e:
            self.status_signal.emit("任务失败", "red")
            self.finished_signal.emit(False, f"发生错误: {str(e)}")
        finally:
            # 恢复 print 函数
            if hasattr(self, 'original_print'):
                import builtins
                builtins.print = self.original_print
            
            # 移除自定义的 loguru sink
            try:
                from loguru import logger
                if hasattr(self, '_loguru_handler_id'):
                    try:
                        logger.remove(self._loguru_handler_id)
                    except:
                        pass
            except Exception:
                pass

# ==========================================
# 基础弹窗类 (FramelessDialog) - 实现无边框和拖动
# ==========================================
class FramelessDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground) # 透明背景以支持圆角
        
        # 拖动逻辑变量
        self._is_dragging = False
        self._drag_position = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._is_dragging = True
            self._drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._is_dragging and event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self._drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._is_dragging = False

# ==========================================
# 对话框类 (CustomDialog, AIConfigDialog, CaptchaDialog)
# ==========================================
class CaptchaDialog(FramelessDialog):
    def __init__(self, parent=None, img_data=None):
        super().__init__(parent)
        self.setWindowTitle("安全验证")
        self.setFixedWidth(400)
        
        # 主容器 (用于绘制背景和边框)
        main_frame = QFrame(self)
        main_frame.setGeometry(0, 0, 400, 400) # 初始大小，会被 layout 撑开，这里不重要
        main_frame.setStyleSheet("""
            QFrame { 
                background-color: #FFFFFF; 
                border-radius: 16px; 
                border: 1px solid #E2E8F0;
            }
        """)
        
        # 阴影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 10)
        main_frame.setGraphicsEffect(shadow)
        
        # 布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10) # 给阴影留空间
        layout.addWidget(main_frame)
        
        inner_layout = QVBoxLayout(main_frame)
        inner_layout.setContentsMargins(30, 40, 30, 40)
        inner_layout.setSpacing(25)
        
        # Title
        title = QLabel("安全验证")
        title.setStyleSheet("font-size: 24px; font-weight: 800; color: #0F172A; border: none;")
        title.setAlignment(Qt.AlignCenter)
        inner_layout.addWidget(title)
        
        # Image
        if img_data:
            img_label = QLabel()
            pixmap = QPixmap()
            pixmap.loadFromData(img_data)
            img_label.setPixmap(pixmap.scaled(180, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            img_label.setAlignment(Qt.AlignCenter)
            img_label.setStyleSheet("border: 1px solid #E2E8F0; border-radius: 12px; padding: 10px; background: #F8FAFC;")
            inner_layout.addWidget(img_label)
            
        # Input
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("在此输入...")
        self.code_input.setAlignment(Qt.AlignCenter)
        self.code_input.setStyleSheet("""
            QLineEdit {
                padding: 14px 16px;
                border: 2px solid #E2E8F0;
                border-radius: 10px;
                background-color: #F8FAFC;
                font-size: 20px;
                font-weight: bold;
                color: #1E293B;
                letter-spacing: 3px;
            }
            QLineEdit:focus {
                border: 2px solid #3B82F6;
                background-color: #FFFFFF;
            }
        """)
        inner_layout.addWidget(self.code_input)
        
        # Button
        self.confirm_btn = JellyButton("确认登录", color="#3B82F6")
        self.confirm_btn.clicked.connect(self.accept)
        inner_layout.addWidget(self.confirm_btn)
        
        self.code_input.setFocus()

    def get_code(self):
        return self.code_input.text()

class CustomDialog(FramelessDialog):
    def __init__(self, parent=None, title="", message="", yes_text="是", no_text="否", icon_type="info", show_cancel=True):
        super().__init__(parent)
        self.result_value = QDialog.Rejected
        self.setFixedWidth(360)
        
        # 主容器
        main_frame = QFrame(self)
        main_frame.setStyleSheet("""
            QFrame { 
                background-color: #FFFFFF; 
                border-radius: 16px; 
                border: 1px solid #E2E8F0;
            }
        """)
        
        # 阴影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 10)
        main_frame.setGraphicsEffect(shadow)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(main_frame)
        
        inner_layout = QVBoxLayout(main_frame)
        inner_layout.setContentsMargins(30, 40, 30, 40)
        inner_layout.setSpacing(20)
        inner_layout.setAlignment(Qt.AlignCenter)
        
        # Icon
        icon_label = QLabel()
        icon_map = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "question": "❓", "success": "✅"}
        icon_label.setText(icon_map.get(icon_type, "ℹ️"))
        icon_label.setStyleSheet("font-size: 64px; background: transparent; border: none;")
        icon_label.setAlignment(Qt.AlignCenter)
        inner_layout.addWidget(icon_label)
        
        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 24px; font-weight: 800; color: #0F172A; margin-top: 10px; border: none;")
        title_label.setAlignment(Qt.AlignCenter)
        inner_layout.addWidget(title_label)
        
        # Message
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet("font-size: 18px; color: #475569; line-height: 1.5; margin-bottom: 10px; border: none;")
        msg_label.setAlignment(Qt.AlignCenter)
        inner_layout.addWidget(msg_label)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        btn_layout.addStretch()
        
        if show_cancel:
            no_btn = JellyButton(no_text, color="#94A3B8")
            no_btn.setFixedWidth(110)
            no_btn.clicked.connect(self.reject_dialog)
            btn_layout.addWidget(no_btn)
            
        yes_btn = JellyButton(yes_text, color="#3B82F6" if icon_type != "error" else "#EF4444")
        yes_btn.setFixedWidth(110)
        yes_btn.clicked.connect(self.accept_dialog)
        btn_layout.addWidget(yes_btn)
        
        btn_layout.addStretch()
        inner_layout.addLayout(btn_layout)

    def accept_dialog(self):
        self.result_value = QDialog.Accepted
        self.accept()
    
    def reject_dialog(self):
        self.result_value = QDialog.Rejected
        self.reject()

    @staticmethod
    def show_message(parent, title, message, icon_type="info"):
        dialog = CustomDialog(parent, title, message, "确定", "", icon_type, False)
        dialog.exec_()

    @staticmethod
    def show_question(parent, title, message, default_yes=False):
        dialog = CustomDialog(parent, title, message, icon_type="question")
        dialog.exec_()
        return dialog.result_value == QDialog.Accepted

class AIConfigDialog(FramelessDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(450)
        
        # 主容器
        main_frame = QFrame(self)
        main_frame.setStyleSheet("""
            QFrame { 
                background-color: #FFFFFF; 
                border-radius: 16px; 
                border: 1px solid #E2E8F0;
            }
        """)
        
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 10)
        main_frame.setGraphicsEffect(shadow)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(main_frame)
        
        inner_layout = QVBoxLayout(main_frame)
        inner_layout.setSpacing(25)
        inner_layout.setContentsMargins(40, 40, 40, 40)
        
        # Title
        title = QLabel("AI 配置")
        title.setStyleSheet("font-size: 24px; font-weight: 800; color: #0F172A; border: none;")
        title.setAlignment(Qt.AlignCenter)
        inner_layout.addWidget(title)
        
        # Info Card
        info = QLabel("💡 配置 AI 模型以启用智能答题功能。支持 OpenAI、DeepSeek 等接口。")
        info.setStyleSheet("background: #EFF6FF; color: #3B82F6; padding: 16px; border-radius: 10px; border: 1px solid #DBEAFE; font-size: 15px; line-height: 1.5;")
        info.setWordWrap(True)
        info.setAlignment(Qt.AlignCenter)
        inner_layout.addWidget(info)
        
        # Form
        form = QVBoxLayout()
        form.setSpacing(15)
        
        self.endpoint_input = QLineEdit()
        self.endpoint_input.setPlaceholderText("API 接口地址")
        form.addWidget(QLabel("接口地址", parent=main_frame)) # 确保样式生效
        form.addWidget(self.endpoint_input)
        
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("API 密钥 (sk-...)")
        self.key_input.setEchoMode(QLineEdit.Password)
        form.addWidget(QLabel("API 密钥", parent=main_frame))
        form.addWidget(self.key_input)
        
        self.show_key = QCheckBox("显示密钥")
        self.show_key.stateChanged.connect(lambda s: self.key_input.setEchoMode(QLineEdit.Normal if s else QLineEdit.Password))
        form.addWidget(self.show_key)
        
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("模型名称 (如: deepseek-chat)")
        form.addWidget(QLabel("模型名称", parent=main_frame))
        form.addWidget(self.model_input)
        
        # 全局样式修正 for Form Labels
        main_frame.setStyleSheet(main_frame.styleSheet() + """
            QLabel { color: #334155; font-size: 16px; font-family: 'Segoe UI', sans-serif; border: none; }
            QLineEdit { 
                padding: 12px 16px; border: 1px solid #E2E8F0; border-radius: 8px; 
                background: #F8FAFC; font-size: 16px; color: #1E293B;
            }
            QLineEdit:focus { border: 1px solid #3B82F6; background: #FFFFFF; }
            QCheckBox { color: #64748B; font-size: 15px; spacing: 8px; }
            QCheckBox::indicator { width: 18px; height: 18px; }
        """)
        
        inner_layout.addLayout(form)
        
        # Buttons
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = JellyButton("取消", color="#94A3B8")
        cancel.setFixedWidth(110)
        cancel.clicked.connect(self.reject)
        save = JellyButton("保存配置", color="#10B981")
        save.setFixedWidth(130)
        save.clicked.connect(self.save_config)
        btns.addWidget(cancel)
        btns.addWidget(save)
        btns.addStretch()
        inner_layout.addLayout(btns)
        
        self.load_config()

    def load_config(self):
        config = configparser.ConfigParser()
        if os.path.exists('ai.conf'):
            try:
                config.read('ai.conf', encoding='utf-8')
                if 'AI' in config:
                    self.endpoint_input.setText(config['AI'].get('API_ENDPOINT', ''))
                    self.key_input.setText(config['AI'].get('API_KEY', ''))
                    self.model_input.setText(config['AI'].get('MODEL', ''))
            except: pass

    def save_config(self):
        config = configparser.ConfigParser()
        config['AI'] = {
            'API_ENDPOINT': self.endpoint_input.text().strip(),
            'API_KEY': self.key_input.text().strip(),
            'MODEL': self.model_input.text().strip()
        }
        try:
            with open('ai.conf', 'w', encoding='utf-8') as f:
                config.write(f)
            CustomDialog.show_message(self, "成功", "配置已保存", "success")
            self.accept()
        except Exception as e:
            CustomDialog.show_message(self, "错误", str(e), "error")

# ==========================================
# 主窗口 (MainWindow)
# ==========================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("微伴助手 Pro")
        self.resize(1000, 700)
        
        # 设置图标
        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.initUI()
        self.initStyle()
        
    def initStyle(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #F0F2F5; }
            QFrame#Card { 
                background-color: #FFFFFF; 
                border-radius: 12px; 
                border: 1px solid #E2E8F0;
            }
            QLabel { color: #334155; font-family: 'Segoe UI', sans-serif; font-size: 16px; }
            QLineEdit {
                padding: 14px 16px;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                background-color: #F8FAFC;
                font-size: 18px;
                color: #1E293B;
            }
            QLineEdit:focus {
                border: 1px solid #3B82F6;
                background-color: #FFFFFF;
            }
            QComboBox {
                padding: 12px 16px;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                background-color: #F8FAFC;
                color: #1E293B;
                font-size: 18px;
            }
            QSpinBox {
                padding: 12px 16px;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                background-color: #F8FAFC;
                color: #1E293B;
                font-size: 18px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 20px;
                border: none;
                background: transparent;
            }
            QProgressBar {
                background-color: #E2E8F0;
                border-radius: 6px;
                height: 18px;
                text-align: center;
                color: #1E293B;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 6px;
            }
            QTextEdit {
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                background-color: #FFFFFF;
                padding: 16px;
                font-family: 'Consolas', 'Menlo', monospace;
                font-size: 17px;
                color: #475569;
                line-height: 1.6;
            }
            QGroupBox {
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 16px;
                font-weight: 600;
                color: #334155;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(24, 24, 24, 24)
        
        # --- 顶部状态栏 ---
        top_bar = QHBoxLayout()
        title_label = QLabel("微伴助手")
        title_label.setStyleSheet("font-size: 26px; font-weight: 800; color: #1E293B;")
        
        self.status_badge = QLabel("准备就绪")
        self.status_badge.setStyleSheet("""
            background-color: #DBEAFE; color: #2563EB; 
            padding: 6px 12px; border-radius: 16px; font-weight: 600; font-size: 13px;
        """)
        
        top_bar.addWidget(title_label)
        top_bar.addWidget(self.status_badge)
        top_bar.addStretch()
        
        # 标语
        slogan = QLabel("🎐 疾风亦有归途")
        slogan.setStyleSheet("color: #64748B; font-weight: 500; font-style: italic; font-size: 14px;")
        top_bar.addWidget(slogan)
        
        main_layout.addLayout(top_bar)
        
        # --- 主体区域 (Left: Config, Right: Log) ---
        body_layout = QHBoxLayout()
        body_layout.setSpacing(20)
        
        # Left Sidebar (420px fixed width)
        left_sidebar = QWidget()
        left_sidebar.setFixedWidth(420)
        left_layout = QVBoxLayout(left_sidebar)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(20)
        
        # 1. 登录卡片
        login_card = QFrame()
        login_card.setObjectName("Card")
        self.add_shadow(login_card)
        login_layout = QVBoxLayout(login_card)
        login_layout.setSpacing(12)
        login_layout.setContentsMargins(20, 20, 20, 20)
        
        login_title = QLabel("用户登录")
        login_title.setStyleSheet("font-size: 18px; font-weight: 700; color: #0F172A;")
        login_layout.addWidget(login_title)
        
        self.account_input = QLineEdit()
        self.account_input.setPlaceholderText("账号")
        login_layout.addWidget(self.account_input)
        
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("密码")
        self.password_input.setEchoMode(QLineEdit.Normal)
        login_layout.addWidget(self.password_input)
        
        self.school_input = QLineEdit()
        self.school_input.setPlaceholderText("学校名称")
        login_layout.addWidget(self.school_input)
        
        self.auto_verify_check = QCheckBox("自动识别验证码")
        self.auto_verify_check.setChecked(True)
        login_layout.addWidget(self.auto_verify_check)
        
        self.login_btn = JellyButton("登录获取课程", color="#3B82F6")
        self.login_btn.clicked.connect(self.login)
        login_layout.addWidget(self.login_btn)
        
        left_layout.addWidget(login_card)
        
        # 2. 任务设置卡片
        task_card = QFrame()
        task_card.setObjectName("Card")
        self.add_shadow(task_card)
        task_layout = QVBoxLayout(task_card)
        task_layout.setSpacing(12)
        task_layout.setContentsMargins(20, 20, 20, 20)
        
        task_title = QLabel("任务配置")
        task_title.setStyleSheet("font-size: 18px; font-weight: 700; color: #0F172A;")
        task_layout.addWidget(task_title)
        
        self.course_combo = QComboBox()
        self.course_combo.addItem("请先登录...")
        self.course_combo.currentIndexChanged.connect(self.update_course_label)
        task_layout.addWidget(self.course_combo)
        
        self.selected_course_display = QLabel("")
        self.selected_course_display.setStyleSheet("""
            QLabel {
                color: #2563EB; 
                font-weight: bold; 
                font-size: 16px;
                background-color: #EFF6FF;
                border: 1px solid #BFDBFE;
                border-radius: 6px;
                padding: 10px;
                margin-top: 5px;
            }
        """)
        self.selected_course_display.setWordWrap(True) # 防止课程名过长
        task_layout.addWidget(self.selected_course_display)
        
        # 考试时间
        time_layout = QHBoxLayout()
        self.exam_time_spin = QSpinBox()
        self.exam_time_spin.setRange(0, 3600)
        self.exam_time_spin.setValue(300)
        self.exam_time_spin.setSuffix(" 秒")
        self.exam_time_spin.setFixedWidth(140)
        
        exam_time_label = QLabel("考试时长")
        exam_time_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #0F172A;")
        time_layout.addWidget(exam_time_label)
        
        time_layout.addSpacing(10)
        time_layout.addWidget(self.exam_time_spin)
        task_layout.addLayout(time_layout)
        
        # 快速按钮
        quick_time_layout = QHBoxLayout()
        for t, label in [(300, "5分"), (600, "10分"), (1200, "20分")]:
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton { 
                    border: 1px solid #E2E8F0; 
                    border-radius: 8px; 
                    padding: 8px 16px; 
                    background: white; 
                    color: #64748B; 
                    font-size: 15px; 
                    font-weight: 600;
                }
                QPushButton:hover { 
                    border-color: #3B82F6; 
                    color: #3B82F6; 
                    background-color: #EFF6FF;
                }
            """)
            btn.clicked.connect(lambda c, x=t: self.exam_time_spin.setValue(x))
            quick_time_layout.addWidget(btn)
        quick_time_layout.addStretch()
        task_layout.addLayout(quick_time_layout)
        
        # 阈值 (Stepper UI)
        threshold_layout = QHBoxLayout()
        threshold_label = QLabel("允许错题")
        threshold_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #0F172A;")
        threshold_layout.addWidget(threshold_label)
        threshold_layout.addStretch()
        
        # 减号按钮
        minus_btn = QPushButton("−")
        minus_btn.setFixedSize(36, 36)
        minus_btn.setCursor(Qt.PointingHandCursor)
        minus_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 18px;
                color: #64748B; font-size: 20px; font-weight: bold; padding-bottom: 3px;
            }
            QPushButton:hover { border-color: #3B82F6; color: #3B82F6; background-color: #F8FAFC; }
            QPushButton:pressed { background-color: #EFF6FF; }
        """)
        
        # 数字框 (隐藏自带箭头，只读)
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 20)
        self.threshold_spin.setValue(5)
        self.threshold_spin.setFixedWidth(60)
        self.threshold_spin.setAlignment(Qt.AlignCenter)
        self.threshold_spin.setButtonSymbols(QSpinBox.NoButtons) # 隐藏自带按钮
        self.threshold_spin.setReadOnly(True) # 只读模式
        self.threshold_spin.setStyleSheet("""
            QSpinBox {
                border: 1px solid #E2E8F0; border-radius: 8px; background-color: #F8FAFC;
                color: #1E293B; font-size: 18px; font-weight: bold; padding: 0px;
            }
            QSpinBox:focus { border: 1px solid #E2E8F0; } /* 移除聚焦边框变色，因为它只读 */
        """)
        
        # 加号按钮
        plus_btn = QPushButton("+")
        plus_btn.setFixedSize(36, 36)
        plus_btn.setCursor(Qt.PointingHandCursor)
        plus_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 18px;
                color: #64748B; font-size: 20px; font-weight: bold; padding-bottom: 3px;
            }
            QPushButton:hover { border-color: #3B82F6; color: #3B82F6; background-color: #F8FAFC; }
            QPushButton:pressed { background-color: #EFF6FF; }
        """)
        
        # 绑定事件 (手动 setValue 以支持只读调节)
        minus_btn.clicked.connect(lambda: self.threshold_spin.setValue(self.threshold_spin.value() - 1))
        plus_btn.clicked.connect(lambda: self.threshold_spin.setValue(self.threshold_spin.value() + 1))
        
        threshold_layout.addWidget(minus_btn)
        threshold_layout.addWidget(self.threshold_spin)
        threshold_layout.addWidget(plus_btn)
        
        task_layout.addLayout(threshold_layout)
        
        left_layout.addWidget(task_card)
        
        # 3. 控制与状态卡片
        ctrl_card = QFrame()
        ctrl_card.setObjectName("Card")
        self.add_shadow(ctrl_card)
        ctrl_layout = QVBoxLayout(ctrl_card)
        ctrl_layout.setSpacing(12)
        ctrl_layout.setContentsMargins(20, 20, 20, 20)
        
        ctrl_title = QLabel("操作中心")
        ctrl_title.setStyleSheet("font-size: 20px; font-weight: 700; color: #0F172A;")
        ctrl_layout.addWidget(ctrl_title)
        
        self.start_btn = JellyButton("开始任务", color="#3B82F6") # 蓝色
        self.start_btn.clicked.connect(self.start_task)
        ctrl_layout.addWidget(self.start_btn)
        
        btns_grid = QHBoxLayout()
        self.ai_btn = JellyButton("AI 配置", color="#8B5CF6") # 紫色
        self.ai_btn.clicked.connect(self.open_ai_config)
        self.reset_btn = JellyButton("重置", color="#64748B") # 灰色
        self.reset_btn.clicked.connect(self.reset_form)
        btns_grid.addWidget(self.ai_btn)
        btns_grid.addWidget(self.reset_btn)
        ctrl_layout.addLayout(btns_grid)
        
        # 进度
        ctrl_layout.addWidget(QLabel("当前进度"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setAlignment(Qt.AlignCenter)
        ctrl_layout.addWidget(self.progress_bar)
        
        left_layout.addWidget(ctrl_card)
        left_layout.addStretch() # Push everything up
        
        body_layout.addWidget(left_sidebar)
        
        # Right Panel: Log (Takes remaining space)
        log_card = QFrame()
        log_card.setObjectName("Card")
        self.add_shadow(log_card)
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(0, 0, 0, 0)
        
        # Log Header
        log_header = QWidget()
        log_header.setStyleSheet("background-color: #F8FAFC; border-top-left-radius: 12px; border-top-right-radius: 12px; border-bottom: 1px solid #E2E8F0;")
        header_layout = QHBoxLayout(log_header)
        header_layout.setContentsMargins(15, 12, 15, 12)
        title = QLabel("学习监控中心")
        title.setStyleSheet("font-weight: 700; font-size: 16px; color: #334155;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        log_layout.addWidget(log_header)
        
        self.log_text = QTextEdit()
        self.log_text.setFrameShape(QFrame.NoFrame)
        log_layout.addWidget(self.log_text)
        
        body_layout.addWidget(log_card, 1) # stretch factor 1
        
        main_layout.addLayout(body_layout)
        
        # 初始化日志
        self.log_text.append("<p style='color:#DC2626; font-weight:bold; font-size:18px;'>⚠️ 本项目仅供学习交流使用，请勿用于商业用途，否则后果自负！！</p>")
        self.log_text.append("<span style='color:#3B82F6; font-weight:bold;'>欢迎使用微伴助手 Pro</span>")
        self.log_text.append("请先在左侧填写登录信息并获取课程...")

    def add_shadow(self, widget):
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        widget.setGraphicsEffect(shadow)

    def update_status(self, text, type="info"):
        colors = {
            "info": ("#DBEAFE", "#2563EB"), # Blue
            "success": ("#D1FAE5", "#059669"), # Green
            "error": ("#FEE2E2", "#DC2626"), # Red
            "warning": ("#FEF3C7", "#D97706") # Orange
        }
        bg, fg = colors.get(type, colors["info"])
        self.status_badge.setText(text)
        self.status_badge.setStyleSheet(f"""
            background-color: {bg}; color: {fg}; 
            padding: 6px 12px; border-radius: 16px; font-weight: 600; font-size: 12px;
        """)

    def update_log(self, message):
        self.log_text.append(message)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def update_course_label(self, index):
        if index >= 0 and self.course_combo.count() > 0:
            txt = self.course_combo.currentText()
            if "请先登录" not in txt:
                self.selected_course_display.setText(f"已选: {txt}")
            else:
                self.selected_course_display.setText("")

    # --- 业务逻辑 (Login/Start) ---
    def login(self):
        account = self.account_input.text()
        password = self.password_input.text()
        school = self.school_input.text()
        
        if not all([account, password, school]):
            CustomDialog.show_message(self, "提示", "请填写完整登录信息", "warning")
            return
            
        self.update_status("正在登录...", "warning")
        self.login_btn.setEnabled(False)
        self.login_btn.setText("登录中...")
        
        # 为了不阻塞UI，这里应该用线程，但为了简单逻辑复用，我们先尝试直接调用（会有短暂卡顿），
        # 或者简单的 ProcessEvents。更好的方式是把 Login 也放入 WorkerThread。
        # 这里为了保持与原版逻辑一致，我们尽量复用原有同步逻辑，但原版也是同步的。
        QApplication.processEvents()
        
        try:
            # 简化版登录逻辑：直接使用 WeiBanHelper
            # 注意：这里需要处理验证码逻辑
            if not self.auto_verify_check.isChecked():
                self.handle_manual_captcha(account, password, school)
            else:
                # 自动验证
                try:
                    self.weiban_instance = WeiBanHelper.WeibanHelper(
                        account=account, password=password, school_name=school,
                        auto_verify=True, project_index=0
                    )
                    self.on_login_success()
                except Exception as e:
                    self.update_log(f"<span style='color:red'>登录失败: {str(e)}</span>")
                    self.update_status("登录失败", "error")
                    self.login_btn.setEnabled(True)
                    self.login_btn.setText("登录获取课程")
        except Exception as e:
            self.update_log(f"错误: {e}")
            self.login_btn.setEnabled(True)
            self.login_btn.setText("登录获取课程")

    def handle_manual_captcha(self, account, password, school):
        # 手动验证码逻辑复用原版，但简化 UI 调用
        try:
            tenant_code = WeiBanHelper.WeibanHelper.get_tenant_code(school_name=school)
            if not tenant_code:
                raise Exception("未找到学校")
            
            # 获取验证码
            verify_time = time.time()
            img_data = WeiBanHelper.WeibanHelper.get_verify_code(get_time=verify_time, download=False)
            
            # 使用新的 CaptchaDialog
            dialog = CaptchaDialog(self, img_data)
            
            if dialog.exec_() == QDialog.Accepted:
                code = dialog.get_code()
                login_data = WeiBanHelper.WeibanHelper.login(account, password, tenant_code, code, verify_time)
                if login_data.get('code') == '0':
                    # 登录成功，初始化实例
                    data = login_data['data']
                    instance = WeiBanHelper.WeibanHelper.__new__(WeiBanHelper.WeibanHelper)
                    instance.ocr = ddddocr.DdddOcr(show_ad=False)
                    instance.session = instance.create_session()
                    instance.tenantCode = tenant_code
                    instance.userId = data["userId"]
                    instance.x_token = data["token"]
                    instance.headers["X-Token"] = instance.x_token
                    instance.project_list = WeiBanHelper.WeibanHelper.get_project_id(data["userId"], tenant_code, data["token"])
                    instance.lab_info = WeiBanHelper.WeibanHelper.get_lab_id(data["userId"], tenant_code, data["token"])
                    self.weiban_instance = instance
                    self.on_login_success()
                else:
                    raise Exception(login_data.get('message', '登录失败'))
            else:
                self.login_btn.setEnabled(True)
                self.login_btn.setText("登录获取课程")
                
        except Exception as e:
            CustomDialog.show_message(self, "登录错误", str(e), "error")
            self.login_btn.setEnabled(True)
            self.login_btn.setText("登录获取课程")

    def on_login_success(self):
        self.update_status("已登录", "success")
        self.update_log("✅ 登录成功，已获取课程列表")
        self.course_combo.clear()
        if hasattr(self.weiban_instance, 'project_list') and self.weiban_instance.project_list:
            for i, p in enumerate(self.weiban_instance.project_list):
                self.course_combo.addItem(f"{i} - {p['projectName']}")
        self.login_btn.setText("已登录")
        # 保持禁用，或允许重新登录? 原版允许
        self.login_btn.setEnabled(True)

    def start_task(self):
        if not hasattr(self, 'weiban_instance'):
            CustomDialog.show_message(self, "提示", "请先登录", "warning")
            return
            
        if not CustomDialog.show_question(self, "确认", "确定要开始执行刷课任务吗？"):
            return
            
        self.start_btn.setEnabled(False)
        self.update_status("任务运行中...", "info")
        self.log_text.clear()
        self.log_text.append("<p style='color:#DC2626; font-weight:bold; font-size:18px;'>⚠️ 本项目仅供学习交流使用，请勿用于商业用途，否则后果自负！！</p>")
        
        self.worker = WorkerThread(
            account=self.account_input.text(),
            password=self.password_input.text(),
            school_name=self.school_input.text(),
            auto_verify=self.auto_verify_check.isChecked(),
            project_index=self.course_combo.currentIndex(),
            exam_time=self.exam_time_spin.value(),
            exam_threshold=self.threshold_spin.value(),
            weiban_instance=self.weiban_instance,
            parent_window=self
        )
        self.worker.update_signal.connect(self.update_log)
        self.worker.status_signal.connect(self.update_status)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.finished_signal.connect(self.on_task_finished)
        self.worker.retake_question_signal.connect(self.handle_retake_question)
        self.worker.parent_window = self
        self.worker.start()

    def handle_retake_question(self, project_name, exam_plan_name, max_score, exam_finish_num, exam_odd_num):
        """处理重考询问"""
        message = f"考试项目：{project_name}\n考试名称：{exam_plan_name}\n\n最高成绩：{max_score} 分\n已考试次数：{exam_finish_num} 次\n剩余次数：{exam_odd_num} 次\n\n是否要重考？"
        result = CustomDialog.show_question(self, "重考确认", message, default_yes=False)
        # 设置结果并通知等待的线程
        if hasattr(self.worker, 'retake_event'):
            self.worker.retake_result = result
            self.worker.retake_event.set()
    
    def on_task_finished(self, success, msg):
        self.start_btn.setEnabled(True)
        if success:
            self.update_status("任务完成", "success")
            CustomDialog.show_message(self, "完成", "任务已完成！", "success")
        else:
            self.update_status("任务中断", "error")
            CustomDialog.show_message(self, "失败", msg, "error")

    def open_ai_config(self):
        AIConfigDialog(self).exec_()

    def reset_form(self):
        if CustomDialog.show_question(self, "重置", "确定清空所有信息吗？"):
            self.account_input.clear()
            self.password_input.clear()
            self.school_input.clear()
            self.course_combo.clear()
            self.course_combo.addItem("请先登录...")
            self.selected_course_display.clear()
            self.progress_bar.setValue(0)
            self.update_status("准备就绪", "info")
            if hasattr(self, 'weiban_instance'):
                del self.weiban_instance

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 全局字体
    font = QFont("Segoe UI", 9)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

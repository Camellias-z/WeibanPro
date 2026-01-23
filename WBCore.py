import json
import os
import sys
import time
import webbrowser
import difflib
import random
import configparser
from random import randint
from typing import Any, Dict, Optional, TYPE_CHECKING, Union, Callable, Tuple
from urllib.parse import parse_qs, urlparse
from datetime import datetime

from loguru import logger
import re
import requests
from requests.exceptions import SSLError, Timeout, ConnectionError, HTTPError, RequestException, ProxyError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from api import WeBanAPI

if TYPE_CHECKING:
    from ddddocr import DdddOcr

if getattr(sys, "frozen", False):
    base_path = os.path.dirname(sys.executable)
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

# 旧版使用的远程题库(answer/answer.json)仍保留路径，但考试优先使用本地 QuestionBank/result.json
answer_dir = os.path.join(base_path, "answer")
answer_path = os.path.join(answer_dir, "answer.json")


def clean_text(text):
    """只保留字母、数字和汉字，自动去除所有符号和空格"""
    return re.sub(r"[^\w\u4e00-\u9fa5]", "", text)


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class WeBanClient:
    """
    整合后的微伴刷课客户端
    以 client.py 的 WeBanClient 类为主要结构
    整合了 WBCore.py 中的 AI 辅助答题、题库匹配、进度回调等功能
    """

    def __init__(
        self,
        tenant_name: str,
        account: str | None = None,
        password: str | None = None,
        user: Dict[str, str] | None = None,
        log=logger,
        progress_callback: Optional[Callable[[int], None]] = None,
        verify_code_callback: Optional[Callable[[bytes], str]] = None,
        manual_answer_callback: Optional[Callable[[Dict], list]] = None,
        retake_callback: Optional[Callable[[str, str, int, int, int], bool]] = None,
        auto_verify: bool = True,
        auto_update_questionbank: bool = False,
        exam_threshold: int = 1,
        finish_exam_time: int = 300,
    ) -> None:
        """
        初始化客户端
        
        :param tenant_name: 学校全称
        :param account: 账号
        :param password: 密码
        :param user: 用户信息字典，包含 userId 和 token
        :param log: 日志记录器
        :param progress_callback: 进度回调函数，接收 0-100 的整数
        :param verify_code_callback: 验证码回调函数，接收验证码图片 bytes，返回验证码字符串
        :param manual_answer_callback: 手动答题回调函数，接收题目信息，返回答案 ID 列表
        :param retake_callback: 重考回调函数，接收(项目名, 考试名, 最高分, 已考次数, 剩余次数)，返回是否重考
        :param auto_verify: 是否自动识别验证码
        :param auto_update_questionbank: 是否自动更新题库
        :param exam_threshold: 考试匹配度阈值
        :param finish_exam_time: 考试完成等待时间（秒）
        """
        self.log = log
        self.tenant_name = tenant_name.strip()
        self.study_time = 15
        self.ocr = self.get_ocr_instance()
        self.progress_callback = progress_callback
        self.verify_code_callback = verify_code_callback
        self.manual_answer_callback = manual_answer_callback
        self.retake_callback = retake_callback
        self.auto_verify = auto_verify
        self.auto_update_questionbank = auto_update_questionbank
        self.exam_threshold = exam_threshold
        self.finish_exam_time = finish_exam_time
        self.questions_to_update = []  # 需要更新的题目列表
        
        if user and all([user.get("userId"), user.get("token")]):
            self.api = WeBanAPI(user=user)
        elif all([self.tenant_name, account, password]):
            self.api = WeBanAPI(account=account, password=password)
        else:
            self.api = WeBanAPI()
        self.tenant_code = self.get_tenant_code()
        if self.tenant_code:
            self.api.set_tenant_code(self.tenant_code)
        else:
            raise ValueError("学校代码获取失败，请检查学校全称是否正确")

    @staticmethod
    def get_project_type(project_category: int) -> str:
        """
        获取项目类型
        :param project_category: 项目类型 1.新生安全教育 2.安全课程 3.专题学习 4.军事理论 9.实验室
        :return: 项目类型字符串
        """
        if project_category == 3:
            return "special"
        elif project_category == 9:
            return "lab"
        else:
            return ""

    def get_ocr_instance(self, _cache: Dict[str, Any] = {"ocr": None}) -> Optional[Union["DdddOcr", None]]:
        """
        检查是否安装 ddddocr 库，多次调用返回同一个 DdddOcr 实例
        """
        if not _cache.get("ocr"):
            try:
                import ddddocr

                try:
                    _cache["ocr"] = ddddocr.DdddOcr(show_ad=False)
                except TypeError:
                    _cache["ocr"] = ddddocr.DdddOcr()
            except Exception:
                ddddocr = None
                self.log.warning("ddddocr 库未安装，自动验证码识别功能将不可用")

        return _cache["ocr"]

    def get_tenant_code(self) -> str:
        """
        获取学校代码
        :return: code
        """
        if not self.tenant_name:
            self.log.error(f"学校全称不能为空")
            return ""
        tenant_list = self.api.get_tenant_list_with_letter()
        if tenant_list.get("code", -1) == "0":
            self.log.info(f"获取学校列表成功")
        tenant_names = []
        maybe_names = []
        for item in tenant_list.get("data", []):
            for entry in item.get("list", []):
                name = entry.get("name", "")
                tenant_names.append(name)
                if self.tenant_name == name.strip():
                    self.log.success(f"找到学校代码: {entry['code']}")
                    return entry["code"]
                if self.tenant_name in name:
                    maybe_names.append(name)
        self.log.error(f"{tenant_names}")
        self.log.error(f"没找到你的学校代码，请检查学校全称是否正确（上面是有效的学校名称）: {self.tenant_name}")
        if maybe_names:
            self.log.error(f"可能的学校名称: {maybe_names}")
        return ""

    def get_progress(self, user_project_id: str, project_prefix: str | None, output: bool = True) -> Dict[str, Any]:
        """
        获取学习进度
        :param output: 是否输出进度信息
        :param user_project_id: 用户项目 ID
        :param project_prefix: 项目前缀
        :return:
        """
        progress = self.api.show_progress(user_project_id)
        if progress.get("code", -1) == "0":
            progress = progress.get("data", {})
            # 推送课
            push_num = progress["pushNum"]
            push_finished_num = progress["pushFinishedNum"]
            # 自选课
            optional_num = progress["optionalNum"]
            optional_finished_num = progress["optionalFinishedNum"]
            # 必修课
            required_num = progress["requiredNum"]
            required_finished_num = progress["requiredFinishedNum"]
            # 考试
            exam_num = progress["examNum"]
            exam_finished_num = progress["examFinishedNum"]
            eta = max(0, self.study_time * (required_num - required_finished_num + optional_num - optional_finished_num + push_num - push_finished_num))
            if output:
                self.log.info(f"{project_prefix} 进度：必修课：{required_finished_num}/{required_num}，推送课：{push_finished_num}/{push_num}，自选课：{optional_finished_num}/{optional_num}，考试：{exam_finished_num}/{exam_num}，预计剩余时间：{eta} 秒")
        return progress

    def login(self, verify_code: str | None = None) -> Dict | None:
        """
        登录功能，整合了自动验证码识别和手动输入验证码
        :param verify_code: 可选的验证码，如果提供则直接使用
        :return: 用户信息字典或 None
        """
        if self.api.user.get("userId"):
            return self.api.user
        
        retry_limit = 3
        for i in range(retry_limit + 2):
            if i > 0:
                self.log.warning(f"登录失败，正在重试 {i}/{retry_limit+2} 次")
            
            verify_time = int(self.api.get_timestamp(13, 0))
            verify_image = self.api.rand_letter_image(verify_time)
            
            # 优先使用提供的验证码
            if verify_code:
                code = verify_code
            # 如果有验证码回调函数，使用回调函数
            elif self.verify_code_callback:
                try:
                    code = self.verify_code_callback(verify_image)
                except Exception as e:
                    self.log.error(f"验证码回调函数出错: {e}")
                    continue
            # 自动识别验证码
            elif i < retry_limit and self.ocr and self.auto_verify:
                try:
                    code = self.ocr.classification(verify_image)
                    self.log.info(f"自动验证码识别结果: {code}")
                    if len(code) != 4:
                        self.log.warning(f"验证码识别失败，正在重试")
                        continue
                except Exception as e:
                    self.log.error(f"验证码识别异常: {e}")
                    continue
            # 手动输入验证码
            else:
                open("verify_code.png", "wb").write(verify_image)
                webbrowser.open(f"file://{os.path.abspath('verify_code.png')}")
                code = input(f"请查看 verify_code.png 输入验证码：")
            
            res = self.api.login(code, verify_time)
            if res.get("detailCode") == "67":
                self.log.warning(f"验证码识别失败，正在重试")
                continue
            if self.api.user.get("userId"):
                return self.api.user
            self.log.error(f"登录出错，请检查账号密码，或删除文件后重试: {res}")
            break
        return None

    def run_study(self, study_time: int = 15, restudy_time: int = 0) -> None:
        """
        运行课程学习，整合了进度回调和课程类型检测
        :param study_time: 学习时间（秒）
        :param restudy_time: 重新学习时间（秒），如果设置则重新学习所有课程
        """
        if study_time:
            self.study_time = study_time

        if restudy_time:
            self.study_time = restudy_time
            self.log.info(f"重新学习模式已开启，所有课程将重新学习，每门课程学习 {self.study_time} 秒")

        # 初始化进度
        if self.progress_callback:
            self.progress_callback(0)

        my_project = self.api.list_my_project()
        if my_project.get("code", -1) != "0":
            self.log.error(f"获取任务列表失败：{my_project}")
            return

        my_project = my_project.get("data", [])
        if not my_project:
            self.log.error(f"获取任务列表失败")
            return

        completion = self.api.list_completion()
        if completion.get("code", -1) != "0":
            self.log.error(f"获取模块完成情况失败：{completion}")

        showable_modules = [d["module"] for d in completion.get("data", []) if d["showable"] == 1]
        if "labProject" in showable_modules:
            self.log.info(f"加载实验室课程")
            lab_project = self.api.lab_index()
            if lab_project.get("code", -1) != "0":
                self.log.error(f"获取实验室课程失败：{lab_project}")
            my_project.append(lab_project.get("data", {}).get("current", {}))
        else:
            # 保留旧版简洁提示风格
            print("没有找到实验课程信息。")
            print("当前账户没有实验课程。")

        # 计算总课程数用于进度计算（所有项目的总和，用于全局进度分母）
        total_courses = 0
        for task in my_project:
            for choose_type in [(3, "必修课"), (1, "推送课"), (2, "自选课")]:
                categories = self.api.list_category(task["userProjectId"], choose_type[0])
                if categories.get("code") == "0":
                    for category in categories.get("data", []):
                        courses = self.api.list_course(task["userProjectId"], category["categoryCode"], choose_type[0])
                        total_courses += len(courses.get("data", []))

        current_course_index = 0

        for task in my_project:
            project_prefix = task["projectName"]
            self.log.info(f"开始处理任务：{project_prefix}")
            need_capt = []

            # 获取学习进度（仅内部使用，不在 UI 再输出一次）
            self.get_progress(task["userProjectId"], project_prefix, output=False)

            # 聚合类别 1：推送课，2：自选课，3：必修课
            for choose_type in [(3, "必修课", "requiredNum", "requiredFinishedNum"),
                                (1, "推送课", "pushNum", "pushFinishedNum"),
                                (2, "自选课", "optionalNum", "optionalFinishedNum")]:
                type_code, type_name, total_key, finished_key = choose_type

                # 与旧版风格对齐：打印获取课程列表提示
                print(f"正在获取 {type_name} (chooseType={type_code}) 的课程列表...")

                categories = self.api.list_category(task["userProjectId"], type_code)
                if categories.get("code") != "0":
                    self.log.error(f"获取 {type_name} 分类失败：{categories}")
                    continue

                # 统计该类型下的总课程数（用于本类型内的进度显示），并按旧版风格打印章节
                type_course_total = 0
                for category in categories.get("data", []):
                    # 简洁章节提示
                    print(f"加载章节 : {category['categoryName']}")
                    courses = self.api.list_course(task["userProjectId"], category["categoryCode"], type_code)
                    type_course_total += len(courses.get("data", []))

                if type_course_total == 0:
                    print(f"{type_name} 没有未完成的课程。")
                    continue

                # 资源加载完成提示
                print("资源加载完成")
                print(f"找到 {type_course_total} 个未完成的 {type_name} 课程")
                type_course_index = 1

                # 图标映射（与 WBCore1 风格一致）
                icon_map = {
                    "推送课": "📢",
                    "自选课": "📂",
                    "必修课": "🎯",
                }
                # 展示用名称：推送课程 / 自选课程 / 必修课程
                display_map = {
                    "推送课": "推送课程",
                    "自选课": "自选课程",
                    "必修课": "必修课程",
                }
                course_icon = icon_map.get(type_name, "📘")
                log_type_display = display_map.get(type_name, type_name)

                for category in categories.get("data", []):
                    category_prefix = f"{type_name} {project_prefix}/{category['categoryName']}"
                    if not restudy_time and category["finishedNum"] >= category["totalNum"]:
                        continue

                    # 获取学习进度（仅内部判断，不额外输出）
                    progress = self.get_progress(task["userProjectId"], project_prefix, output=False)
                    if not restudy_time and progress[finished_key] >= progress[total_key]:
                        self.log.info(f"{category_prefix} 已达到要求，跳过")
                        break

                    courses = self.api.list_course(task["userProjectId"], category["categoryCode"], type_code)
                    for course in courses.get("data", []):
                        course_name_real = course.get("resourceName", "未知课程")
                        course_prefix = f"{category_prefix}/{course_name_real}"

                        # 获取学习进度（类别级别，仅内部判断）
                        progress = self.get_progress(task["userProjectId"], category_prefix, output=False)
                        if not restudy_time and progress[finished_key] >= progress[total_key]:
                            break

                        # 已完成课程直接跳过（树状输出里已经能看到哪些被学习）
                        if not restudy_time and course.get("finished") == 1:
                            continue

                        # 1. 打印进度表头与课程名称（模仿旧版输出）
                        print(f"[进度 {type_course_index:02d}/{type_course_total:02d}] {course_icon} {log_type_display}")
                        print(f"     ├── 📖 {course_name_real}")

                        # 启动课程
                        start_success = True
                        try:
                            self.api.study(course["resourceId"], task["userProjectId"])
                        except Exception as e:
                            start_success = False
                            self.log.error(f"{course_prefix} 启动失败: {e}")

                        # 2. 打印启动结果
                        if start_success:
                            print(f"     ├── 🔛 启动成功")
                        else:
                            print(f"     ├── ❌ 启动失败")

                        # 如果没有 userCourseId，则认为无需单独完成接口
                        if "userCourseId" not in course:
                            print(f"     └── ✅ 最终完成")
                            current_course_index += 1
                            type_course_index += 1
                            if self.progress_callback and total_courses > 0:
                                progress_percent = int((current_course_index / total_courses) * 80)
                                self.progress_callback(progress_percent)
                            continue

                        # 预先获取课程 URL 并判断类型
                        course_url = self.api.get_course_url(course["resourceId"], task["userProjectId"])["data"] + "&weiban=weiban"
                        query = parse_qs(urlparse(course_url).query)
                        if query.get("csCapt", [None])[0] == "true":
                            self.log.warning(f"课程需要验证码，暂时无法处理...")
                            need_capt.append(course_prefix)
                            print(f"     └── ❌ 最终失败(需要验证码)")
                            type_course_index += 1
                            continue

                        # 检测课程类型（整合自 WBCore.py）
                        course_type = "weiban"
                        special_finish = False
                        user_activity_id = None

                        if query.get("lyra", [None])[0] == "lyra":  # 安全实训
                            special_finish = True
                            user_activity_id = query.get("userActivityId", [None])[0]
                            course_type = "lyra"
                        elif query.get("weiban", [None])[0] != "weiban":
                            course_type = "open"
                        elif query.get("source", [None])[0] == "moon":
                            course_type = "moon"

                        # 3. 显示静态学习时间（模仿“⏳ 学习中(17s)”）
                        # 以 study_time 为中心做一个小范围随机
                        base_time = max(10, self.study_time)
                        sleep_time = random.randint(base_time - 5, base_time + 5)
                        print(f"     ├── ⏳ 学习中({sleep_time}s)")
                        time.sleep(sleep_time)

                        # 完成课程（整合自 WBCore.py 的课程类型处理）
                        finish_status = "✅ 最终完成"
                        try:
                            if special_finish and user_activity_id:
                                res = self.api.finish_lyra(user_activity_id)
                            elif course_type == "open":
                                res = self.api.finish_by_token(course["userCourseId"], course_type="open")
                            elif course_type == "moon":
                                res = self.api.finish_by_token(course["userCourseId"], course_type="moon")
                            else:
                                token = None
                                if query.get("csCapt", [None])[0] == "true":
                                    self.log.warning(f"课程需要验证码，暂时无法处理...")
                                    need_capt.append(course_prefix)
                                    finish_status = "❌ 最终失败(需要验证码)"
                                else:
                                    res = self.api.finish_by_token(course["userCourseId"], token)
                                    if "ok" not in res:
                                        self.log.error(f"{course_prefix} 完成失败：{res}")
                                        finish_status = "❌ 最终失败"
                        except Exception as e:
                            self.log.error(f"{course_prefix} 完成失败：{e}")
                            finish_status = "❌ 最终失败"

                        # 4. 打印最终结果
                        print(f"     └── {finish_status}")

                        # 树状输出已经清晰展示完成情况，这里不再额外输出成功日志，避免重复和花眼

                        # 更新进度
                        current_course_index += 1
                        type_course_index += 1
                        if self.progress_callback and total_courses > 0:
                            progress_percent = int((current_course_index / total_courses) * 80)  # 课程学习占80%
                            self.progress_callback(progress_percent)

            if need_capt:
                self.log.warning(f"以下课程需要验证码，请手动完成：")
                for c in need_capt:
                    self.log.warning(f" - {c}")

            self.log.success(f"{project_prefix} 课程学习完成")

    def _get_answer_from_bank(self, question_title: str, option_list: list = None, verbose: bool = True) -> Tuple[list, bool, float]:
        """
        从题库中获取答案（整合自 WBCore.py 的题库匹配算法）
        :param question_title: 题目标题
        :param option_list: 选项列表
        :param verbose: 是否输出详细信息（警告、匹配信息等）
        :return: (答案列表, 是否匹配成功, 匹配度)
        """
        # 加载题库：优先使用本地 QuestionBank/result.json（与 WBCore1 风格一致）
        answers_json: Dict[str, list] = {}
        try:
            question_bank_path = resource_path("QuestionBank/result.json")
            with open(question_bank_path, encoding="utf-8") as f:
                raw = json.load(f)

            for title, data in raw.items():
                title_clean = clean_text(title)
                if title_clean not in answers_json:
                    answers_json[title_clean] = []
                for opt in data.get("optionList", []):
                    if opt.get("isCorrect", 1) == 1:
                        answers_json[title_clean].append(opt.get("content", ""))
        except Exception as e:
            print(f"读取本地 QuestionBank 题库失败: {e}")
            return [], False, 0.0

        question_title_clean = clean_text(question_title)

        # 先尝试精确匹配
        if question_title_clean in answers_json:
            data_answers = answers_json[question_title_clean]
            answer_list = data_answers

            # 如果提供了选项列表，检查选项匹配度
            if option_list and answer_list:
                option_match_count = 0
                for opt in option_list:
                    best_similarity = 0.0
                    for ans in data_answers:
                        similarity = difflib.SequenceMatcher(
                            None,
                            opt.get("content", ""),
                            ans
                        ).ratio()
                        best_similarity = max(best_similarity, similarity)
                    if best_similarity > 0.5:
                        option_match_count += 1

                option_match_ratio = option_match_count / len(option_list)
                if option_match_ratio < 0.7:
                    if verbose:
                        print(f"警告：题库中的选项与实际选项相似度低({option_match_ratio:.2f})，建议更新题库")
                    return answer_list, True, option_match_ratio

            return answer_list, True, 1.0

        # 如果精确匹配失败，尝试模糊匹配
        closest_match = difflib.get_close_matches(question_title_clean, answers_json.keys(), n=1, cutoff=0.8)
        if closest_match:
            match = closest_match[0]
            similarity = difflib.SequenceMatcher(None, question_title_clean, match).ratio()
            if verbose:
                print(f"题目模糊匹配成功 - 相似度: {similarity:.2f}")
                print(f"原题目: {question_title}")
                print(f"匹配题目: {match}")

            data_answers = answers_json[match]
            answer_list = data_answers

            # 如果提供了选项列表，同样检查选项匹配度
            if option_list and answer_list:
                option_match_count = 0
                for opt in option_list:
                    best_similarity = 0.0
                    for ans in data_answers:
                        sim = difflib.SequenceMatcher(
                            None,
                            opt.get("content", ""),
                            ans
                        ).ratio()
                        best_similarity = max(best_similarity, sim)
                    if best_similarity > 0.5:
                        option_match_count += 1

                option_match_ratio = option_match_count / len(option_list)
                if option_match_ratio < 0.7:
                    if verbose:
                        print(f"警告：题库中的选项与实际选项相似度低({option_match_ratio:.2f})，建议更新题库")
                    return answer_list, True, option_match_ratio * similarity

            return answer_list, True, similarity

        if verbose:
            print("题库中未找到匹配的题目")
        return [], False, 0.0

    def _ai_response(self, question_title: str, option_list: list, question_type: int) -> Tuple[str, str]:
        """
        AI 辅助答题（整合自 WBCore.py）
        :param question_title: 题目标题
        :param option_list: 选项列表
        :param question_type: 题目类型 1:单选 2:多选
        :return: (答案ID字符串, 答案内容)
        """
        try:
            config = configparser.ConfigParser()
            config.read('ai.conf')
            
            if not config.has_section('AI'):
                self.log.warning("ai.conf文件中缺少[AI]部分")
                return "", ""
            
            api_endpoint = config['AI'].get('API_ENDPOINT')
            api_key = config['AI'].get('API_KEY')
            model = config['AI'].get('MODEL')
            
            if not api_endpoint or not api_key or not model:
                self.log.warning("AI配置不完整，请检查ai.conf文件")
                return "", ""
            
            self.log.info("正在使用AI回答问题...")
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            # 构造消息
            if question_type == 1:  # 单选
                system_content = "本题为单选题，请根据题目和选项回答问题，以json格式输出正确的选项对应的id（即正确选项'id'键对应的值）和内容（即正确选项'content'键对应的值），回答只应该包含两个键，示例回答：{\"id\":\"0196739f-f8b7-4d5e-b8c7-6a31eaf631eb\",\"content\":\"回答一\"}除此之外不要输出任何多余的内容。"
            else:  # 多选
                system_content = "本题为多选题，你必须选择两个或以上选项，请根据题目和选项回答问题，以json格式输出正确的选项对应的id（即正确选项'id'键对应的值）和内容（即正确选项'content'键对应的值），回答只应该包含两个键，你需要使用逗号连接多个值，示例回答：{\"id\":\"0196739f-f8b7-4d5e-b8c7-6a31eaf631eb,b434e65e-8aa8-4b36-9fa9-224273efb6b0\",\"content\":\"回答一，回答二\"}除此之外不要输出任何多余的内容。"
            
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": f"{question_title}\n{option_list}"}
            ]
            
            data = {
                "model": model,
                "messages": messages,
                "temperature": 0.3
            }
            
            # 处理 URL
            base_url = api_endpoint.rstrip('/')
            if base_url.endswith('/v1'):
                url = f"{base_url}/chat/completions"
            elif base_url.endswith('/chat/completions'):
                url = base_url
            else:
                url = f"{base_url}/v1/chat/completions"
            
            response = requests.post(url, headers=headers, json=data, timeout=60)
            
            if response.status_code == 200:
                response_json = response.json()
                content = response_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                # 解析 JSON 响应
                try:
                    if content.startswith("```") and "```" in content:
                        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                        content = content.rsplit("```", 1)[0] if "```" in content else content
                    
                    content = content.strip()
                    data = json.loads(content)
                    id_value = data['id']
                    content_value = data['content']
                    return id_value, content_value
                except (json.JSONDecodeError, KeyError) as e:
                    self.log.error(f"AI响应解析错误: {e}")
                    return "", ""
            else:
                self.log.error(f"AI请求失败，状态码: {response.status_code}")
                return "", ""
        except Exception as e:
            self.log.error(f"AI回答出错: {e}")
            return "", ""

    def update_question_bank(self, question_title: str, options: list, correct_answers: list) -> bool:
        """
        更新题库（整合自 WBCore.py）
        :param question_title: 题目标题
        :param options: 选项列表
        :param correct_answers: 正确答案的索引列表
        :return: 是否更新成功
        """
        try:
            # 尝试使用 answer_path，如果不存在则使用 QuestionBank/result.json
            if os.path.exists(answer_path):
                question_bank_path = answer_path
            else:
                question_bank_path = resource_path("QuestionBank/result.json")
            
            if not os.path.exists(question_bank_path):
                os.makedirs(os.path.dirname(question_bank_path), exist_ok=True)
                question_bank = {}
            else:
                with open(question_bank_path, 'r', encoding='utf8') as f:
                    question_bank = json.loads(f.read())
            
            # 构造新的题目数据结构
            option_list = []
            for idx, option in enumerate(options):
                is_correct = 1 if idx in correct_answers else 2
                option_data = {
                    "content": option.get("content", ""),
                    "sequence": idx + 1,
                    "selected": is_correct,
                    "isCorrect": is_correct,
                    "attachmentList": []
                }
                if "id" in option and option["id"]:
                    option_data["id"] = option["id"]
                option_list.append(option_data)
            
            # 更新或添加题目
            question_bank[question_title] = {"optionList": option_list}
            
            # 写回题库文件
            with open(question_bank_path, 'w', encoding='utf8') as f:
                json.dump(question_bank, f, ensure_ascii=False, indent=4)
            
            self.log.info(f"题库更新成功: {question_title}")
            return True
        except Exception as e:
            self.log.error(f"题库更新失败: {str(e)}")
            return False

    def run_exam(self, use_time: int = 250, retake: bool = False) -> None:
        """
        运行考试功能，整合了 AI 辅助答题、题库匹配、重考逻辑和手动答题
        :param use_time: 总用时（秒）
        :param retake: 是否重考
        """
        # 更新进度到80%（考试开始）
        if self.progress_callback:
            self.progress_callback(80)

        # 加载题库：优先使用本地 QuestionBank/result.json，不再依赖远程下载
        answers_json = {}
        try:
            question_bank_path = resource_path("QuestionBank/result.json")
            with open(question_bank_path, encoding="utf-8") as f:
                raw = json.load(f)

            for title, data in raw.items():
                title_clean = clean_text(title)
                if title_clean not in answers_json:
                    answers_json[title_clean] = []
                for opt in data.get("optionList", []):
                    if opt.get("isCorrect", 1) == 1:
                        answers_json[title_clean].append(clean_text(opt.get("content", "")))

            self.log.success("本地 QuestionBank 题库加载成功，将优先使用题库答题")
        except Exception as e:
            self.log.warning(f"读取本地 QuestionBank 题库失败，本次考试将主要依赖 AI 作答: {e}")

        # 获取项目
        projects = self.api.list_my_project()
        if projects.get("code", -1) != "0":
            self.log.error(f"获取考试列表失败：{projects}")
            return

        projects = projects.get("data", [])

        completion = self.api.list_completion()
        if completion.get("code", -1) != "0":
            self.log.error(f"获取模块完成情况失败：{completion}")

        showable_modules = [d["module"] for d in completion.get("data", []) if d["showable"] == 1]
        if "labProject" in showable_modules:
            self.log.info(f"加载实验室课程")
            lab_project = self.api.lab_index()
            if lab_project.get("code", -1) != "0":
                self.log.error(f"获取实验室课程失败：{lab_project}")
            projects.append(lab_project.get("data", {}).get("current", {}))

        total_plans = 0
        for project in projects:
            exam_plans = self.api.exam_list_plan(project["userProjectId"])
            if exam_plans.get("code", -1) == "0":
                total_plans += len(exam_plans.get("data", []))

        current_plan_index = 0

        for project in projects:
            self.log.info(f"开始考试项目 {project['projectName']}")
            user_project_id = project["userProjectId"]
            # 获取考试计划
            exam_plans = self.api.exam_list_plan(user_project_id)
            if exam_plans.get("code", -1) != "0":
                self.log.error(f"获取考试计划失败：{exam_plans}")
                continue
            exam_plans = exam_plans["data"]
            
            for plan in exam_plans:
                # 更新进度
                if self.progress_callback and total_plans > 0:
                    plan_progress = 80 + (current_plan_index / total_plans) * 18
                    self.progress_callback(int(plan_progress))
                
                # 重考逻辑（整合自 WBCore.py）
                if plan["examFinishNum"] != 0:
                    project_name = project['projectName']
                    exam_plan_name = plan['examPlanName']
                    max_score = plan['examScore']
                    exam_finish_num = plan['examFinishNum']
                    exam_odd_num = plan['examOddNum']
                    
                    # 如果有重考回调函数，使用回调函数询问用户
                    should_retake = False
                    if self.retake_callback:
                        try:
                            should_retake = self.retake_callback(project_name, exam_plan_name, max_score, exam_finish_num, exam_odd_num)
                        except Exception as e:
                            self.log.error(f"重考回调函数出错: {e}")
                            should_retake = False
                    elif retake:
                        # 如果没有回调函数但 retake 参数为 True，直接重考
                        should_retake = True
                    
                    if should_retake:
                        self.log.info(f"考试项目 {project_name}/{exam_plan_name} 最高成绩 {max_score} 分。已考试次数 {exam_finish_num} 次，还剩 {exam_odd_num} 次。开始重考...")
                    else:
                        self.log.info(f"考试项目 {project_name}/{exam_plan_name} 最高成绩 {max_score} 分。已考试次数 {exam_finish_num} 次，还剩 {exam_odd_num} 次。跳过重考")
                        current_plan_index += 1
                        continue
                
                user_exam_plan_id = plan["id"]
                exam_plan_id = plan["examPlanId"]
                
                # 检查考试时间状态（整合自 WBCore.py）
                exam_time_state = plan.get("examTimeState", 2)
                if exam_time_state != 2:
                    can_not_exam_info = plan.get("canNotExamInfo", "")
                    self.log.warning(f"考试计划 '{plan['examPlanName']}' 无法参加考试: '{can_not_exam_info}'")
                    current_plan_index += 1
                    continue
                
                # 预请求（准备试卷信息）
                prepare_paper = self.api.exam_prepare_paper(user_exam_plan_id)
                if prepare_paper.get("code", -1) != "0":
                    self.log.error(f"获取考试信息失败：{prepare_paper}")
                    current_plan_index += 1
                    continue
                prepare_paper = prepare_paper["data"]
                question_num = prepare_paper["questionNum"]
                self.log.info(f"考试信息：用户：{prepare_paper['realName']}，ID：{prepare_paper['userIDLabel']}，题目数：{question_num}，试卷总分：{prepare_paper['paperScore']}，限时 {prepare_paper['answerTime']} 分钟")
                per_time = use_time // question_num if question_num > 0 else 5

                # 获取考试题目
                exam_paper = self.api.exam_start_paper(user_exam_plan_id)
                if exam_paper.get("code", -1) != "0":
                    self.log.error(f"获取考试题目失败：{exam_paper}")
                    if exam_paper.get("detailCode") == "10018":
                        self.log.warning(f"考试项目 {project['projectName']}/{plan['examPlanName']} 需要手动处理，请在网站上开启一次考试后重试")
                    current_plan_index += 1
                    continue
                exam_paper = exam_paper.get("data", {})
                question_list = exam_paper.get("questionList", [])
                
                have_answer = []  # 有答案的题目
                no_answer = []  # 无答案的题目

                for question in question_list:
                    answer_list, matched, similarity = self._get_answer_from_bank(
                        question["title"],
                        question.get("optionList", []),
                        verbose=False  # 预扫描阶段不输出详细信息
                    )
                    if matched and answer_list:
                        have_answer.append(question)
                    else:
                        no_answer.append(question)

                # 简洁统计信息
                print(f"题目总数：{question_num}，题库命中：{len(have_answer)} 题，未命中：{len(no_answer)} 题")
                
                match_count = 0
                ai_count = 0
                total_questions = len(question_list)
                progress_per_question = 18 / total_questions if total_questions > 0 else 0
                current_question_progress = 80

                # 处理无答案的题目（优先题库，其次 AI，再次随机；此处只做简洁输出）
                for i, question in enumerate(no_answer):
                    question_title = question["title"]
                    question_type = question["type"]  # 1是单选，2是多选
                    question_type_name = question.get("typeLabel", "单选题" if question_type == 1 else "多选题")
                    
                    print(f"题目: {question_title}")

                    answers_ids = []
                    ai_content = None
                    
                    # 如果有手动答题回调函数，使用回调函数
                    if self.manual_answer_callback:
                        try:
                            answers_ids = self.manual_answer_callback(question)
                        except Exception as e:
                            self.log.error(f"手动答题回调函数出错: {e}")
                    
                    # 如果没有回调函数或回调函数返回空，尝试AI答题
                    if not answers_ids:
                        # 检查AI配置
                        try:
                            config = configparser.ConfigParser()
                            config.read('ai.conf')
                            has_ai_config = (
                                'AI' in config and 
                                config['AI'].get('API_ENDPOINT') and 
                                config['AI'].get('API_KEY') and 
                                config['AI'].get('MODEL')
                            )
                        except Exception:
                            has_ai_config = False
                        
                        if has_ai_config:
                            print("<——————————未匹配到答案，将使用AI获取答案——————————>\n")
                            answer_ids_str, content = self._ai_response(
                                question["title"],
                                question["optionList"],
                                question["type"]
                            )
                            if answer_ids_str:
                                answers_ids = answer_ids_str.split(",") if "," in answer_ids_str else [answer_ids_str]
                                ai_content = content
                                ai_count += 1
                                print(f"{question_type_name}，AI获取的答案: {content}")
                            else:
                                # AI返回空时的备用方案
                                print("AI未能获取答案，随机选择一个选项")
                                if question["type"] == 1:  # 单选
                                    answers_ids = [question["optionList"][0]["id"]]
                                else:  # 多选
                                    answers_ids = [opt["id"] for opt in question["optionList"][:2]]
                        else:
                            # 无AI配置时的备用方案
                            print("<——————————!!!未匹配到答案，可配置ai.conf文件通过大模型答题!!!——————————>\n")
                            if question["type"] == 1:  # 单选
                                answers_ids = [question["optionList"][0]["id"]]
                            else:  # 多选
                                answers_ids = [opt["id"] for opt in question["optionList"][:2]]
                    
                    # 记录答案
                    if not self.record_answer(user_exam_plan_id, question["id"], per_time, answers_ids, exam_plan_id):
                        raise RuntimeError(f"答题失败，请重新考试：{question}")

                # 处理有答案的题目（题库命中的部分）
                if have_answer:
                    print(f"开始使用题库作答，共 {len(have_answer)} 题")
                for i, question in enumerate(have_answer):
                    question_title = question["title"]
                    question_type = question["type"]  # 1是单选，2是多选
                    question_type_name = question.get("typeLabel", "单选题" if question_type == 1 else "多选题")
                    
                    print(f"题目: {question_title}")

                    answer_list, matched, similarity = self._get_answer_from_bank(question["title"], question.get("optionList", []), verbose=True)
                    answers_ids = []
                    
                    # 匹配选项
                    found_match = False
                    similarity_threshold = 0.8  # 设置相似度阈值
                    use_ai = similarity < similarity_threshold  # 如果相似度低于阈值，使用AI答题
                    
                    if not use_ai:
                        for answer in answer_list:
                            for option in question["optionList"]:
                                opt_content_clean = clean_text(option.get("content", ""))
                                similarity = difflib.SequenceMatcher(None, opt_content_clean, answer).ratio()
                                if similarity > 0.8 or opt_content_clean == answer:
                                    answers_ids.append(option["id"])
                                    print(f"答案: {answer}")
                                    found_match = True
                                    break
                    
                    if found_match and len(answers_ids) == len(answer_list):
                        match_count += 1
                        print("<===答案匹配成功===>\n")
                        # 简洁等待提示
                        # 题库题统一用 per_time 秒
                        time.sleep(per_time)
                        if not self.record_answer(
                            user_exam_plan_id,
                            question["id"],
                            per_time + 1,
                            answers_ids,
                            exam_plan_id
                        ):
                            raise RuntimeError(f"答题失败，请重新考试：{question}")
                    else:
                        # 如果题库匹配度低或选项未完全匹配，使用AI答题
                        try:
                            config = configparser.ConfigParser()
                            config.read('ai.conf')
                            has_ai_config = (
                                'AI' in config and 
                                config['AI'].get('API_ENDPOINT') and 
                                config['AI'].get('API_KEY') and 
                                config['AI'].get('MODEL')
                            )
                        except Exception:
                            has_ai_config = False
                        
                        if has_ai_config:
                            if use_ai:
                                print("<——————————题库匹配度低，使用AI答题——————————>\n")
                            else:
                                print("<——————————题目匹配但选项未找到匹配项，尝试AI答题——————————>\n")
                            
                            answer_ids_str, content = self._ai_response(
                                question["title"],
                                question["optionList"],
                                question["type"]
                            )
                            if answer_ids_str:
                                answers_ids = answer_ids_str.split(",") if "," in answer_ids_str else [answer_ids_str]
                                ai_count += 1
                                print(f"{question_type_name}，AI获取的答案: {content}")
                            else:
                                # AI返回空时的备用方案
                                print("AI未能获取答案，随机选择一个选项")
                                if question["type"] == 1:  # 单选
                                    answers_ids = [question["optionList"][0]["id"]]
                                else:  # 多选
                                    answers_ids = [opt["id"] for opt in question["optionList"][:2]]
                        else:
                            print("<——————————!!!题目匹配但选项未找到匹配项，并且未正确配置AI!!!——————————>\n")
                            # 无AI配置时的备用方案
                            if question["type"] == 1:  # 单选
                                answers_ids = [question["optionList"][0]["id"]]
                            else:  # 多选
                                answers_ids = [opt["id"] for opt in question["optionList"][:2]]
                        
                        # 记录答案
                        if not self.record_answer(user_exam_plan_id, question["id"], per_time, answers_ids, exam_plan_id):
                            raise RuntimeError(f"答题失败，请重新考试：{question}")
                    
                    # 更新进度
                    current_question_progress += progress_per_question
                    if self.progress_callback:
                        self.progress_callback(int(current_question_progress))

                # 输出匹配度（与 WBCore1.py 风格一致）
                print("答案匹配度: ", match_count+ai_count, " / ", len(question_list))
                print("，其中 AI 作答有", ai_count, "题")
                print(f" - 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

                if len(question_list) - match_count > self.exam_threshold:
                    print(f"题库匹配度过低, '{plan['examPlanName']}' 暂未提交,请再次打开程序并修改设置")
                    current_plan_index += 1
                    continue

                print("请耐心等待考试完成（等待时长为你填写的考试时间 默人300秒）\n")
                
                # 更新进度到98%
                if self.progress_callback:
                    self.progress_callback(98)
                
                # 等待考试完成
                time.sleep(self.finish_exam_time)
                
                # 提交试卷
                submit_res = self.api.exam_submit_paper(user_exam_plan_id)
                if submit_res.get("code", -1) != "0":
                    raise RuntimeError(f"提交试卷失败，请重新考试：{submit_res}")
                
                score = submit_res.get("data", {}).get("score", "未知")
                if score != "未知":
                    print(f"【考试成绩】: {score} 分")
                else:
                    print("【考试成绩】: 未能获取分数")
                
                print(" - 考试已完成 \n")
                print(f" - 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                
                # 更新进度到100%
                if self.progress_callback:
                    self.progress_callback(100)
                
                current_plan_index += 1

    def record_answer(self, user_exam_plan_id: str, question_id: str, per_time: int, answers_ids: list, exam_plan_id: str) -> bool:
        """
        记录答题
        :param user_exam_plan_id: 用户考试计划 ID
        :param question_id: 题目 ID
        :param per_time: 用时
        :param answers_ids: 答案 ID 列表
        :param exam_plan_id: 考试计划 ID
        :return:
        """
        res = self.api.exam_record_question(user_exam_plan_id, question_id, per_time, answers_ids, exam_plan_id)
        if res.get("code", -1) != "0":
            self.log.error(f"答题失败，请重新开启考试：{res}")
            return False
        self.log.info(f"保存答案成功")
        return True

    def sync_answers(self) -> None:
        """
        根据历史考试结果，把“正确答案”同步进本地 QuestionBank/result.json。
        设计为手动或外部调用，不再使用 answer/answer.json。
        """
        try:
            question_bank_path = resource_path("QuestionBank/result.json")
            if os.path.exists(question_bank_path):
                with open(question_bank_path, "r", encoding="utf-8") as f:
                    answers_json = json.load(f)
            else:
                answers_json = {}
        except Exception as e:
            self.log.error(f"读取 QuestionBank/result.json 失败：{e}")
            answers_json = {}

        user_project_ids = [p["userProjectId"] for p in self.api.list_my_project().get("data", [])]
        completion = self.api.list_completion()
        if completion.get("code", -1) != "0":
            self.log.error(f"获取模块完成情况失败：{completion}")

        showable_modules = [d["module"] for d in completion.get("data", []) if d["showable"] == 1]
        if "labProject" in showable_modules:
            self.log.info(f"加载实验室课程")
            lab_project = self.api.lab_index()
            if lab_project.get("code", -1) != "0":
                self.log.error(f"获取实验室课程失败：{lab_project}")
            user_project_ids.append(lab_project.get("data", {}).get("current", {}).get("userProjectId"))

        for user_project_id in user_project_ids:
            for plan in self.api.exam_list_plan(user_project_id).get("data", []):
                for history in self.api.exam_list_history(plan["examPlanId"], plan["examType"]).get("data", []):
                    questions = self.api.exam_review_paper(history["id"], history["isRetake"])["data"].get("questions", [])
                    for answer in questions:
                        title = answer["title"]
                        option_list = answer.get("optionList", [])

                        old_opts = {
                            o["content"]: o.get("isCorrect", 1)
                            for o in answers_json.get(title, {}).get("optionList", [])
                        }
                        new_opts = old_opts | {
                            o.get("content", ""): o.get("isCorrect", 1) for o in option_list
                        }
                        for content in new_opts.keys() - old_opts.keys():
                            self.log.info(f"发现题目：{title} 新选项：{content}")

                        answers_json[title] = {
                            "type": answer.get("type", 1),
                            "optionList": [
                                {"content": content, "isCorrect": is_correct}
                                for content, is_correct in new_opts.items()
                            ],
                        }

        try:
            os.makedirs(os.path.dirname(question_bank_path), exist_ok=True)
            with open(question_bank_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(answers_json, indent=2, ensure_ascii=False, sort_keys=True))
                f.write("\n")
            self.log.success("QuestionBank/result.json 已根据历史考试结果同步更新")
        except Exception as e:
            self.log.error(f"写入 QuestionBank/result.json 失败：{e}")


# ==========================================
# 兼容层：WeibanHelper 类（适配 main.py 的接口）
# ==========================================
class WeibanHelper:
    """
    兼容旧版接口的 WeibanHelper 类
    包装 WeBanClient 以适配 main.py 的调用方式
    """
    
    def __init__(self, account, password, school_name, auto_verify=False, project_index=0, auto_update_questionbank=False):
        """
        初始化（兼容旧接口）
        :param account: 账号
        :param password: 密码
        :param school_name: 学校名称
        :param auto_verify: 是否自动验证码
        :param project_index: 项目索引
        :param auto_update_questionbank: 是否自动更新题库
        """
        self.account = account
        self.password = password
        self.school_name = school_name
        self.auto_verify = auto_verify
        self.project_index = project_index
        self.auto_update_questionbank = auto_update_questionbank
        
        # 初始化内部客户端（使用自定义 logger 以便日志能正确显示）
        from loguru import logger
        self.client = WeBanClient(
            tenant_name=school_name,
            account=account,
            password=password,
            log=logger,  # 使用 loguru logger
            auto_verify=auto_verify,
            auto_update_questionbank=auto_update_questionbank
        )
        
        # 登录
        user = self.client.login()
        if not user:
            raise Exception("登录失败")
        
        # 获取项目列表
        self.project_list = self.get_project_id(user["userId"], self.client.tenant_code, user["token"])
        self.lab_info = self.get_lab_id(user["userId"], self.client.tenant_code, user["token"])
        
        # 设置用户信息
        self.tenantCode = self.client.tenant_code
        self.userId = user["userId"]
        self.x_token = user["token"]
        self.userProjectId = ""
        self.headers = {"X-Token": self.x_token}
        
        # 初始化其他属性
        self.finish_exam_time = 300
        self.exam_threshold = 1
        self.progress_callback = None
        self.retake_callback = None
        self.tempUserCourseId = ""
        
        # 创建 session（兼容旧接口）
        self.session = self.create_session()
    
    def create_session(self):
        """创建带重试的会话（兼容旧接口）"""
        session = requests.Session()
        retry_strategy = Retry(
            total=5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
            backoff_factor=1
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers = self.headers.copy()
        return session
    
    def run(self):
        """运行刷课（兼容旧接口）"""
        # 设置进度回调
        if self.progress_callback:
            self.client.progress_callback = self.progress_callback
        
        # 运行刷课（WeBanClient 会自动处理所有项目）
        self.client.run_study(study_time=15)
        return True
    
    def autoExam(self):
        """自动考试（兼容旧接口）"""
        # 设置进度回调
        if self.progress_callback:
            self.client.progress_callback = self.progress_callback
        
        # 设置重考回调
        if self.retake_callback:
            self.client.retake_callback = self.retake_callback
        
        # 设置考试参数
        self.client.exam_threshold = self.exam_threshold
        self.client.finish_exam_time = self.finish_exam_time
        
        # 运行考试（retake 参数不再使用，由回调函数决定）
        self.client.run_exam(use_time=250, retake=True)
        return True
    
    @staticmethod
    def get_tenant_code(school_name: str) -> str:
        """获取学校代码（静态方法，兼容旧接口）"""
        api = WeBanAPI()
        tenant_list = api.get_tenant_list_with_letter()
        if tenant_list.get("code", -1) == "0":
            for item in tenant_list.get("data", []):
                for entry in item.get("list", []):
                    if entry.get("name", "").strip() == school_name.strip():
                        return entry["code"]
        return ""
    
    @staticmethod
    def get_verify_code(get_time, download=False):
        """获取验证码（静态方法，兼容旧接口）"""
        import uuid
        api = WeBanAPI()
        verify_time = int(get_time) if isinstance(get_time, float) else get_time
        img_data = api.rand_letter_image(verify_time)
        
        if download:
            if not os.path.exists("code"):
                os.mkdir("code")
            img_uuid = uuid.uuid4()
            with open(f"code/{img_uuid}.jpg", "wb") as file:
                file.write(img_data)
            return img_uuid
        else:
            return img_data
    
    @staticmethod
    def login(account, password, tenant_code, verify_code, verify_time):
        """登录（静态方法，兼容旧接口）"""
        api = WeBanAPI(account=account, password=password)
        api.set_tenant_code(tenant_code)
        result = api.login(verify_code, verify_time)
        return result
    
    @staticmethod
    def get_project_id(user_id, tenant_code, token: str):
        """获取项目ID列表（静态方法，兼容旧接口）"""
        url = "https://weiban.mycourse.cn/pharos/index/listMyProject.do"
        headers = {
            "X-Token": token,
            "ContentType": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.82",
        }
        data = {"tenantCode": tenant_code, "userId": user_id, "ended": 2}
        response = requests.post(url=url, headers=headers, data=data)
        result = response.json()
        if result.get("code") == "0":
            data_list = result.get("data", [])
            if len(data_list) <= 0:
                return []
            return data_list
        return []
    
    @staticmethod
    def get_lab_id(user_id, tenant_code, token: str):
        """获取实验室ID（静态方法，兼容旧接口）"""
        url = f"https://weiban.mycourse.cn/pharos/lab/index.do?timestamp={int(time.time())}"
        headers = {
            "X-Token": token,
            "ContentType": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.82",
        }
        data = {"tenantCode": tenant_code, "userId": user_id}
        response = requests.get(url, headers=headers, params=data)
        response_data = response.json()
        
        if response_data.get('code') == '0' and response_data.get('detailCode') == '0':
            if 'current' in response_data.get('data', {}):
                lab_info = response_data['data']['current']
                return lab_info
        return None

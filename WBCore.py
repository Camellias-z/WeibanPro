import difflib
import os.path
import time
import uuid
from urllib.parse import parse_qs, urlparse

import ddddocr
import requests
import json
import datetime
from datetime import datetime
import random
import sys

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

from PIL import Image
from requests.exceptions import SSLError, Timeout, ConnectionError, HTTPError, RequestException, ProxyError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import encrypted

from openai import OpenAI
import configparser

class WeibanHelper:
    tenantCode = 0
    userId = ""
    x_token = ""
    userProjectId = ""
    project_list = {}
    ocr = None
    finish_exam_time = 0
    exam_threshold = 1
    headers = {
        "X-Token": "",
        "ContentType": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.82",
    }

    tempUserCourseId = ""

    def __init__(self, account, password, school_name, auto_verify=False, project_index=0, auto_update_questionbank=False):
        self.ocr = ddddocr.DdddOcr(show_ad=False)
        tenant_code = self.get_tenant_code(school_name=school_name)
        verify_time = time.time()
        self.session = self.create_session()
        
        # 初始化题库更新相关属性
        self.questions_to_update = []
        self.auto_update_questionbank = auto_update_questionbank
        
        if not auto_verify:
            img_file_uuid = self.get_verify_code(get_time=verify_time, download=True)
            Image.open(f"code/{img_file_uuid}.jpg").show()
            verify_code = input("请输入验证码: ")
        else:
            verify_code = self.ocr.classification(self.get_verify_code(get_time=verify_time, download=False))
        login_data = self.login(account, password, tenant_code, verify_code, verify_time)

        if auto_verify:
            while login_data['code'] == '-1' and str(login_data).find("验证码") != -1:
                verify_time = time.time()
                verify_code = self.ocr.classification(self.get_verify_code(get_time=verify_time, download=False))
                login_data = self.login(account, password, tenant_code, verify_code, verify_time)
                time.sleep(5)
        # 假设login_data是从某个请求返回的JSON数据中获取的
        if 'data' in login_data:
            login_data = login_data['data']
            self.project_list = WeibanHelper.get_project_id(
                login_data["userId"], tenant_code, login_data["token"]
            )
            self.lab_info = WeibanHelper.get_lab_id(
                login_data["userId"], tenant_code, login_data["token"]
            )
            if self.lab_info:  # 检查是否成功获取到实验课信息
                print(f"实验课程名称: {self.lab_info['projectName']}")
                print(f"实验课程ID: {self.lab_info['userProjectId']}")
            else:
                print("当前账户没有实验课程。")
        else:
            # 如果 'data' 键不存在，输出提示信息
            print("登录失败，可能是学校名称输入错误。\n")
            print(f"返回的错误信息: {login_data}\n")

        if self.project_list is None and self.lab_info is not None:
            self.init(tenant_code, login_data["userId"], login_data["token"], self.lab_info["userProjectId"])
            self.project_list = []
        elif self.project_list is not None:
            project_id = self.project_list[project_index]["userProjectId"]
            self.init(tenant_code, login_data["userId"], login_data["token"], project_id)

    def init(self, code, id, token, projectId):
        self.tenantCode = code
        self.userId = id
        self.x_token = token
        self.userProjectId = projectId
        self.headers["X-Token"] = self.x_token

    def create_session(self):
        """
        创建一个带有重试策略的会话对象。
        """
        session = requests.Session()
        retry_strategy = Retry(
            total=5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],  # 替换 `method_whitelist`
            backoff_factor=1
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def retry_request(self, func, *args, **kwargs):
        """
        封装的重试请求方法。
        """
        retry_count = kwargs.pop('retry_count', 5)
        wait_time = kwargs.pop('wait_time', 3)
        
        for attempt in range(retry_count):
            try:
                return func(*args, **kwargs)  # 调用传入的函数并返回其结果
            except (SSLError, Timeout, ConnectionError, HTTPError, RequestException, ProxyError) as e:
                url_info = args[0] if args else "Unknown URL"
                print(f"网络错误 [{type(e).__name__}]: {e}，URL: {url_info}，正在重试 {attempt + 1} / {retry_count} 次...")
                time.sleep(wait_time)  # 等待指定时间后重试
                if attempt == retry_count - 1:
                    print("达到最大重试次数，跳过此操作。")
                    return None  # 如果最终失败，返回 None

    def start(self, courseId):
        """
        启动课程学习的请求方法，包含错误处理和重试机制。
        :param courseId: 课程ID，用于启动指定的课程学习。
        """
        url = "https://weiban.mycourse.cn/pharos/usercourse/study.do"
        data = {
            "userProjectId": self.userProjectId,
            "tenantCode": self.tenantCode,
            "userId": self.userId,
            "courseId": courseId,
        }
        headers = {"x-token": self.x_token}
        retry_count = 0
        max_retries = 5  # 最大重试次数
        timeout = 10

        while retry_count < max_retries:
            try:
                # print(f"尝试启动课程 (第 {retry_count + 1} 次) ...")

                # 发起请求
                response = self.session.post(
                    url,
                    data=data,
                    headers=headers,
                    proxies={"http": None, "https": None},  # 禁用代理
                    timeout=timeout  # 设置超时时间
                )

                # 检查状态码
                if response.status_code != 200:
                    print(f"请求失败，状态码: {response.status_code}，响应内容: {response.text}")
                    retry_count += 1
                    time.sleep(5)  # 等待5秒后重试
                    continue

                # 检查返回内容是否为空
                if not response.text:
                    print(f"请求返回了空内容，URL: {url}")
                    retry_count += 1
                    time.sleep(5)  # 等待5秒后重试
                    continue

                # 解析返回的 JSON 数据
                try:
                    response_json = response.json()
                except json.JSONDecodeError as e:
                    print(f"[JSON 解析错误] 错误信息: {e}")  # ，响应内容: {response.text}
                    retry_count += 1
                    time.sleep(5)  # 等待5秒后重试
                    continue

                # 打印服务器完整响应
                # print(f"服务器返回完整的响应: {response_json}")

                # 检查请求是否成功
                code = response_json.get("code")
                detail_code = response_json.get("detailCode")

                if code == '0' and detail_code == '0':
                    # 课程启动成功
                    # print("课程启动成功")
                    # print(f" - 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    return True # 成功后退出重试循环
                else:
                    # 课程启动失败
                    print(
                        f"启动课程失败，错误代码: {code}，详细代码: {detail_code}，消息: {response_json.get('message', '无消息内容')}")
                    retry_count += 1
                    time.sleep(5)  # 等待5秒后重试

            except (ProxyError, SSLError, Timeout, ConnectionError, HTTPError, RequestException) as e:
                # 网络错误处理
                print(f"[网络错误] [{type(e).__name__}]: {e}，URL: {url}")
                retry_count += 1
                time.sleep(5)  # 等待5秒后重试

        print(f"已达到最大重试次数 ({max_retries})，启动课程失败。")
        return False

    def get_course_url(self, course_id):
        """
        获取课程链接，用于检查是否需要验证码等信息
        """
        url = "https://weiban.mycourse.cn/pharos/usercourse/getCourseUrl.do"
        data = {
            "userProjectId": self.userProjectId,
            "tenantCode": self.tenantCode,
            "userId": self.userId,
            "courseId": course_id,
        }
        # 使用 retry_request 包装请求
        response = self.retry_request(self.session.post, url, data=data, headers=self.headers)
        if response and response.status_code == 200:
            try:
                return response.json()
            except json.JSONDecodeError:
                return None
        return None

    def run(self):
        # 添加回调函数参数，用于更新进度
        progress_callback = getattr(self, 'progress_callback', None)
        
        # 初始化进度为0%
        if progress_callback:
            progress_callback(0)
        
        # 遍历 chooseType 1(推送课), 2(自选课), 3(必修课) 进行刷课
        # 增加了 1 (推送课)
        for chooseType in [1, 2, 3]:
            type_name = {1: "推送课", 2: "自选课", 3: "必修课"}.get(chooseType, "未知类型")
            print(f"正在获取 {type_name} (chooseType={chooseType}) 的课程列表...")
            
            finishIdList = self.retry_request(self.getFinishIdList, chooseType)

            if finishIdList is None:
                print(f"无法获取 finishIdList，跳过 {type_name} 的课程处理。")
                continue

            course_list = self.retry_request(self.getCourse, chooseType)

            if course_list is None:
                print(f"无法获取课程列表，跳过 {type_name} 的课程处理。")
                continue
            
            if not course_list:
                print(f"{type_name} 没有未完成的课程。")
                continue

            num = len(course_list)
            index = 1
            # 计算总数量
            total_courses = num
            
            print(f"找到 {num} 个未完成的 {type_name} 课程")          
            for item in course_list:
                # 兼容旧版本只返回ID的情况（如果API未更新）和新版本返回字典的情况
                if isinstance(item, dict):
                    i = item['id']
                    course_name_real = item['name']
                else:
                    i = item
                    course_name_real = "未知课程"
                    
                # 预处理：获取课程类型和详细信息
                course_type = "weiban"
                special_finish = False
                user_activity_id = None
                log_type_display = type_name # 默认显示中文名，如 "开放课程" (需映射)
                
                # 简单的类型映射
                type_map_display = {"推送课": "推送课程", "自选课": "自选课程", "必修课": "必修课程"}
                log_type_display = type_map_display.get(type_name, type_name)

                # 检查课程是否有特殊限制（如验证码）或特殊类型
                course_url_data = self.get_course_url(i)
                if course_url_data and course_url_data.get("code") == "0":
                    url_str = course_url_data.get("data", "")
                    if url_str:
                        query = parse_qs(urlparse(url_str).query)
                        # 检查 csCapt 参数
                        if query.get("csCapt", [None])[0] == "true":
                            print(f"警告: 课程 {i} 需要验证码 (csCapt=true)，暂时跳过。")
                            index += 1
                            continue
                        
                        # 检查特殊课程类型
                        if query.get("lyra", [None])[0] == "lyra":  # 安全实训
                            special_finish = True
                            user_activity_id = query.get("userActivityId", [None])[0]
                            log_type_display = "安全实训"
                            # print(f"检测到 Lyra 安全实训课程 (ID: {user_activity_id})")
                        elif query.get("weiban", ["weiban"])[0] != "weiban":
                            course_type = "open"
                            log_type_display = "开放课程"
                            # print("检测到 Open 类型课程")
                        elif query.get("source", [None])[0] == "moon":
                            course_type = "moon"
                            log_type_display = "Moon课程"
                            # print("检测到 Moon 类型课程")
                
                # 打印开始状态提示
                # print(f">> [进度 {index:02d}/{num:02d}] 正在学习: {log_type_display} (预计 {20}s) ...", end="\r")
                
                # 定义图标映射
                icon_map = {
                    "推送课程": "📢", 
                    "自选课程": "📂", 
                    "必修课程": "🎯", 
                    "开放课程": "📚", 
                    "安全实训": "🛡️", 
                    "Moon课程": "🌙"
                }
                course_icon = icon_map.get(log_type_display, "📘")

                # 1. 打印表头
                print(f"[进度 {index:02d}/{num:02d}] {course_icon} {log_type_display} ")
                print(f"     ├── 📖 {course_name_real}")

                # 启动课程
                start_success = self.start(i)
                
                # 2. 打印启动成功
                if start_success:
                    print(f"     ├── 🔛 启动成功")
                else:
                    print(f"     ├── ❌ 启动失败")

                # 模拟学习时间
                sleep_time = random.randint(15, 20)
                
                # 3. 静态显示学习进度
                print(f"     ├── ⏳ 学习中({sleep_time}s)   ")
                time.sleep(sleep_time)
                
                finish_status = "✅ 最终完成"
                # 完成课程
                if special_finish and user_activity_id:
                     self.finish_lyra(user_activity_id)
                elif i in finishIdList:
                    res = self.retry_request(self.finish, i, finishIdList[i], course_type)
                    # 简单检查结果，如果返回 None 或者 json code 不为 0，标记为失败
                    if not res or '"code":"0"' not in res:
                        finish_status = "❌ 最终失败"
                else:
                    # print(f"错误: 无法找到课程 {i} 对应的 finishId (userCourseId)，尝试使用临时ID")
                    if self.tempUserCourseId:
                         res = self.retry_request(self.finish, i, self.tempUserCourseId, course_type)
                         if not res or '"code":"0"' not in res:
                             finish_status = "❌ 最终失败"
                    else:
                        finish_status = "❌ 最终失败(无ID)"
                
                # 4. 打印最终结果
                print(f"     └── {finish_status}")

                # 更新进度
                if progress_callback:
                    # 计算当前完成百分比 (当前课程数/总课程数*80)
                    # 刷课部分占0%到80%
                    # 这里简单的累加可能不够精确，但在多分类循环中难以精确计算总进度，暂且这样
                    current_progress = int(index / total_courses * 80)
                    progress_callback(current_progress)
                
                index += 1
            print(f"{type_name} 刷课完成\n")
        
        return True

    # js里的时间戳似乎都是保留了三位小数的.
    def __get_timestamp(self):
        return str(round(time.time(), 3))

    # Magic: 用于构造、拼接"完成学习任务"的url
    def __gen_rand(self):
        return ("3.4.1" + str(random.random())).replace(".", "")

    def getProgress(self):
        url = "https://weiban.mycourse.cn/pharos/project/showProgress.do"
        data = {
            "userProjectId": self.userProjectId,
            "tenantCode": self.tenantCode,
            "userId": self.userId,
        }
        response = requests.post(url, data=data, headers=self.headers)
        data = json.loads(response.text)
        return data["data"]["progressPet"]

    def getAnswerList(self):
        """
        获取答题记录的列表，通过逐条获取的方式处理多个记录
        """
        answer_list = []
        url = "https://weiban.mycourse.cn/pharos/exam/reviewPaper.do?timestamp=" + self.__get_timestamp()
        exam_id_list = self.listHistory()  # 调用 listHistory 来获取多个考试ID
        for exam_id in exam_id_list:
            data = {
                "tenantCode": self.tenantCode,
                "userId": self.userId,
                "userExamId": exam_id,
                "isRetake": "2"
            }
            response = self.session.post(url, data=data, headers=self.headers)
            if response.status_code == 200:
                answer_list.append(response.text)  # 存储每条考试的答题记录
        return answer_list

    def listHistory(self):
        """
        获取用户的历史考试记录，并返回多个考试ID
        """
        result = []
        url = "https://weiban.mycourse.cn/pharos/exam/listHistory.do?timestamp=" + self.__get_timestamp()
        exam_plan_id_list = self.listExamPlan()  # 获取考试计划ID列表
        for exam_plan_id in exam_plan_id_list:
            dataList = {
                "tenantCode": self.tenantCode,
                "userId": self.userId,
                "examPlanId": exam_plan_id
            }
            response = self.session.post(url, headers=self.headers, data=dataList)
            data = json.loads(response.text)
            if data['code'] == '-1':
                return result
            else:
                for history in data['data']:  # 遍历历史考试记录
                    result.append(history['id'])
        return result

    def listExamPlan(self):
        """
        获取用户的考试计划ID列表
        """
        url = "https://weiban.mycourse.cn/pharos/record/project/listExamPlanStat.do?timestamp=" + self.__get_timestamp()
        data = {
            "tenantCode": self.tenantCode,
            "userId": self.userId,
            "userProjectId": self.userProjectId
        }
        response = requests.post(url, headers=self.headers, data=data)
        exam_plan_id_list = []
        for exam_plan in json.loads(response.text)['data']:
            exam_plan_id_list.append(exam_plan['examPlanId'])
        return exam_plan_id_list

    def getCategory(self, chooseType):
        result = []
        url = "https://weiban.mycourse.cn/pharos/usercourse/listCategory.do"
        data = {
            "userProjectId": self.userProjectId,
            "tenantCode": self.tenantCode,
            "userId": self.userId,
            "chooseType": chooseType,
        }
        response = requests.post(url, data=data, headers=self.headers)
        list = json.loads(response.text)["data"]
        for i in list:
            if i["totalNum"] > i["finishedNum"]:
                result.append(i["categoryCode"])
        return result

    def getCourse(self, chooseType):
        url = "https://weiban.mycourse.cn/pharos/usercourse/listCourse.do"
        result = []
        for i in self.getCategory(chooseType):
            data = {
                "userProjectId": self.userProjectId,
                "tenantCode": self.tenantCode,
                "userId": self.userId,
                "chooseType": chooseType,
                "name": "",
                "categoryCode": i,
            }
            response = requests.post(url, data=data, headers=self.headers)
            text = response.text
            data = json.loads(text)["data"]
            for i in data:
                if i["finished"] == 2:
                    result.append({"id": i["resourceId"], "name": i["resourceName"]})
        return result

    def autoExam(self):
        list_plan_url = f"https://weiban.mycourse.cn/pharos/exam/listPlan.do"
        before_paper_url = f"https://weiban.mycourse.cn/pharos/exam/beforePaper.do"
        get_verify_code_url = f"https://weiban.mycourse.cn/pharos/login/randLetterImage.do?time="
        check_verify_code_url = f"https://weiban.mycourse.cn/pharos/exam/checkVerifyCode.do?timestamp"
        start_paper_url = f"https://weiban.mycourse.cn/pharos/exam/startPaper.do?"
        submit_url = f"https://weiban.mycourse.cn/pharos/exam/submitPaper.do?timestamp="
        answer_data = None
        
        # 添加进度回调
        progress_callback = getattr(self, 'progress_callback', None)
        
        # 考试部分开始时为80%
        if progress_callback:
            progress_callback(80)

        with open(resource_path("QuestionBank/result.json"), 'r', encoding='utf8') as f:
            answer_data = json.loads(f.read())

        def retry_request_2(method, url, headers=None, data=None, max_retries=5, retry_delay=5):
            for attempt in range(max_retries):
                try:
                    if method == "GET":
                        response = requests.get(url, headers=headers, data=data)
                    elif method == "POST":
                        response = requests.post(url, headers=headers, data=data)
                    else:
                        raise ValueError("Invalid method type")
                    response.raise_for_status()  # 检查是否返回了错误的状态码
                    return response
                except (requests.exceptions.RequestException, ValueError) as e:
                    print(
                        f"网络错误:Request failed: {e}. 正在重试:Attempt {attempt + 1} / {max_retries}次. Retrying...")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                    else:
                        print("Max retries reached. Request failed.")
                        raise

        def get_answer_list(question_title, option_list=None):
            """
            从题库中获取答案列表
            
            :param question_title: 题目标题
            :param option_list: 可选，实际的选项列表，用于匹配检查
            :return: (答案列表, 是否匹配成功, 匹配度)
            """
            # 先尝试精确匹配
            if question_title in answer_data:
                data = answer_data[question_title]
                answer_list = [i['content'] for i in data['optionList'] if i['isCorrect'] == 1]
                
                # 如果提供了选项列表，检查选项是否有足够匹配度
                if option_list and answer_list:
                    # 检查选项的数量是否一致
                    if len(option_list) != len(data['optionList']):
                        print(f"警告：题库中的选项数量({len(data['optionList'])})与实际选项数量({len(option_list)})不一致")
                    
                    # 检查每个选项内容的相似度
                    option_match_count = 0
                    for i, opt in enumerate(option_list):
                        best_similarity = 0
                        for db_opt in data['optionList']:
                            similarity = difflib.SequenceMatcher(None, opt['content'], db_opt['content']).ratio()
                            best_similarity = max(best_similarity, similarity)
                        
                        if best_similarity > 0.5:  # 如果选项相似度大于0.5，认为有匹配
                            option_match_count += 1
                    
                    option_match_ratio = option_match_count / len(option_list)
                    if option_match_ratio < 0.7:  # 如果不到70%的选项匹配，认为题库需要更新
                        print(f"警告：题库中的选项与实际选项相似度低({option_match_ratio:.2f})，建议更新题库")
                        # 返回答案列表，成功但低相似度
                        return answer_list, True, option_match_ratio
                    
                return answer_list, True, 1.0
            
            # 如果精确匹配失败，尝试模糊匹配
            closest_match = difflib.get_close_matches(question_title, answer_data.keys(), n=1, cutoff=0.8)
            answer_list = []
            if closest_match:
                match = closest_match[0]
                # 打印匹配度，帮助调试
                similarity = difflib.SequenceMatcher(None, question_title, match).ratio()
                print(f"题目模糊匹配成功 - 相似度: {similarity:.2f}")
                print(f"原题目: {question_title}")
                print(f"匹配题目: {match}")
                
                data = answer_data[match]
                for i in data['optionList']:
                    if i['isCorrect'] == 1:
                        answer_list.append(i['content'])
                
                # 如果提供了选项列表，同样检查选项匹配度
                if option_list and answer_list:
                    option_match_count = 0
                    for i, opt in enumerate(option_list):
                        best_similarity = 0
                        for db_opt in data['optionList']:
                            similarity = difflib.SequenceMatcher(None, opt['content'], db_opt['content']).ratio()
                            best_similarity = max(best_similarity, similarity)
                        
                        if best_similarity > 0.5:
                            option_match_count += 1
                    
                    option_match_ratio = option_match_count / len(option_list)
                    if option_match_ratio < 0.7:
                        print(f"警告：题库中的选项与实际选项相似度低({option_match_ratio:.2f})，建议更新题库")
                        return answer_list, True, option_match_ratio * similarity
                
                return answer_list, True, similarity
            else:
                print("题库中未找到匹配的题目")
                return answer_list, False, 0.0

        def get_verify_code():
            now = time.time()
            content = retry_request_2("GET", get_verify_code_url + str(now), headers=self.headers).content
            return self.ocr.classification(content), now
        
        def ai_response(input, type):
            try:
                config = configparser.ConfigParser()
                config.read('ai.conf')
                
                if not config.has_section('AI'):
                    print("错误: ai.conf文件中缺少[AI]部分")
                    return "", ""
                
                api_endpoint = config['AI'].get('API_ENDPOINT')
                api_key = config['AI'].get('API_KEY')
                model = config['AI'].get('MODEL')
                
                if not api_endpoint or not api_key or not model:
                    print("错误: AI配置不完整，请检查ai.conf文件")
                    return "", ""
                    
                # 隐藏API信息输出
                # print(f"正在使用AI回答问题... (API: {api_endpoint}, 模型: {model})")
                print("正在使用AI回答问题...")
                
                # 统一使用 OpenAI 兼容格式 (requests 实现，兼容性最好)
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                
                # 构造消息
                if type == 1:  # 单选
                    messages = [
                        {
                            "role": "system", 
                            "content": "本题为单选题，请根据题目和选项回答问题，以json格式输出正确的选项对应的id（即正确选项'id'键对应的值）和内容（即正确选项'content'键对应的值），回答只应该包含两个键，示例回答：{\"id\":\"0196739f-f8b7-4d5e-b8c7-6a31eaf631eb\",\"content\":\"回答一\"}除此之外不要输出任何多余的内容。"
                        },
                        {
                            "role": "user",
                            "content": input
                        }
                    ]
                else:  # 多选
                    messages = [
                        {
                            "role": "system", 
                            "content": "本题为多选题，你必须选择两个或以上选项，请根据题目和选项回答问题，以json格式输出正确的选项对应的id（即正确选项'id'键对应的值）和内容（即正确选项'content'键对应的值），回答只应该包含两个键，你需要使用逗号连接多个值，示例回答：{\"id\":\"0196739f-f8b7-4d5e-b8c7-6a31eaf631eb,b434e65e-8aa8-4b36-9fa9-224273efb6b0\",\"content\":\"回答一，回答二\"}除此之外不要输出任何多余的内容。"
                        },
                        {
                            "role": "user",
                            "content": input
                        }
                    ]
                
                data = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.3  # 降低随机性，提高准确率
                }
                
                try:
                    # 自动处理 URL 拼接，兼容末尾带/或不带/的情况，以及是否包含/v1的情况
                    # 标准 OpenAI 格式通常是 /v1/chat/completions
                    # 如果用户填写的 URL 已经包含 /v1，则不再追加 /v1，只追加 /chat/completions
                    # 为了最大兼容性，我们假设用户填写的是 Base URL (例如 https://api.deepseek.com 或 https://api.moonshot.cn/v1)
                    
                    base_url = api_endpoint.rstrip('/')
                    if base_url.endswith('/v1'):
                        url = f"{base_url}/chat/completions"
                    elif base_url.endswith('/chat/completions'): # 用户直接填了完整路径
                        url = base_url
                    else:
                        url = f"{base_url}/v1/chat/completions"

                    response = requests.post(url, headers=headers, json=data, timeout=60)
                    
                    if response.status_code == 200:
                        response_json = response.json()
                        content = response_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                        
                        # 尝试解析JSON响应
                        try:
                            # 检查并删除可能的Markdown代码块标记
                            if content.startswith("```") and "```" in content:
                                # 删除开始的```json或```等标记
                                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                                # 删除结束的```标记
                                content = content.rsplit("```", 1)[0] if "```" in content else content
                            
                            # 清理可能的首尾空白
                            content = content.strip()
                            
                            data = json.loads(content)
                            id_value = data['id']
                            content_value = data['content']
                            return id_value, content_value
                        except (json.JSONDecodeError, KeyError) as e:
                            print(f"AI响应解析错误: {e}")
                            # 隐藏原始响应输出
                            # print(f"原始响应: {content}")
                            return "", ""
                    else:
                        print(f"AI请求失败，状态码: {response.status_code}")
                        # 尝试打印错误详情
                        # print(f"错误响应: {response.text}")
                        return "", ""
                except requests.exceptions.RequestException as e:
                    print(f"网络请求错误: {e}")
                    return "", ""
                    
            except Exception as e:
                print(f"AI回答出错: {e}")
                return "", ""

        # 获取当前系统时间
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 获取所有计划
        plan_data = retry_request_2("POST", list_plan_url, headers=self.headers, data={
            "tenantCode": self.tenantCode,
            "userId": self.userId,
            "userProjectId": self.userProjectId
        }).json()

        if plan_data['code'] != '0':
            print("获取考试计划失败")
            return

        # 遍历所有考试计划
        exam_plans = plan_data['data']
        total_plans = len(exam_plans)
        
        for i, plan in enumerate(exam_plans):
            plan_id = plan['id']
            exam_plan_id = plan['examPlanId']
            exam_plan_name = plan['examPlanName']
            exam_time_state = plan['examTimeState']
            can_not_exam_info = plan.get("canNotExamInfo", "")
            start_Time = plan['startTime']
            end_Time = plan['endTime']

            # 更新进度，考试计划进度从80%到95%，按比例分配
            if progress_callback and total_plans > 0:
                plan_progress = 80 + (i / total_plans) * 18  # 80% 到 98%
                progress_callback(int(plan_progress))

            # Before
            print(retry_request_2("POST", before_paper_url, headers=self.headers, data={
                "tenantCode": self.tenantCode,
                "userId": self.userId,
                "userExamPlanId": plan_id
            }).text)

            # 检查是否能够参加考试
            if exam_time_state != 2:
                print(f"考试计划 '{exam_plan_name}' 无法参加考试: '{can_not_exam_info}' \n")
                continue  # 跳过这个考试，继续下一个

            print(f"开始执行 '{exam_plan_name}' 考试开放为时间: {start_Time} 到 {end_Time}\n")
            # Prepare
            print(retry_request_2("POST", f"https://weiban.mycourse.cn/pharos/exam/preparePaper.do?timestamp",
                                  headers=self.headers, data={
                    "tenantCode": self.tenantCode,
                    "userId": self.userId,
                    "userExamPlanId": plan_id,
                }).text)

            # 验证码校验
            verify_count = 0
            while True:
                verify_code, verify_time = get_verify_code()
                verify_data = retry_request_2("POST", check_verify_code_url, headers=self.headers, data={
                    "tenantCode": self.tenantCode,
                    "time": verify_time,
                    "userId": self.userId,
                    "verifyCode": verify_code,
                    "userExamPlanId": plan_id,
                    "timestamp": self.__get_timestamp()
                }).json()

                if verify_data['code'] == '0':
                    break

                verify_count += 1
                if verify_count > 3:
                    print("验证码识别失败")
                    return

            # 开始考试
            paper_data = retry_request_2("POST", start_paper_url, headers=self.headers, data={
                "tenantCode": self.tenantCode,
                "userId": self.userId,
                "userExamPlanId": plan_id,
            }).json()['data']

            # 提取题目列表
            question_list = paper_data['questionList']
            match_count = 0
            ai_count = 0
            
            # 计算每道题目对应的进度增量
            # 考试进度从80%到98%，留出0%给考试等待阶段
            total_questions = len(question_list)
            progress_per_question = 18 / total_questions if total_questions > 0 else 0
            current_question_progress = 80  # 初始进度80%
            
            for question_index, question in enumerate(question_list):
                answerIds = None
                question_title = question['title']
                question_type = question['type'] # 1是单选，2是多选
                question_type_name = question['typeLabel']
                option_list = question['optionList']
                submit_answer_id_list = []

                # 获取答案列表和初始的匹配标志
                answer_list, matched_question, similarity = get_answer_list(question_title, option_list)

                print(f"题目: {question_title}")

                # 加载AI配置
                try:
                    config = configparser.ConfigParser()
                    config.read('ai.conf')
                    has_ai_config = (
                        'AI' in config and 
                        config['AI'].get('API_ENDPOINT') and 
                        config['AI'].get('API_KEY') and 
                        config['AI'].get('MODEL')
                    )
                    # 不再显示AI配置信息
                    # if has_ai_config:
                    #     print(f"AI配置已读取: {config['AI']['API_ENDPOINT']}, 模型: {config['AI']['MODEL']}")
                except Exception as e:
                    print(f"读取AI配置文件出错: {e}")
                    has_ai_config = False

                # 检查题目标题是否匹配
                if answer_list:
                    found_match = False
                    similarity_threshold = 0.8  # 设置相似度阈值
                    use_ai = similarity < similarity_threshold  # 如果相似度低于阈值，使用AI答题
                    
                    if not use_ai:
                        for answer in answer_list:
                            # 增加模糊匹配逻辑
                            for option in option_list:
                                similarity = difflib.SequenceMatcher(None, option['content'], answer).ratio()
                                if similarity > 0.8 or option['content'] == answer:
                                    submit_answer_id_list.append(option['id'])
                                    # 移除"(匹配选项: xxx)"部分，只显示答案
                                    print(f"答案: {answer}")
                                    found_match = True
                                    break

                    if found_match and len(submit_answer_id_list) == len(answer_list):
                        match_count += 1
                        print("<===答案匹配成功===>\n")
                        answerIds = None  # 使用submit_answer_id_list
                    elif has_ai_config:
                        # 如果题库匹配度低或选项未完全匹配，使用AI答题
                        if use_ai:
                            print("<——————————题库匹配度低，使用AI答题——————————>\n")
                        else:
                            print("<——————————题目匹配但选项未找到匹配项，尝试AI答题——————————>\n")
                            
                        # 记录原题目以便后续更新题库
                        question_for_update = {
                            "title": question_title,
                            "options": option_list,
                            "question_type": question_type
                        }
                        self.questions_to_update.append(question_for_update)
                        
                        problemInput = f"{question_title}\n{option_list}"
                        answerIds, content = ai_response(problemInput, question_type)
                        if answerIds:
                            print(f"{question_type_name}，AI获取的答案: {content}")
                            ai_count += 1
                            
                            # 自动更新题库（如果配置了自动更新）
                            if hasattr(self, 'auto_update_questionbank') and self.auto_update_questionbank:
                                # 解析AI答案，找出对应选项的索引
                                correct_indices = []
                                for i, opt in enumerate(option_list):
                                    if opt['content'] in content:
                                        correct_indices.append(i)
                                
                                if correct_indices:
                                    self.update_question_bank(question_title, option_list, correct_indices)
                                    print("已自动更新题库")
                        else:
                            # AI返回空时的备用方案
                            print("AI未能获取答案，随机选择一个选项")
                            if question_type == 1:  # 单选
                                answerIds = option_list[0]['id']
                            else:  # 多选，选择前两个选项
                                if len(option_list) >= 2:
                                    answerIds = f"{option_list[0]['id']},{option_list[1]['id']}"
                                else:
                                    answerIds = option_list[0]['id']
                    else:
                        print("<——————————!!!题目匹配但选项未找到匹配项，并且未正确配置AI!!!——————————>\n")
                        # 无AI配置时的备用方案
                        if question_type == 1:  # 单选
                            answerIds = option_list[0]['id']
                        else:  # 多选，选择前两个选项
                            if len(option_list) >= 2:
                                answerIds = f"{option_list[0]['id']},{option_list[1]['id']}"
                            else:
                                answerIds = option_list[0]['id']
                elif has_ai_config:
                    print("<——————————未匹配到答案，将使用AI获取答案——————————>\n")
                    
                    # 记录原题目以便后续更新题库
                    question_for_update = {
                        "title": question_title,
                        "options": option_list,
                        "question_type": question_type
                    }
                    self.questions_to_update.append(question_for_update)
                    
                    problemInput = f"{question_title}\n{option_list}"
                    answerIds, content = ai_response(problemInput, question_type)
                    if answerIds:
                        print(f"{question_type_name}，AI获取的答案: {content}")
                        ai_count += 1
                        
                        # 自动更新题库（如果配置了自动更新）
                        if hasattr(self, 'auto_update_questionbank') and self.auto_update_questionbank:
                            # 解析AI答案，找出对应选项的索引
                            correct_indices = []
                            for i, opt in enumerate(option_list):
                                if opt['content'] in content:
                                    correct_indices.append(i)
                            
                            if correct_indices:
                                self.update_question_bank(question_title, option_list, correct_indices)
                                print("已自动更新题库")
                    else:
                        # AI返回空时的备用方案
                        print("AI未能获取答案，随机选择一个选项")
                        if question_type == 1:  # 单选
                            answerIds = option_list[0]['id']
                        else:  # 多选，选择前两个选项
                            if len(option_list) >= 2:
                                answerIds = f"{option_list[0]['id']},{option_list[1]['id']}"
                            else:
                                answerIds = option_list[0]['id']
                else:
                    print("<——————————!!!未匹配到答案，可配置ai.conf文件通过大模型答题!!!——————————>\n")
                    # 无AI配置时的备用方案
                    if question_type == 1:  # 单选
                        answerIds = option_list[0]['id']
                    else:  # 多选，选择前两个选项
                        if len(option_list) >= 2:
                            answerIds = f"{option_list[0]['id']},{option_list[1]['id']}"
                        else:
                            answerIds = option_list[0]['id']

                # 记录答案
                record_data = {
                    "answerIds": answerIds if answerIds is not None else ",".join(submit_answer_id_list),
                    "questionId": question['id'],
                    "tenantCode": self.tenantCode,
                    "userId": self.userId,
                    "userExamPlanId": plan_id,
                    "examPlanId": exam_plan_id,
                    "useTime": random.randint(60, 90)
                }
                retry_request_2("POST",
                                f"https://weiban.mycourse.cn/pharos/exam/recordQuestion.do?timestamp={time.time()}",
                                headers=self.headers, data=record_data)
                
                # 更新当前题目进度
                current_question_progress += progress_per_question
                if progress_callback:
                    progress_callback(int(current_question_progress))

            # 输出匹配度
            print("答案匹配度: ", match_count+ai_count, " / ", len(question_list))
            print("，其中 AI 作答有", ai_count, "题")
            print(f" - 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            if len(question_list) - match_count > self.exam_threshold:
                print(f"题库匹配度过低, '{exam_plan_name}' 暂未提交,请再次打开程序并修改设置")
                return

            print("请耐心等待考试完成（等待时长为你填写的考试时间 默人300秒）\n")
            
            # 在显示等待消息后更新进度条到98%
            if progress_callback:
                progress_callback(98)

            # 提交考试
            submit_data = {
                "tenantCode": self.tenantCode,
                "userId": self.userId,
                "userExamPlanId": plan_id,
            }
            
            # 等待考试完成
            time.sleep(self.finish_exam_time)
            
            # 获取并解析响应
            submit_response = retry_request_2("POST", submit_url + str(int(time.time()) + 600), 
                                  headers=self.headers, data=submit_data)
            submit_text = submit_response.text
            print(submit_text)
            
            # 直接解析返回的JSON来获取分数
            try:
                submit_json = json.loads(submit_text)
                if submit_json and submit_json.get("code") == "0":
                    score = submit_json.get("data", {}).get("score")
                    if score is not None:
                        print(f"【考试成绩】: {score} 分")
                    else:
                        print("【考试成绩】: 未能获取分数")
            except Exception as e:
                print(f"解析考试成绩失败: {str(e)}")
                
            print(" - 考试已完成 \n")
            print(f" - 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            
            # 更新进度到100%，表示考试全部完成
            if progress_callback:
                progress_callback(100)
            
            # 获取更详细的考试信息
            try:
                # 查找最近的考试记录以获取详细信息
                history_url = "https://weiban.mycourse.cn/pharos/exam/listHistory.do"
                history_data = {
                    "tenantCode": self.tenantCode,
                    "userId": self.userId,
                    "userProjectId": self.userProjectId,
                }
                history_response = retry_request_2("POST", history_url, headers=self.headers, data=history_data).json()
                
                if history_response.get("code") == "0" and history_response.get("data"):
                    # 获取最新的考试记录
                    latest_exam = history_response["data"][0] if history_response["data"] else None
                    if latest_exam:
                        user_exam_id = latest_exam.get("userExamId")
                        if user_exam_id:
                            # 获取详细考试结果
                            review_result = self.exam_review_paper(user_exam_id)
                            if review_result.get("code") == "0":
                                review_data = review_result.get("data", {})
                                use_time = review_data.get("useTime", 0)
                                submit_time = review_data.get("submitTime", "")
                                print(f"【提交时间】: {submit_time}")
                                print(f"【用时】: {use_time} 秒")
            except Exception as e:
                print(f"获取考试详细信息失败: {str(e)}")

    def getFinishIdList(self, chooseType):
        url = "https://weiban.mycourse.cn/pharos/usercourse/listCourse.do"
        result = {}
        for i in self.getCategory(chooseType):
            data = {
                "userProjectId": self.userProjectId,
                "tenantCode": self.tenantCode,
                "userId": self.userId,
                "chooseType": chooseType,
                "categoryCode": i,
            }
            response = requests.post(url, data=data, headers=self.headers)
            text = response.text
            data = json.loads(text)["data"]
            for i in data:
                if i["finished"] == 2:
                    if "userCourseId" in i:
                        result[i["resourceId"]] = i["userCourseId"]
                        # print(i['resourceName'])
                        self.tempUserCourseId = i["userCourseId"]
                    else:
                        result[i["resourceId"]] = self.tempUserCourseId
            print(f"加载章节 : {i['categoryName']}")
        print("\n资源加载完成")
        return result

    def finish_lyra(self, user_activity_id):
        """
        完成安全实训 (Lyra)
        :param user_activity_id: 用户活动 ID
        :return: 响应文本
        """
        url = "https://lyra.mycourse.cn/lyraapi/study/course/finish.api"
        data = {"userActivityId": user_activity_id}
        
        try:
            response = self.session.post(url, data=data, headers=self.headers, timeout=15)
            response_json = response.json()
            if response_json.get("code") == "0":
                # print(f"Lyra 安全实训完成成功: {user_activity_id}")
                return response.text
            else:
                # print(f"Lyra 安全实训完成失败: {response.text}")
                return response.text
        except Exception as e:
            # print(f"Lyra 请求异常: {e}")
            return None

    # 感谢以下项目的思路
    def finish(self, courseId, finishId, course_type="weiban"):
        """
        完成课程学习
        :param courseId: 课程ID
        :param finishId: 用户课程ID
        :param course_type: 课程类型 (weiban, open, moon)
        :return: 响应文本
        """
        from datetime import datetime
        import random
        # 获取当前系统时间
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 直接使用finishId完成课程，参考WeBan-3.5.20/api.py中的finish_by_token方法
        # print(f"直接使用finishId完成课程 (类型: {course_type})")
        
        # 完成任务的接口
        if course_type == "open":
            finish_url = "https://open.mycourse.cn/proteus/usercourse/finish.do"
            # 尝试添加额外参数，模拟真实请求
            # params 已经在下面定义了，这里可能需要针对 Open 课程做特殊处理
        elif course_type == "moon":
            finish_url = "https://moon.mycourse.cn/moonapi/api/study/activity/microCourse/v1/finishedCourse"
        else: # weiban
            finish_url = f"https://weiban.mycourse.cn/pharos/usercourse/v2/{finishId}.do"
        
        # 生成随机的jQuery回调函数名
        callback = f"jQuery3210{''.join(random.choices('0123456789', k=15))}_{int(time.time() * 1000)}"
        
        # 生成请求参数
        params = {
            "callback": callback,
            "userCourseId": finishId,
            "tenantCode": self.tenantCode,
            "_": str(int(time.time() * 1000) + 1),
        }
        
        try:
            # 发送 GET 请求完成任务
            # 添加 Referer 头，某些接口可能需要
            headers = self.headers.copy()
            
            # 针对不同类型的 Referer
            if course_type == "open":
                 headers["Referer"] = "https://open.mycourse.cn/"
            elif course_type == "moon":
                 headers["Referer"] = "https://moon.mycourse.cn/"
            else:
                 headers["Referer"] = "https://weiban.mycourse.cn/"
            
            # 使用 self.session 发送请求，而不是 requests.get
            response = self.session.get(finish_url, params=params, headers=headers, timeout=15)
            second_attempt_response = response.text
        except Exception as e:
            # print(f"finish函数请求异常: {e}")
            second_attempt_response = f"{{\"msg\":\"fail\",\"code\":\"-1\",\"detailCode\":\"-1\", \"error\": \"{str(e)}\"}}"

        # 检查响应是否成功
        if ('{"msg":"ok"' in second_attempt_response
                and '"code":"0"' in second_attempt_response
                and '"detailCode":"0"' in second_attempt_response):
            # 输出请求成功的消息
            # print("finish函数请求成功🗹")
            # 输出响应文本
            # print(second_attempt_response)
            # 输出指定文本和当前系统时间
            # print(f" - 当前时间: {current_time} \n")
            # 返回响应文本
            return second_attempt_response
        else:
            # 输出请求失败的消息
            # print("finish函数请求失败🗵")
            # 输出响应文本
            # print(second_attempt_response)
            # 输出指定文本和当前系统时间
            # print(f" - 当前时间: {current_time} \n")
            # 返回响应文本
            return second_attempt_response

    def get_method_token(self, course_id):
        url = "https://weiban.mycourse.cn/pharos/usercourse/getCaptcha.do"
        params = {
            "userCourseId": course_id,
            "userProjectId": self.userProjectId,
            "userId": self.userId,
            "tenantCode": self.tenantCode
        }
        text = requests.get(url, headers=self.headers, params=params).text
        try:
            question_id = json.loads(text)['captcha']['questionId']
        except (json.JSONDecodeError, KeyError) as e:
            print(f"获取验证码问题ID失败: {e}")
            print(f"响应内容: {text}")
            return None
        
        url = "https://weiban.mycourse.cn/pharos/usercourse/checkCaptcha.do"
        params = {
            "userCourseId": course_id,
            "userProjectId": self.userProjectId,
            "userId": self.userId,
            "tenantCode": self.tenantCode,
            "questionId": question_id
        }
        data = {
            "coordinateXYs": "[{\"x\":199,\"y\":448},{\"x\":241,\"y\":466},{\"x\":144,\"y\":429}]"
        }
        text = requests.post(url, headers=self.headers, params=params, data=data).text
        try:
            return json.loads(text)['data']['methodToken']
        except (json.JSONDecodeError, KeyError) as e:
            print(f"获取methodToken失败: {e}")
            print(f"响应内容: {text}")
            return None
    
    def exam_submit_paper(self, user_exam_plan_id: str) -> dict:
        """
        提交考试
        :param user_exam_plan_id: 用户考试计划 ID
        :return:
        {
          "code": "0",
          "data": {
            "score": 100,  # 这里是考试分数
            "redpacketInfo": {
              "redpacketName": "",
              "redpacketComment": "",
              "redpacketMoney": 0.0,
              "isSendRedpacket": 2
            },
            "ebookInfo": { "displayBook": 2 }
          },
          "detailCode": "0"
        }
        """
        submit_url = f"https://weiban.mycourse.cn/pharos/exam/submitPaper.do?timestamp={int(time.time()) + 600}"
        submit_data = {
            "tenantCode": self.tenantCode,
            "userId": self.userId,
            "userExamPlanId": user_exam_plan_id,
        }
        response = self.session.post(submit_url, headers=self.headers, data=submit_data)
        try:
            return response.json()
        except:
            return {"code": "-1", "data": {}, "message": "提交考试失败，无法解析响应"}

    def exam_review_paper(self, user_exam_id: str, is_retake: int = 2) -> dict:
        """
        查看考试结果
        :param user_exam_id: 用户考试ID
        :param is_retake: 是否重考，2为否
        :return:
        {
          "code": "0",
          "data": {
            "submitTime": "2025-05-19 01:59:37",
            "score": 100,  # 总分
            "useTime": 526,  # 用时(秒)
            "questions": [
              # 题目详情和答案...
            ]
          }
        }
        """
        review_url = "https://weiban.mycourse.cn/pharos/exam/reviewPaper.do"
        review_data = {
            "tenantCode": self.tenantCode,
            "userId": self.userId,
            "userExamId": user_exam_id,
            "isRetake": is_retake
        }
        response = self.session.post(review_url, headers=self.headers, data=review_data)
        try:
            return response.json()
        except:
            return {"code": "-1", "data": {}, "message": "查看考试结果失败，无法解析响应"}

    @staticmethod
    def get_project_id(user_id, tenant_code, token: str):
        url = "https://weiban.mycourse.cn/pharos/index/listMyProject.do"
        headers = {
            "X-Token": token,
            "ContentType": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.82",
        }
        data = {"tenantCode": tenant_code, "userId": user_id, "ended": 2}
        text = requests.post(url=url, headers=headers, data=data).text
        data = json.loads(text)["data"]
        if len(data) <= 0:
            print("已完成全部")
            # exit(1)
        else:
            return data

    def get_lab_id(user_id, tenant_code, token: str):
        """
        获取用户的实验课程信息。
        """
        url = f"https://weiban.mycourse.cn/pharos/lab/index.do?timestamp={int(time.time())}"
        headers = {
            "X-Token": token,
            "ContentType": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.82",
        }
        data = {"tenantCode": tenant_code, "userId": user_id}
        response = requests.get(url, headers=headers, params=data)
        response_data = response.json()  # 解析JSON响应

        if response_data['code'] == '0' and response_data['detailCode'] == '0':
            # 检查 'current' 键是否存在于响应数据中
            if 'current' in response_data['data']:
                # 提取实验课程的信息
                lab_info = response_data['data']['current']
                return lab_info
            else:
                print("没有找到实验课程信息。")
                return None
        else:
            print("获取实验课程信息失败")
            return None

    # Todo(状态输出用于Web对接)
    # def generate_finish(self):
    #

    @staticmethod
    def get_tenant_code(school_name: str) -> str:
        tenant_list = requests.get(
            "https://weiban.mycourse.cn/pharos/login/getTenantListWithLetter.do"
        ).text
        data = json.loads(tenant_list)["data"]
        for i in data:
            for j in i["list"]:
                if j["name"] == school_name:
                    return j["code"]

    @staticmethod
    def get_verify_code(get_time, download=False):
        img_uuid = uuid.uuid4()
        img_data = requests.get(
            f"https://weiban.mycourse.cn/pharos/login/randLetterImage.do?time={get_time}"
        ).content
        if img_data is None:
            print("验证码获取失败")
            exit(1)
        # 如果code目录不存在则创建
        if download:
            if not os.path.exists("code"):
                os.mkdir("code")
            with open(f"code/{img_uuid}.jpg", "wb") as file:
                file.write(img_data)
            return img_uuid
        else:
            return img_data

    @staticmethod
    def login(account, password, tenant_code, verify_code, verify_time):
        url = "https://weiban.mycourse.cn/pharos/login/login.do"
        payload = {
            "userName": account,
            "password": password,
            "tenantCode": tenant_code,
            "timestamp": verify_time,
            "verificationCode": verify_code,
        }
        ret = encrypted.login(payload)
        response = requests.post(url, data={"data": ret})
        text = response.text
        data = json.loads(text)
        print(data)
        if data['code'] == '-1':
            if str(data).find("不匹配") != -1:
                exit(1)
        return data

    def update_question_bank(self, question_title, options, correct_answers):
        """
        更新题库中的题目和选项
        
        :param question_title: 题目标题
        :param options: 选项列表，格式为[{"content": "选项内容", "id": "选项ID"}]
        :param correct_answers: 正确答案的索引列表，从0开始
        :return: 是否更新成功
        """
        try:
            # 读取题库文件
            question_bank_path = "QuestionBank/result.json"
            with open(question_bank_path, 'r', encoding='utf8') as f:
                question_bank = json.loads(f.read())
            
            # 构造新的题目数据结构
            option_list = []
            for idx, option in enumerate(options):
                is_correct = 1 if idx in correct_answers else 2
                option_data = {
                    "content": option["content"],
                    "sequence": idx + 1,
                    "selected": is_correct,
                    "isCorrect": is_correct,
                    "attachmentList": []
                }
                if "id" in option and option["id"]:
                    option_data["id"] = option["id"]
                    option_data["questionId"] = question_title  # 使用题目作为questionId
                option_list.append(option_data)
            
            # 更新或添加题目
            question_bank[question_title] = {"optionList": option_list}
            
            # 写回题库文件
            with open(question_bank_path, 'w', encoding='utf8') as f:
                json.dump(question_bank, f, ensure_ascii=False, indent=4)
            
            print(f"题库更新成功: {question_title}")
            return True
        except Exception as e:
            print(f"题库更新失败: {str(e)}")
            return False

    def export_questions_to_update(self):
        """
        导出需要更新的题目到文件
        
        :return: 导出的文件路径
        """
        if not self.questions_to_update:
            print("没有需要更新的题目")
            return None
        
        try:
            # 确保目录存在
            update_dir = "QuestionBank/updates"
            if not os.path.exists(update_dir):
                os.makedirs(update_dir)
            
            # 生成导出文件名
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            export_path = f"{update_dir}/questions_update_{timestamp}.json"
            
            # 写入文件
            with open(export_path, 'w', encoding='utf8') as f:
                json.dump(self.questions_to_update, f, ensure_ascii=False, indent=4)
            
            print(f"已导出{len(self.questions_to_update)}个需要更新的题目到: {export_path}")
            return export_path
        except Exception as e:
            print(f"导出题目更新失败: {str(e)}")
            return None

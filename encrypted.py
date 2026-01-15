# From https://github.com/JefferyHcool/weibanbot/blob/main/enco.py
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad
import base64
from base64 import urlsafe_b64decode, urlsafe_b64encode


def fill_key(key):
    key_size = 128
    filled_key = key.ljust(key_size // 8, b'\x00')
    return filled_key


def aes_encrypt(data, key):
    cipher = AES.new(key, AES.MODE_ECB)
    ciphertext = cipher.encrypt(pad(data.encode('utf-8'), AES.block_size))
    base64_cipher = base64.b64encode(ciphertext).decode('utf-8')
    result_cipher = base64_cipher.replace('+', '-').replace('/', '_')
    return result_cipher


def aes_encrypt_new(data):
    """
    AES加密 - 新方法
    :param data: json 字符串
    :return: base64 编码的加密字符串
    """
    key = urlsafe_b64decode("d2JzNTEyAAAAAAAAAAAAAA==")  # wbs512
    return urlsafe_b64encode(AES.new(key, AES.MODE_ECB).encrypt(pad(data.encode(), AES.block_size))).decode()


def login(payload):
    # 使用新的加密方法
    if "tenantCode" in payload:
        encrypted = aes_encrypt_new(
            f'{{"keyNumber":"{payload["userName"]}","password":"{payload["password"]}","tenantCode":"{payload["tenantCode"]}","time":{payload["timestamp"]},"verifyCode":"{payload["verificationCode"]}"}}'
        )
    else:
        encrypted = aes_encrypt_new(
            f'{{"keyNumber":"{payload["userName"]}","password":"{payload["password"]}","time":{payload["timestamp"]},"verifyCode":"{payload["captchaCode"] if "captchaCode" in payload else payload["verificationCode"]}"}}'
        )

    return encrypted
    # You can add logic for different payload.entry values here

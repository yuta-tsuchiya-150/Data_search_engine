import re
from fastapi import Request

def is_mobile_device(request: Request) -> bool:
    """
    リクエストの User-Agent または クエリパラメータからモバイル端末(スマホ)アクセスかを判定。
    ?device=mobile または ?device=desktop で強制切り替え可能。
    """
    # 1. クエリパラメータによる明示的判定
    forced_device = request.query_params.get("device")
    if forced_device == "mobile":
        return True
    elif forced_device == "desktop":
        return False

    # 2. User-Agent ヘッダーの解析
    user_agent = request.headers.get("user-agent", "").lower()
    
    mobile_patterns = [
        r'iphone', r'ipod', r'android.*mobile', r'windows phone',
        r'blackberry', r'mobile', r'opera mini', r'silk'
    ]
    
    for pattern in mobile_patterns:
        if re.search(pattern, user_agent):
            return True
            
    return False

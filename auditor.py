import os
import google.generativeai as genai
import re

def audit_dog_content(title, content, keyword, api_key=None):
    """
    超厳格なAI監査員 (Ultra-Strict Quality & Safety Auditor)
    文字化けの原因となる絵文字を禁止し、15秒に収まる簡潔さを徹底する。
    """
    if api_key:
        import json
        import os
        from google.oauth2 import service_account

        service_account_str = os.environ.get("GEMINI_SERVICE_ACCOUNT")
        credentials = None
        if service_account_str:
            try:
                info = json.loads(service_account_str)
                credentials = service_account.Credentials.from_service_account_info(info)
            except Exception:
                if os.path.exists(service_account_str):
                    try:
                        credentials = service_account.Credentials.from_service_account_file(service_account_str)
                    except Exception:
                        pass
        if credentials:
            genai.configure(credentials=credentials)
        else:
            genai.configure(api_key=api_key)
    
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    audit_prompt = f"""
    You are a HIGHLY STRICT Content Compliance Officer for the YouTube channel "Doggo Bliss".
    
    Current Content to Audit:
    Title: {title}
    Content: {content}
    Search Keyword: {keyword}
    
    === QUALITY & SAFETY RULES ===
    1. NO EMOJIS: Use ONLY letters and basic punctuation (.,!,?). Emojis cause rendering errors (□). FAIL if you see emojis. Basic punctuation including question marks (?) is fully allowed.
    2. STRICTLY DOGS & HUMANS/OWNERS: Only dogs and humans/owners (and the bond/relationship between them) are allowed. Mentions of owners, humans, and human-dog interactions are fully permitted. Absolute FAIL only if other unrelated pets or species (such as cats, birds, hamsters) are mentioned.
    3. SHORT & PUNCHY: The content must be readable within 15 seconds. If too long, FAIL and shorten it.
    4. NATURAL ENGLISH: Must sound like a native speaker. No awkward translations.
    
    === OUTPUT FORMAT ===
    Result: [PASS or FAIL]
    Feedback: [If FAIL, explain why and give clear instructions to fix]
    """
    
    try:
        response = model.generate_content(audit_prompt)
        text = response.text
        
        is_pass = "Result: PASS" in text
        feedback = ""
        if "Feedback:" in text:
            match = re.search(r"Feedback:\s*(.*)", text, re.DOTALL)
            if match: feedback = match.group(1).strip()
            
        if "ABORT_POST" in feedback:
            print("🚨 監査員が重大なリスクを検知しました。投稿を中止します。")
            return False, "CRITICAL_SAFETY_ABORT"
            
        return is_pass, feedback
        
    except Exception as e:
        print(f"Audit Error: {e}")
        return False, "Audit system error. Please retry."

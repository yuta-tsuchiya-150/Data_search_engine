import os
import json
import httpx
from typing import List, Dict, Any, Optional

class GeminiFilesManager:
    """
    Google Gemini Files API 連携マネージャー。
    自前DBに画像やドキュメントを保存せず、Google の Gemini AI サーバーへ直接ファイルをアップロード・管理。
    """
    
    # ローカルのメタデータキャッシュ (Google上のfile_uriリスト)
    _CACHE_FILE = "configs/gemini_files_registry.json"

    @staticmethod
    def get_api_key() -> str:
        return os.getenv("GEMINI_API_KEY", "").strip()

    @staticmethod
    def _load_registry() -> List[Dict[str, Any]]:
        if os.path.exists(GeminiFilesManager._CACHE_FILE):
            try:
                with open(GeminiFilesManager._CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    @staticmethod
    def _save_registry(registry: List[Dict[str, Any]]):
        os.makedirs(os.path.dirname(GeminiFilesManager._CACHE_FILE), exist_ok=True)
        with open(GeminiFilesManager._CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)

    @staticmethod
    async def upload_file_to_gemini(file_bytes: bytes, filename: str, mime_type: str, display_name: str = "") -> Dict[str, Any]:
        """
        画像・ドキュメントファイルを Google Gemini サーバーへ直接アップロード (Resumable Upload)
        """
        api_key = GeminiFilesManager.get_api_key()
        display = display_name if display_name else filename

        if not api_key:
            # APIキー未設定時のローカル擬似登録（フォールバック）
            fake_info = {
                "name": f"files/local_mock_{int(httpx.__name__.__len__())}_{filename}",
                "file_uri": f"https://generativelanguage.googleapis.com/v1beta/files/mock_{filename}",
                "display_name": display,
                "mime_type": mime_type,
                "size_bytes": len(file_bytes),
                "source": "local_mock"
            }
            registry = GeminiFilesManager._load_registry()
            registry.append(fake_info)
            GeminiFilesManager._save_registry(registry)
            return {"status": "ok", "file": fake_info, "message": "APIキー未設定のため擬似登録されました"}

        try:
            # 1. Google Resumable Upload の初期化
            init_url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={api_key}"
            headers = {
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(file_bytes)),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json"
            }
            meta_body = {
                "file": {
                    "display_name": display
                }
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                res_init = await client.post(init_url, headers=headers, json=meta_body)
                upload_url = res_init.headers.get("X-Goog-Upload-URL")
                
                if not upload_url:
                    return {"status": "error", "message": f"Upload initialization failed: {res_init.text}"}

                # 2. バイトデータの送信
                upload_headers = {
                    "X-Goog-Upload-Offset": "0",
                    "X-Goog-Upload-Command": "upload, finalize",
                    "Content-Length": str(len(file_bytes))
                }
                res_upload = await client.post(upload_url, headers=upload_headers, content=file_bytes)

                if res_upload.status_code == 200:
                    file_info = res_upload.json().get("file", {})
                    file_record = {
                        "name": file_info.get("name"),
                        "file_uri": file_info.get("uri"),
                        "display_name": file_info.get("displayName", display),
                        "mime_type": file_info.get("mimeType", mime_type),
                        "size_bytes": file_info.get("sizeBytes", len(file_bytes)),
                        "source": "google_gemini_server"
                    }
                    registry = GeminiFilesManager._load_registry()
                    registry.append(file_record)
                    GeminiFilesManager._save_registry(registry)

                    return {"status": "ok", "file": file_record}
                else:
                    return {"status": "error", "message": f"Upload failed: {res_upload.text}"}
        except Exception as e:
            return {"status": "error", "message": f"Gemini Files Upload Exception: {str(e)}"}

    @staticmethod
    def get_registered_files() -> List[Dict[str, Any]]:
        """Google Gemini サーバー上に保管されている登録済みファイル一覧を取得"""
        return GeminiFilesManager._load_registry()

    @staticmethod
    def delete_registered_file(file_name_or_uri: str) -> bool:
        """登録済みファイルの登録解除"""
        registry = GeminiFilesManager._load_registry()
        new_reg = [f for f in registry if f.get("name") != file_name_or_uri and f.get("file_uri") != file_name_or_uri]
        GeminiFilesManager._save_registry(new_reg)
        return True

import os
import asyncio
import logging
import zipfile
from typing import List
from fastapi import UploadFile
import fitz # pymupdf

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FileServiceError(Exception):
    """文件服务基础异常类"""
    pass


class UnsupportedFileTypeError(FileServiceError):
    """不支持的文件类型异常"""
    pass


class FileSizeExceededError(FileServiceError):
    """文件大小超限异常"""
    pass


class FileService:
    """
    文件服务类，仅负责文本提取，不保存文件
    
    支持的文件格式：
    - PDF (.pdf)
    - Word (.docx)
    - 纯文本/Markdown (.txt/.md)
    """

    def __init__(self, max_file_size_mb: int = 10):
        """初始化文件服务"""
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.allowed_extensions = ['pdf', 'docx', 'txt', 'md']
        logger.info(f"文件服务初始化成功，最大文件大小: {max_file_size_mb}MB")
    
    def _validate_file_type(self, filename: str) -> bool:
        """验证文件类型"""
        file_ext = os.path.splitext(filename)[1].lower().lstrip('.')
        return file_ext in self.allowed_extensions
    
    def _validate_file_size(self, file_size: int) -> bool:
        """验证文件大小"""
        return file_size <= self.max_file_size_bytes

    def _validate_file_signature(self, file_path: str, file_ext: str) -> bool:
        """基于文件头做轻量魔数校验，防止仅改扩展名绕过。"""
        with open(file_path, "rb") as f:
            header = f.read(8)

        ext = file_ext.lower().lstrip(".")
        if ext == "pdf":
            return header.startswith(b"%PDF")
        if ext == "docx":
            return header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06") or header.startswith(b"PK\x07\x08")
        if ext in {"txt", "md"}:
            return b"\x00" not in header
        return False

    def _validate_docx_archive(self, file_path: str) -> None:
        """拒绝加密、超大或异常压缩比的 DOCX，降低解压炸弹风险。"""
        try:
            with zipfile.ZipFile(file_path) as archive:
                entries = archive.infolist()
                if len(entries) > 2_000:
                    raise FileServiceError("DOCX 文件条目过多")
                total_size = sum(item.file_size for item in entries)
                compressed_size = sum(max(item.compress_size, 1) for item in entries)
                if total_size > 50 * 1024 * 1024:
                    raise FileServiceError("DOCX 解压后内容过大")
                if total_size / max(compressed_size, 1) > 100:
                    raise FileServiceError("DOCX 压缩比异常")
                if any(item.flag_bits & 0x1 for item in entries):
                    raise FileServiceError("不支持加密 DOCX")
                if "word/document.xml" not in archive.namelist():
                    raise FileServiceError("DOCX 缺少正文结构")
        except zipfile.BadZipFile as exc:
            raise FileServiceError("DOCX 文件结构损坏") from exc
    
    def extract_text_from_pdf(self, file_path: str) -> str:
        """解析 PDF 文件（使用 PyMuPDF）"""
        try:
            logger.info(f"开始解析 PDF: {file_path}")
            doc = fitz.open(file_path)
            pages_text = []
            
            for page in doc:
                # 使用 sort=True 按照从上到下、从左到右的顺序提取文本
                text = page.get_text(sort=True)
                if text:
                    pages_text.append(text)
            
            full_text = "\n\n".join(pages_text)
            
            doc.close()

            if not full_text.strip():
                raise ValueError("PDF 解析成功但内容为空")
            
            logger.info(f"PDF 解析成功，提取文本长度: {len(full_text)} 字符")
            return full_text
            
        except Exception as e:
            logger.error(f"PDF 解析失败: {str(e)}")
            raise FileServiceError(f"PDF 解析失败: {str(e)}")
    
    def extract_text_from_docx(self, file_path: str) -> str:
        """解析 Word 文档 (.docx)"""
        try:
            from docx import Document
            logger.info(f"开始解析 Word 文档: {file_path}")
            
            doc = Document(file_path)
            full_text = "\n\n".join([p.text for p in doc.paragraphs if p.text.strip()])
            
            if not full_text.strip():
                raise ValueError("Word 文档解析成功但内容为空")
            
            logger.info(f"Word 文档解析成功，提取文本长度: {len(full_text)} 字符")
            return full_text
        except ImportError:
            raise FileServiceError("缺少 python-docx 库")
        except Exception as e:
            logger.error(f"Word 文档解析失败: {str(e)}")
            raise FileServiceError(f"Word 文档解析失败: {str(e)}")
    
    def extract_text_from_txt(self, file_path: str) -> str:
        """读取纯文本文件"""
        try:
            logger.info(f"开始读取文本文件: {file_path}")
            encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
            
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        full_text = f.read()
                    if full_text.strip():
                        logger.info(f"文本文件读取成功 (编码: {encoding})")
                        return full_text
                except UnicodeDecodeError:
                    continue
            
            raise ValueError("无法使用常见编码读取文本文件")
        except Exception as e:
            logger.error(f"文本文件读取失败: {str(e)}")
            raise FileServiceError(f"文本文件读取失败: {str(e)}")
    
    def extract_text(self, file_path: str) -> str:
        """根据文件类型自动选择提取方法"""
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext == '.pdf':
            return self.extract_text_from_pdf(file_path)
        elif file_ext == '.docx':
            return self.extract_text_from_docx(file_path)
        elif file_ext in {'.txt', '.md'}:
            return self.extract_text_from_txt(file_path)
        else:
            raise UnsupportedFileTypeError(f"不支持的文件类型: {file_ext}")

    async def process_fastapi_file(self, upload_file: UploadFile) -> str:
        """
        处理 FastAPI 上传的文件，仅提取文本内容，不保存文件
        
        Args:
            upload_file: FastAPI 的 UploadFile 对象
            
        Returns:
            str: 提取的文本内容
        """
        import tempfile
        import shutil
        
        try:
            # 1. 验证文件类型
            if not self._validate_file_type(upload_file.filename):
                raise UnsupportedFileTypeError(
                    f"不支持的文件类型: {upload_file.filename}。"
                    f"支持的格式: {', '.join(self.allowed_extensions)}"
                )
            
            # 2. 验证文件大小
            file_size = 0
            if hasattr(upload_file, 'size') and upload_file.size is not None:
                file_size = upload_file.size
            else:
                # 如果 size 为 None，需要读取文件来获取大小
                upload_file.file.seek(0, 2)  # 移动到文件末尾
                file_size = upload_file.file.tell()
                upload_file.file.seek(0)  # 重置到文件开头
            
            if not self._validate_file_size(file_size):
                raise FileSizeExceededError(
                    f"文件大小 ({file_size / 1024 / 1024:.2f}MB) "
                    f"超过限制 ({self.max_file_size_bytes / 1024 / 1024}MB)"
                )
            
            # 3. 创建临时文件进行处理
            file_ext = os.path.splitext(upload_file.filename)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
                temp_path = temp_file.name
                try:
                    shutil.copyfileobj(upload_file.file, temp_file)
                finally:
                    upload_file.file.close()
            
            logger.info(f"临时文件已创建: {temp_path}")
            
            # 4. 基于魔数再次验证文件类型
            if not self._validate_file_signature(temp_path, file_ext):
                raise UnsupportedFileTypeError(f"文件内容与扩展名不匹配: {upload_file.filename}")
            if file_ext.lower() == ".docx":
                self._validate_docx_archive(temp_path)

            # 5. 提取文本（PDF/DOCX 解析为同步 IO/CPU 操作，放入线程避免阻塞事件循环）
            try:
                try:
                    configured_timeout = int(os.getenv("FILE_PARSE_TIMEOUT_SECONDS", "30"))
                except ValueError:
                    configured_timeout = 30
                timeout_seconds = min(max(configured_timeout, 5), 120)
                try:
                    text_content = await asyncio.wait_for(
                        asyncio.to_thread(self.extract_text, temp_path),
                        timeout=timeout_seconds,
                    )
                except TimeoutError as exc:
                    raise FileServiceError("文件解析超时") from exc
                
                # 6. 验证内容有效性
                if not text_content or not text_content.strip():
                    raise FileServiceError("文件解析成功但内容为空")
                if len(text_content) > 500_000:
                    raise FileServiceError("文件文本内容过长，请上传更精简的简历")
                
                logger.info(f"文本提取成功，长度: {len(text_content)} 字符")
                return text_content
            finally:
                # 7. 删除临时文件
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                        logger.info(f"临时文件已删除: {temp_path}")
                except Exception as e:
                    logger.warning(f"删除临时文件失败: {str(e)}")
            
        except (UnsupportedFileTypeError, FileSizeExceededError, FileServiceError):
            raise
        except Exception as e:
            logger.error(f"处理 FastAPI 文件失败: {str(e)}")
            raise FileServiceError(f"文件处理失败: {str(e)}")


# 实例化默认服务对象
file_service = FileService()

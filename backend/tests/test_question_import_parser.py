import zipfile

import pytest

from app.files.file_service import FileService, FileServiceError
from ai.workflows.question_bank_support.import_parser import parse_question_document


def test_parse_markdown_questions_and_multiline_answers():
    content = """
Q1. 为什么 Redis 常被用于缓存？
A: 因为它以内存访问为主。
底层原理还包括高效数据结构。

问题2：如何避免缓存击穿？
答案：可以使用互斥锁或逻辑过期。
"""

    questions = parse_question_document(content=content, filename="redis.md", source_id="file-1")

    assert [item["question_text"] for item in questions] == [
        "为什么 Redis 常被用于缓存？",
        "如何避免缓存击穿？",
    ]
    assert "底层原理" in questions[0]["reference_answer"]
    assert questions[1]["source_type"] == "upload"


def test_parse_plain_numbered_question_list():
    questions = parse_question_document(
        content="1. 什么是 MVCC？\n2. 可重复读和读已提交有什么区别？",
        filename="database.md",
        source_id="file-2",
    )

    assert len(questions) == 2
    assert questions[0]["reference_answer"] is None


def test_docx_archive_rejects_excessive_uncompressed_content(tmp_path):
    path = tmp_path / "questions.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"x" * (51 * 1024 * 1024))

    with pytest.raises(FileServiceError, match="解压后内容过大"):
        FileService()._validate_docx_archive(str(path))
